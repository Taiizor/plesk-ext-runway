# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- connections, listeners -------------------------------------------------------------------

def unix_connections(path):
    """Connections of the listener bound to `path`: accepted (state 03) or still in its accept
    queue (state 02), from /proc/net/unix."""
    count = 0
    try:
        with open("/proc/net/unix", "r", errors="replace") as fh:
            next(fh, None)
            for row in fh:
                parts = row.split()
                if len(parts) >= 8 and parts[7] == path and parts[5] in ("02", "03"):
                    count += 1
    except OSError:
        pass
    return count


def unix_listener_inodes(path):
    """Socket inodes of the listeners bound to `path` (state 01 with the listening flag)."""
    inodes = set()
    try:
        with open("/proc/net/unix", "r", errors="replace") as fh:
            next(fh, None)
            for row in fh:
                parts = row.split()
                if len(parts) >= 8 and parts[7] == path and parts[3] == "00010000":
                    inodes.add(parts[6])
    except OSError:
        pass
    return inodes


def tcp_connections(port):
    """Connections (accepted or queued, state 01) whose local port is `port`."""
    count = 0
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(name, "r") as fh:
                rows = fh.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            parts = row.split()
            try:
                if len(parts) > 3 and parts[3] == "01" and int(parts[1].rsplit(":", 1)[1], 16) == port:
                    count += 1
            except (IndexError, ValueError):
                pass
    return count


def unit_pids(unit):
    """Processes in the cgroup of a unit (cgroup v2, else v1's systemd hierarchy)."""
    group = unit_show([unit], ["ControlGroup"]).get(unit, {}).get("ControlGroup", "")
    if not group or not group.startswith("/"):
        return []
    for base in ("/sys/fs/cgroup", "/sys/fs/cgroup/systemd", "/sys/fs/cgroup/unified"):
        text = _read_text(base + group + "/cgroup.procs", 65536)
        if text:
            return [int(pid) for pid in text.split() if pid.isdigit()]
    return []


def pids_hold_sockets(pids, inodes):
    """True when one of the processes has one of the socket inodes open."""
    wanted = set("socket:[%s]" % inode for inode in inodes)
    for pid in pids:
        try:
            for fd in os.listdir("/proc/%d/fd" % pid):
                try:
                    if os.readlink("/proc/%d/fd/%s" % (pid, fd)) in wanted:
                        return True
                except OSError:
                    continue
        except OSError:
            continue
    return False
