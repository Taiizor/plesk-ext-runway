# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- state helpers ------------------------------------------------------------------------------

def zd_update_state(domain_id, **fields):
    """Changes helper-owned fields of the stored state under the state lock; returns the stored
    state (raw)."""
    return update_state_flags(domain_id, **fields)


def zd_flags_block(domain_id):
    """The reason a switch must not move the traffic or start an instance now, or None."""
    stored = read_json(app_state_path(domain_id))
    if not isinstance(stored, dict):
        return "removed"
    if not stored.get("enabled"):
        return "disabled"
    if stored.get("suspended"):
        return "suspended"
    if stored.get("stopped") or stored.get("tampered"):
        return "stopped"
    return None


def switch_fault(point):
    """Test-only: the root-owned flag SWITCH_FAULT_FLAG ("<kill|term>:<point>", younger than one
    hour) makes the switch job signal itself at that point (docs/DESIGN.md section 12.11)."""
    try:
        st = os.lstat(SWITCH_FAULT_FLAG)
    except OSError:
        return
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or time.time() - st.st_mtime > RECONCILE_PAUSE_MAX:
        return
    kind, _sep, where = (_read_text(SWITCH_FAULT_FLAG, 200) or "").partition(":")
    if where.strip() != point:
        return
    os.kill(os.getpid(), signal.SIGKILL if kind.strip() == "kill" else signal.SIGTERM)
    time.sleep(1)


def ensure_converge_unit():
    """Installs and enables runway-converge.service (boot repair of interrupted switches) once
    an application uses zero-downtime slots."""
    path = os.path.join(UNIT_DIR, UNIT_CONVERGE)
    text = "\n".join([
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]",
        "Description=Runway: settle interrupted zero-downtime switches before the web server starts",
        "After=local-fs.target systemd-tmpfiles-setup.service",
        "Before=nginx.service apache2.service httpd.service",
        "",
        "[Service]",
        "Type=oneshot",
        "ExecStart=%s _converge" % HELPER_COPY,
        "TimeoutStartSec=180",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])
    if _read_exact(path, 8192) != text:
        write_file_atomic(path, text, 0o644)
        systemctl("daemon-reload")
    if not unit_enabled(UNIT_CONVERGE):
        systemctl("enable", UNIT_CONVERGE)


def remove_converge_unit():
    systemctl("disable", UNIT_CONVERGE)
    remove_quietly(os.path.join(UNIT_DIR, UNIT_CONVERGE))


def write_unit_file(path, text, mode=0o644):
    """Writes a unit or environment file when its content changed; True when it did."""
    if _read_exact(path, 1024 * 1024) == text:
        return False
    write_file_atomic(path, text, mode)
    return True


def write_slot_units(state, pw, slot):
    """Renders the unit and environment file of one instance ("" = the 1.0 unit); True when a
    file changed."""
    domain_id = state["domain_id"]
    view = slot_view(state, slot) if slot else state
    changed = write_unit_file(env_file_path(domain_id, slot), render_env_file(view, pw), 0o600)
    changed = write_unit_file(os.path.join(UNIT_DIR, app_unit(domain_id, slot)), render_app_unit(view, pw)) or changed
    return changed


def retire_legacy(state):
    """After the first switch: the 1.0 unit is no longer used (disabled, files removed)."""
    domain_id = state["domain_id"]
    unit = UNIT_APP % domain_id
    if os.path.exists(os.path.join(UNIT_DIR, unit)):
        systemctl("disable", "--now", unit, timeout=120)
        remove_quietly(os.path.join(UNIT_DIR, unit))
        remove_quietly(env_file_path(domain_id))
        systemctl("daemon-reload")
        systemctl("reset-failed", unit)


def retire_slots(state, pw, preserve_release=False):
    """The setting is off and the 1.0 unit is live (or nothing runs): removes the slot units and
    environment files, frees the slot ports and their sockets, and sets slot "". The pointer keeps
    naming the 1.0 instance until the snippet no longer uses it (convergence). Returns the
    updated state."""
    domain_id = state["domain_id"]
    units = [app_unit(domain_id, slot) for slot in SLOTS if os.path.exists(os.path.join(UNIT_DIR, app_unit(domain_id, slot)))]
    if units:
        systemctl("disable", "--now", *units, timeout=120)
    for slot in SLOTS:
        remove_quietly(os.path.join(UNIT_DIR, app_unit(domain_id, slot)))
        remove_quietly(env_file_path(domain_id, slot))
        unlink_socket_entry(domain_id, socket_name(slot))
    ops_retire_slots(state, preserve_release)
    zd_update_state(domain_id, slot="", port_a=0, port_b=0, switch=None)
    state.update({"slot": "", "port_a": 0, "port_b": 0, "switch": None})
    if units:
        systemctl("daemon-reload")
        systemctl("reset-failed", *units)
    return state


# --- convergence ----------------------------------------------------------------------------

def zd_converge_locked(state, pw, log=None, boot=False):
    """Repairs the slot units and the pointer of one application (the caller holds its deploy
    lock; docs/DESIGN.md section 12.8). Settles an interrupted switch from where the pointer
    points, stops leftover instances only when the pointer is confirmed elsewhere, enables the
    live unit, and removes pointer files the generated configuration no longer uses. Never
    starts an application. Returns the (updated) state."""
    domain_id = state["domain_id"]

    def note(text):
        if log:
            log.line(text)
        zd_journal(state, text)

    listen = state.get("listen")
    if listen in ("tcp", "unix") and (zd_has_slots(state) or (slot_files_left(domain_id) and pointer_wanted(state))):
        pointer = read_pointer_slot(state)
        intent = state.get("switch")
        live = state["slot"]
        if boot:
            enabled = [slot for slot in ("",) + SLOTS
                       if os.path.exists(os.path.join(UNIT_DIR, app_unit(domain_id, slot))) and unit_enabled(app_unit(domain_id, slot))]
            if len(enabled) == 1:
                live = enabled[0]
            elif enabled:
                live = pointer if pointer in enabled else (live if live in enabled else enabled[0])
        elif intent:
            target = intent["to"]
            live = target if pointer == target and unit_is_active(app_unit(domain_id, target)) else intent["from"]
        if intent or live != state["slot"]:
            fields = {"slot": live, "switch": None}
            if live != state["slot"]:
                fields["switched_at"] = now_iso()
            zd_update_state(domain_id, **fields)
            state.update(fields)
            if intent:
                note("settled an interrupted switch (%s to %s): %s serves." % (slot_label(intent["from"]), slot_label(intent["to"]),
                                                                              slot_label(live)))
        web_unit, web_kind = (None, None) if boot else web_traffic_server()
        changed = False
        if pointer != live:
            changed = write_pointer(state, pw, live)
            pointer = live
        elif listen == "unix" and tmpfiles_link_slot(domain_id) != live:
            write_tmpfiles(state, pw, link_slot=live)
        leftover = [slot for slot in ("",) + SLOTS if slot != live and os.path.exists(os.path.join(UNIT_DIR, app_unit(domain_id, slot)))
                    and unit_is_active(app_unit(domain_id, slot))]
        confirmed = True
        if listen == "tcp" and web_unit:
            if leftover and (changed or not web_effective(web_unit, web_kind, include_mtime(domain_id))):
                # Another instance still runs: it stops only once the running configuration of
                # the web server names the live port (a confirmed reload).
                with FileLock("web-reload"):
                    try:
                        confirmed = web_reload_confirm(web_unit, web_kind)[0]
                    except HelperError:
                        confirmed = False
            elif changed:
                # Nothing to stop: the reload only has to happen.
                with FileLock("web-reload"):
                    web_reload_nowait(web_unit)
        for slot in ("",) + SLOTS:
            unit = app_unit(domain_id, slot)
            if slot == live or not os.path.exists(os.path.join(UNIT_DIR, unit)):
                continue
            active = slot in leftover
            if active and not confirmed:
                continue
            if active or unit_enabled(unit):
                if boot:
                    systemctl("disable", unit)
                    systemctl("stop", "--no-block", unit)
                else:
                    systemctl("disable", "--now", unit, timeout=120)
                    systemctl("reset-failed", unit)
                if active:
                    note("stopped %s, left over from an interrupted switch." % unit)
            if listen == "unix" and slot in SLOTS and not active:
                unlink_socket_entry(domain_id, socket_name(slot))
        live_unit = app_unit(domain_id, live)
        if state.get("enabled") and not state.get("suspended") and not state.get("stopped") \
                and os.path.exists(os.path.join(UNIT_DIR, live_unit)) and not unit_enabled(live_unit):
            systemctl("enable", live_unit)
        if live and os.path.exists(os.path.join(UNIT_DIR, UNIT_APP % domain_id)) and not unit_is_active(UNIT_APP % domain_id):
            retire_legacy(state)
    if not boot and not zd_has_slots(state) and slot_files_left(domain_id):
        # The setting is off and the 1.0 unit is the live instance: after an interrupted switch
        # back to it (settled above), or when it was turned off before the first switch. The slots
        # go; a slot that still runs while the pointer is in use stops only after the pointer was
        # confirmed on the 1.0 unit (above, then at the next run).
        running = [slot for slot in SLOTS if os.path.exists(os.path.join(UNIT_DIR, app_unit(domain_id, slot)))
                   and unit_is_active(app_unit(domain_id, slot))]
        if not running or not pointer_wanted(state):
            state = retire_slots(state, pw)
            if log:
                log.line("Removed the units of the zero-downtime slots (the setting is off).")
    # Pointer files that the domain's generated configuration no longer uses.
    if not (listen == "unix" and zd_has_slots(state)) and os.path.lexists(link_path(domain_id)) \
            and not config_references(state, link_path(domain_id)):
        remove_link(domain_id)
        tmpfiles_drop_link(state, pw)
    if not (listen == "tcp" and zd_has_slots(state)) and os.path.exists(include_paths(domain_id)[0]) \
            and not config_references(state, "%s/%d." % (WEB_DIR, domain_id)):
        remove_include(domain_id)
    return state


def zd_converge(state, boot=False):
    """Convergence of one application when its deploy lock is free (skipped while busy)."""
    lock = FileLock("deploy-%d" % state["domain_id"])
    if not lock.acquire(blocking=False):
        return False
    try:
        fresh, pw = load_app_state(state["domain_id"])
        zd_converge_locked(fresh, pw, boot=boot)
        return True
    finally:
        lock.release()


def zd_needs_converge(raw):
    """Applications the convergence looks at: with slots (or the intent record of an interrupted
    switch), or with slot units or pointer files left over."""
    if not isinstance(raw.get("domain_id"), int):
        return False
    return zd_has_slots(raw) or slot_files_left(raw["domain_id"]) or os.path.lexists(link_path(raw["domain_id"])) \
        or os.path.exists(include_paths(raw["domain_id"])[0])


def internal_converge():
    """runway-converge.service (boot) or a manual run: converges every application. Before the
    web server runs nothing is reloaded and the enabled unit decides (boot mode)."""
    boot = web_traffic_server()[0] is None
    for raw in list(iter_app_states()):
        if not zd_needs_converge(raw):
            continue
        try:
            zd_converge(raw, boot=boot)
        except Exception as exc:  # noqa: BLE001 - one application must not stop the others
            sys.stderr.write("runway: convergence of #%s failed: %s\n" % (raw.get("domain_id"), exc))


# --- plain restart ----------------------------------------------------------------------------

def zd_plain_restart(state, pw, block=False, release_staged=False):
    """Restarts the live instance in place (short interruption; the caller holds the deploy
    lock): stops every other app unit, makes the 1.0 unit live when the setting is off, points
    the web server at the live instance and restarts it. Returns (state, unit)."""
    domain_id = state["domain_id"]
    if not state.get("zero_downtime") and (state.get("slot") or slot_files_left(domain_id)):
        # Turned off (or a worker now): the 1.0 unit becomes the live instance, the slots go.
        state = retire_slots(state, pw, preserve_release=True) if release_staged else retire_slots(state, pw)
        write_slot_units(state, pw, "")
        systemctl("daemon-reload")
    live = state.get("slot") or ""
    others = [app_unit(domain_id, slot) for slot in ("",) + SLOTS
              if slot != live and os.path.exists(os.path.join(UNIT_DIR, app_unit(domain_id, slot)))]
    if others:
        systemctl("disable", "--now", *others, timeout=120)
    unit = app_unit(domain_id, live)
    if pointer_wanted(state):
        changed = write_pointer(state, pw, live)
        if changed:
            web_unit = web_traffic_server()[0]
            if web_unit:
                with FileLock("web-reload"):
                    web_reload_nowait(web_unit)
    if state.get("switch") or state.get("restart_plain"):
        zd_update_state(domain_id, switch=None, restart_plain=False)
        state.update({"switch": None, "restart_plain": False})
    prepare_start(live_view(state), pw)
    systemctl("enable", unit, check=True)
    systemctl("reset-failed", unit)
    if block:
        proc = systemctl("restart", unit, timeout=120)
        if proc.returncode != 0:
            raise HelperError("systemctl restart failed: %s" % proc.stderr.strip())
    else:
        systemctl("restart", "--no-block", unit, check=True)
    return state, unit
