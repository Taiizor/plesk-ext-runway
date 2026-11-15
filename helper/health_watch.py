# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Health watch (opt-in per application, docs/DESIGN.md section 7)
# ---------------------------------------------------------------------------

def epoch_iso(value):
    """Epoch seconds -> '2026-11-13T07:00:00+00:00', None for anything else."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).replace(microsecond=0).isoformat()


def health_watch_path(domain_id):
    return os.path.join(HEALTH_WATCH_DIR, "%d.json" % domain_id)


def read_health_watch(domain_id):
    data = read_json(health_watch_path(domain_id))
    return data if isinstance(data, dict) else {}


def _recent_restarts(watch, now):
    return [t for t in watch.get("restarts") or []
            if isinstance(t, (int, float)) and not isinstance(t, bool) and 0 <= now - t < HEALTH_WATCH_WINDOW]


def health_watch_status(domain_id, state):
    """The "health_watch" object of app-status (null without the watch)."""
    if not isinstance(state, dict) or not state.get("health_watch"):
        return None
    watch = read_health_watch(domain_id)
    now = time.time()

    def number(key, default):
        value = state.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else default

    return {
        "interval": number("health_interval", HEALTH_WATCH_INTERVAL_DEFAULT),
        "failures_limit": number("health_failures", HEALTH_WATCH_FAILURES_DEFAULT),
        "failures": int(watch.get("failures") or 0),
        "checked_iso": epoch_iso(watch.get("checked_epoch")),
        "result": watch.get("result") if watch.get("result") in ("healthy", "unhealthy", "skipped") else None,
        "detail": str(watch.get("detail") or "")[:300],
        "code": str(watch.get("code") or "")[:40],
        "params": watch.get("params") if isinstance(watch.get("params"), dict) else {},
        "restarts_last_hour": len(_recent_restarts(watch, now)),
        "max_restarts": HEALTH_WATCH_MAX_RESTARTS,
        "restarted_iso": epoch_iso(watch.get("restarted_epoch")),
        "restart_detail": str(watch.get("restart_detail") or "")[:300],
        "restart_code": str(watch.get("restart_code") or "")[:40],
        "restart_params": watch.get("restart_params") if isinstance(watch.get("restart_params"), dict) else {},
        "paused": bool(watch.get("paused")),
    }


def sync_health_units():
    """Installs and starts runway-health.timer while an application has the health watch on, and
    removes it (with its service) when none has: servers without it run nothing."""
    service_path = os.path.join(UNIT_DIR, UNIT_HEALTH)
    timer_path = os.path.join(UNIT_DIR, UNIT_HEALTH_TIMER)
    states = list(iter_app_states())
    for raw in states:
        # The failures and restarts of a watch that was turned off are forgotten.
        if not raw.get("health_watch") and isinstance(raw.get("domain_id"), int) and not isinstance(raw.get("domain_id"), bool):
            remove_quietly(health_watch_path(raw["domain_id"]))
    if not any(raw.get("health_watch") for raw in states):
        if os.path.exists(timer_path) or os.path.exists(service_path):
            systemctl("disable", "--now", UNIT_HEALTH_TIMER)
            remove_quietly(timer_path)
            remove_quietly(service_path)
            systemctl("daemon-reload")
            systemctl("reset-failed", UNIT_HEALTH, UNIT_HEALTH_TIMER)
        return False
    service = "\n".join([
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]",
        "Description=Runway: health watch (restarts an application whose health check keeps failing)",
        "",
        "[Service]",
        "Type=oneshot",
        "ExecStart=%s _health" % HELPER_COPY,
        "TimeoutStartSec=600",
        "",
    ])
    timer = "\n".join([
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]",
        "Description=Runway: health watch every %d seconds" % HEALTH_WATCH_TICK,
        "",
        "[Timer]",
        "OnActiveSec=%d" % HEALTH_WATCH_TICK,
        "OnUnitActiveSec=%d" % HEALTH_WATCH_TICK,
        "AccuracySec=1",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ])
    changed = write_unit_file(service_path, service)
    changed = write_unit_file(timer_path, timer) or changed
    if changed:
        systemctl("daemon-reload")
    if changed or not unit_enabled(UNIT_HEALTH_TIMER) or not unit_is_active(UNIT_HEALTH_TIMER):
        systemctl("enable", "--now", UNIT_HEALTH_TIMER)
    return True


def internal_health(now_mode=False):
    """runway-health.service (every HEALTH_WATCH_TICK seconds): the health watch of every application
    that has it on. now_mode ("_health now", tests and by hand): every one of them at once, without
    the interval and the start grace. Prints what it did (the journal of runway-health.service)."""
    ensure_dir(HEALTH_WATCH_DIR, 0o700)
    watched = set()
    for raw in list(iter_app_states()):
        domain_id = raw.get("domain_id")
        if not isinstance(domain_id, int) or isinstance(domain_id, bool) or not raw.get("health_watch"):
            continue
        watched.add(domain_id)
        try:
            line = health_watch_app(domain_id, now_mode)
        except Exception as exc:  # noqa: BLE001 - one application must not stop the others
            line = "#%d: %s" % (domain_id, exc)
        if line:
            print(line, flush=True)
    for name in _listdir(HEALTH_WATCH_DIR):
        match = re.match(r"^(\d+)\.json$", name)
        if match and int(match.group(1)) not in watched:
            remove_quietly(os.path.join(HEALTH_WATCH_DIR, name))


def health_watch_app(domain_id, now_mode=False):
    """One application of the health watch when its check is due; never while a deployment, a
    save or a switch holds its deploy lock (they restart it themselves). Returns a log line."""
    watch = read_health_watch(domain_id)
    state, _pw = load_app_state(domain_id)
    if not state["health_watch"]:
        return None
    if not now_mode and time.time() - float(watch.get("checked_epoch") or 0) < state["health_interval"] - 2:
        return None
    lock = FileLock("deploy-%d" % domain_id)
    if unit_is_active(UNIT_DEPLOY % domain_id) or not lock.acquire(blocking=False):
        return None
    try:
        state, pw = load_app_state(domain_id)
        return _health_watch_locked(state, pw, watch, now_mode)
    finally:
        lock.release()


def _health_watch_locked(state, pw, watch, now_mode):
    domain_id = state["domain_id"]
    now = time.time()
    path = health_watch_path(domain_id)
    slots = zd_has_slots(state)
    unit = app_unit(domain_id, state["slot"]) if slots else UNIT_APP % domain_id
    view = live_view(state) if slots else state
    if not state["health_watch"] or not state["enabled"] or state["suspended"] or state["stopped"] or state["tampered"]:
        if watch.get("failures"):
            watch["failures"] = 0
            write_json(path, watch)
        return None
    info = unit_show([unit], ["ActiveState", "SubState", "ActiveEnterTimestampMonotonic"]).get(unit, {})
    if info.get("ActiveState") != "active" or info.get("SubState") != "running":
        # Not running: systemd restarts a crashed application itself (Restart=always), and a
        # starting one is not judged yet.
        if watch.get("failures"):
            watch["failures"] = 0
            write_json(path, watch)
        return None
    entered = info.get("ActiveEnterTimestampMonotonic") or ""
    entered = int(entered) if entered.isdigit() else 0
    instance = "%s@%d" % (unit, entered)
    if watch.get("instance") != instance:
        # Another instance (restarted by anybody): its failures start from zero.
        watch.update({"instance": instance, "failures": 0})
    if not now_mode and entered and time.monotonic() - entered / 1e6 < HEALTH_WATCH_GRACE:
        write_json(path, watch)
        return None
    listener, ldetail, lcode, lparams = listener_info(view, pw)
    if listener in ("foreign", "tampered"):
        # Another user holds the endpoint: a restart would not help (the status reports it).
        watch.update({"checked_epoch": now, "result": "skipped", "detail": ldetail, "code": lcode, "params": lparams})
        write_json(path, watch)
        return None
    result, detail, code, params = health_check(view, listener, pw, HEALTH_WATCH_TIMEOUT)
    healthy = result == "healthy"
    watch.update({"checked_epoch": now, "result": "healthy" if healthy else "unhealthy",
                  "detail": detail, "code": code, "params": params})
    if healthy:
        watch.update({"failures": 0, "paused": False})
        write_json(path, watch)
        return None
    watch["failures"] = int(watch.get("failures") or 0) + 1
    if watch["failures"] < state["health_failures"]:
        write_json(path, watch)
        return "#%d: health check failed (%d of %d in a row): %s" % (domain_id, watch["failures"], state["health_failures"], detail)
    restarts = _recent_restarts(watch, now)
    watch["restarts"] = restarts
    if len(restarts) >= HEALTH_WATCH_MAX_RESTARTS:
        if not watch.get("paused"):
            ops_event(state, "health_paused", {"restarts_last_hour": len(restarts)})
            journal_note(domain_id, "health watch: %d failed health checks in a row (last: %s), but no restart: it "
                                    "restarted the application %d times within the last hour and restarts it again once "
                                    "the oldest of them is an hour ago." % (watch["failures"], detail, len(restarts)))
        watch["paused"] = True
        write_json(path, watch)
        return "#%d: not restarted (%d restarts within the last hour): %s" % (domain_id, len(restarts), detail)
    message = "health watch: restarting the application after %d failed health checks in a row (last: %s)." % (
        watch["failures"], detail)
    journal_note(domain_id, message)
    if slots:
        zd_plain_restart(state, pw)
    else:
        prepare_start(state, pw)
        systemctl("enable", unit, check=True)
        systemctl("reset-failed", unit)
        systemctl("restart", "--no-block", unit, check=True)
    restarts.append(now)
    watch.update({"restarts": restarts, "restarted_epoch": now, "restart_detail": detail, "restart_code": code,
                  "restart_params": params, "failures": 0, "paused": False, "instance": None})
    write_json(path, watch)
    ops_event(state, "health_restart", {"restarts_last_hour": len(restarts)})
    return "#%d: %s" % (domain_id, message)


FLAG_KEYS = ("stopped", "tampered", "tampered_at", "tampered_detail")
CLEARED_FLAGS = {"stopped": False, "tampered": False, "tampered_at": "", "tampered_detail": ""}
