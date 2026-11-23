# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Deploy job (runs inside runway-deploy-<id>.service as root)
# ---------------------------------------------------------------------------

def _build_preexec(pw, app_root):
    def preexec():
        drop_privileges(pw)
        os.umask(0o027)
        os.chdir(app_root)
    return preexec


class DeployTerminated(HelperError):
    """SIGTERM from systemd while a deployment runs (TimeoutStartSec reached, or the unit was stopped
    because the application was disabled or its domain suspended)."""


def _triggers_moved(domain_id):
    """True when a trigger file changed after the last snapshot (e.g. touched during a build)."""
    try:
        state, pw = load_app_state(domain_id)
    except HelperError:
        return False
    if not state["auto_deploy"]:
        return False
    now = trigger_mtimes(pw, state["app_dir"])
    seen = read_json(app_triggers_path(domain_id), {}) or {}
    return any(now.get(key) and now.get(key) != seen.get(key) for key in ("deploy", "restart"))


def _rearm_deploy(domain_id):
    """Starts the deploy unit again shortly after this run ended (a trigger file changed when no
    time was left in this run): the path unit does not report changes made while its service runs."""
    run(["systemd-run", "--on-active=60", "--unit=runway-redeploy-%d" % domain_id, "--collect", "--quiet",
         "--description=Runway: deploy again (trigger file changed during a deployment)",
         "/usr/bin/systemctl", "start", "--no-block", UNIT_DEPLOY % domain_id], timeout=60)


def internal_deploy(domain_id):
    job = "deploy-%d" % domain_id
    lock = FileLock(job)
    # The panel's app-apply and the convergence hold the lock briefly (zero-downtime slots).
    if not lock.acquire(blocking=True, timeout=120):
        _deploy_lock_busy(domain_id, job)
        return
    started = time.time()

    def on_term(_signum, _frame):
        if _TERM["critical"]:
            # A zero-downtime switch moved (or is moving) the traffic: it finishes first.
            _TERM["pending"] = True
            return
        try:
            limit = deploy_timeout(load_app_state(domain_id)[0])
        except HelperError:
            limit = 0
        if limit and time.time() - started >= limit - 10:
            raise DeployTerminated("The deployment was killed by the deploy unit timeout (%d s)." % limit)
        raise DeployTerminated("The deployment was stopped (the application was disabled, its domain was "
                               "suspended or the deploy unit was stopped).")

    signal.signal(signal.SIGTERM, on_term)
    try:
        # Up to three rounds: a panel request queued meanwhile, or a trigger file touched while the
        # previous round ran (systemd's path unit does not watch while the deploy unit runs).
        for _round in range(3):
            _deploy_once(domain_id, job)
            if _TERM["pending"]:
                break
            if os.path.exists(job_paths(job)[2]):
                continue
            if not _triggers_moved(domain_id):
                break
            try:
                state = load_app_state(domain_id)[0]
            except HelperError:
                break
            # Every round may build and switch: the same allowance deploy_timeout() adds.
            if time.time() - started + state["build_timeout"] + 300 + switch_allowance(state) > deploy_timeout(state) \
                    or _round == 2:
                _rearm_deploy(domain_id)
                break
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        lock.release()


def open_public_files(state, pw):
    """The step that makes the files in the application's document root readable for the web
    server (docs/DESIGN.md section 7, Public files), as the system user: None when the application
    has no stored document root (workers never have one) or it does not lie strictly inside the
    application root, else {changed, skipped_links, truncated, passable} (_user_open_public_files).
    Raises HelperError."""
    rel = state.get("document_root") or ""
    if not rel or state.get("listen") == "none":
        return None
    try:
        absolute = v_document_root(rel, pw.pw_dir)[1]
    except HelperError:
        return None
    try:
        web_gid = grp.getgrnam(WEB_GROUP).gr_gid
    except KeyError:
        web_gid = -1
    return call_as_user(pw, _user_open_public_files, state["app_dir"], absolute, PUBLIC_FILES_MAX,
                        PUBLIC_FILES_SECONDS, web_gid, timeout=PUBLIC_FILES_SECONDS + 30)


def public_files_summary(result, path):
    """One line about a run of open_public_files() (deploy log)."""
    notes = []
    if result.get("passable"):
        count = int(result["passable"])
        notes.append("o+x for %d folder%s on the way to it" % (count, "" if count == 1 else "s"))
    if result.get("skipped_links"):
        count = int(result["skipped_links"])
        notes.append("%d symbolic link%s skipped" % (count, "" if count == 1 else "s"))
    if result.get("truncated"):
        notes.append("stopped at the limit of %d entries, %d seconds or %d folder levels: the rest was not checked"
                     % (PUBLIC_FILES_MAX, PUBLIC_FILES_SECONDS, PUBLIC_FILES_DEPTH))
    return "Made %d files and folders in %s readable for the web server%s" % (
        int(result.get("changed") or 0), path, " (%s)" % "; ".join(notes) if notes else "")


def deploy_open_public_files(state, pw, log):
    """Deploy job, after a build or fetch: open_public_files() as one line of the deploy log. A
    failure is logged and never fails the deployment (a SIGTERM of the deploy unit still ends it)."""
    path = os.path.normpath(pw.pw_dir) + "/" + state["document_root"] if state.get("document_root") else ""
    try:
        result = open_public_files(state, pw)
    except DeployTerminated:
        raise
    except Exception as exc:  # noqa: BLE001 - the deployment goes on
        log.line("WARNING: the files in the document root %s could not be made readable for the web server: %s"
                 % (path, exc))
        return
    if result is not None:
        log.line(public_files_summary(result, path))


def _deploy_lock_busy(domain_id, job):
    """The deploy lock stayed busy: a panel request fails with the reason, and the job starts again
    a minute later so a trigger file is not lost."""
    request_path = job_paths(job)[2]
    if os.path.exists(request_path):
        remove_quietly(request_path)
        job_set_status(job, state="failed", finished_at=now_iso(), exit_code=1,
                       message="Another operation of this application held its lock for two minutes; the deployment "
                               "did not start. Try again.")
    else:
        _rearm_deploy(domain_id)


def restart_and_check(state, pw, unit, log, restarted=False):
    """Restarts `unit` (unless `restarted`) and checks that it runs and listens on the endpoint of
    `state` (a slot view for zero-downtime slots). Returns (ok, message); raises HelperError."""
    if not restarted:
        prepare_start(state, pw)
        log.line("Restarting %s" % unit)
        systemctl("reset-failed", unit)
        proc = systemctl("restart", unit, timeout=120)
        if proc.returncode != 0:
            raise HelperError("systemctl restart failed: %s" % proc.stderr.strip())
    if state["listen"] == "none":
        time.sleep(3)
        if not unit_running(unit):
            raise HelperError("The worker is not running (it keeps exiting). Check the application log.")
        log.line("Worker is running (workers have no listener to check).")
        return True, None
    deadline = time.time() + 30
    listener, detail = "none", ""
    while time.time() < deadline:
        listener, detail = listener_state(state, pw)
        if listener != "none" or not unit_is_active(unit):
            break
        time.sleep(0.5)
    endpoint = endpoint_socket(state) if state["listen"] == "unix" else "127.0.0.1:%d" % int(state["port"])
    hint = "RUNWAY_SOCKET" if state["listen"] == "unix" else "PORT"
    if listener == "tampered":
        contain_tampering(state, detail)
        raise HelperError("The socket path was tampered with (%s); the application was stopped." % detail)
    if listener == "foreign":
        raise HelperError("Another user's process holds the application endpoint (%s). "
                          "The application cannot serve the domain until it is released." % detail)
    if listener == "ok":
        log.line("Application is listening on %s" % endpoint)
        return True, None
    if not unit_running(unit):
        raise HelperError("The service is not running (it keeps exiting). Check the application log.")
    if unit_is_active(unit):
        log.line("WARNING: the service is running but nothing listens on %s yet. "
                 "Make sure the application listens on the %s environment variable." % (endpoint, hint))
        return True, "Service running, but nothing listens on %s yet" % endpoint
    raise HelperError("The service stopped right after starting. Check the application log.")


def _deploy_once(domain_id, job):
    _status_path, _log_path, request_path = job_paths(job)
    request = read_json(request_path)
    remove_quietly(request_path)
    state, pw = load_app_state(domain_id)
    if state.get("switch"):
        zd_converge_locked(state, pw)
        state, pw = load_app_state(domain_id)
    triggers_now = trigger_mtimes(pw, state["app_dir"])
    fetch = None
    if isinstance(request, dict):
        mode = request.get("mode") if request.get("mode") in DEPLOY_TITLES else "restart"
        fetch = request.get("fetch") if mode == "fetch" else None
        source = "panel"
    else:
        seen = read_json(app_triggers_path(domain_id), {}) or {}
        if triggers_now.get("deploy") and triggers_now.get("deploy") != seen.get("deploy"):
            mode = "build"
        elif triggers_now.get("restart") and triggers_now.get("restart") != seen.get("restart"):
            mode = "restart"
        else:
            return
        source = "trigger file"
    write_json(app_triggers_path(domain_id), triggers_now)
    if not state["enabled"] or state["suspended"]:
        if source == "panel":
            job_set_status(job, state="failed", finished_at=now_iso(),
                           message="The domain is suspended" if state["suspended"] else "The application is disabled")
        return
    queued = {} if source == "panel" else {"queued_at": now_iso(), "queued_epoch": time.time()}
    # A stopped application is built (or fetched) but not started: the title says so.
    title, title_key = deploy_title(mode, state["stopped"])
    job_set_status(job, state="running", title=title, title_key=title_key, title_params={},
                   started_at=now_iso(), finished_at=None, source=source, message=None, **queued)
    log = JobLog(job)
    ok = False
    message = None
    options = ops_options(domain_id)
    record = ops_begin(state, mode, "request" if source == "panel" else source,
                       request.get("actor") if isinstance(request, dict) else "trigger file")
    release = None
    created = False
    release_context = {"previous": None, "switch": False}
    # In-place builds always use the logical source, even while a previous isolated release runs.
    build_state = dict(state, _release_dir=state["app_dir"])
    try:
        log.line("Deployment started (%s, triggered from %s)" % (mode, source))
        log.line("Application root: %s" % state["app_dir"])
        if not call_as_user(pw, os.path.isdir, state["app_dir"]):
            raise HelperError("Application root %s does not exist or is not accessible" % state["app_dir"])
        ops_preflight(state, pw, options)
        if mode == "rollback":
            if not options["releases"]:
                raise HelperError("Release management is disabled")
            release = ops_valid_release(request.get("release"))
            entry = ops_require_release(domain_id, release)
            if entry["runtime"] != state["runtime"] or entry["toolchain"] != state["toolchain"] \
                    or entry.get("start_hash") != hashlib.sha256(state["start_cmd"].encode()).hexdigest():
                raise HelperError("Restore the release's runtime, toolchain and start command before rolling back")
            build_state = dict(state, _release_dir=ops_release_path(pw, domain_id, release))
        elif options["releases"] and mode in ("build", "fetch"):
            release = record["id"]
            created = True
            build_state, copied = ops_prepare_release(state, pw, options, release)
            log.line("Prepared isolated release %s (%d bytes); shared paths were not copied." % (release, copied["bytes"]))
        elif mode == "restart":
            data = ops_release_state(domain_id)
            release = (data.get("slots") or {}).get(state.get("slot") or "")
        build = mode == "build"
        if mode == "fetch":
            spec = v_fetch(fetch)
            build = spec["build"]
            fetch_into_app(ops_execution_state(build_state), pw, spec, log)
        if build and state["build_cmd"]:
            isolation_prepare(build_state, pw)
            env = merged_env(build_state, pw)
            env.update({"HOME": isolation_environment_home(build_state, pw), "USER": pw.pw_name, "LOGNAME": pw.pw_name,
                        "LANG": "C.UTF-8", "SHELL": "/bin/bash", "TMPDIR": "/tmp"})
            if state["toolchain"] and not toolchain_installed(state["runtime"], state["toolchain"]):
                raise HelperError("Toolchain %s %s is not installed" % (state["runtime"], state["toolchain"]))
            log.line("Runtime: %s %s" % (state["runtime"], state["toolchain"] or "(no toolchain)"))
            log.line("$ " + state["build_cmd"].replace("\n", "\n$ "))
            started = time.time()
            if isolation_options(domain_id)["enabled"]:
                env = isolation_outer_environment(env, ["/bin/bash", "-e", "-c", state["build_cmd"]])
            command = isolation_command(ops_execution_state(build_state), pw,
                                        ["/bin/bash", "-e", "-c", state["build_cmd"]], build=True)
            code = stream_process(command, log, state["build_timeout"],
                                  env, preexec=_build_preexec(pw, ops_execution_state(build_state)["app_dir"]))
            log.line("Build finished in %.1fs with exit code %d" % (time.time() - started, code))
            if code != 0:
                raise HelperError("Build failed with exit code %d; the running application was left untouched." % code)
        elif build:
            log.line("No build command configured; skipping build.")
        # The build may have taken long: never start an app that was disabled or whose
        # domain was suspended in the meantime.
        fresh, fresh_pw = load_app_state(domain_id)
        if any(fresh.get(key) != state.get(key) for key in ("app_dir", "sysuser", "runtime", "toolchain", "start_cmd")):
            raise HelperError("Application identity or commands changed during deployment; retry with the current configuration")
        if created:
            call_as_user(pw, _user_release_walk, build_state["_release_dir"], options["shared_paths"],
                         options["release_max_mb"] * 1024 * 1024, time.monotonic() + 60, None, True, timeout=65)
            call_as_user(pw, _user_shared_links, state["app_dir"], build_state["_release_dir"],
                         options["shared_paths"], state["runtime"], timeout=30)
        if mode in ("build", "fetch"):
            # Files the build or fetch wrote into a document root inside the application root
            # become readable for the web server, before the new version starts (also for a
            # stopped application: the web server serves the document root without it).
            deploy_open_public_files(fresh, fresh_pw, log)
        if not fresh["enabled"] or fresh["suspended"]:
            raise HelperError("The application was disabled or the domain suspended during the build; "
                              "it was not restarted.")
        release_context["selected"] = release
        if fresh["stopped"] or not zd_has_slots(fresh):
            release_context["previous"] = ops_stage_release(fresh, release, target=fresh.get("slot") or "")
            if release_context["previous"] is not None:
                write_units(fresh, fresh_pw)
                systemctl("daemon-reload", check=True)
        unit = UNIT_APP % domain_id
        if fresh["stopped"]:
            # Stop persists: only Start, Restart, Build & restart in the panel or saving starts it again.
            log.line("The application is stopped; it was not started. Start it to run this version.")
            ok = True
            message = "The application is stopped; it was not started"
            return
        if zd_has_slots(fresh):
            # Zero-downtime slots (docs/DESIGN.md section 12.4): a switch, or a plain restart (also
            # of an application that became a worker while a slot runs: the 1.0 unit does not exist
            # then, zd_restart() retires the slots first).
            ok, message = zd_restart(fresh, pw, job, log, release_context=release_context)
            return
        ok, message = restart_and_check(fresh, pw, unit, log)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        log.line("ERROR: %s" % exc)
    finally:
        try:
            restore_units = ops_release_result(state, pw, options, release, release_context["previous"], ok, created,
                                               switched=release_context["switch"])
            if created and not ok and release_context["previous"] is None:
                call_as_user(pw, _user_remove_release, pw.pw_dir, domain_id, release, timeout=120)
            if not ok and restore_units:
                restored, restored_pw = load_app_state(domain_id)
                write_units(restored, restored_pw)
                systemctl("daemon-reload")
                if not release_context["switch"] and restored["enabled"] and not restored["stopped"] and not restored["suspended"]:
                    prepare_start(live_view(restored), restored_pw)
                    systemctl("restart", app_unit(domain_id, restored.get("slot") or ""), timeout=120)
        except Exception as exc:
            log.line("WARNING: release cleanup/recovery could not finish: %s" % exc)
            if not ok:
                message = (message or "Deployment failed") + "; release cleanup/recovery needs attention"
        log.line("Deployment %s." % ("succeeded" if ok else "failed"))
        log.close()
        try:
            ops_finish(state, record, ok, message, job, release)
        except Exception:
            pass
        job_set_status(job, state="succeeded" if ok else "failed", finished_at=now_iso(),
                       exit_code=0 if ok else 1, message=message)
