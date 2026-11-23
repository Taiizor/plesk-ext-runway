# Copyright 2026 Taiizor. Licensed under the MIT License.

def cmd_reapply_all(_payload):
    """Re-renders unit files, environment files and tmpfiles entries of every configured app and
    prepares the socket directories (used after an extension upgrade; running services keep
    running and pick the changes up at their next restart). Errors are reported per app."""
    ensure_layout()
    count = 0
    errors = []
    for raw in list(iter_app_states()):
        domain_id = raw.get("domain_id")
        try:
            dropped = _sanitize_stored_env(raw)
            if dropped:
                errors.append("#%s: removed %s from the environment variables (no longer allowed)"
                              % (domain_id, ", ".join(dropped)))
            state, pw = validate_app(raw)
            state["port"] = raw.get("port", 0)
            state.update(helper_fields(raw))
            if zd_has_slots(state):
                # Zero-downtime slots: the units and env files of both slots; the pointer only
                # while no deployment holds the deploy lock (docs/DESIGN.md section 12.8).
                ensure_converge_unit()
                lock = FileLock("deploy-%d" % state["domain_id"])
                if lock.acquire(blocking=False):
                    try:
                        state, pw = load_app_state(state["domain_id"])
                        if state["switch"]:
                            # An interrupted switch is settled from the pointer first (§12.8).
                            zd_converge_locked(state, pw)
                            state, pw = load_app_state(state["domain_id"])
                        write_units(state, pw)
                        if pointer_wanted(state):
                            write_pointer(state, pw, state["slot"])
                    finally:
                        lock.release()
                else:
                    errors.append("#%s: a deployment is running; its units were not re-rendered" % domain_id)
            else:
                write_units(state, pw)
            if state["listen"] == "unix":
                ensure_socket_dir(state["domain_id"], pw)
            sync_public_files_units(state)
            count += 1
        except Exception as exc:  # noqa: BLE001
            errors.append("#%s: %s" % (domain_id, exc))
            if isinstance(domain_id, int):
                for unit in all_app_units(domain_id):
                    if _strip_privileged_exec(os.path.join(UNIT_DIR, unit)):
                        errors.append("#%s: removed root-privileged Exec lines from the old unit file%s"
                                      % (domain_id, "" if unit == UNIT_APP % domain_id else " " + unit))
    systemctl("daemon-reload")
    sync_health_units()
    sync_metrics_units()
    return {"count": count, "errors": errors}


def cmd_install(_payload):
    if systemd_version() == 0:
        raise HelperError("systemd is required but was not found")
    ensure_layout()
    result = cmd_reapply_all(None)
    result["info"] = cmd_info(None)
    return result


def cmd_uninstall(payload):
    keep_toolchains = bool((payload or {}).get("keep_toolchains"))
    sync_metrics_units(enabled=False)
    removed = []
    for state in list(iter_app_states()):
        try:
            remove_app(int(state["domain_id"]))
            removed.append(state.get("domain_id"))
        except Exception:  # noqa: BLE001 - best effort during uninstall
            pass
    systemctl("stop", UNIT_ADMIN_JOB)
    if os.path.exists(os.path.join(UNIT_DIR, UNIT_CONVERGE)):
        remove_converge_unit()
        systemctl("daemon-reload")
    # No application is left: the health watch timer goes too.
    sync_health_units()
    for name in _listdir(TMPFILES_DIR):
        if name == "runway.conf" or re.match(r"^runway-\d+\.conf$", name):
            remove_quietly(os.path.join(TMPFILES_DIR, name))
    shutil.rmtree(RUN_DIR, ignore_errors=True)
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    shutil.rmtree(CONF_DIR, ignore_errors=True)
    if keep_toolchains:
        remove_quietly(HELPER_COPY)
    else:
        shutil.rmtree(BASE_DIR, ignore_errors=True)
    return {"removed_apps": removed}


def cmd_web_reconfigure(payload):
    domains = (payload or {}).get("domains") or []
    if not isinstance(domains, list) or len(domains) > 500:
        raise HelperError("Invalid domain list")
    plesk = shutil.which("plesk", path=ROOT_PATH) or "/usr/sbin/plesk"
    errors = []
    for name in domains:
        name = v_domain_name(name)
        proc = run([plesk, "sbin", "httpdmng", "--reconfigure-domain", name], timeout=300)
        if proc.returncode != 0:
            errors.append("%s: %s" % (name, (proc.stderr or proc.stdout).strip()[-500:]))
    if errors:
        raise HelperError("Web server reconfiguration failed: " + "; ".join(errors))
    return {"reconfigured": domains}
