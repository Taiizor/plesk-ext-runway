# Copyright 2026 Taiizor. Licensed under the MIT License.

# Seconds reapply-all and rerender_runtime_apps wait per application for a short holder of its
# deploy lock (a deployment is not waited for: runway-rerender-<id> re-renders it afterwards).
RERENDER_LOCK_WAIT = 10


def reapply_app_locked(state, pw):
    """Re-renders the units and environment files of one application and, while in use, its
    pointer (an interrupted switch is settled first). The caller holds the deploy lock and read
    `state` under it. Returns the state and the password entry."""
    if zd_has_slots(state):
        ensure_converge_unit()
        if state["switch"]:
            zd_converge_locked(state, pw)
            state, pw = load_app_state(state["domain_id"])
    write_units(state, pw)
    if pointer_wanted(state):
        write_pointer(state, pw, state["slot"])
    return state, pw


def rerender_marker_path(domain_id):
    return os.path.join(RERENDER_DIR, "%d" % domain_id)


def schedule_rerender(domain_id):
    """Re-renders an application a minute from now in runway-rerender-<id> (transient, `_rerender`):
    reapply-all or a toolchain change found its deploy lock busy. A pending run stays (systemd-run
    refuses a second unit of the same name); app-remove stops it. The marker RERENDER_DIR/<id>
    stays until the re-render has run, so Reconcile can schedule a lost one again."""
    ensure_dir(RERENDER_DIR, 0o700)
    # A new token per request: a re-render that already runs removes only the marker it read.
    write_file_atomic(rerender_marker_path(domain_id), "%s %.6f\n" % (VERSION, time.time()), 0o600)
    run(["systemd-run", "--on-active=60", "--unit=runway-rerender-%d" % domain_id, "--collect", "--quiet",
         "--description=Runway: re-render the units of application #%d (deploy lock was busy)" % domain_id,
         HELPER_COPY, "_rerender", str(domain_id)], timeout=60)


def internal_rerender(domain_id):
    """runway-rerender-<id>.service: the re-render of reapply-all or rerender_runtime_apps that was
    deferred while the deploy lock was busy. It waits for the lock as long as a deployment may
    hold it; nothing is started or restarted (the change takes effect at the next restart)."""
    token = _read_marker(domain_id)
    try:
        state = load_app_state(domain_id)[0]
    except HelperError:
        remove_quietly(rerender_marker_path(domain_id))
        return  # removed (or no longer valid) meanwhile
    lock = FileLock("deploy-%d" % domain_id)
    if not lock.acquire(blocking=True, timeout=deploy_timeout(state) + 600):
        sys.stderr.write("runway: the deploy lock of #%d stayed busy; its units were not re-rendered\n" % domain_id)
        return
    try:
        try:
            state, pw = load_app_state(domain_id)
        except HelperError:
            remove_quietly(rerender_marker_path(domain_id))
            return
        state, pw = reapply_app_locked(state, pw)
        if _read_marker(domain_id) == token:
            # A request that came meanwhile (e.g. another upgrade) keeps its marker: Reconcile
            # schedules it again, with the code installed then.
            remove_quietly(rerender_marker_path(domain_id))
    finally:
        lock.release()
    systemctl("daemon-reload")
    if state["listen"] == "unix":
        ensure_socket_dir(domain_id, pw)
    sync_public_files_units(state)


def _read_marker(domain_id):
    try:
        with open(rerender_marker_path(domain_id), "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(200)
    except OSError:
        return None


def reschedule_rerenders():
    """Reconcile (apps-list {converge: true}): a deferred re-render whose transient unit is gone (a
    reboot, a refused app-remove) is scheduled again; the markers of removed applications go."""
    for name in _listdir(RERENDER_DIR):
        if not re.match(r"^\d+$", name):
            continue
        try:
            if os.path.exists(app_state_path(int(name))):
                schedule_rerender(int(name))
            else:
                remove_quietly(os.path.join(RERENDER_DIR, name))
        except Exception as exc:  # noqa: BLE001 - Reconcile must go on
            sys.stderr.write("runway: the re-render of #%s could not be scheduled: %s\n" % (name, exc))


def _strip_app_units(domain_id, errors):
    """Removes root-privileged Exec lines from the unit files of an application that is not
    re-rendered now (docs/DESIGN.md section 12.8, upgrade)."""
    for unit in all_app_units(domain_id):
        if _strip_privileged_exec(os.path.join(UNIT_DIR, unit)):
            errors.append("#%s: removed root-privileged Exec lines from the old unit file%s"
                          % (domain_id, "" if unit == UNIT_APP % domain_id else " " + unit))


def cmd_reapply_all(_payload):
    """Re-renders unit files, environment files and tmpfiles entries of every configured app and
    prepares the socket directories (used after an extension upgrade; running services keep
    running and pick the changes up at their next restart). Errors are reported per app; an app
    whose deploy lock is busy is re-rendered a minute after (schedule_rerender)."""
    ensure_layout()
    count = 0
    errors = []
    for raw in list(iter_app_states()):
        domain_id = raw.get("domain_id")
        try:
            dropped = _sanitize_stored_env(raw)
            if dropped:
                errors.append("#%s: removed %s from the environment variables (no longer allowed)"
                              % (domain_id, ", ".join(dropped)))
            state, pw = validate_app(raw)
            state["port"] = raw.get("port", 0)
            state.update(helper_fields(raw))
            lock, busy = try_deploy_lock(state["domain_id"], RERENDER_LOCK_WAIT)
            if lock is None:
                schedule_rerender(state["domain_id"])
                errors.append("#%s: %s; its units are re-rendered once the deploy lock is free"
                              % (domain_id, "a deployment is running" if busy == "deployment" else "another operation is in progress"))
                _strip_app_units(domain_id, errors)
                continue
            try:
                state, pw = load_app_state(state["domain_id"])
                state, pw = reapply_app_locked(state, pw)
            finally:
                lock.release()
            if state["listen"] == "unix":
                ensure_socket_dir(state["domain_id"], pw)
            sync_public_files_units(state)
            count += 1
        except Exception as exc:  # noqa: BLE001
            errors.append("#%s: %s" % (domain_id, exc))
            if isinstance(domain_id, int):
                _strip_app_units(domain_id, errors)
    systemctl("daemon-reload")
    sync_health_units()
    sync_metrics_units()
    return {"count": count, "errors": errors}


def cmd_install(_payload):
    if systemd_version() == 0:
        raise HelperError("systemd is required but was not found")
    ensure_layout()
    result = cmd_reapply_all(None)
    result["info"] = cmd_info(None)
    return result


def cmd_uninstall(payload):
    keep_toolchains = bool((payload or {}).get("keep_toolchains"))
    sync_metrics_units(enabled=False)
    removed = []
    errors = []
    for state in list(iter_app_states()):
        try:
            remove_app(int(state["domain_id"]), force=True)
            removed.append(state.get("domain_id"))
        except Exception as exc:  # noqa: BLE001 - best effort during uninstall
            errors.append("#%s: %s" % (state.get("domain_id"), exc))
    # Whatever a removal left behind (a failure above, a writer that finished meanwhile, a state
    # file that was unreadable): no application unit may outlive the extension.
    try:
        leftover = remove_leftover_app_units()
        if leftover:
            errors.append("removed leftover units: %s" % ", ".join(leftover))
    except Exception as exc:  # noqa: BLE001 - the rest of the uninstall must still run
        errors.append("leftover units: %s" % exc)
    systemctl("stop", UNIT_ADMIN_JOB)
    if os.path.exists(os.path.join(UNIT_DIR, UNIT_CONVERGE)):
        remove_converge_unit()
        systemctl("daemon-reload")
    # No application is left: the health watch timer goes too.
    sync_health_units()
    for name in _listdir(TMPFILES_DIR):
        if name == "runway.conf" or re.match(r"^runway-\d+\.conf$", name):
            remove_quietly(os.path.join(TMPFILES_DIR, name))
    shutil.rmtree(RUN_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    shutil.rmtree(CONF_DIR, ignore_errors=True)
    if keep_toolchains:
        remove_quietly(HELPER_COPY)
    else:
        shutil.rmtree(BASE_DIR, ignore_errors=True)
    return {"removed_apps": removed, "errors": errors}


RE_APP_UNIT_FILE = re.compile(r"^runway-(?:app-\d+(?:-[ab])?\.service|deploy-\d+\.(?:service|path)|public-files-\d+\.(?:service|timer))$")


def remove_leftover_app_units():
    """Uninstall: stops and deletes every per-application unit file of Runway that is still in
    UNIT_DIR, and the pending re-renders. Returns the names of the removed files."""
    names = sorted(name for name in _listdir(UNIT_DIR) if RE_APP_UNIT_FILE.match(name))
    systemctl("stop", "runway-rerender-*.timer", "runway-rerender-*.service",
              "runway-redeploy-*.timer", "runway-redeploy-*.service", timeout=60)
    if names:
        try:
            systemctl("disable", "--now", *names, timeout=120)
        except HelperError:
            pass  # a unit that does not stop in time: its file goes anyway
        for name in names:
            remove_quietly(os.path.join(UNIT_DIR, name))
        systemctl("daemon-reload")
        systemctl("reset-failed", *names)
    return names


def cmd_web_reconfigure(payload):
    domains = (payload or {}).get("domains") or []
    if not isinstance(domains, list) or len(domains) > 500:
        raise HelperError("Invalid domain list")
    plesk = shutil.which("plesk", path=ROOT_PATH) or "/usr/sbin/plesk"
    errors = []
    for name in domains:
        name = v_domain_name(name)
        proc = run([plesk, "sbin", "httpdmng", "--reconfigure-domain", name], timeout=300)
        if proc.returncode != 0:
            errors.append("%s: %s" % (name, (proc.stderr or proc.stdout).strip()[-500:]))
    if errors:
        raise HelperError("Web server reconfiguration failed: " + "; ".join(errors))
    return {"reconfigured": domains}
