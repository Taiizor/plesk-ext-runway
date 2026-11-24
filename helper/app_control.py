# Copyright 2026 Taiizor. Licensed under the MIT License.

def cmd_app_apply(payload):
    result = _app_apply(payload)
    # The health watch timer exists while an application has the watch on.
    sync_health_units()
    sync_public_files_units(result["state"])
    return result


# An application's deploy lock: a deployment holds it for its whole job; a save, Start, Restart,
# Recover, the health watch, the convergence, a re-render and a policy change hold it for seconds.
# Seconds a command waits for such a short holder (None: DEPLOY_LOCK_WAIT, read at call time).
DEPLOY_LOCK_WAIT = 30
STOP_LOCK_WAIT = 10


def try_deploy_lock(domain_id, wait=None):
    """(lock, None) with the deploy lock of an application held (the caller releases it); (None,
    "deployment") while its deploy unit is active (a deployment holds the lock or waits for it: it
    goes first); (None, "busy") when another operation kept the lock for `wait` seconds."""
    unit = UNIT_DEPLOY % domain_id
    lock = FileLock("deploy-%d" % domain_id)
    deadline = time.time() + (DEPLOY_LOCK_WAIT if wait is None else wait)
    while True:
        if unit_is_active(unit):
            return None, "deployment"
        if lock.acquire(blocking=False):
            if not unit_is_active(unit):
                return lock, None
            # A deployment started meanwhile and waits for this lock.
            lock.release()
            return None, "deployment"
        if time.time() >= deadline:
            return None, "busy"
        time.sleep(0.5)


def deploy_lock(domain_id, deployment_message, busy_message=None):
    """try_deploy_lock() for a command: the held lock, or a HelperError with the reason's message
    and code ("deployment_running" or "operation_in_progress": the panel words them itself)."""
    lock, reason = try_deploy_lock(domain_id)
    if lock is None:
        if reason == "deployment":
            raise HelperError(deployment_message, code="deployment_running")
        raise HelperError(busy_message or "Another operation of this application is still in progress. Please try again in a moment.",
                          code="operation_in_progress")
    return lock


def contain_tampering_waiting(state, pw, detail):
    """contain_tampering() for callers without the deploy lock (status queries, Reconcile): it
    waits up to STOP_LOCK_WAIT for a Start in progress, which could otherwise run the application
    again right after the containment; never for a deployment, and it contains anyway when the
    lock stays busy (security first). With the lock it checks again first: the operation it
    waited for may have removed the entry (prepare_start unlinks it) or changed the application.
    `state` (the caller's stored state) gets the flags of a containment."""
    lock = try_deploy_lock(state["domain_id"], STOP_LOCK_WAIT)[0]
    try:
        current = state
        if lock is not None:
            current = read_json(app_state_path(state["domain_id"]))
            if not isinstance(current, dict) or current.get("listen") != "unix" or current.get("tampered"):
                return
            found = socket_check(current, pw)
            if not found:
                return
            detail = found[0]
        contain_tampering(current, detail)
        if current is not state:
            state.update({key: current[key] for key in ("stopped", "tampered", "tampered_detail")})
    finally:
        if lock is not None:
            lock.release()


def _app_apply(payload):
    payload = dict(payload or {})
    keep_env = "env" not in payload
    if keep_env:
        # The panel omits "env" when it did not load/edit it: keep the stored secrets (read again
        # under the deploy lock below; this copy only serves the checks before it).
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
    # Every writer shares the deploy lock, including classic applications: a concurrent save
    # must never restore an old unconfined unit while an administrator enables isolation.
    if not state["enabled"] or state["suspended"]:
        # Disabling or suspension ends a running deployment first (a switch finishes or rolls back).
        systemctl("disable", "--now", UNIT_PATH % domain_id)
        systemctl("stop", UNIT_DEPLOY % domain_id, timeout=ZD_DEPLOY_STOP + 30)
        lock = FileLock("deploy-%d" % domain_id)
        if not lock.acquire(blocking=True, timeout=60):
            raise HelperError("Another operation of this application is still in progress. Please try again in a moment.",
                              code="operation_in_progress")
    else:
        # A running deployment refuses the save at once (the 1.0 wording, docs/DESIGN.md section
        # 12.5; the smoke tests match on it); a short operation (the health watch, the convergence,
        # another save) is waited for.
        lock = deploy_lock(domain_id, "A deployment is running for this application. Wait until it finishes, then save again.",
                           "Another deployment or settings change is in progress. Wait until it finishes, then save again.")
    try:
        stored = read_json(app_state_path(domain_id))
        if keep_env:
            # A save or a restore that ended while this one waited for the lock may have changed them.
            payload["env"] = stored.get("env", {}) if isinstance(stored, dict) else {}
        state, pw = validate_app(payload)
        if state["zero_downtime"] or (isinstance(stored, dict) and (zd_has_slots(helper_fields(stored)) or stored.get("zero_downtime")
                                                                    or slot_files_left(domain_id))):
            if isinstance(stored, dict) and helper_fields(stored)["switch"]:
                # An interrupted switch is settled from the pointer before anything is re-pointed
                # or stopped (the instance that carries the traffic must keep running).
                try:
                    current, current_pw = load_app_state(domain_id)
                    zd_converge_locked(current, current_pw)
                except HelperError:
                    pass
            return _zd_app_apply(state, pw, restart, start, resume, actor=ops_actor(payload.get("actor")))
        return _classic_app_apply(state, pw, restart, start, resume)
    finally:
        lock.release()


def _classic_app_apply(state, pw, restart, start, resume):
    domain_id = state["domain_id"]
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


def _zd_app_apply(state, pw, restart, start, resume, actor="system"):
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
                job = start_deploy_job(domain_id, "restart", False, actor=actor)["job"]
            elif start and (restart or not running):
                state = zd_plain_restart(state, pw)[0]
    else:
        systemctl("disable", "--now", *existing_app_units(domain_id), timeout=120)
    return {"port": state["port"], "state": state, "switchable": zd_switchable(state), "job": job}


def cmd_app_remove(payload):
    domain_id = v_domain_id((payload or {}).get("domain_id"))
    remove_app(domain_id)
    return {"removed": domain_id}


def remove_app(domain_id, force=False):
    """Stops and deletes everything of an application: its units (the 1.0 unit and both
    zero-downtime slots), environment files, state, tmpfiles entry, socket directory, root link,
    web server include files and job files (the ports are free with the state file). The removal
    waits up to LOCK_TIMEOUT for the deploy lock (its holders are short once the deploy unit is
    stopped); force (uninstall) removes everything also when another operation keeps it longer."""
    units = [UNIT_PATH % domain_id, UNIT_DEPLOY % domain_id] + [
        unit for unit in all_app_units(domain_id)
        if unit == UNIT_APP % domain_id or os.path.exists(os.path.join(UNIT_DIR, unit))]
    units += [unit for unit in (UNIT_PUBLIC_FILES_TIMER % domain_id, UNIT_PUBLIC_FILES % domain_id)
              if os.path.exists(os.path.join(UNIT_DIR, unit))]
    # First the transient timers (runway-rerender-<id>, runway-redeploy-<id>): none of them may
    # write the units again or start a deployment while the units stop.
    systemctl("stop", UNIT_RERENDER_TIMER % domain_id, UNIT_RERENDER % domain_id,
              "runway-redeploy-%d.timer" % domain_id, "runway-redeploy-%d.service" % domain_id, timeout=60)
    systemctl("disable", "--now", *units, timeout=120)
    lock = FileLock("deploy-%d" % domain_id)
    if not lock.acquire(blocking=True, timeout=LOCK_TIMEOUT) and not force:
        raise HelperError("Another operation of this application is still in progress. Please try again in a moment.",
                          code="operation_in_progress")
    try:
        # A writer may have completed while removal waited; drain any newly created slots too.
        units = list(dict.fromkeys(units + existing_app_units(domain_id)))
        systemctl("disable", "--now", *units, timeout=120)
        _remove_app_files(domain_id, units)
    finally:
        lock.release()


def _remove_app_files(domain_id, units):
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
    remove_quietly(rerender_marker_path(domain_id))
    ops_remove_metadata(domain_id)
    # Isolation is an administrator policy: customer removal/recreation and recovery must keep it.
    systemctl("daemon-reload")
    systemctl("reset-failed", *units)
    sync_health_units()


def cmd_app_action(payload):
    """start | restart: explicit start (clears "stopped"/"tampered", enables and starts the unit);
    stop: stops and disables the unit and remembers it ("stopped": also across reboots, trigger
    files and deployments, until the next start); recover: restart of an application that hit
    systemd's start limit (Reconcile; refused for stopped applications)."""
    payload = payload or {}
    domain_id = v_domain_id(payload.get("domain_id"))
    action = payload.get("action")
    state, pw = load_app_state(domain_id)
    if action not in ("start", "restart", "recover"):
        # Stop waits a moment for a Start or a save in progress, so it is not overridden by it, but
        # never for a deployment: it also stops a running switch (docs/DESIGN.md section 12.4), and
        # it goes ahead without the lock when the lock stays busy.
        lock = try_deploy_lock(domain_id, STOP_LOCK_WAIT)[0] if action == "stop" else None
        try:
            if lock is not None:
                state, pw = load_app_state(domain_id)
            return _app_action(state, pw, action, payload)
        finally:
            if lock is not None:
                lock.release()
    # Start, Restart and Recover share the deploy lock with every writer of the units, so none of
    # them starts a unit while a save or an isolation policy change rewrites it (docs/DESIGN.md
    # section 12.5): a running deployment refuses them, a short operation is waited for.
    stopped_before = bool(state["stopped"])
    lock = deploy_lock(domain_id, "A deployment is already running for this application",
                       "Another operation of this application is still in progress. Please try again in a moment.")
    try:
        state, pw = load_app_state(domain_id)
        if state["stopped"] and not stopped_before and action != "recover":
            # A Stop (or a containment) arrived while this action waited: the later request wins.
            raise HelperError("The application was stopped while this action waited; start it again", code="stopped_meanwhile")
        return _app_action(state, pw, action, payload)
    finally:
        lock.release()


def _app_action(state, pw, action, payload):
    if zd_has_slots(state):
        actor = ops_actor(payload.get("actor"))
        result = _zd_app_action(state, pw, action, bool(payload.get("plain")), actor=actor)
        ops_event(state, "app_stop" if action == "stop" else "app_start", {"action": action, "actor": actor})
        return result
    return _classic_app_action(state, pw, action, payload)


def _classic_app_action(state, pw, action, payload):
    domain_id = state["domain_id"]
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
    ops_event(state, "app_stop" if action == "stop" else "app_start", {"action": action, "actor": ops_actor(payload.get("actor"))})
    return {"action": action}


def _zd_app_action(state, pw, action, plain, actor="system"):
    """app-action of an application with zero-downtime slots (docs/DESIGN.md section 12.5; start,
    restart and recover run under the deploy lock, see cmd_app_action): restart of a running
    application starts the switch job ({action, job}); plain (Restart in place), start and recover
    act on the live unit; stop stops every app unit."""
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
    if state["switch"]:
        # An interrupted switch is settled from the pointer first, so the instance that carries
        # the traffic is the one started or restarted (docs/DESIGN.md section 12.8).
        try:
            zd_converge_locked(state, pw)
        except HelperError:
            pass
        state, pw = load_app_state(domain_id)
    live_unit = app_unit(domain_id, state["slot"])
    if action == "restart" and (plain or unit_is_active(live_unit)):
        if state["stopped"] or state["tampered"]:
            update_state_flags(domain_id, **CLEARED_FLAGS)
            state.update(CLEARED_FLAGS)
        if not plain and not state["restart_plain"] and zd_switchable(state) and zd_target(state) is not None:
            return {"action": action, "job": start_deploy_job(domain_id, "restart", False, actor=actor)["job"]}
        zd_plain_restart(state, pw)
        return {"action": action}
    if action != "recover" and (state["stopped"] or state["tampered"]):
        update_state_flags(domain_id, **CLEARED_FLAGS)
        state.update(CLEARED_FLAGS)
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


DEPLOY_TITLES = {"build": "Build & restart", "restart": "Restart", "fetch": "Fetch & restart", "rollback": "Roll back release"}
# Titles of deployments of a stopped application (Stop persists): they build or fetch, but never start.
DEPLOY_TITLES_STOPPED = {"build": "Build (application stopped)",
                         "restart": "Restart skipped (application stopped)",
                         "fetch": "Fetch (application stopped)", "rollback": "Select release (application stopped)"}
DEPLOY_TITLE_KEYS_STOPPED = {"build": "deploy_build_only", "restart": "deploy_restart_skipped",
                             "fetch": "deploy_fetch_only", "rollback": "deploy_rollback_only"}


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
    # The deploy job holds this lock while it runs: a running job refuses the request at once, a
    # short holder (the health watch, a save) is waited for.
    lock = deploy_lock(domain_id, "A deployment is already running for this application")
    try:
        # What the operation waited for (a save, a Stop) may have changed the state.
        state, _pw = load_app_state(domain_id)
        if not state["enabled"]:
            raise HelperError("The application is disabled")
        if state["suspended"]:
            raise HelperError("The domain is suspended")
        stopped = state["stopped"] or state["tampered"]
        if payload.get("start") and stopped:
            # "Build & restart" in the panel is an explicit start: it clears "stopped". Deploys
            # from the CLI, fetches and trigger files build a stopped application but keep it stopped.
            update_state_flags(domain_id, **CLEARED_FLAGS)
            systemctl("enable", app_unit(domain_id, state["slot"]))
            stopped = False
        return start_deploy_job(domain_id, mode, stopped, fetch, actor=ops_actor(payload.get("actor")))
    finally:
        lock.release()


def start_deploy_job(domain_id, mode, stopped, fetch=None, release=None, actor="system"):
    """Queues a request for the deploy unit and starts it (the caller holds the deploy lock)."""
    job = "deploy-%d" % domain_id
    unit = UNIT_DEPLOY % domain_id
    title, title_key = deploy_title(mode, stopped)
    ensure_helper_copy()
    _status_path, _log, request_path = job_paths(job)
    ensure_dir(JOBS_DIR, 0o700)
    request = {"mode": mode, "source": "panel", "actor": ops_actor(actor)}
    if release:
        request["release"] = ops_valid_release(release)
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
