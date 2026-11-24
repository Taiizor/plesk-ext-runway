# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# systemd helpers
# ---------------------------------------------------------------------------

def systemctl(*args, check=False, timeout=90):
    return run(["systemctl"] + list(args), check=check, timeout=timeout)


def unit_show(units, props):
    if not units:
        return {}
    cmd = ["systemctl", "show", "--no-pager"]
    for prop in props:
        cmd += ["-p", prop]
    # TZ=UTC: timestamps come as "Wed 2026-11-11 16:10:15 UTC" whatever the server's time zone is.
    proc = run(cmd + list(units), timeout=30, env=root_env({"TZ": "UTC"}))
    result = {}
    blocks = proc.stdout.strip().split("\n\n") if proc.stdout.strip() else []
    for unit, block in zip(units, blocks):
        values = {}
        for line in block.splitlines():
            if "=" in line:
                key, val = line.split("=", 1)
                values[key] = val
        result[unit] = values
    return result


# ControlGroup of a unit as systemctl show prints it ("/system.slice/runway-app-12.service").
RE_CONTROL_GROUP = re.compile(r"^(/[A-Za-z0-9_.@:-]+)+$")


def memory_value(value):
    """MemoryCurrent of systemctl show as an int, or None ("[not set]", "infinity", empty)."""
    value = value or ""
    return int(value) if value.isdigit() and int(value) < 2 ** 63 else None


def cgroup_file_cache(group):
    """Bytes of the kernel's file cache (page cache) charged to a unit's cgroup, or None when
    unknown. Files an application reads or writes stay cached and are charged to its cgroup, so
    systemd's MemoryCurrent grows with the files it serves although the kernel frees that cache
    whenever memory is needed (or the unit reaches its MemoryMax). It is active_file +
    inactive_file of memory.stat minus file_mapped: the file pages on the kernel's file lists
    that no process maps. Mapped file pages (program code, libraries, .NET assemblies, files an
    application maps such as SQLite or bbolt databases) are its working set and stay with its
    own memory, like shared memory (shmem, on the anonymous lists). file_mapped also counts mapped
    shared memory, so the result is a lower bound (clipped at 0). cgroup v2:
    /sys/fs/cgroup<group>; cgroup v1 and hybrid setups: the memory controller's hierarchy, with
    its hierarchical totals."""
    if not group or not RE_CONTROL_GROUP.match(group) or any(part in (".", "..") for part in group.split("/")):
        return None
    for base, keys, mapped in (("/sys/fs/cgroup", ("active_file", "inactive_file"), "file_mapped"),
                               ("/sys/fs/cgroup/memory", ("total_active_file", "total_inactive_file"),
                                "total_mapped_file")):
        text = _read_text(base + group + "/memory.stat", 65536)
        if not text:
            continue
        values = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                values[parts[0]] = int(parts[1])
        if all(key in values for key in keys + (mapped,)):
            return max(0, sum(values[key] for key in keys) - values[mapped])
    return None


def unit_memory(info):
    """Memory of a unit from a unit_show entry with MemoryCurrent and ControlGroup (docs/DESIGN.md
    section 7): memory_bytes (MemoryCurrent, as before), memory_cache_bytes (the unmapped file
    cache in it) and memory_used_bytes (the rest: the application's own memory, mapped files
    included). Without a readable memory.stat
    the cache is None and the used memory falls back to MemoryCurrent."""
    current = memory_value(info.get("MemoryCurrent"))
    if current is None:
        return {"memory_bytes": None, "memory_used_bytes": None, "memory_cache_bytes": None}
    cache = cgroup_file_cache(info.get("ControlGroup", ""))
    if cache is None:
        return {"memory_bytes": current, "memory_used_bytes": current, "memory_cache_bytes": None}
    cache = min(cache, current)
    return {"memory_bytes": current, "memory_used_bytes": current - cache, "memory_cache_bytes": cache}


def unit_running(unit):
    info = unit_show([unit], ["ActiveState", "SubState"]).get(unit, {})
    return info.get("ActiveState") == "active" and info.get("SubState") == "running"


def unit_is_active(unit):
    state = run(["systemctl", "is-active", unit], timeout=30).stdout.strip()
    return state in ("active", "activating", "reloading", "deactivating")


def systemd_time_iso(value):
    """'Wed 2026-11-11 16:10:15 UTC' (systemctl show with TZ=UTC) -> '2026-11-11T16:10:15+00:00'."""
    match = re.match(r"^(?:\w{3} )?(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) UTC$", (value or "").strip())
    return "%sT%s+00:00" % (match.group(1), match.group(2)) if match else None


def systemd_version():
    try:
        first = run(["systemctl", "--version"], timeout=15).stdout.splitlines()[0]
        return int(re.search(r"systemd (\d+)", first).group(1))
    except Exception:  # noqa: BLE001
        return 0


def env_quote(value):
    # systemd EnvironmentFile= double-quoted value: backslash escapes \ " ` $
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return '"' + escaped + '"'


def sanitize_description(text):
    return re.sub(r"[^A-Za-z0-9._@+-]", "_", text)[:120]


def toolchain_env(state, pw):
    """Environment shared by builds and the running application: toolchain + per-user caches
    (adapter env()) and the runtime's listen conventions (e.g. ASPNETCORE_URLS, SERVER_PORT)."""
    rt = RUNTIMES.get(state["runtime"])
    paths = []
    env = {}
    if rt is not None:
        if state["toolchain"] and rt.toolchain != "none":
            spec = dict(rt.env(isolation_environment_home(state, pw), state["toolchain"], state["app_dir"]))
            paths = list(spec.pop("PATH", []))
            env.update(spec)
        # A zero-downtime slot of a unix application may have no port of its own (slot b): its
        # listen conventions name its socket (e.g. ASPNETCORE_URLS=http://unix:.../b.sock).
        if state.get("port") or (state.get("_slot") and state.get("listen") == "unix"):
            env.update(rt.listen_env(state))
    env["PATH"] = ":".join(paths + [USER_PATH])
    return env


def socket_dir(domain_id):
    return "%s/%d" % (RUN_DIR, domain_id)


def socket_path(domain_id):
    return socket_dir(domain_id) + "/app.sock"


# Socket file names in /run/runway/<id>: the 1.0 instance's and the two slots'.
SOCKET_NAMES = ("app.sock", "a.sock", "b.sock")


def socket_name(slot):
    return "%s.sock" % slot if slot else "app.sock"


def slot_socket_path(domain_id, slot):
    return "%s/%s" % (socket_dir(domain_id), socket_name(slot))


def link_path(domain_id):
    """The web server's path of a switchable unix application: a root-owned symlink in the
    root-owned /run/runway, so no instance and no customer can remove or replace it."""
    return "%s/%d.sock" % (RUN_DIR, domain_id)


def link_target(domain_id, slot):
    return "%d/%s" % (domain_id, socket_name(slot))


def endpoint_socket(state):
    """The socket an instance binds: app.sock, or the slot's socket in a slot view."""
    return state.get("_socket") or socket_path(state["domain_id"])


def web_server_group():
    try:
        return grp.getgrnam(WEB_GROUP).gr_name
    except KeyError:
        raise HelperError("The web server group '%s' does not exist; use the TCP listen mode" % WEB_GROUP)


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def ensure_run_dir():
    """/run/runway: a real directory owned by root, mode 0755 (only root creates entries in it, so
    no customer can plant or replace /run/runway/<id>)."""
    try:
        st = os.lstat(RUN_DIR)
    except FileNotFoundError:
        st = None
    if st is not None and not stat.S_ISDIR(st.st_mode):
        os.unlink(RUN_DIR)
        st = None
    if st is None:
        os.mkdir(RUN_DIR, 0o755)
    fd = os.open(RUN_DIR, _DIR_FLAGS)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o755)
    finally:
        os.close(fd)


def ensure_socket_dir(domain_id, pw):
    """Creates /run/runway/<id> as root, owned by the system user and the web server group,
    mode 2750 (setgid: sockets inherit the group). An existing entry must be a real directory
    (anything else is replaced); owner and mode are re-applied through an O_NOFOLLOW descriptor."""
    gid = grp.getgrnam(web_server_group()).gr_gid
    ensure_run_dir()
    parent = os.open(RUN_DIR, _DIR_FLAGS)
    try:
        name = str(int(domain_id))
        try:
            st = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            st = None
        if st is not None and not stat.S_ISDIR(st.st_mode):
            os.unlink(name, dir_fd=parent)
            st = None
        if st is None:
            os.mkdir(name, 0o700, dir_fd=parent)
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent)
        try:
            os.fchown(fd, pw.pw_uid, gid)
            os.fchmod(fd, 0o2750)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def remove_socket_dir(domain_id):
    """Root: removes /run/runway/<id> and its entries (the application is gone or uses TCP now).
    Entries are unlinked through a directory descriptor, never followed."""
    try:
        parent = os.open(RUN_DIR, _DIR_FLAGS)
    except OSError:
        return
    try:
        name = str(int(domain_id))
        try:
            fd = os.open(name, _DIR_FLAGS, dir_fd=parent)
        except OSError:
            try:
                os.unlink(name, dir_fd=parent)
            except OSError:
                pass
            return
        try:
            names = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    names.append(entry.name)
                    if len(names) >= 1000:
                        break
            for entry in names:
                try:
                    st = os.stat(entry, dir_fd=fd, follow_symlinks=False)
                    if not stat.S_ISDIR(st.st_mode):
                        os.unlink(entry, dir_fd=fd)
                except OSError:
                    pass
        except OSError:
            pass
        finally:
            os.close(fd)
        try:
            os.rmdir(name, dir_fd=parent)
        except OSError:
            pass
    finally:
        os.close(parent)


def tmpfiles_path(domain_id):
    return os.path.join(TMPFILES_DIR, "runway-%d.conf" % domain_id)


def write_tmpfiles(state, pw, link_slot=None):
    """systemd-tmpfiles entry that recreates the socket directory at boot (before the units
    start), or removes the entry when the application does not use a unix socket. link_slot
    (zero-downtime, written under the deploy lock only): also recreate the root link
    /run/runway/<id>.sock to that slot's socket ("" = app.sock of the 1.0 instance)."""
    path = tmpfiles_path(state["domain_id"])
    if state.get("listen") != "unix":
        remove_quietly(path)
        return
    ensure_dir(TMPFILES_DIR, 0o755)
    if not os.path.isfile(TMPFILES_BASE):
        write_file_atomic(TMPFILES_BASE, "# Managed by the Plesk Runway extension. Do not edit.\n"
                          "d %s 0755 root root -\n" % RUN_DIR, 0o644)
    text = ("# Managed by the Plesk Runway extension. Do not edit.\n"
            "d %s 2750 %s %s -\n" % (socket_dir(state["domain_id"]), pw.pw_name, web_server_group()))
    if link_slot is not None:
        text += "L %s - - - - %s\n" % (link_path(state["domain_id"]), link_target(state["domain_id"], link_slot))
    write_file_atomic(path, text, 0o644)


def tmpfiles_link_slot(domain_id):
    """The slot of the L line of the tmpfiles entry, or None without one."""
    text = _read_text(tmpfiles_path(domain_id), 4096) or ""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 7 and parts[0] == "L" and parts[1] == link_path(domain_id):
            return _slot_of_target(domain_id, parts[6])
    return None


def _slot_of_target(domain_id, target):
    for slot in ("",) + SLOTS:
        if target == link_target(domain_id, slot):
            return slot
    return None


def socket_check(state, pw):
    """Unix mode: (detail, code, params) when a socket path of the application in
    /run/runway/<id> (app.sock; with zero-downtime slots also a.sock and b.sock) is anything but
    a socket owned by the application's user (e.g. a symbolic link to another application's
    socket, which nginx would follow), else None (also when nothing is there)."""
    names = SOCKET_NAMES if zd_has_slots(state) else ("app.sock",)
    for name in names:
        path = "%s/%s" % (socket_dir(state["domain_id"]), name)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode):
            try:
                target = os.readlink(path)[:200]
            except OSError:
                target = "?"
            return ("%s was replaced by a symbolic link to %s" % (path, target), "socket_symlink",
                    {"path": path, "target": target})
        if not stat.S_ISSOCK(st.st_mode):
            return "%s is not a socket" % path, "socket_not_socket", {"path": path}
        if st.st_uid != pw.pw_uid:
            return ("%s belongs to uid %d, not to %s" % (path, st.st_uid, pw.pw_name), "socket_owner",
                    {"path": path, "uid": st.st_uid, "user": pw.pw_name})
    return None


def unix_connect(path, uid, timeout):
    """Root connects to the unix socket at `path` (in a directory the customer controls) without
    following a symbolic link swapped in after a check: the path is opened with O_PATH|O_NOFOLLOW,
    the descriptor must be a socket owned by `uid`, and the connection goes through
    /proc/self/fd/<n>, i.e. to exactly that inode. Raises OSError otherwise."""
    fd = os.open(path, _O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if not stat.S_ISSOCK(st.st_mode):
            raise OSError("%s is not a socket" % path)
        if st.st_uid != uid:
            raise OSError("%s belongs to uid %d" % (path, st.st_uid))
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            sock.connect("/proc/self/fd/%d" % fd)
        except BaseException:
            sock.close()
            raise
        return sock
    finally:
        os.close(fd)


def socket_tampered(state, pw):
    """The detail text of socket_check(), or None."""
    found = socket_check(state, pw)
    return found[0] if found else None


def journal_note(domain_id, message, priority=4):
    """Writes a message into the journal of the application unit (shown in its application log)."""
    fields = "MESSAGE=Runway: %s\nPRIORITY=%d\nSYSLOG_IDENTIFIER=runway\nOBJECT_SYSTEMD_UNIT=%s\n" % (
        message.replace("\n", " "), priority, UNIT_APP % domain_id)
    try:
        proc = run(["logger", "--journald"], input_text=fields, timeout=15)
        if proc.returncode == 0:
            return
    except HelperError:
        pass
    try:
        run(["logger", "-t", "runway", "-p", "daemon.warning", "app #%d: %s" % (domain_id, message)], timeout=15)
    except HelperError:
        pass


def contain_tampering(state, detail):
    """The socket path of a unix-mode application was tampered with: stop and disable the service,
    remove the offending entry (as root, through a directory descriptor: unlink never follows a
    link), remember it in the state (Start clears it) and note it in the application's journal."""
    domain_id = state["domain_id"]
    # Unlink first (nginx stops following the link at once), stop the service, unlink again in
    # case the still running application recreated it. With zero-downtime slots every app unit
    # and every socket name of the application.
    slots = zd_has_slots(state)
    names = SOCKET_NAMES if slots else ("app.sock",)
    for name in names:
        unlink_socket_entry(domain_id, name)
    if slots:
        systemctl("disable", "--now", *existing_app_units(domain_id), timeout=120)
    else:
        systemctl("disable", "--now", UNIT_APP % domain_id, timeout=120)
    for name in names:
        unlink_socket_entry(domain_id, name)
    with FileLock("ports"):
        stored = read_json(app_state_path(domain_id))
        if isinstance(stored, dict):
            stored.update({"stopped": True, "tampered": True, "tampered_at": now_iso(),
                           "tampered_detail": detail[:300]})
            write_json(app_state_path(domain_id), stored)
    state.update({"stopped": True, "tampered": True, "tampered_detail": detail[:300]})
    journal_note(domain_id, "the application was stopped because its socket path was tampered with (%s). "
                 "Start it again from the panel after checking the start command." % detail)


def update_state_flags(domain_id, **flags):
    """Changes flags (stopped, tampered, ...) of the stored state under the state lock."""
    with FileLock("ports"):
        stored = read_json(app_state_path(domain_id))
        if not isinstance(stored, dict):
            raise HelperError("Application #%d is not configured" % domain_id)
        stored.update(flags)
        write_json(app_state_path(domain_id), stored)
    return stored


def prepare_start(state, pw):
    """Everything a start of the application unit needs that the unit cannot do itself (it runs
    no root lines): the socket directory in unix mode, and files that Runway manages inside the
    application root (as the user). Called by every path that starts or restarts the unit."""
    state = ops_execution_state(state)
    isolation_prepare(state, pw)
    if state.get("listen") == "unix":
        ensure_socket_dir(state["domain_id"], pw)
        # e.g. the socket of the previous system user after a subscription change; only the
        # offending entries (the socket of a running slot stays).
        for _attempt in range(len(SOCKET_NAMES)):
            found = socket_check(state, pw)
            if not found:
                break
            unlink_socket_entry(state["domain_id"], os.path.basename(found[2]["path"]))
    rt = RUNTIMES.get(state["runtime"])
    if rt is not None:
        rt.prepare_start(state, pw)


def unlink_socket_entry(domain_id, name="app.sock"):
    """Root: removes whatever /run/runway/<id>/<name> is (never follows it)."""
    try:
        fd = os.open(socket_dir(domain_id), _DIR_FLAGS)
    except OSError:
        return
    try:
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(st.st_mode):
            os.rmdir(name, dir_fd=fd)
        else:
            os.unlink(name, dir_fd=fd)
    except OSError:
        pass
    finally:
        os.close(fd)


_SYSTEMD_VERSION = []


def cached_systemd_version():
    if not _SYSTEMD_VERSION:
        _SYSTEMD_VERSION.append(systemd_version())
    return _SYSTEMD_VERSION[0]


def forced_env(state):
    """Runway-managed variables. Unix socket mode exports only RUNWAY_SOCKET (no PORT, HOST or
    LISTEN_ADDR: the unit denies every TCP bind there, and frameworks that prefer PORT would try
    to bind it); the port stays reserved in the state so switching back to TCP keeps it."""
    env = {
        "RUNWAY_APP_ROOT": state["app_dir"],
        "RUNWAY_LISTEN": state.get("listen", "tcp"),
    }
    if state.get("listen") == "unix":
        env["RUNWAY_SOCKET"] = endpoint_socket(state)
    else:
        port = str(state["port"])
        env.update({"PORT": port, "HOST": "127.0.0.1", "LISTEN_ADDR": "127.0.0.1:" + port})
    if state.get("_slot"):
        # Zero-downtime slot (docs/DESIGN.md section 12): its socket or port is in the variables above.
        env["RUNWAY_SLOT"] = state["_slot"]
    return env


def merged_env(state, pw):
    """Toolchain env + user-defined variables + Runway-managed variables (in that precedence order)."""
    state = ops_execution_state(state)
    env = toolchain_env(state, pw)
    for key, val in state["env"].items():
        if key == "PATH":
            if val:
                env["PATH"] = val + ":" + env["PATH"]
        else:
            env[key] = val
    env.update(forced_env(state))
    if isolation_options(state["domain_id"])["enabled"]:
        env["HOME"] = isolation_home(state, pw)
        env["TMPDIR"] = "/tmp"
    return env


def render_env_file(state, pw):
    env = merged_env(state, pw)
    env["RUNWAY_START_CMD"] = state["start_cmd"] or "echo 'No start command configured' >&2; exit 1"
    if isolation_options(state["domain_id"])["enabled"]:
        env = isolation_outer_environment(env, ["/bin/bash", "-c", env["RUNWAY_START_CMD"]])
    lines = ["# Managed by the Plesk Runway extension. Do not edit."]
    for key in sorted(env):
        lines.append("%s=%s" % (key, env_quote(env[key])))
    return "\n".join(lines) + "\n"


def render_app_unit(state, pw):
    """The unit of the 1.0 instance, or of a zero-downtime slot for a slot view (slot_view())."""
    state = ops_execution_state(state)
    domain_id = state["domain_id"]
    slot = state.get("_slot") or ""
    group = grp.getgrgid(pw.pw_gid).gr_name
    lines = [
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]",
        ("Description=Runway app #%d slot %s (%s, %s)" % (domain_id, slot, sanitize_description(state["domain"]), state["runtime"])
         if slot else "Description=Runway app #%d (%s, %s)" % (domain_id, sanitize_description(state["domain"]), state["runtime"])),
        # Soft ordering after local databases (units that do not exist are ignored), so an app that
        # needs its database at boot does not exhaust the start limit while it recovers. Slots start
        # after the boot repair of interrupted switches.
        "After=network-online.target mariadb.service mysql.service postgresql.service"
        + (" " + UNIT_CONVERGE if slot else ""),
        "Wants=network-online.target",
        "StartLimitIntervalSec=120",
        "StartLimitBurst=%d" % APP_START_LIMIT_BURST,
        "",
        "[Service]",
        "Type=simple",
        "User=%s" % pw.pw_name,
        "Group=%s" % group,
        "WorkingDirectory=%s" % state["app_dir"],
        "EnvironmentFile=%s" % env_file_path(domain_id, slot),
    ]
    if state.get("listen") == "unix":
        # /run/runway/<id> is created by the helper (prepare_start) and by systemd-tmpfiles at boot
        # (/etc/tmpfiles.d/runway-<id>.conf). No Exec line of this unit ever runs as root ("+"/"!"):
        # every Exec line gets the customer's environment file.
        lines.append("ExecStartPre=/bin/rm -f %s" % endpoint_socket(state))
    lines += [
        # ${VAR} as a separate word expands to exactly one argument (no word splitting).
        ("ExecStart=" + " ".join(isolation_command(state, pw, ["/bin/bash", "-c", state["start_cmd"]])))
        if isolation_options(domain_id)["enabled"] else "ExecStart=/bin/bash -c ${RUNWAY_START_CMD}",
        "Restart=always",
        "RestartSec=3",
        "TimeoutStopSec=30",
        ("SyslogIdentifier=runway-app-%d-%s" % (domain_id, slot)) if slot else ("SyslogIdentifier=runway-app-%d" % domain_id),
        # Unix socket mode needs a group-connectable socket (group = web server group).
        "UMask=%s" % ("0007" if state.get("listen") == "unix" else "0027"),
        "LimitNOFILE=65536",
        "NoNewPrivileges=yes",
        "PrivateTmp=yes",
        "PrivateDevices=yes",
        "ProtectSystem=full",
        # An isolated application starts bubblewrap, which mounts a fresh /proc in its user
        # namespace: the kernel refuses that while every procfs of the mount namespace has
        # read-only or masked paths over it (mount_too_revealing), which ProtectKernelTunables
        # adds. bubblewrap makes /proc/sys, sysrq-trigger, irq and bus read-only in the sandbox
        # itself, and the service runs unprivileged (docs/DESIGN.md section 14).
        "ProtectKernelTunables=%s" % ("no" if isolation_options(domain_id)["enabled"] else "yes"),
        "ProtectKernelModules=yes",
        "ProtectControlGroups=yes",
        "RestrictSUIDSGID=yes",
        "RestrictRealtime=yes",
        "LockPersonality=yes",
        "CPUAccounting=yes",
        "MemoryAccounting=yes",
        "IOAccounting=yes",
        "BlockIOAccounting=yes",
        "IPAccounting=yes",
    ]
    if cached_systemd_version() >= 249:
        # Applications may only bind their own port, so a Runway app can never squat another
        # app's port (Unix sockets are not affected by these settings).
        if state.get("listen") == "unix":
            lines.append("SocketBindDeny=any")
        else:
            lines += ["SocketBindAllow=tcp:%d" % int(state["port"]), "SocketBindDeny=any"]
    limits = isolation_limits(state)
    if limits["memory_mb"]:
        lines.append("MemoryMax=%dM" % limits["memory_mb"])
    if limits["cpu_percent"]:
        lines.append("CPUQuota=%d%%" % limits["cpu_percent"])
    if limits["tasks"]:
        lines.append("TasksMax=%d" % limits["tasks"])
    if (limits["memory_mb"] or limits["cpu_percent"]) and cached_systemd_version() >= 254:
        # systemd 254+ (MemoryPressureWatch=auto) bind-mounts memory.pressure writable into the
        # cgroup tree that ProtectControlGroups made read-only; with that second cgroup2 mount the
        # .NET runtime no longer finds the unit's MemoryMax and CPUQuota and sizes its heap for the
        # whole machine. Without the watch it sees the limits again (docs/DESIGN.md section 7).
        lines.append("MemoryPressureWatch=off")
    lines += ["", "[Install]", "WantedBy=multi-user.target", ""]
    return "\n".join(lines)


def switch_allowance(state):
    """Seconds a zero-downtime switch may take (0 for applications without slots): readiness,
    drain and ZD_SWITCH_EXTRA for the marker wait, the reload confirmation and the stops."""
    if not zd_has_slots(state):
        return 0
    return int(state.get("ready_timeout") or ZD_READY_DEFAULT) + int(state.get("drain_seconds") or 0) + ZD_SWITCH_EXTRA


def deploy_timeout(state):
    """Backstop of the deploy unit: a fetch (bounded by FETCH_TIMEOUT and the build timeout), the
    build itself, and 300 s for the restart and the listener check (plus the switch allowance
    with zero-downtime slots). The helper enforces its own deadlines for each step;
    TimeoutStartSec only catches a hung job."""
    release_allowance = 600 if ops_options(state["domain_id"])["releases"] or ops_release_state(state["domain_id"]) else 0
    return min(FETCH_TIMEOUT, state["build_timeout"]) + state["build_timeout"] + 300 + switch_allowance(state) + release_allowance


def render_deploy_service(state):
    domain_id = state["domain_id"]
    timeout = deploy_timeout(state)
    lines = [
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]",
        "Description=Runway deploy job #%d (%s)" % (domain_id, sanitize_description(state["domain"])),
        "",
        "[Service]",
        "Type=oneshot",
        "ExecStart=%s _deploy %d" % (HELPER_COPY, domain_id),
        "TimeoutStartSec=%d" % timeout,
    ]
    if zd_has_slots(state):
        # A stopped job ends an interrupted switch (stops the new version, or finishes the
        # switch after the commit) before systemd kills it.
        lines.append("TimeoutStopSec=%d" % ZD_DEPLOY_STOP)
    lines += [
        "Nice=10",
        "IOSchedulingClass=best-effort",
        "IOSchedulingPriority=7",
    ]
    return "\n".join(lines + build_limit_lines(state) + [""])


def build_limit_lines(state):
    """Builds run customer code: always cap tasks, and apply the admin's build limits."""
    limits = isolation_limits(state, build=True)
    lines = ["TasksMax=%d" % (int(limits.get("tasks") or 0) or DEFAULT_BUILD_TASKS)]
    if limits.get("memory_mb"):
        lines.append("MemoryMax=%dM" % int(limits["memory_mb"]))
    if limits.get("cpu_percent"):
        lines.append("CPUQuota=%d%%" % int(limits["cpu_percent"]))
    return lines


def render_deploy_path(state):
    domain_id = state["domain_id"]
    root = state["app_dir"]
    return "\n".join([
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]",
        "Description=Runway deploy trigger #%d (%s)" % (domain_id, sanitize_description(state["domain"])),
        "",
        "[Path]",
        "PathChanged=%s/%s" % (root, TRIGGER_DEPLOY),
        "PathChanged=%s/%s" % (root, TRIGGER_RESTART),
        "Unit=%s" % (UNIT_DEPLOY % domain_id),
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])
