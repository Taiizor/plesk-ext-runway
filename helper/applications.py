# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Commands: applications
# ---------------------------------------------------------------------------

def ensure_helper_copy():
    """Installs a stable copy of this helper for systemd units to reference."""
    ensure_dir(BASE_DIR)
    ensure_dir(BIN_DIR)
    source = os.path.realpath(__file__)
    if source == HELPER_COPY:
        return
    with open(source, "rb") as fh:
        content = fh.read()
    try:
        with open(HELPER_COPY, "rb") as fh:
            if fh.read() == content:
                return
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=BIN_DIR)
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)
    os.chmod(tmp, 0o755)
    os.rename(tmp, HELPER_COPY)


def ensure_layout():
    ensure_dir(BASE_DIR)
    ensure_dir(GO_ROOT_DIR)
    ensure_dir(STATE_DIR, 0o700)
    ensure_dir(APPS_DIR, 0o700)
    ensure_dir(JOBS_DIR, 0o700)
    ensure_dir(LOCK_DIR, 0o700)
    ensure_dir(CACHE_DIR, 0o700)
    ensure_dir(CONF_DIR, 0o755)
    ensure_dir(ENV_DIR, 0o700)
    ensure_helper_copy()
    try:
        ensure_composer_wrapper()
    except OSError:
        pass


def trigger_mtimes(pw, app_dir):
    try:
        return call_as_user(pw, _user_trigger_mtimes, app_dir, timeout=10)
    except HelperError:
        return {"deploy": None, "restart": None}


def write_units(state, pw):
    """Renders the units and environment files of an application. Without zero-downtime slots
    exactly the 1.0 set (with its tmpfiles entry); with slots both slot units and their
    environment files, and the 1.0 unit while it is the live instance. The pointer (include files,
    root link, tmpfiles entry of a switchable application) is not written here (write_pointer(),
    under the deploy lock)."""
    domain_id = state["domain_id"]
    if not zd_has_slots(state):
        write_tmpfiles(state, pw)
        write_file_atomic(env_file_path(domain_id), render_env_file(state, pw), 0o600)
        write_file_atomic(os.path.join(UNIT_DIR, UNIT_APP % domain_id), render_app_unit(state, pw), 0o644)
    else:
        if not state.get("slot"):
            write_slot_units(state, pw, "")
        for slot in SLOTS:
            if state.get("listen") == "tcp" and not slot_port(state, slot):
                continue
            write_slot_units(state, pw, slot)
    write_file_atomic(os.path.join(UNIT_DIR, UNIT_DEPLOY % domain_id), render_deploy_service(state), 0o644)
    write_file_atomic(os.path.join(UNIT_DIR, UNIT_PATH % domain_id), render_deploy_path(state), 0o644)


def app_status(domain_id, state=None):
    pw = None
    if state:
        try:
            pw = pwd.getpwnam(str(state.get("sysuser")))
        except KeyError:
            pw = None
    if state and pw is not None and state.get("listen") == "unix":
        # Unix mode: a socket path that is not the application's own socket is contained at once
        # (docs/DESIGN.md section 7, "tampered"): nginx would follow a symbolic link elsewhere.
        found = socket_check(state, pw)
        if found and not state.get("tampered"):
            contain_tampering_waiting(state, pw, found[0])
        elif found:
            unlink_socket_entry(domain_id, os.path.basename(found[2]["path"]))
    slots = bool(state) and zd_has_slots(state)
    live = (state.get("slot") or "") if state else ""
    units = [app_unit(domain_id, live), UNIT_DEPLOY % domain_id, UNIT_PATH % domain_id]
    others = [slot for slot in ("",) + SLOTS if slot != live] if slots else []
    props = ["LoadState", "ActiveState", "SubState", "MainPID", "ExecMainStartTimestamp",
             "NRestarts", "MemoryCurrent", "ControlGroup", "Result", "UnitFileState", "ActiveEnterTimestamp"]
    shown = unit_show(units + [app_unit(domain_id, slot) for slot in others], props)
    app = shown.get(units[0], {})
    memory = unit_memory(app)
    started = app.get("ExecMainStartTimestamp") or None
    status = {
        "configured": state is not None,
        "service": {
            "load_state": app.get("LoadState"),
            "active_state": app.get("ActiveState"),
            "sub_state": app.get("SubState"),
            "main_pid": int(app.get("MainPID") or 0),
            "started_at": started,
            "started_iso": systemd_time_iso(started),
            "restarts": int(app.get("NRestarts") or 0) if (app.get("NRestarts") or "").isdigit() else 0,
            # MemoryCurrent; memory_used_bytes and memory_cache_bytes split it (unit_memory).
            "memory_bytes": memory["memory_bytes"],
            "memory_used_bytes": memory["memory_used_bytes"],
            "memory_cache_bytes": memory["memory_cache_bytes"],
            "result": app.get("Result"),
            "enabled": app.get("UnitFileState"),
        },
        "watcher": {
            "active_state": shown.get(units[2], {}).get("ActiveState"),
            "enabled": shown.get(units[2], {}).get("UnitFileState"),
        },
        "deploy": job_get_status("deploy-%d" % domain_id),
    }
    if state:
        status["enabled"] = bool(state.get("enabled"))
        status["suspended"] = bool(state.get("suspended"))
        status["stopped"] = bool(state.get("stopped"))
        status["tampered"] = bool(state.get("tampered"))
        if state.get("tampered"):
            status["tampered_at"] = state.get("tampered_at") or None
            status["tampered_detail"] = state.get("tampered_detail") or ""
        status["listen_mode"] = state.get("listen", "tcp")
        status["mode"] = state.get("mode", "web")
        status["mount_path"] = state.get("mount_path", "")
        status["static_paths"] = state.get("static_paths", [])
        status["health_path"] = state.get("health_path", "")
        # Expected response content of the health check ("" while it is off).
        status["health_match"] = state.get("health_match") if isinstance(state.get("health_match"), str) else ""
        status["health"] = "unknown"
        status["health_detail"] = "" if state.get("health_path") else "No health check path configured"
        status["health_code"] = "" if state.get("health_path") else "no_path"
        status["health_params"] = {}
        # Health watch: null while it is off.
        status["health_watch"] = health_watch_status(domain_id, state)
        # Zero-downtime deployments (docs/DESIGN.md section 12.10).
        status["zero_downtime"] = bool(state.get("zero_downtime"))
        status["switchable"] = zd_switchable(state)
        status["slot"] = live
        status["switched_at"] = state.get("switched_at") or None
        status["restart_plain"] = bool(state.get("restart_plain"))
        status["switch"] = state.get("switch")
        status["ready_timeout"] = state.get("ready_timeout", ZD_READY_DEFAULT)
        status["drain_seconds"] = state.get("drain_seconds", ZD_DRAIN_DEFAULT)
        if slots:
            status["slots"] = {}
            for slot in ("",) + SLOTS:
                unit = app_unit(domain_id, slot)
                info = shown.get(unit, {})
                if info.get("LoadState") in (None, "not-found") and slot != live:
                    continue
                mem = unit_memory(info)
                start = info.get("ExecMainStartTimestamp") or None
                if state.get("listen") == "unix":
                    endpoint = slot_socket_path(domain_id, slot)
                elif state.get("listen") == "tcp" and slot_port(state, slot):
                    endpoint = "127.0.0.1:%d" % slot_port(state, slot)
                else:
                    endpoint = None
                status["slots"][slot] = {
                    "unit": unit, "active_state": info.get("ActiveState"), "sub_state": info.get("SubState"),
                    "main_pid": int(info.get("MainPID") or 0) if (info.get("MainPID") or "").isdigit() else 0,
                    "memory_bytes": mem["memory_bytes"], "memory_used_bytes": mem["memory_used_bytes"],
                    "memory_cache_bytes": mem["memory_cache_bytes"],
                    "started_iso": systemd_time_iso(start), "enabled": info.get("UnitFileState"),
                    "endpoint": endpoint, "live": slot == live,
                }
        deploy = status["deploy"]
        if isinstance(deploy, dict) and deploy.get("phase") and deploy.get("state") in ("queued", "running"):
            deploy["phase_elapsed"] = max(0, int(time.time() - float(deploy.get("phase_started_epoch") or time.time())))
    if state and state.get("port"):
        view = live_view(state) if slots else state
        status["port"] = (slot_port(state, live) or state["port"]) if slots and state.get("listen") == "tcp" else state["port"]
        if state.get("listen") == "unix":
            status["socket"] = endpoint_socket(view)
            if zd_switchable(state):
                status["proxy_socket"] = link_path(domain_id)
        if pw is not None:
            listener, detail, code, params = listener_info(view, pw)
        else:
            listener, detail, code, params = "none", "", "none", {}
        status["listener"] = listener
        status["listener_detail"] = detail
        status["listener_code"] = code
        status["listener_params"] = params
        status["listening"] = listener == "ok"
        if state.get("health_path"):
            (status["health"], status["health_detail"], status["health_code"],
             status["health_params"]) = health_check(view, listener, pw)
        if slots and pw is not None and state.get("listen") == "tcp" and state.get("zero_downtime") and not state.get("switch") \
                and not (isinstance(status["deploy"], dict) and status["deploy"].get("phase")):
            standby = slot_port(state, "a" if live == "b" else "b")
            if standby:
                uids = tcp_listener_uids(standby)
                if not uids:
                    status.update({"standby_listener": "none", "standby_detail": "nothing listens on 127.0.0.1:%d" % standby,
                                   "standby_code": "standby_none", "standby_params": {"port": standby}})
                elif uids == {pw.pw_uid}:
                    status.update({"standby_listener": "ok", "standby_detail": "the application's user listens on 127.0.0.1:%d" % standby,
                                   "standby_code": "standby_ok", "standby_params": {"port": standby}})
                else:
                    others = ", ".join(str(uid) for uid in sorted(uids - {pw.pw_uid}))
                    status.update({"standby_listener": "foreign",
                                   "standby_detail": "port %d of the next switch is held by uid %s; the switch uses another port" % (standby, others),
                                   "standby_code": "standby_foreign", "standby_params": {"port": standby, "uids": others}})
    try:
        record_app_metric_sample(domain_id, state)
    except Exception:
        pass
    return status


def health_check(state, listener, pw=None, timeout=HEALTH_TIMEOUT):
    """One HTTP GET of the health path (timeout: 2 s for the status, 5 s for the health watch;
    Host = domain): (healthy | unhealthy | unknown, detail, code, params). Only talks to an
    endpoint held by the application's own user (listener "ok"); a unix socket is opened without
    following a symbolic link (unix_connect). Without an expected response content only the status
    line is read (2xx/3xx: healthy); with one (health_match) the whole response is read within the
    same deadline (health_read_response) and a 2xx/3xx answer must also contain it
    (health_match_result)."""
    if listener != "ok":
        return "unknown", "The application is not listening", "not_listening", {}
    expect = health_expectation(state)
    try:
        host = state["domain"].encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        host = state["domain"].encode("ascii", "replace").decode("ascii")
    request = ("GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: runway-health/%s\r\nAccept: */*\r\n"
               "Connection: close\r\n\r\n" % (state["health_path"], host, VERSION)).encode("ascii", "replace")
    deadline = time.time() + timeout
    data = b""
    sock = None
    try:
        if state.get("listen") == "unix":
            if pw is None:
                pw = pwd.getpwnam(str(state.get("sysuser")))
            sock = unix_connect(endpoint_socket(state), pw.pw_uid, timeout)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(("127.0.0.1", int(state["port"])))
        sock.sendall(request)
        if expect is not None:
            data = health_read_response(sock, deadline)
        else:
            while b"\r\n" not in data and len(data) < 4096:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise socket.timeout("timed out")
                sock.settimeout(remaining)
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
    except (OSError, KeyError) as exc:
        error = str(exc) or type(exc).__name__
        return "unhealthy", "Health check failed: %s" % error, "failed", {"error": error}
    finally:
        if sock is not None:
            sock.close()
    match = re.match(br"^HTTP/\d(?:\.\d)?\s+(\d{3})", data)
    if not match:
        return "unhealthy", "Health check got no valid HTTP response", "no_http", {}
    code = int(match.group(1))
    if expect is not None and 200 <= code < 400:
        return health_match_result(expect, data, code, state["health_path"])
    return (("healthy" if 200 <= code < 400 else "unhealthy"), "HTTP %d from %s" % (code, state["health_path"]),
            "http", {"code": code, "path": state["health_path"]})
