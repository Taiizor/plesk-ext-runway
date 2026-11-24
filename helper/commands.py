# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Commands: info / toolchains / jobs
# ---------------------------------------------------------------------------

def cmd_info(_payload):
    os_release = {}
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if "=" in line:
                    key, val = line.rstrip("\n").split("=", 1)
                    os_release[key] = val.strip('"')
    except OSError:
        pass
    try:
        arch = host_arch()
    except HelperError:
        arch = (os.uname().machine, None)
    return {
        "helper_version": VERSION,
        "python": sys.version.split()[0],
        "systemd": systemd_version(),
        "os": os_release.get("PRETTY_NAME", ""),
        "arch": arch[0],
        "rust_target": arch[1],
        "build_deps": build_deps_status(),
        "isolation_deps": isolation_dependencies_status(),
        "installed": os.path.isfile(HELPER_COPY),
        "fetch_insecure": fetch_insecure_allowed(),
        "selinux": selinux_mode(),
        "update_source": read_update_source(),
    }


def selinux_mode():
    """enforcing | permissive | None (no SELinux): nginx/Apache may then need policy changes to
    reach the applications (README, Requirements)."""
    value = _read_text("/sys/fs/selinux/enforce", 8)
    if value == "1":
        return "enforcing"
    if value == "0":
        return "permissive"
    return None


def v_runtime(value):
    if value not in RUNTIMES:
        raise HelperError("Unknown runtime")
    return value


def toolchain_list(runtime):
    """Installed (managed) or detected toolchains of a runtime: [{id, label, path, ...}], newest first."""
    rt = RUNTIMES.get(runtime)
    if rt is None or rt.toolchain == "none":
        return []
    try:
        return rt.list_installed()
    except (HelperError, OSError):
        return []


def cmd_runtimes(_payload):
    return {"runtimes": [rt.meta() for rt in RUNTIMES.values()]}


def cmd_toolchains(_payload):
    in_use = toolchains_in_use()
    runtimes = {}
    for key, rt in RUNTIMES.items():
        runtimes[key] = {"installed": toolchain_list(key), "in_use": in_use.get(key, {}),
                         "toolchain": rt.toolchain, "build_deps": _which_status(rt.build_deps())}
    return {
        "runtimes": runtimes,
        "build_deps": build_deps_status(),
        "job": job_get_status("admin"),
        "isolation_deps": isolation_dependencies_status(),
    }


def cmd_releases(payload):
    """Versions that can be installed: {available: [{id, label}], error}. Network failures are
    reported in "error" and never fail the command, so the UI keeps working offline."""
    payload = payload or {}
    rt = RUNTIMES[v_runtime(payload.get("runtime"))]
    available = []
    error = None
    try:
        available = rt.list_available(bool(payload.get("force"))) or []
    except Exception as exc:  # noqa: BLE001
        error = "%s release list: %s" % (rt.label, exc)
    return {"runtime": rt.key, "available": available, "error": error,
            "toolchain": rt.toolchain, "install_help": rt.install_help}


def start_admin_job(action, args, title=None, title_key=None, title_params=None):
    """Starts the administrator's background job (toolchains, build dependencies, self-update)
    in runway-job-admin.service. title_key + title_params let the panel translate the title
    (title stays the English text); by default they follow the action and its runtime."""
    title = title or {"build-deps": "Install build dependencies",
                      "isolation-deps": "Install isolation dependencies"}.get(action, action)
    rt = RUNTIMES.get(args.get("runtime")) if args.get("runtime") else None
    if title_key is None:
        title_key = action.replace("-", "_")
    if title_params is None:
        title_params = {"runtime": rt.label, "version": args.get("version", "")} if rt else {}
    with FileLock("admin-job"):
        if unit_is_active(UNIT_ADMIN_JOB):
            raise HelperError("Another background job (toolchain or update) is still running. "
                              "Please wait until it finishes.")
        ensure_helper_copy()
        status_path, _log_path, request_path = job_paths("admin")
        ensure_dir(JOBS_DIR, 0o700)
        write_json(request_path, {"action": action, "args": args})
        remove_quietly(status_path)
        job_set_status("admin", state="queued", title=title, title_key=title_key, title_params=title_params,
                       queued_at=now_iso(), queued_epoch=time.time(), started_at=None, finished_at=None, message=None)
        run(["systemctl", "reset-failed", UNIT_ADMIN_JOB], timeout=30)
        cmd = ["systemd-run", "--unit=" + UNIT_ADMIN_JOB[:-len(".service")], "--collect", "--quiet",
               "--description=Runway: " + title,
               "--property=RuntimeMaxSec=7200", "--property=Nice=5",
               HELPER_COPY, "_job", "admin"]
        proc = run(cmd, timeout=60)
        if proc.returncode != 0:
            job_set_status("admin", state="failed", finished_at=now_iso(), message=(proc.stderr or proc.stdout).strip())
            raise HelperError("Could not start background job: %s" % (proc.stderr or proc.stdout).strip())
    return {"job": "admin"}


def _admin_runtime(payload):
    rt = RUNTIMES[v_runtime((payload or {}).get("runtime"))]
    if rt.toolchain == "none":
        raise HelperError("The %s runtime has no installable toolchain" % rt.label)
    return rt, rt.check_version((payload or {}).get("version"))


def cmd_toolchain_install(payload):
    rt, version = _admin_runtime(payload)
    rt.check_installable(version)
    return start_admin_job("install", {"runtime": rt.key, "version": version}, "Install %s %s" % (rt.label, version))


def cmd_toolchain_update(payload):
    rt, version = _admin_runtime(payload)
    if not rt.updatable(version):
        raise HelperError("Only channel toolchains can be updated (Rust stable/beta/nightly, Bun latest, "
                          "Python: newest patch of the minor version)")
    return start_admin_job("update", {"runtime": rt.key, "version": version}, "Update %s %s" % (rt.label, version))


def cmd_toolchain_remove(payload):
    rt, version = _admin_runtime(payload)
    target = rt.resolve(version)
    used = []
    for toolchain, domains in toolchains_in_use().get(rt.key, {}).items():
        # A configured channel id (Java major "21", Python minor "3.13", .NET "10.0") may point at
        # any build it matches (its env file was rendered when another build was the newest).
        if toolchain == version or rt.resolve(toolchain) == target or rt.may_use(toolchain, target):
            used += [str(domain) for domain in domains]
    if used:
        raise HelperError("Toolchain is used by: %s" % ", ".join(sorted(set(used))))
    with FileLock("admin-job"):
        if unit_is_active(UNIT_ADMIN_JOB):
            raise HelperError("A toolchain job is running. Please wait until it finishes.")
        rt.remove(version)
    return {"removed": version}


def rerender_runtime_apps(runtime, log=None):
    """Re-renders the env files and units of every app of a runtime (after a toolchain install or
    update): channel ids such as Java "21" or Python "3.13" then point at the newest build. Running
    services pick the change up at their next restart."""
    count = 0
    for raw in list(iter_app_states()):
        if raw.get("runtime") != runtime or not raw.get("toolchain"):
            continue
        try:
            state, pw = validate_app(raw)
            state["port"] = raw.get("port", 0)
            state.update(helper_fields(raw))
            lock, busy = try_deploy_lock(state["domain_id"], RERENDER_LOCK_WAIT)
            if lock is None:
                schedule_rerender(state["domain_id"])
                if log:
                    log.line("App #%s: %s; its environment is updated once the deploy lock is free."
                             % (state["domain_id"], "a deployment is running" if busy == "deployment" else "another operation is in progress"))
                continue
            try:
                state, pw = load_app_state(state["domain_id"])
                write_units(state, pw)
            finally:
                lock.release()
            count += 1
        except Exception as exc:  # noqa: BLE001
            if log:
                log.line("Could not update the environment of app #%s: %s" % (raw.get("domain_id"), exc))
    if count:
        systemctl("daemon-reload")
        if log:
            log.line("Updated the environment of %d application(s) using %s (effective at their next restart)."
                     % (count, runtime))
    return count


def cmd_build_deps_install(_payload):
    return start_admin_job("build-deps", {})


def cmd_isolation_deps_install(_payload):
    return start_admin_job("isolation-deps", {})


def cmd_job_status(payload):
    job = v_job((payload or {}).get("job"))
    lines = v_int((payload or {}).get("lines", 200), 1, 5000, "lines")
    status = job_get_status(job)
    status["log"] = tail_file(job_paths(job)[1], lines)
    return status


def internal_admin_job():
    status_path, log_path, request_path = job_paths("admin")
    request = read_json(request_path)
    remove_quietly(request_path)
    if not isinstance(request, dict):
        return
    job_set_status("admin", state="running", started_at=now_iso(), pid=os.getpid())
    log = JobLog("admin")
    log.line("Job started: %s" % request.get("action"))
    try:
        action = request.get("action")
        args = request.get("args") or {}
        if action in ("install", "update"):
            rt = RUNTIMES[v_runtime(args.get("runtime"))]
            version = rt.check_version(args.get("version"))
            if action == "install":
                rt.install(version, log)
            else:
                rt.update(version, log)
            rerender_runtime_apps(rt.key, log)
        elif action == "build-deps":
            job_build_deps(log)
        elif action == "isolation-deps":
            job_isolation_deps(log)
        elif action == "self-update":
            job_self_update(args, log)
        else:
            raise HelperError("Unknown job action")
        log.line("Job finished successfully.")
        job_set_status("admin", state="succeeded", finished_at=now_iso(), exit_code=0, message=None)
    except Exception as exc:  # noqa: BLE001
        log.line("ERROR: %s" % exc)
        job_set_status("admin", state="failed", finished_at=now_iso(), exit_code=1, message=str(exc))
    finally:
        log.close()
