# Copyright 2026 Taiizor. Licensed under the MIT License.

def cmd_app_config(payload):
    domain_id = v_domain_id((payload or {}).get("domain_id"))
    state = read_json(app_state_path(domain_id))
    if not isinstance(state, dict):
        return {"config": None}
    return {"config": {"env": state.get("env") or {}, "port": state.get("port"), "app_dir": state.get("app_dir")}}


def cmd_app_page(payload):
    """Everything the domain page needs, in a single helper invocation."""
    payload = payload or {}
    domain_id = v_domain_id(payload.get("domain_id"))
    state = read_json(app_state_path(domain_id))
    state = state if isinstance(state, dict) else None
    result = {
        "toolchains": dict((key, toolchain_list(key)) for key in RUNTIME_KEYS),
        "build_deps": build_deps_status(),
        "config": {"env": (state.get("env") or {})} if state else None,
        "status": app_status(domain_id, state),
    }
    try:
        pw = v_sysuser(payload.get("sysuser"))
        _rel, app_dir = v_app_root(payload.get("app_root"), pw.pw_dir)
        inspect = call_as_user(pw, _user_inspect_app_root, app_dir,
                               v_document_roots(payload.get("document_roots"), pw.pw_dir))
        inspect["path"] = app_dir
        inspect["home"] = pw.pw_dir
        result["inspect"] = inspect
    except HelperError as exc:
        result["inspect"] = {"error": str(exc)}
    stored = state or {}
    listen = payload.get("listen") or stored.get("listen") or "tcp"
    listen = listen if listen in LISTEN_MODES else "tcp"
    runtime = payload.get("runtime") or stored.get("runtime")
    chosen = payload.get("toolchain") or (stored.get("toolchain") if stored.get("runtime") == runtime else "") or ""
    result["defaults"] = {}
    for key in RUNTIME_KEYS:
        toolchain = str(chosen) if key == runtime else ""
        if not toolchain and key == "php":
            toolchain = (result["toolchains"].get("php") or [{}])[0].get("id", "")
        result["defaults"][key] = runtime_defaults(key, result["inspect"], listen, toolchain)
        # Defaults for the other listen modes (and toolchains), so the form can follow a change
        # without another request: variants["<listen>|<toolchain>"], toolchain "" unless the
        # runtime's defaults depend on it.
        toolchain_ids = [""]
        if RUNTIMES[key].defaults_per_toolchain:
            toolchain_ids += [item["id"] for item in result["toolchains"].get(key) or [] if item.get("id")]
        variants = {}
        for mode in ("tcp", "unix"):
            for tc in toolchain_ids:
                variant = runtime_defaults(key, result["inspect"], mode, tc or (toolchain if not toolchain_ids[1:] else ""))
                variant.pop("listen", None)
                variants["%s|%s" % (mode, tc)] = variant
        result["defaults"][key]["variants"] = variants
    return result


def _user_write_sample(app_dir, files, force):
    """Runs as the customer: writes the sample files without following symbolic links."""
    entries = _scan_names(app_dir, 5, count_cap=6, skip=("tmp",))[0]
    if entries and not force:
        raise HelperError("The application root is not empty (%s). Remove the files first or overwrite them."
                          % ", ".join(sorted(entries)), code="not_empty")
    written = []
    for rel in sorted(files):
        content, mode = files[rel]
        path = os.path.join(app_dir, rel)
        os.makedirs(os.path.dirname(path), 0o750, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "w") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(content)
        written.append(rel)
    return written


def cmd_app_sample(payload):
    """Writes the runtime's minimal HTTP sample app into the application root, as the user.
    Refuses a non-empty application root unless "force" is set."""
    payload = payload or {}
    v_domain_id(payload.get("domain_id"))
    pw = v_sysuser(payload.get("sysuser"))
    _rel, app_dir = v_app_root(payload.get("app_root"), pw.pw_dir)
    rt = RUNTIMES[v_runtime(payload.get("runtime"))]
    listen = payload.get("listen") or rt.default_listen
    if listen not in LISTEN_MODES:
        raise HelperError("Invalid listen mode")
    toolchain = v_toolchain(rt.key, payload.get("toolchain"))
    if not toolchain and rt.toolchain != "none":
        installed = [item["id"] for item in toolchain_list(rt.key)]
        if rt.key == "php" and listen == "unix":
            installed = [t for t in installed if t.startswith("frankenphp-")] or installed
        toolchain = installed[0] if installed else ""
    if listen == "unix" and rt.unix_toolchain_re and not re.match(rt.unix_toolchain_re, toolchain or ""):
        raise HelperError("The %s sample can listen on a unix socket only with a %s toolchain; install one "
                          "or choose TCP." % (rt.label, "FrankenPHP" if rt.key == "php" else rt.unix_toolchain_re),
                          code="unix_unsupported")
    files = rt.sample(listen, toolchain)
    if not files:
        raise HelperError("There is no sample app for the %s runtime" % rt.label)
    call_as_user(pw, _user_prepare_app_root, app_dir)
    written = call_as_user(pw, _user_write_sample, app_dir, files, bool(payload.get("force")))
    inspect = call_as_user(pw, _user_inspect_app_root, app_dir)
    return {"written": written, "toolchain": toolchain,
            "defaults": runtime_defaults(rt.key, inspect, listen, toolchain)}


def cmd_app_status(payload):
    domain_id = v_domain_id((payload or {}).get("domain_id"))
    state = read_json(app_state_path(domain_id))
    return app_status(domain_id, state if isinstance(state, dict) else None)


def cmd_app_logs(payload):
    domain_id = v_domain_id((payload or {}).get("domain_id"))
    lines = v_int((payload or {}).get("lines", 200), 1, 2000, "lines")
    kind = (payload or {}).get("kind", "app")
    if kind == "deploy":
        return {"log": tail_file(job_paths("deploy-%d" % domain_id)[1], lines)}
    if kind != "app":
        raise HelperError("Invalid log kind")
    # Newest first, so the byte budget keeps the most recent entries; reversed afterwards. Both
    # zero-downtime slots write their own journal identifier (runway-app-<id>-a/-b): merged by time.
    cmd = ["journalctl"]
    for unit in all_app_units(domain_id):
        cmd += ["-u", unit]
    text = capped_output(cmd + ["-n", str(lines), "-r", "--no-pager", "-o", "short-iso", "--no-hostname"])
    return {"log": "\n".join(reversed(text.splitlines()))}


def capped_output(cmd, max_bytes=LOG_READ_CAP, timeout=60):
    """Runs cmd and returns at most max_bytes of its output, each line capped to LOG_LINE_CAP."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, env=root_env())
    data = bytearray()
    deadline = time.time() + timeout
    fd = proc.stdout.fileno()
    try:
        while len(data) < max_bytes:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            ready, _, _ = select.select([fd], [], [], min(remaining, 1.0))
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()
    lines = data[:max_bytes].decode("utf-8", "replace").splitlines()
    return "\n".join(line if len(line) <= LOG_LINE_CAP else line[:LOG_LINE_CAP] + " [...]" for line in lines)


def cmd_app_inspect(payload):
    payload = payload or {}
    pw = v_sysuser(payload.get("sysuser"))
    _rel, app_dir = v_app_root(payload.get("app_root"), pw.pw_dir)
    result = call_as_user(pw, _user_inspect_app_root, app_dir, v_document_roots(payload.get("document_roots"), pw.pw_dir))
    result["path"] = app_dir
    result["home"] = pw.pw_dir
    return result


def cmd_docroot_check(payload):
    """Checks a document root before the panel asks Plesk to use it: as the system user, it must
    stay inside the home directory with symbolic links resolved and, when it exists, be a directory
    (codes docroot_outside, docroot_not_dir). Changes nothing."""
    payload = payload or {}
    pw = v_sysuser(payload.get("sysuser"))
    rel, absolute = v_document_root(payload.get("document_root"), pw.pw_dir)
    result = call_as_user(pw, _user_check_document_root, absolute, pw.pw_dir)
    result["document_root"] = rel
    return result


def cmd_docroot_access(payload):
    """After the panel changed a document root through Plesk: lets the web server group pass the
    directories from the home directory down to it (o+x where needed, as the system user)."""
    payload = payload or {}
    pw = v_sysuser(payload.get("sysuser"))
    rel, absolute = v_document_root(payload.get("document_root"), pw.pw_dir)
    try:
        web_gid = grp.getgrnam(WEB_GROUP).gr_gid
    except KeyError:
        web_gid = -1
    result = call_as_user(pw, _user_open_document_root, absolute, pw.pw_dir, web_gid)
    result["document_root"] = rel
    return result


def cmd_app_docroot(payload):
    """The domain's document root as Plesk has it now (docs/DESIGN.md section 6): the panel sends it
    after it changed the document root on the Runway page (open: true), Reconcile when the stored
    copy differs from Plesk's (open: false). Stores it in the application's state like app-apply
    ("" for workers and invalid values) and, with open, makes the files in it readable for the web
    server when it lies inside the application root (open_public_files; a failure is reported in
    "public", the state is stored anyway). Without a state: configured false, nothing changes."""
    payload = payload or {}
    domain_id = v_domain_id(payload.get("domain_id"))
    nothing = {"configured": False, "document_root": "", "public": None}
    if not isinstance(read_json(app_state_path(domain_id)), dict):
        return nothing
    state, pw = load_app_state(domain_id)
    rel = v_state_document_root(payload.get("document_root"), pw.pw_dir) if state["listen"] != "none" else ""
    with FileLock("ports"):
        stored = read_json(app_state_path(domain_id))
        if not isinstance(stored, dict):
            return nothing
        if stored.get("document_root") != rel:
            stored["document_root"] = rel
            write_json(app_state_path(domain_id), stored)
    state["document_root"] = rel
    public = None
    if payload.get("open"):
        try:
            public = open_public_files(state, pw)
        except HelperError as exc:
            public = {"error": str(exc)}
    return {"configured": True, "document_root": rel, "public": public}


def cmd_apps_list(payload):
    """Every application with the state of its live unit. converge: true (the panel's scheduled
    Reconcile only) also repairs zero-downtime slots and pointers (docs/DESIGN.md section 12.8)."""
    converge = bool((payload or {}).get("converge"))
    states = list(iter_app_states())
    for state in states:
        if not isinstance(state.get("domain_id"), int):
            continue
        if converge and zd_needs_converge(state):
            try:
                zd_converge(state)
            except Exception as exc:  # noqa: BLE001 - one application must not stop the list
                journal_note(state["domain_id"], "the convergence failed: %s" % exc)
        # Unix mode: contain a tampered socket path (docs/DESIGN.md section 7). Reconcile calls
        # apps-list every 10 minutes, so the check also runs when nobody looks at the panel.
        if state.get("listen") != "unix":
            continue
        try:
            pw = pwd.getpwnam(str(state.get("sysuser")))
        except KeyError:
            continue
        found = socket_check(state, pw)
        if found and not state.get("tampered"):
            contain_tampering(state, found[0])
        elif found:
            unlink_socket_entry(state["domain_id"], os.path.basename(found[2]["path"]))
    if converge:
        states = list(iter_app_states())
    units = []
    for state in states:
        live = state.get("slot") if state.get("slot") in SLOTS else ""
        units.append(app_unit(int(state["domain_id"]), live))
    extra = [app_unit(int(s["domain_id"]), slot) for s in states if zd_has_slots(helper_fields(s)) or s.get("zero_downtime")
             for slot in ("",) + SLOTS]
    shown = unit_show(list(dict.fromkeys(units + extra)),
                      ["ActiveState", "SubState", "MemoryCurrent", "ControlGroup", "Result", "NRestarts"])
    apps = []
    for state, unit in zip(states, units):
        info = shown.get(unit, {})
        memory = unit_memory(info)
        fields = helper_fields(state)
        slots = zd_has_slots(dict(state, **fields))
        if slots:
            # Both versions run during a switch: the application's memory is their sum (per field;
            # a slot without a readable memory.stat adds its MemoryCurrent to the used memory).
            total = dict.fromkeys(memory)
            for slot in ("",) + SLOTS:
                for key, value in unit_memory(shown.get(app_unit(int(state["domain_id"]), slot), {})).items():
                    if value is not None:
                        total[key] = (total[key] or 0) + value
            if total["memory_bytes"] is not None:
                memory = total
        live_port = state.get("port")
        if slots and state.get("listen") == "tcp":
            view = dict(state, **fields)
            live_port = slot_port(view, fields["slot"]) or state.get("port")
        apps.append({
            "domain_id": state.get("domain_id"),
            "domain": state.get("domain"),
            "runtime": state.get("runtime"),
            "toolchain": state.get("toolchain"),
            "limits": state.get("limits") or {},
            "port": state.get("port"),
            "live_port": live_port,
            "zero_downtime": bool(state.get("zero_downtime")),
            "switchable": state.get("listen") in ("tcp", "unix") and slots,
            "slot": fields["slot"],
            "port_a": fields["port_a"],
            "port_b": fields["port_b"],
            "switching": bool(fields["switch"]),
            "enabled": state.get("enabled"),
            "listen": state.get("listen", "tcp"),
            "mode": state.get("mode", "web"),
            # The stored copy of the document root (Reconcile sends Plesk's when it differs).
            "document_root": state.get("document_root") if isinstance(state.get("document_root"), str) else "",
            "updated_epoch": state.get("updated_epoch"),
            "suspended": bool(state.get("suspended")),
            "stopped": bool(state.get("stopped")),
            "tampered": bool(state.get("tampered")),
            "sysuser": state.get("sysuser"),
            "app_dir": state.get("app_dir"),
            "home_changed": _home_changed(state),
            "active_state": info.get("ActiveState"),
            "sub_state": info.get("SubState"),
            "result": info.get("Result"),
            # systemd gave up (start limit): "start-limit-hit" for manual starts, while the
            # automatic restarts of systemd 255 end "failed" with the last exit result.
            "start_limit_hit": info.get("ActiveState") == "failed" and (
                info.get("Result") == "start-limit-hit"
                or int(info.get("NRestarts") or 0 if (info.get("NRestarts") or "").isdigit() else 0) >= APP_START_LIMIT_BURST),
            "memory_bytes": memory["memory_bytes"],
            "memory_used_bytes": memory["memory_used_bytes"],
            "memory_cache_bytes": memory["memory_cache_bytes"],
        })
    return {"apps": apps, "reconcile_paused": reconcile_paused()}


def reconcile_paused():
    """True while the root-only test flag RECONCILE_PAUSE_FLAG exists and is younger than one
    hour (a forgotten flag cannot disable the clean-up for good)."""
    try:
        st = os.lstat(RECONCILE_PAUSE_FLAG)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == 0 and time.time() - st.st_mtime < RECONCILE_PAUSE_MAX


def _home_changed(state):
    """True when the stored absolute app directory no longer matches the system user's
    home (subscription renamed) or the system user no longer exists."""
    try:
        home = pwd.getpwnam(str(state.get("sysuser"))).pw_dir
    except KeyError:
        return True
    return state.get("app_dir") != os.path.normpath(home) + "/" + str(state.get("app_root"))


RE_PRIVILEGED_EXEC = re.compile(r"^\s*Exec[A-Za-z]*\s*=\s*[-@:+!]*[+!]")


def _strip_privileged_exec(path):
    """Removes Exec lines that run as root ("+"/"!" prefix) from a unit file of an older version
    whose state cannot be re-rendered (e.g. its stored variables are no longer valid)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return False
    kept = [line for line in lines if not RE_PRIVILEGED_EXEC.match(line)]
    if len(kept) == len(lines):
        return False
    write_file_atomic(path, "\n".join(kept) + "\n", 0o644)
    return True


def _sanitize_stored_env(raw):
    """Drops variables that are no longer allowed (RESERVED_ENV, LOADER_ENV) from a stored state
    of an older version and saves it. Returns the dropped names."""
    env = raw.get("env")
    if not isinstance(env, dict):
        return []
    dropped = sorted(key for key in env if key in RESERVED_ENV or key in LOADER_ENV)
    if dropped and isinstance(raw.get("domain_id"), int):
        for key in dropped:
            env.pop(key, None)
        with FileLock("ports"):
            stored = read_json(app_state_path(raw["domain_id"]))
            if isinstance(stored, dict):
                stored["env"] = env
                write_json(app_state_path(raw["domain_id"]), stored)
    return dropped
