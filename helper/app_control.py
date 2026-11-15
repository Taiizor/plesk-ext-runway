# Copyright 2026 Taiizor. Licensed under the MIT License.

def cmd_app_apply(payload):
    result = _app_apply(payload)
    # The health watch timer exists while an application has the watch on.
    sync_health_units()
    return result


def _app_apply(payload):
    payload = dict(payload or {})
    if "env" not in payload:
        # The panel omits "env" when it did not load/edit it: keep the stored secrets.
        stored = read_json(app_state_path(v_domain_id(payload.get("domain_id"))))
        payload["env"] = stored.get("env", {}) if isinstance(stored, dict) else {}
    state, pw = validate_app(payload)
    domain_id = state["domain_id"]
    restart = bool((payload or {}).get("restart", True))
    # start=false: enable the units but leave starting to a deploy job that builds first.
    start = bool((payload or {}).get("start", True))
    # resume=true: an explicit save by the user, which clears "stopped"/"tampered". Without it
    # (Reconcile, CLI) the flags of the stored state are kept: a stopped app stays stopped.
    resume = bool((payload or {}).get("resume"))
    if state["enabled"] and not state["suspended"] and state["toolchain"] \
            and not toolchain_installed(state["runtime"], state["toolchain"]):
        raise HelperError("%s toolchain '%s' is not installed on this server" % (RUNTIMES[state["runtime"]].label, state["toolchain"]))
    stored = read_json(app_state_path(domain_id))
    if state["zero_downtime"] or (isinstance(stored, dict) and (zd_has_slots(helper_fields(stored)) or stored.get("zero_downtime")
                                                                or slot_files_left(domain_id))):
        # Zero-downtime slots (docs/DESIGN.md section 12.5): the whole apply runs under the deploy
        # lock, so no switch, convergence or other writer of the pointer interleaves with it.
        lock = FileLock("deploy-%d" % domain_id)
        if not state["enabled"] or state["suspended"]:
            # Disabling or suspension ends a running deployment first (a switch finishes or rolls back).
            systemctl("disable", "--now", UNIT_PATH % domain_id)
            systemctl("stop", UNIT_DEPLOY % domain_id, timeout=ZD_DEPLOY_STOP + 30)
            if not lock.acquire(blocking=True, timeout=60):
                raise HelperError("Another operation of this application is still in progress. Please try again in a moment.")
        elif unit_is_active(UNIT_DEPLOY % domain_id) or not lock.acquire(blocking=False):
            raise HelperError("A deployment is running for this application. Wait until it finishes, then save again.")
        try:
            if isinstance(stored, dict) and helper_fields(stored)["switch"]:
                # An interrupted switch is settled from the pointer before anything is re-pointed
                # or stopped (the instance that carries the traffic must keep running).
                try:
                    current, current_pw = load_app_state(domain_id)
                    zd_converge_locked(current, current_pw)
                except HelperError:
                    pass
            return _zd_app_apply(state, pw, restart, start, resume)
        finally:
            lock.release()
    if not start and state["enabled"] and not state["suspended"] and unit_is_active(UNIT_DEPLOY % domain_id):
        raise HelperError("A deployment is running for this application. Wait until it finishes, then save again.")
    ensure_layout()
    if state["listen"] == "unix":
        web_server_group()
    # Runs as the customer: done before taking the global lock (it cannot be trusted to finish quickly).
    call_as_user(pw, _user_prepare_app_root, state["app_dir"])
    with FileLock("ports"):
        previous = read_json(app_state_path(domain_id))
        # The helper's own port wins over the panel's copy (stored_port()); the panel's port only
        # counts for an application without a stored state.
        state["port"] = allocate_port(domain_id, stored_port(previous) or state["port"], state["port_range"])
        for key in FLAG_KEYS:
            state[key] = previous.get(key, CLEARED_FLAGS[key]) if isinstance(previous, dict) and not resume \
                else CLEARED_FLAGS[key]
        state["updated_epoch"] = time.time()
        write_json(app_state_path(domain_id), state)
    if not previous or previous.get("app_dir") != state["app_dir"]:
        write_json(app_triggers_path(domain_id), trigger_mtimes(pw, state["app_dir"]))
    write_units(state, pw)
    if state["listen"] != "unix":
        remove_socket_dir(domain_id)
    systemctl("daemon-reload", check=True)
    app_unit, path_unit = UNIT_APP % domain_id, UNIT_PATH % domain_id
    if state["enabled"] and not state["suspended"]:
        if state["auto_deploy"]:
            systemctl("enable", path_unit, check=True)
            systemctl("restart", path_unit)
        else:
            systemctl("disable", "--now", path_unit)
        if state["stopped"]:
            # Stopped by the user (or contained by Runway): enabled for builds, but not running.
            systemctl("disable", "--now", app_unit, timeout=120)
        else:
            systemctl("enable", app_unit, check=True)
            if start and (restart or not unit_is_active(app_unit)):
                prepare_start(state, pw)
                systemctl("reset-failed", app_unit)
                systemctl("restart", "--no-block", app_unit)
    else:
        # Stop triggers first, then any running build (its cgroup is killed), then the app.
        systemctl("disable", "--now", path_unit)
        systemctl("stop", UNIT_DEPLOY % domain_id, timeout=150)
        systemctl("disable", "--now", app_unit)
    return {"port": state["port"], "state": state, "switchable": False, "job": None}


def _zd_app_apply(state, pw, restart, start, resume):
    """app-apply of an application that has, gets or had zero-downtime slots (the deploy lock is
    held): renders both slots, keeps the live instance running, writes the pointer, and starts
    the switch job for a restart (docs/DESIGN.md section 12.5)."""
    domain_id = state["domain_id"]
    ensure_layout()
    if state["listen"] == "unix":
        web_server_group()
    call_as_user(pw, _user_prepare_app_root, state["app_dir"])
    with FileLock("ports"):
        previous = read_json(app_state_path(domain_id))
        previous = previous if isinstance(previous, dict) else None
        # The helper's own port wins over the panel's copy (a switch may have given the 1.0 unit
        # a new one).
        state["port"] = allocate_port(domain_id, stored_port(previous) or state["port"], state["port_range"])
        for key in FLAG_KEYS:
            state[key] = previous.get(key, CLEARED_FLAGS[key]) if previous and not resume else CLEARED_FLAGS[key]
        state.update(helper_fields(previous))
        if previous and zd_has_slots(state) and (previous.get("listen") != state["listen"] or previous.get("sysuser") != state["sysuser"]
                                                 or previous.get("app_dir") != state["app_dir"]):
            # The web server configuration or the socket owner changes: the next restart is plain,
            # also while the 1.0 unit is still the live instance (a switch would leave the site
            # without a backend between Plesk's regeneration and the pointer move, and a new system
            # user does not own the running instance's socket).
            state["restart_plain"] = True
        if state["zero_downtime"] and state["listen"] == "tcp":
            if not state["port_a"]:
                state["port_a"] = state["port"]
            if not state["port_b"] or state["port_b"] in (state["port"], state["port_a"]):
                state["port_b"] = allocate_extra_port(domain_id, state["port_range"], {state["port"], state["port_a"]})
        elif not state["slot"]:
            state["port_a"] = state["port_b"] = 0
        state["updated_epoch"] = time.time()
        write_json(app_state_path(domain_id), state)
    if not previous or previous.get("app_dir") != state["app_dir"]:
        write_json(app_triggers_path(domain_id), trigger_mtimes(pw, state["app_dir"]))
    active = state["enabled"] and not state["suspended"]
    live = state["slot"]
    if live and (not state["zero_downtime"] or state["listen"] == "none") \
            and (not active or state["stopped"] or not unit_is_active(app_unit(domain_id, live))):
        # Turned off (or a worker now) while nothing runs: back to the 1.0 unit at once.
        state = retire_slots(state, pw)
        live = ""
    elif not zd_has_slots(state) and slot_files_left(domain_id):
        # Turned off before the first switch (the slots were rendered but never ran): their units
        # and environment files go now.
        state = retire_slots(state, pw)
    if zd_has_slots(state):
        ensure_converge_unit()
    write_units(state, pw)
    if pointer_wanted(state):
        if write_pointer(state, pw, live):
            web_unit, web_kind = web_traffic_server()
            if web_unit and config_references(state, "%s/%d." % (WEB_DIR, domain_id)):
                # The include is in use: the traffic reaches the live instance before any other
                # instance stops below.
                with FileLock("web-reload"):
                    web_reload_confirm(web_unit, web_kind)
    elif state["listen"] == "unix":
        write_tmpfiles(state, pw)
    if state["listen"] != "unix":
        remove_socket_dir(domain_id)
        remove_quietly(tmpfiles_path(domain_id))
    systemctl("daemon-reload", check=True)
    path_unit = UNIT_PATH % domain_id
    live_unit = app_unit(domain_id, live)
    others = [unit for unit in existing_app_units(domain_id) if unit != live_unit]
    job = None
    if active:
        if state["auto_deploy"]:
            systemctl("enable", path_unit, check=True)
            systemctl("restart", path_unit)
        else:
            systemctl("disable", "--now", path_unit)
        if state["stopped"]:
            # Stopped by the user (or contained by Runway): enabled for builds, but not running.
            systemctl("disable", "--now", *existing_app_units(domain_id), timeout=120)
        else:
            if others:
                systemctl("disable", "--now", *others, timeout=120)
            systemctl("enable", live_unit, check=True)
            running = unit_is_active(live_unit)
            if start and restart and running and not state["restart_plain"] and zd_switchable(state) and zd_target(state) is not None:
                job = start_deploy_job(domain_id, "restart", False)["job"]
            elif start and (restart or not running):
                state = zd_plain_restart(state, pw)[0]
    else:
        systemctl("disable", "--now", *existing_app_units(domain_id), timeout=120)
    return {"port": state["port"], "state": state, "switchable": zd_switchable(state), "job": job}


def cmd_app_remove(payload):
    domain_id = v_domain_id((payload or {}).get("domain_id"))
    remove_app(domain_id)
    return {"removed": domain_id}


def remove_app(domain_id):
    """Stops and deletes everything of an application: its units (the 1.0 unit and both
    zero-downtime slots), environment files, state, tmpfiles entry, socket directory, root link,
    web server include files and job files (the ports are free with the state file)."""
    units = [UNIT_PATH % domain_id, UNIT_DEPLOY % domain_id] + [
        unit for unit in all_app_units(domain_id)
        if unit == UNIT_APP % domain_id or os.path.exists(os.path.join(UNIT_DIR, unit))]
    systemctl("disable", "--now", *units, timeout=120)
    for unit in units:
        remove_quietly(os.path.join(UNIT_DIR, unit))
    for slot in ("",) + SLOTS:
        remove_quietly(env_file_path(domain_id, slot))
    remove_quietly(app_state_path(domain_id))
    remove_quietly(app_triggers_path(domain_id))
    remove_quietly(tmpfiles_path(domain_id))
    remove_socket_dir(domain_id)
    remove_link(domain_id)
    remove_include(domain_id)
    for path in job_paths("deploy-%d" % domain_id):
        remove_quietly(path)
    remove_quietly(health_watch_path(domain_id))
    systemctl("daemon-reload")
    systemctl("reset-failed", *units)
    sync_health_units()


def cmd_app_action(payload):
    """start | restart: explicit start (clears "stopped"/"tampered", enables and starts the unit);
    stop: stops and disables the unit and remembers it ("stopped": also across reboots, trigger
    files and deployments, until the next start); recover: restart of an application that hit
    systemd's start limit (Reconcile; refused for stopped applications)."""
    domain_id = v_domain_id((payload or {}).get("domain_id"))
    action = (payload or {}).get("action")
    state, pw = load_app_state(domain_id)
    if zd_has_slots(state):
        return _zd_app_action(state, pw, action, bool((payload or {}).get("plain")))
    unit = UNIT_APP % domain_id
    if action in ("start", "restart", "recover"):
        if not state["enabled"]:
            raise HelperError("The application is disabled")
        if state["suspended"]:
            raise HelperError("The domain is suspended")
        if action == "recover":
            if state["stopped"]:
                raise HelperError("The application is stopped")
        elif state["stopped"] or state["tampered"]:
            update_state_flags(domain_id, **CLEARED_FLAGS)
            state.update(CLEARED_FLAGS)
        prepare_start(state, pw)
        systemctl("enable", unit, check=True)
        systemctl("reset-failed", unit)
        systemctl("restart" if action == "restart" else "start", "--no-block", unit, check=True)
    elif action == "stop":
        update_state_flags(domain_id, stopped=True)
        systemctl("disable", "--now", unit, check=True, timeout=120)
    else:
        raise HelperError("Invalid action")
    return {"action": action}


def _zd_app_action(state, pw, action, plain):
    """app-action of an application with zero-downtime slots (docs/DESIGN.md section 12.5):
    restart of a running application starts the switch job ({action, job}); plain (Restart in
    place), start and recover act on the live unit; stop stops every app unit."""
    domain_id = state["domain_id"]
    if action == "stop":
        update_state_flags(domain_id, stopped=True)
        systemctl("disable", "--now", *existing_app_units(domain_id), check=True, timeout=120)
        return {"action": action}
    if action not in ("start", "restart", "recover"):
        raise HelperError("Invalid action")
    if not state["enabled"]:
        raise HelperError("The application is disabled")
    if state["suspended"]:
        raise HelperError("The domain is suspended")
    if action == "recover" and state["stopped"]:
        raise HelperError("The application is stopped")
    lock = FileLock("deploy-%d" % domain_id)
    busy = unit_is_active(UNIT_DEPLOY % domain_id) or not lock.acquire(blocking=False)
    try:
        if not busy and state["switch"]:
            # An interrupted switch is settled from the pointer first, so the instance that carries
            # the traffic is the one started or restarted (docs/DESIGN.md section 12.8).
            try:
                zd_converge_locked(state, pw)
            except HelperError:
                pass
            state, pw = load_app_state(domain_id)
        live_unit = app_unit(domain_id, state["slot"])
        if action == "restart" and (busy or plain or unit_is_active(live_unit)):
            if busy:
                raise HelperError("A deployment is already running for this application")
            if action != "recover" and (state["stopped"] or state["tampered"]):
                update_state_flags(domain_id, **CLEARED_FLAGS)
                state.update(CLEARED_FLAGS)
            if not plain and not state["restart_plain"] and zd_switchable(state) and zd_target(state) is not None:
                return {"action": action, "job": start_deploy_job(domain_id, "restart", False)["job"]}
            zd_plain_restart(state, pw)
            return {"action": action}
        if action != "recover" and (state["stopped"] or state["tampered"]):
            update_state_flags(domain_id, **CLEARED_FLAGS)
            state.update(CLEARED_FLAGS)
        if not busy:
            if not state["zero_downtime"] and state["slot"]:
                # Turned off and nothing runs: the 1.0 unit starts instead of the slot.
                zd_plain_restart(state, pw)
                return {"action": action}
            if pointer_wanted(state) and write_pointer(state, pw, state["slot"]):
                web_unit = web_traffic_server()[0]
                if web_unit:
                    with FileLock("web-reload"):
                        web_reload_nowait(web_unit)
        prepare_start(live_view(state), pw)
        systemctl("enable", live_unit, check=True)
        systemctl("reset-failed", live_unit)
        systemctl("restart" if action == "restart" else "start", "--no-block", live_unit, check=True)
        return {"action": action}
    finally:
        if not busy:
            lock.release()


DEPLOY_TITLES = {"build": "Build & restart", "restart": "Restart", "fetch": "Fetch & restart"}
# Titles of deployments of a stopped application (Stop persists): they build or fetch, but never start.
DEPLOY_TITLES_STOPPED = {"build": "Build (application stopped)",
                         "restart": "Restart skipped (application stopped)",
                         "fetch": "Fetch (application stopped)"}
DEPLOY_TITLE_KEYS_STOPPED = {"build": "deploy_build_only", "restart": "deploy_restart_skipped",
                             "fetch": "deploy_fetch_only"}


def deploy_title(mode, stopped):
    """(title, title_key) of a deploy job: the English title and the key the panel translates."""
    if stopped:
        return DEPLOY_TITLES_STOPPED[mode], DEPLOY_TITLE_KEYS_STOPPED[mode]
    return DEPLOY_TITLES[mode], "deploy_" + mode


def cmd_app_deploy(payload):
    payload = payload or {}
    domain_id = v_domain_id(payload.get("domain_id"))
    fetch = v_fetch(payload["fetch"]) if payload.get("fetch") else None
    mode = "fetch" if fetch else ("build" if bool(payload.get("build", True)) else "restart")
    state, _pw = load_app_state(domain_id)
    if not state["enabled"]:
        raise HelperError("The application is disabled")
    if state["suspended"]:
        raise HelperError("The domain is suspended")
    job = "deploy-%d" % domain_id
    unit = UNIT_DEPLOY % domain_id
    lock = FileLock(job)
    # The deploy job holds this lock while it runs; a running job means "busy".
    if unit_is_active(unit) or not lock.acquire(blocking=False):
        raise HelperError("A deployment is already running for this application")
    try:
        stopped = state["stopped"] or state["tampered"]
        if payload.get("start") and stopped:
            # "Build & restart" in the panel is an explicit start: it clears "stopped". Deploys
            # from the CLI, fetches and trigger files build a stopped application but keep it stopped.
            update_state_flags(domain_id, **CLEARED_FLAGS)
            systemctl("enable", app_unit(domain_id, state["slot"]))
            stopped = False
        return start_deploy_job(domain_id, mode, stopped, fetch)
    finally:
        lock.release()


def start_deploy_job(domain_id, mode, stopped, fetch=None):
    """Queues a request for the deploy unit and starts it (the caller holds the deploy lock)."""
    job = "deploy-%d" % domain_id
    unit = UNIT_DEPLOY % domain_id
    title, title_key = deploy_title(mode, stopped)
    ensure_helper_copy()
    _status_path, _log, request_path = job_paths(job)
    ensure_dir(JOBS_DIR, 0o700)
    request = {"mode": mode, "source": "panel"}
    if fetch:
        request["fetch"] = fetch
    write_json(request_path, request)
    job_set_status(job, state="queued", title=title, title_key=title_key, title_params={},
                   queued_at=now_iso(), queued_epoch=time.time(), started_at=None, finished_at=None, message=None,
                   phase="", slot_from=None, slot_to=None)
    systemctl("reset-failed", unit)
    proc = systemctl("start", "--no-block", unit)
    if proc.returncode != 0:
        remove_quietly(request_path)
        job_set_status(job, state="failed", finished_at=now_iso(), message=proc.stderr.strip())
        raise HelperError("Could not start deployment: %s" % proc.stderr.strip())
    return {"job": job}
