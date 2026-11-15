# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- the switch -------------------------------------------------------------------------------

class SwitchJob(object):
    """Phase bookkeeping of a switch in the deploy job status (docs/DESIGN.md section 12.4)."""

    def __init__(self, job, log, source, target):
        self.job = job
        self.log = log
        self.source = source
        self.target = target

    def phase(self, name, limit=0):
        job_set_status(self.job, phase=name, phase_started_epoch=time.time() if name else None,
                       phase_limit=int(limit), slot_from=self.source, slot_to=self.target)
        if name:
            switch_fault(name)


def zd_restart(state, pw, job, log, release_context=None):
    """Deploy job of an application with zero-downtime slots: a switch, or a plain restart when
    the next restart must be plain or nothing runs that could keep serving. Returns
    (ok, message); raises HelperError on failure."""
    domain_id = state["domain_id"]
    live = state.get("slot") or ""
    target = zd_target(state)
    reason = None
    if state.get("restart_plain"):
        reason = "the listen mode or the system user changed"
    elif state.get("listen") not in ("tcp", "unix"):
        reason = "workers have no traffic to switch"
    elif target is None:
        reason = "zero-downtime deployments are off"
    elif not unit_is_active(app_unit(domain_id, live)):
        reason = "nothing is running"
    if release_context is not None:
        # Select the code for the instance this branch actually starts, including first start
        # and forced in-place restart. A nominal inactive target may never be used by that branch.
        selected_slot = target if not reason else (live if state.get("zero_downtime") else "")
        release_context["switch"] = not bool(reason)
        release_context["previous"] = ops_stage_release(state, release_context["selected"], target=selected_slot)
        if release_context["previous"] is not None:
            write_units(state, pw)
            systemctl("daemon-reload", check=True)
    if reason:
        log.line("Restarting in place (%s)." % reason)
        if release_context is None:
            state, unit = zd_plain_restart(state, pw, block=True)
        else:
            state, unit = zd_plain_restart(state, pw, block=True, release_staged=True)
        return restart_and_check(live_view(state), pw, unit, log, restarted=True)
    return zd_switch(state, pw, job, log, live, target)


def zd_stop_new(unit):
    systemctl("stop", unit, timeout=120)
    systemctl("reset-failed", unit)


def zd_wait_marker(state, web_unit, web_kind, log):
    """Step 1: the generated configuration of the web server that carries the traffic uses the
    switchable snippet of the listen mode, and it is active (reload when it is not yet)."""
    if not web_unit:
        return
    marker = ZD_MARKER % state["domain_id"]
    reference = pointer_reference(state, web_kind)
    deadline = time.time() + ZD_MARKER_WAIT
    httpdmng = None
    waited = False
    while True:
        text, mtime = generated_config(state, web_kind)
        if text and marker in text and reference in text:
            if web_effective(web_unit, web_kind, mtime):
                return
            with FileLock("web-reload"):
                if web_effective(web_unit, web_kind, mtime):
                    return
                ok, _reason, detail, _before = web_reload_confirm(web_unit, web_kind)
            if ok:
                return
            raise SwitchFailed("The web server could not be reloaded: %s" % detail)
        if not waited:
            log.line("Waiting for the web server configuration of %s with the zero-downtime snippet." % state["domain"])
            waited = True
        if time.time() >= deadline:
            if httpdmng is not None:
                raise SwitchFailed("The web server configuration of %s does not use Runway's zero-downtime snippet: %s"
                                   % (state["domain"], httpdmng or "httpdmng reported no error"))
            plesk = shutil.which("plesk", path=ROOT_PATH) or "/usr/sbin/plesk"
            log.line("Regenerating the configuration of %s (httpdmng)." % state["domain"])
            try:
                proc = run([plesk, "sbin", "httpdmng", "--reconfigure-domain", state["domain"]], timeout=ZD_HTTPDMNG_TIMEOUT)
                httpdmng = (proc.stderr or proc.stdout).strip()[-1000:]
            except HelperError as exc:
                httpdmng = str(exc)
            deadline = time.time() + 10
        time.sleep(1)


def zd_ensure_include(state, live, web_unit, web_kind):
    """tcp, before a switch: the include files name the live port and are active."""
    domain_id = state["domain_id"]
    with FileLock("web-reload"):
        changed = write_include(domain_id, slot_port(state, live))
        if web_unit and (changed or not web_effective(web_unit, web_kind, include_mtime(domain_id))):
            ok, _reason, detail, _before = web_reload_confirm(web_unit, web_kind)
            if not ok:
                raise SwitchFailed("The web server could not be reloaded: %s" % detail)


def zd_prepare_port(state, live, target, log):
    """tcp: the port of the new instance must be free and differ from the live one; otherwise it
    gets a newly allocated port (stored in the state). Returns the port."""
    domain_id = state["domain_id"]
    port_live = slot_port(state, live)
    port_new = slot_port(state, target)
    reason = None
    if not port_new or port_new == port_live:
        reason = "it is the port of the running version"
    else:
        uids = tcp_listener_uids(port_new)
        if uids:
            reason = "port %d is held by uid %s" % (port_new, ", ".join(str(uid) for uid in sorted(uids)))
    if reason:
        key = "port_" + target if target else "port"
        with FileLock("ports"):
            stored = read_json(app_state_path(domain_id))
            if not isinstance(stored, dict):
                raise HelperError("Application #%d is not configured" % domain_id)
            avoid = set(p for p in (state.get("port"), state.get("port_a"), state.get("port_b"), port_live) if p)
            new = allocate_extra_port(domain_id, state["port_range"], avoid)
            stored[key] = new
            write_json(app_state_path(domain_id), stored)
        if port_new:
            log.line("The new version gets port %d (%s)." % (new, reason))
        state[key] = new
        port_new = new
    return port_new


def zd_wait_ready(state, pw, view, live, live_inodes, log, limit):
    """Step 3: waits until the new instance listens on its own endpoint (and its health path
    answers). Returns ("ready", ""), ("stopped", reason) or ("failed", message)."""
    domain_id = state["domain_id"]
    unit = app_unit(domain_id, view.get("_slot") or "")
    unix = state["listen"] == "unix"
    endpoint = view["_socket"] if unix else "127.0.0.1:%d" % int(view["port"])
    expect = ("$RUNWAY_SOCKET (%s)" % endpoint) if unix else ("127.0.0.1:$PORT (%d)" % int(view["port"]))
    live_path = slot_socket_path(domain_id, live)
    deadline = time.time() + limit
    seen = False
    last = "nothing listens on %s" % endpoint
    while True:
        block = zd_flags_block(domain_id)
        if block:
            return "stopped", block
        info = unit_show([unit], ["ActiveState", "SubState", "NRestarts", "Result", "ExecMainStatus"]).get(unit, {})
        active = info.get("ActiveState")
        restarts = int(info.get("NRestarts") or 0) if (info.get("NRestarts") or "").isdigit() else 0
        if active in ("active", "activating", "reloading"):
            seen = True
        if active == "failed" or (seen and active == "inactive") or restarts > 0:
            return "failed", ("The new version exited during startup (status=%s/%s); it must listen on %s"
                              % (info.get("ExecMainStatus") or "?", info.get("Result") or "?", expect))
        if unix:
            # A second listener on the live instance's path while that instance still holds its
            # own listener: the path was taken over (e.g. a hardcoded app.sock). Without that
            # evidence (the live instance restarted), only a listener held by one of the new
            # version's processes counts (reading /proc/<pid>/fd needs CAP_SYS_PTRACE).
            current = unix_listener_inodes(live_path)
            stray = current - live_inodes
            if stray and ((live_inodes and live_inodes <= current) or pids_hold_sockets(unit_pids(unit), stray)):
                return "failed", ("The new version listens on %s instead of $RUNWAY_SOCKET (%s)" % (live_path, endpoint))
        listener, detail, code, _params = listener_info(view, pw)
        if listener == "tampered":
            contain_tampering(state, detail)
            raise HelperError("The socket path was tampered with (%s); the application was stopped." % detail)
        if listener == "foreign":
            return "failed", "Another user's process holds the endpoint of the new version (%s)" % detail
        if listener == "ok":
            if not state.get("health_path"):
                return "ready", ""
            health, hdetail, _code, _params = health_check(view, "ok", pw)
            if health == "healthy":
                return "ready", ""
            last = hdetail
        else:
            last = detail
        if time.time() >= deadline:
            return "failed", "The new version was not ready within %d s (%s)" % (limit, last)
        time.sleep(0.5)


def zd_drain(state, live, limit, old_workers, web_unit):
    """Step 5: waits (at most `limit` s) until the old instance has no connection left; tcp also
    until no web server worker of before the reload is alive. Ends early after a SIGTERM."""
    if limit <= 0:
        return
    unix = state["listen"] == "unix"
    path = slot_socket_path(state["domain_id"], live)
    port = slot_port(state, live)
    deadline = time.time() + limit
    while time.time() < deadline and not _TERM["pending"]:
        if unix:
            busy = unix_connections(path)
        else:
            busy = tcp_connections(port) or any(os.path.exists("/proc/%d" % pid) for pid in old_workers or ())
        if not busy:
            return
        time.sleep(0.5)


def zd_switch(state, pw, job, log, live, target):
    """The switch of docs/DESIGN.md section 12.4 (the deploy lock is held). Returns
    (ok, message); raises SwitchFailed/HelperError when the new version was not activated."""
    domain_id = state["domain_id"]
    sj = SwitchJob(job, log, live, target)
    unit_live, unit_new = app_unit(domain_id, live), app_unit(domain_id, target)
    started = False
    stop_new_on_error = True
    critical = False
    live_file = None
    keep_hint = " The running version keeps serving; Restart in place runs the new version with an interruption."
    try:
        sj.phase("prepare")
        log.line("Zero-downtime switch from %s to %s." % (slot_label(live), slot_label(target)))
        zd_converge_locked(state, pw, log)
        state, pw = load_app_state(domain_id)
        if (state.get("slot") or "") != live or zd_target(state) != target:
            live, target = state.get("slot") or "", zd_target(state)
            if target is None or not zd_switchable(state):
                # The convergence settled an interrupted switch back to the 1.0 unit (the setting
                # is off): the restart of the setting off, in place.
                return zd_restart(state, pw, job, log)
            sj = SwitchJob(job, log, live, target)
            unit_live, unit_new = app_unit(domain_id, live), app_unit(domain_id, target)
        if unit_is_active(unit_new):
            stop_new_on_error = False
            raise SwitchFailed("A previous switch is still being cleaned up (%s is running); try again in a minute." % unit_new)
        unix = state["listen"] == "unix"
        web_unit, web_kind = web_traffic_server()
        live_inodes = set()
        if unix:
            ensure_socket_dir(domain_id, pw)
            found = socket_check(state, pw)
            if found:
                contain_tampering(state, found[0])
                raise HelperError("The socket path was tampered with (%s); the application was stopped." % found[0])
            unlink_socket_entry(domain_id, socket_name(target))
            live_inodes = unix_listener_inodes(slot_socket_path(domain_id, live))
            # The live instance's socket file: a failed new version that took its path is detected
            # by a different (or missing) file afterwards (zd_rescue_live()).
            live_file = socket_file_id(slot_socket_path(domain_id, live))
        else:
            zd_prepare_port(state, live, target, log)
        zd_wait_marker(state, web_unit, web_kind, log)
        if not unix:
            zd_ensure_include(state, live, web_unit, web_kind)
        view = slot_view(state, target)
        if write_slot_units(state, pw, target):
            systemctl("daemon-reload")

        sj.phase("starting")
        with FileLock("ports"):
            block = zd_flags_block(domain_id)
        if block:
            return True, "The application was stopped during the switch; the new version was not started."
        zd_update_state(domain_id, switch={"from": live, "to": target, "phase": "starting", "started_epoch": time.time()})
        prepare_start(view, pw)
        systemctl("reset-failed", unit_new)
        started = True
        proc = systemctl("start", "--no-block", unit_new)
        if proc.returncode != 0:
            raise SwitchFailed("The new version could not be started: %s" % proc.stderr.strip())
        log.line("Started %s; waiting until it is ready (at most %d s)." % (unit_new, state["ready_timeout"]))

        sj.phase("waiting", state["ready_timeout"])
        result, detail = zd_wait_ready(state, pw, view, live, live_inodes, log, state["ready_timeout"])
        if result == "stopped":
            return zd_stopped_during(state, unit_new, target)
        if result != "ready":
            raise SwitchFailed(detail + "." + keep_hint)
        log.line("The new version is ready.")

        sj.phase("switching")
        _TERM["critical"] += 1
        critical = True
        old_workers = None
        with FileLock("ports"):
            block = zd_flags_block(domain_id)
            if not block:
                stored = read_json(app_state_path(domain_id))
                intent = dict(stored.get("switch") or {}, phase="switching")
                stored["switch"] = intent
                write_json(app_state_path(domain_id), stored)
        if block:
            return zd_stopped_during(state, unit_new, target)
        if unix:
            # The socket the link will name: a socket of the application's user (O_PATH check).
            try:
                unix_connect(view["_socket"], pw.pw_uid, 2.0).close()
            except OSError as exc:
                raise SwitchFailed("The new version's socket cannot be used (%s)." % exc + keep_hint)
            set_link(domain_id, target)
            stop_new_on_error = False
            # At once, not after the commit: a reboot recreates the link from this entry, and the
            # boot repair decides from the link and the enabled units (docs/DESIGN.md section 12.8).
            write_tmpfiles(state, pw, link_slot=target)
        else:
            with FileLock("web-reload"):
                try:
                    write_include(domain_id, slot_port(state, target))
                    if web_unit:
                        ok, reason, detail, old_workers = web_reload_confirm(web_unit, web_kind)
                    else:
                        ok, reason, detail = True, "", ""
                except (HelperError, OSError) as exc:
                    # e.g. a systemctl call that timed out: whether the web server already runs with
                    # the new port is unknown, so the old one is restored and confirmed first.
                    ok, reason, detail = False, "unknown", str(exc)
                if not ok:
                    # The new version is stopped only once the running configuration names the old
                    # port again: a refused reload (configuration test) left it in place, otherwise
                    # a confirmed reload of the restored include files.
                    restored, rdetail = False, ""
                    try:
                        write_include(domain_id, slot_port(state, live))
                        if reason == "reload" or not web_unit:
                            restored = True
                        else:
                            restored, _r, rdetail, _b = web_reload_confirm(web_unit, web_kind)
                    except (HelperError, OSError) as exc:
                        rdetail = str(exc)
                    if not restored:
                        stop_new_on_error = False
                        raise SwitchFailed("The web server did not confirm its configuration (%s; %s); both versions keep "
                                           "running until the next check." % (detail, rdetail))
                    if reason == "reload":
                        raise SwitchFailed("The web server could not be reloaded: %s." % detail + keep_hint)
                    raise SwitchFailed("The web server did not confirm the new configuration (%s)." % detail + keep_hint)
            stop_new_on_error = False
        log.line("The web server now sends the traffic to %s." % slot_label(target))
        switch_fault("moved")
        with FileLock("ports"):
            stored = read_json(app_state_path(domain_id))
            stored.update({"slot": target, "switched_at": now_iso(),
                           "switch": dict(stored.get("switch") or {"from": live, "to": target}, phase="draining")})
            write_json(app_state_path(domain_id), stored)
        state.update({"slot": target})
        switch_fault("committed")
        systemctl("enable", unit_new)
        if os.path.exists(os.path.join(UNIT_DIR, unit_live)):
            systemctl("disable", unit_live)
        if zd_flags_block(domain_id):
            systemctl("disable", "--now", *existing_app_units(domain_id), timeout=120)
            zd_update_state(domain_id, switch=None)
            return True, "The application was stopped during the switch."

        sj.phase("draining", state["drain_seconds"])
        zd_drain(state, live, state["drain_seconds"], old_workers, web_unit)
        sj.phase("stopping")
        message = "Switched from %s to %s" % (slot_label(live), slot_label(target))
        try:
            zd_stop_new(unit_live)
            if unix:
                unlink_socket_entry(domain_id, socket_name(live))
            if not live:
                retire_legacy(state)
            if not target:
                # Clears the intent record with the slots (a switch back to the 1.0 unit).
                retire_slots(state, pw)
            zd_update_state(domain_id, switch=None)
        except (HelperError, OSError) as exc:
            # The new version serves: the switch succeeded. The intent record stays, so the
            # convergence (scheduled reconcile, within 10 minutes) stops the old version.
            log.line(message + ".")
            log.line("WARNING: stopping %s failed (%s); the next check retries it." % (slot_label(live), exc))
            zd_journal(state, "%s; stopping %s failed (%s), the next check retries it." % (message, slot_label(live), exc), 4)
            return True, "%s; stopping %s failed, the next check retries it" % (message, slot_label(live))
        log.line(message + ".")
        zd_journal(state, message.lower()[:1] + message[1:] + " (zero-downtime deployment).")
        return True, None
    except DeployTerminated:
        if started and stop_new_on_error:
            zd_stop_new(unit_new)
            if state["listen"] == "unix":
                unlink_socket_entry(domain_id, socket_name(target))
                zd_rescue_live(state, pw, live, live_file, log)
            zd_update_state(domain_id, switch=None)
        raise
    except HelperError as exc:
        if started and stop_new_on_error:
            zd_stop_new(unit_new)
            if state["listen"] == "unix":
                unlink_socket_entry(domain_id, socket_name(target))
                zd_rescue_live(state, pw, live, live_file, log)
            zd_update_state(domain_id, switch=None)
        elif not started:
            zd_update_state(domain_id, switch=None)
        if isinstance(exc, SwitchFailed):
            zd_journal(state, "the zero-downtime deployment failed: %s" % exc)
        raise
    finally:
        if critical:
            _TERM["critical"] -= 1
        try:
            sj.phase("")
        except Exception:  # noqa: BLE001 - never hide the real result
            pass


def zd_stopped_during(state, unit_new, target):
    """Stop or disable during the switch, before the traffic moved: the new version goes."""
    zd_stop_new(unit_new)
    if state["listen"] == "unix":
        unlink_socket_entry(state["domain_id"], socket_name(target))
    zd_update_state(state["domain_id"], switch=None)
    return True, "The application was stopped during the switch; the new version was not started."


def socket_file_id(path):
    """(device, inode) of the socket file at `path` (lstat, never followed), or None."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino) if stat.S_ISSOCK(st.st_mode) else None


def zd_rescue_live(state, pw, live, live_file, log):
    """Unix, after a failed switch: a new version that bound the live instance's path (e.g. a
    hardcoded app.sock; gunicorn and asyncio remove an existing socket before they bind, Go,
    gunicorn and uvicorn unlink their path when they stop) replaced or removed the live socket
    file (`live_file`, recorded before the new version started). The live instance is then
    unreachable: restart it in place. A live socket file that is still the same file is left
    alone: a connection that fails because the instance is busy is no reason to interrupt it."""
    if live_file is None:
        return
    path = slot_socket_path(state["domain_id"], live)
    if socket_file_id(path) == live_file:
        return
    unit = app_unit(state["domain_id"], live)
    if not unit_is_active(unit):
        return
    log.line("The running version lost its socket %s (the new version replaced or removed it); restarting it in place." % path)
    prepare_start(slot_view(state, live), pw)
    systemctl("restart", "--no-block", unit)
