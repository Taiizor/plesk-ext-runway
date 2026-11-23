# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Public files
# ---------------------------------------------------------------------------

def public_files_watch_enabled(state):
    """Stopped applications still serve static paths; disabled or suspended ones are left alone."""
    return bool(state.get("document_root") and state.get("listen") != "none"
                and state.get("enabled") and not state.get("suspended"))


def sync_public_files_units(state):
    """One bounded permission check per application, independent of builds and panel requests."""
    domain_id = state["domain_id"]
    service_name = UNIT_PUBLIC_FILES % domain_id
    timer_name = UNIT_PUBLIC_FILES_TIMER % domain_id
    service_path = os.path.join(UNIT_DIR, service_name)
    timer_path = os.path.join(UNIT_DIR, timer_name)
    if not public_files_watch_enabled(state):
        if os.path.exists(timer_path) or os.path.exists(service_path):
            systemctl("disable", "--now", timer_name)
            systemctl("stop", service_name)
            remove_quietly(timer_path)
            remove_quietly(service_path)
            systemctl("daemon-reload")
            systemctl("reset-failed", service_name, timer_name)
        return
    service = "\n".join([
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]", "Description=Runway: public file permissions for application #%d" % domain_id, "",
        "[Service]", "Type=oneshot", "ExecStart=%s _public-files %d" % (HELPER_COPY, domain_id),
        "TimeoutStartSec=%d" % (PUBLIC_FILES_SECONDS + 60), "Nice=10", "",
    ])
    timer = "\n".join([
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]", "Description=Runway: check public file permissions every minute", "",
        "[Timer]", "OnActiveSec=15", "OnUnitInactiveSec=60", "AccuracySec=1", "",
        "[Install]", "WantedBy=timers.target", "",
    ])
    changed = write_unit_file(service_path, service)
    changed = write_unit_file(timer_path, timer) or changed
    if changed:
        systemctl("daemon-reload", check=True)
    if changed or not unit_enabled(timer_name) or not unit_is_active(timer_name):
        systemctl("enable", "--now", timer_name, check=True)


def internal_public_files(domain_id):
    """Repair later uploads with the same ownership, path and symlink rules as the build step."""
    lock = FileLock("public-files-%d" % domain_id)
    if not lock.acquire(blocking=False):
        return
    try:
        state, pw = load_app_state(domain_id)
        if not public_files_watch_enabled(state) or state.get("tampered") or unit_is_active(UNIT_DEPLOY % domain_id):
            return
        # Do not hold the deploy lock: a permission scan must never delay a deployment. The
        # descriptor-based walk tolerates files being replaced by a concurrent build or upload.
        result = open_public_files(state, pw)
        if result is not None and (result.get("changed") or result.get("passable") or result.get("truncated")):
            print(public_files_summary(result, state["document_root"]))
    finally:
        lock.release()
