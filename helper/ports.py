# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------

def listening_ports():
    ports = set()
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(name, "r") as fh:
                rows = fh.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            parts = row.split()
            if len(parts) > 3 and parts[3] == "0A":  # TCP_LISTEN
                try:
                    ports.add(int(parts[1].rsplit(":", 1)[1], 16))
                except (IndexError, ValueError):
                    pass
    return ports


def assigned_ports(exclude_id=None):
    """Ports of every application (the port of the 1.0 instance and the ports of the
    zero-downtime slots) except those of exclude_id."""
    ports = {}
    for state in iter_app_states():
        if state.get("domain_id") == exclude_id:
            continue
        for key in ("port", "port_a", "port_b"):
            value = state.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value:
                ports[value] = state.get("domain_id")
    return ports


def allocate_extra_port(domain_id, port_range, avoid):
    """A free port of the range for a zero-downtime slot: not assigned to any application, not in
    `avoid` (the application's own ports) and not listening. Called under the "ports" lock."""
    taken = assigned_ports(exclude_id=domain_id)
    listening = listening_ports()
    for port in range(port_range[0], port_range[1] + 1):
        if port not in taken and port not in avoid and port not in listening:
            return port
    raise HelperError("No free port left in range %d-%d" % tuple(port_range))


def allocate_port(domain_id, current, port_range):
    taken = assigned_ports(exclude_id=domain_id)
    if current and current not in taken:
        return current
    listening = listening_ports()
    for port in range(port_range[0], port_range[1] + 1):
        if port not in taken and port not in listening:
            return port
    raise HelperError("No free port left in range %d-%d" % tuple(port_range))


def tcp_listener_uids(port):
    """uids of the sockets listening on `port` (any address), from /proc/net/tcp{,6}."""
    uids = set()
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(name, "r") as fh:
                rows = fh.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            parts = row.split()
            if len(parts) > 7 and parts[3] == "0A":
                try:
                    if int(parts[1].rsplit(":", 1)[1], 16) == port:
                        uids.add(int(parts[7]))
                except (IndexError, ValueError):
                    pass
    return uids


def listener_info(state, pw):
    """Returns (state, detail, code, params): "ok" when the app's own user listens on the app's
    endpoint, "none" when nothing listens, "foreign" when another user holds the TCP port (hijack
    attempt), "tampered" when the unix socket path is not the application's own socket (e.g. a
    symbolic link to another application's socket), "worker" for listen mode none (nothing to
    check). detail is English; code + params let the panel translate it (docs/DESIGN.md 7)."""
    if state.get("listen") == "none":
        return "worker", "workers are not checked for a listener", "worker", {}
    if state.get("listen") == "unix":
        path = endpoint_socket(state)
        if state.get("tampered"):
            return "tampered", state.get("tampered_detail") or path, "tampered", {"path": path}
        found = socket_check(state, pw)
        if found:
            return "tampered", found[0], found[1], found[2]
        try:
            os.lstat(path)
        except OSError:
            return "none", path, "none", {"endpoint": path}
        try:
            # Never follows a symbolic link swapped in after socket_check() (O_PATH, see unix_connect).
            unix_connect(path, pw.pw_uid, 0.5).close()
            return "ok", path, "ok", {"endpoint": path}
        except OSError:
            return "none", path, "none", {"endpoint": path}
    port = int(state.get("port") or 0)
    endpoint = "127.0.0.1:%d" % port
    uids = tcp_listener_uids(port) if port else set()
    if not uids:
        return "none", endpoint, "none", {"endpoint": endpoint}
    if uids == {pw.pw_uid}:
        return "ok", endpoint, "ok", {"endpoint": endpoint}
    others = ", ".join(str(uid) for uid in sorted(uid for uid in uids if uid != pw.pw_uid))
    return "foreign", "port %d is held by uid %s" % (port, others), "foreign", {"port": port, "uids": others}


def listener_state(state, pw):
    """(state, detail) of listener_info()."""
    return listener_info(state, pw)[:2]


def port_is_listening(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def iter_app_states():
    try:
        names = os.listdir(APPS_DIR)
    except OSError:
        return
    for name in sorted(names):
        if re.match(r"^\d+\.json$", name):
            state = read_json(os.path.join(APPS_DIR, name))
            if isinstance(state, dict):
                yield state
