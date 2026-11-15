# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Zero-downtime deployments (docs/DESIGN.md section 12)
#
# An application with the setting on runs in one of two slot units (runway-app-<id>-a/-b); a
# switch starts the other slot, waits until it is ready, moves the web server's pointer to it
# (unix: the root link /run/runway/<id>.sock; tcp: the include files in /etc/runway/web and a
# graceful reload), drains and stops the old one. The pointer is the truth about which instance
# carries the traffic: everything that finds an interrupted switch decides from it.
# ---------------------------------------------------------------------------

_O_PATH = getattr(os, "O_PATH", 0o10000000)
# SIGTERM of the deploy job inside a critical section (from the traffic move on) only sets
# "pending"; the job then finishes the switch instead of leaving it half done.
_TERM = {"critical": 0, "pending": False}


class SwitchFailed(HelperError):
    """A switch that failed while the running version keeps serving."""


def zd_has_slots(state):
    """True when the application uses (or still uses) zero-downtime slots: the setting is on, a
    slot is still the live instance after it was turned off, or the intent record of an
    interrupted switch exists (also of a switch back to the 1.0 unit that already committed: the
    old slot may still run, and the convergence, Stop, suspension and the socket check must cover
    it until the slots are retired)."""
    return bool(state.get("zero_downtime")) or state.get("slot") in SLOTS or isinstance(state.get("switch"), dict)


def slot_files_left(domain_id):
    """True when a unit or environment file of a zero-downtime slot exists (e.g. after the
    setting was turned off before the first switch, or after the boot repair of an interrupted
    switch back to the 1.0 unit): the convergence and app-apply retire them."""
    return any(os.path.exists(os.path.join(UNIT_DIR, app_unit(domain_id, slot))) or os.path.exists(env_file_path(domain_id, slot))
               for slot in SLOTS)


def zd_switchable(state):
    """The web server snippet of the application must use the pointer (PHP stores this)."""
    return state.get("listen") in ("tcp", "unix") and zd_has_slots(state)


def zd_target(state):
    """The instance a switch starts: the other slot while the setting is on, the 1.0 unit ("")
    when it was turned off and a slot is still live; None when there is nothing to switch."""
    if state.get("zero_downtime") and state.get("listen") in ("tcp", "unix"):
        return "a" if state.get("slot") == "b" else "b"
    if state.get("slot") in SLOTS:
        return ""
    return None


def slot_label(slot):
    """Name of an instance in messages: "slot a", or the classic (single-instance) unit."""
    return "slot %s" % slot if slot else "the classic unit"


def slot_port(state, slot):
    if slot == "a":
        return state.get("port_a") or state.get("port")
    if slot == "b":
        return state.get("port_b")
    return state.get("port")


def slot_view(state, slot):
    """The state as one instance sees it: a slot's port, socket and RUNWAY_SLOT (render_app_unit,
    render_env_file, listen_env, listener_info, health_check and prepare_start use it)."""
    view = dict(state)
    if slot:
        view["_slot"] = slot
        view["port"] = slot_port(state, slot) or 0
    view["_socket"] = slot_socket_path(state["domain_id"], slot)
    return view


def live_view(state):
    return slot_view(state, state.get("slot") or "")


def existing_app_units(domain_id):
    """App units of the application that have a unit file (systemctl refuses unknown names)."""
    units = [unit for unit in all_app_units(domain_id) if os.path.exists(os.path.join(UNIT_DIR, unit))]
    return units or [UNIT_APP % domain_id]


def unit_enabled(unit):
    return run(["systemctl", "is-enabled", unit], timeout=30).stdout.strip() in ("enabled", "enabled-runtime")


def zd_journal(state, message, priority=5):
    journal_note(state["domain_id"], message, priority)


# --- pointer: root link (unix) and include files (tcp) ------------------------------------------

def set_link(domain_id, slot):
    """Root: points /run/runway/<id>.sock at the slot's socket: a new symlink under a random name,
    renamed over the old one through the directory descriptor of /run/runway (atomic, never
    follows anything). Returns True when it changed."""
    ensure_run_dir()
    target = link_target(domain_id, slot)
    name = "%d.sock" % domain_id
    fd = os.open(RUN_DIR, _DIR_FLAGS)
    try:
        try:
            if os.readlink(name, dir_fd=fd) == target:
                return False
        except OSError:
            pass
        tmp = ".%d.%s.tmp" % (domain_id, base64.b16encode(os.urandom(6)).decode("ascii").lower())
        os.symlink(target, tmp, dir_fd=fd)
        try:
            os.rename(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
        except OSError:
            try:
                os.unlink(tmp, dir_fd=fd)
            except OSError:
                pass
            raise
        return True
    finally:
        os.close(fd)


def read_link_slot(domain_id):
    """The slot the root link points at ("" = app.sock), or None (missing or not Runway's)."""
    path = link_path(domain_id)
    try:
        st = os.lstat(path)
        if not stat.S_ISLNK(st.st_mode) or st.st_uid != 0:
            return None
        return _slot_of_target(domain_id, os.readlink(path))
    except OSError:
        return None


def remove_link(domain_id):
    try:
        fd = os.open(RUN_DIR, _DIR_FLAGS)
    except OSError:
        return
    try:
        name = "%d.sock" % domain_id
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISDIR(st.st_mode):
            os.unlink(name, dir_fd=fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _read_exact(path, limit=4096):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return None


def write_include(domain_id, port):
    """Root-owned include files of a switchable tcp application naming the live port (nginx:
    $runway_upstream; Apache: RUNWAY_UPSTREAM_<id> and RUNWAY_PORT_<id>). Returns True when a
    file changed."""
    ensure_dir(WEB_DIR, 0o755)
    nginx, apache = include_paths(domain_id)
    header = "# Managed by the Plesk Runway extension. Do not edit.\n"
    changed = False
    for path, text in ((nginx, header + "set $runway_upstream 127.0.0.1:%d;\n" % int(port)),
                       (apache, header + "Define RUNWAY_UPSTREAM_%d http://127.0.0.1:%d\nDefine RUNWAY_PORT_%d %d\n"
                        % (domain_id, int(port), domain_id, int(port)))):
        if _read_exact(path) != text:
            write_file_atomic(path, text, 0o644)
            changed = True
    return changed


def read_include_port(domain_id):
    match = re.search(r"^set \$runway_upstream 127\.0\.0\.1:(\d{1,5});$", _read_exact(include_paths(domain_id)[0]) or "", re.M)
    return int(match.group(1)) if match else None


def include_mtime(domain_id):
    mtimes = []
    for path in include_paths(domain_id):
        try:
            mtimes.append(os.stat(path).st_mtime)
        except OSError:
            pass
    return max(mtimes) if mtimes else 0.0


def remove_include(domain_id):
    for path in include_paths(domain_id):
        remove_quietly(path)
    try:
        os.rmdir(WEB_DIR)  # only when no other application uses it
    except OSError:
        pass


def read_pointer_slot(state):
    """The instance the pointer names: the root link's slot (unix) or the slot whose port the
    include names (tcp; the intent's target, the live slot and the intent's source first, because
    the 1.0 port and slot a's port may be the same number while only one of them runs)."""
    domain_id = state["domain_id"]
    if state.get("listen") == "unix":
        return read_link_slot(domain_id)
    if state.get("listen") != "tcp":
        return None
    port = read_include_port(domain_id)
    if port is None:
        return None
    intent = state.get("switch") or {}
    order = [intent.get("to"), state.get("slot") or "", intent.get("from"), "a", "b", ""]
    for slot in order:
        if slot is not None and slot_port(state, slot) == port:
            return slot
    return None


def pointer_wanted(state):
    """The pointer files must name the live instance: the application is switchable, or its web
    server snippet may still use them (until Plesk regenerated the 1.0 snippet)."""
    domain_id = state["domain_id"]
    return state.get("listen") in ("tcp", "unix") and (zd_switchable(state) or os.path.lexists(link_path(domain_id))
                                                      or os.path.exists(include_paths(domain_id)[0]))


def write_pointer(state, pw, slot):
    """Points the web server at `slot` (the caller holds the application's deploy lock). tcp:
    returns True when the include files changed (a reload makes it effective)."""
    domain_id = state["domain_id"]
    if state.get("listen") == "unix":
        ensure_socket_dir(domain_id, pw)
        set_link(domain_id, slot)
        write_tmpfiles(state, pw, link_slot=slot)
        return False
    if state.get("listen") == "tcp":
        port = slot_port(state, slot)
        return bool(port) and write_include(domain_id, port)
    return False


def tmpfiles_drop_link(state, pw):
    """The tmpfiles entry without its L line (the root link is no longer used)."""
    if state.get("listen") == "unix" and tmpfiles_link_slot(state["domain_id"]) is not None:
        write_tmpfiles(state, pw)
