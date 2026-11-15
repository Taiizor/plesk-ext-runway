# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Metrics & Resource Monitoring (SQLite Time-Series)
# ---------------------------------------------------------------------------

import sqlite3

METRICS_DB_PATH = STATE_DIR + "/metrics.sqlite"
_CPU_PREV_FILE = CACHE_DIR + "/cpu_prev.json"
_DISK_CACHE = {}


def _open_metrics_db():
    ensure_dir(STATE_DIR, 0o700)
    db = sqlite3.connect(METRICS_DB_PATH, timeout=10.0)
    db.execute("PRAGMA journal_mode=WAL;")
    db.execute("PRAGMA synchronous=NORMAL;")
    with db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS app_metrics (
                domain_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                cpu_percent REAL NOT NULL,
                memory_bytes INTEGER NOT NULL,
                memory_used_bytes INTEGER NOT NULL,
                disk_bytes INTEGER NOT NULL,
                restarts INTEGER NOT NULL,
                PRIMARY KEY (domain_id, timestamp)
            );
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_app_metrics_time ON app_metrics (domain_id, timestamp);")
        db.execute("""
            CREATE TABLE IF NOT EXISTS server_metrics (
                timestamp INTEGER NOT NULL PRIMARY KEY,
                cpu_percent REAL NOT NULL,
                memory_used_bytes INTEGER NOT NULL,
                memory_total_bytes INTEGER NOT NULL,
                disk_used_bytes INTEGER NOT NULL,
                disk_total_bytes INTEGER NOT NULL
            );
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_server_metrics_time ON server_metrics (timestamp);")
    return db


def _fast_dir_size(path):
    now = time.time()
    cached = _DISK_CACHE.get(path)
    if cached and now - cached[0] < 120:
        return cached[1]
    if not os.path.exists(path):
        return 0
    try:
        proc = subprocess.run(["du", "-sk", path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
        out = proc.stdout.decode("utf-8", "replace").split()
        if out and out[0].isdigit():
            size = int(out[0]) * 1024
            _DISK_CACHE[path] = (now, size)
            return size
    except Exception:
        pass
    return 0


def _load_cpu_prev():
    data = read_json(_CPU_PREV_FILE)
    return data if isinstance(data, dict) else {}


def _save_cpu_prev(data):
    ensure_dir(CACHE_DIR, 0o700)
    write_json(_CPU_PREV_FILE, data)


def record_app_metric_sample(domain_id, state=None):
    """Records a single metrics point for an application."""
    if state is None:
        raw = read_json(app_state_path(domain_id))
        state = raw if isinstance(raw, dict) else {}
    if not state:
        return None

    unit = app_unit(domain_id, state.get("slot") or "")
    props = ["ActiveState", "MainPID", "MemoryCurrent", "CPUUsageNSec", "NRestarts", "ControlGroup"]
    shown = unit_show([unit], props).get(unit, {})
    active = shown.get("ActiveState") == "active"

    now = int(time.time())
    memory = unit_memory(shown) if active else {"memory_bytes": 0, "memory_used_bytes": 0}
    restarts = int(shown.get("NRestarts") or 0) if (shown.get("NRestarts") or "").isdigit() else 0
    raw_cpu_nsec = int(shown.get("CPUUsageNSec") or 0) if (shown.get("CPUUsageNSec") or "").isdigit() else 0

    cpu_prev = _load_cpu_prev()
    prev_key = "app_%d" % domain_id
    prev_entry = cpu_prev.get(prev_key)
    cpu_percent = 0.0

    if active and prev_entry and isinstance(prev_entry, list) and len(prev_entry) == 2:
        prev_time, prev_nsec = prev_entry
        dt = now - prev_time
        dnsec = raw_cpu_nsec - prev_nsec
        if dt > 0 and dnsec >= 0:
            cpu_percent = min(100.0 * (os.cpu_count() or 1), max(0.0, (dnsec / (dt * 1e9)) * 100.0))

    if active and raw_cpu_nsec > 0:
        cpu_prev[prev_key] = [now, raw_cpu_nsec]
        _save_cpu_prev(cpu_prev)

    disk_bytes = _fast_dir_size(state.get("app_dir", "")) if active else 0

    try:
        db = _open_metrics_db()
        with db:
            db.execute("""
                INSERT OR REPLACE INTO app_metrics
                (domain_id, timestamp, cpu_percent, memory_bytes, memory_used_bytes, disk_bytes, restarts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (domain_id, now, round(cpu_percent, 2), memory.get("memory_bytes") or 0,
                  memory.get("memory_used_bytes") or 0, disk_bytes, restarts))
            # Occasional cleanup: remove data older than 14 days
            if now % 100 == 0:
                db.execute("DELETE FROM app_metrics WHERE timestamp < ?", (now - 14 * 86400,))
        db.close()
    except Exception:
        pass

    return {
        "timestamp": now,
        "cpu_percent": round(cpu_percent, 2),
        "memory_bytes": memory.get("memory_bytes") or 0,
        "memory_used_bytes": memory.get("memory_used_bytes") or 0,
        "disk_bytes": disk_bytes,
        "restarts": restarts,
    }


def record_server_metric_sample():
    """Records server-wide CPU, memory and disk usage."""
    now = int(time.time())
    cpu_percent = 0.0

    # CPU from /proc/stat
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        parts = [float(x) for x in line.split()[1:8]]
        total_time = sum(parts)
        idle_time = parts[3] + (parts[4] if len(parts) > 4 else 0)
        cpu_prev = _load_cpu_prev()
        prev_entry = cpu_prev.get("server")
        if prev_entry and isinstance(prev_entry, list) and len(prev_entry) == 2:
            prev_total, prev_idle = prev_entry
            diff_total = total_time - prev_total
            diff_idle = idle_time - prev_idle
            if diff_total > 0:
                cpu_percent = max(0.0, min(100.0, (1.0 - diff_idle / diff_total) * 100.0))
        cpu_prev["server"] = [total_time, idle_time]
        _save_cpu_prev(cpu_prev)
    except Exception:
        pass

    # Memory from /proc/meminfo
    mem_total = 0
    mem_used = 0
    try:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                p = line.split(":")
                if len(p) == 2:
                    meminfo[p[0].strip()] = int(p[1].split()[0]) * 1024
        mem_total = meminfo.get("MemTotal", 0)
        mem_avail = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        mem_used = max(0, mem_total - mem_avail)
    except Exception:
        pass

    # Disk from statvfs
    disk_total = 0
    disk_used = 0
    try:
        st = os.statvfs("/")
        disk_total = st.f_blocks * st.f_frsize
        disk_used = (st.f_blocks - st.f_bfree) * st.f_frsize
    except Exception:
        pass

    try:
        db = _open_metrics_db()
        with db:
            db.execute("""
                INSERT OR REPLACE INTO server_metrics
                (timestamp, cpu_percent, memory_used_bytes, memory_total_bytes, disk_used_bytes, disk_total_bytes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (now, round(cpu_percent, 2), mem_used, mem_total, disk_used, disk_total))
            if now % 100 == 0:
                db.execute("DELETE FROM server_metrics WHERE timestamp < ?", (now - 14 * 86400,))
        db.close()
    except Exception:
        pass

    return {
        "timestamp": now,
        "cpu_percent": round(cpu_percent, 2),
        "memory_used_bytes": mem_used,
        "memory_total_bytes": mem_total,
        "disk_used_bytes": disk_used,
        "disk_total_bytes": disk_total,
    }


def cmd_app_metrics(payload):
    payload = payload or {}
    domain_id = v_domain_id(payload.get("domain_id"))
    time_range = payload.get("range", "1h")
    if time_range not in ("1h", "24h", "7d"):
        time_range = "1h"

    # Always sample the current point
    latest = record_app_metric_sample(domain_id)

    now = int(time.time())
    if time_range == "1h":
        since = now - 3600
        step = 60
    elif time_range == "24h":
        since = now - 86400
        step = 300
    else:
        since = now - 7 * 86400
        step = 3600

    results = []
    try:
        db = _open_metrics_db()
        cursor = db.cursor()
        query = """
            SELECT
                (timestamp / ?) * ? AS t,
                ROUND(AVG(cpu_percent), 2) AS cpu,
                CAST(AVG(memory_bytes) AS INTEGER) AS mem,
                CAST(AVG(memory_used_bytes) AS INTEGER) AS mem_used,
                CAST(MAX(disk_bytes) AS INTEGER) AS disk,
                MAX(restarts) AS restarts
            FROM app_metrics
            WHERE domain_id = ? AND timestamp >= ?
            GROUP BY t
            ORDER BY t ASC
        """
        cursor.execute(query, (step, step, domain_id, since))
        for row in cursor.fetchall():
            results.append({
                "time": row[0],
                "cpu": row[1] or 0.0,
                "memory": row[2] or 0,
                "memory_used": row[3] or 0,
                "disk": row[4] or 0,
                "restarts": row[5] or 0,
            })
        db.close()
    except Exception:
        pass

    # If results are sparse (e.g. freshly installed app), backfill baseline points
    if len(results) < 2 and latest:
        base_mem = latest.get("memory_bytes") or 0
        base_mem_used = latest.get("memory_used_bytes") or 0
        base_disk = latest.get("disk_bytes") or 0
        base_restarts = latest.get("restarts") or 0
        count = 10 if time_range == "1h" else 12
        for i in range(count, 0, -1):
            t = now - i * step
            results.append({
                "time": t,
                "cpu": 0.0,
                "memory": base_mem,
                "memory_used": base_mem_used,
                "disk": base_disk,
                "restarts": base_restarts,
            })
        results.append({
            "time": latest["timestamp"],
            "cpu": latest["cpu_percent"],
            "memory": base_mem,
            "memory_used": base_mem_used,
            "disk": base_disk,
            "restarts": base_restarts,
        })
        results.sort(key=lambda r: r["time"])

    return {"ok": True, "range": time_range, "step": step, "metrics": results, "latest": latest}


def cmd_server_metrics(payload):
    payload = payload or {}
    time_range = payload.get("range", "1h")
    if time_range not in ("1h", "24h", "7d"):
        time_range = "1h"

    latest = record_server_metric_sample()
    now = int(time.time())
    if time_range == "1h":
        since = now - 3600
        step = 60
    elif time_range == "24h":
        since = now - 86400
        step = 300
    else:
        since = now - 7 * 86400
        step = 3600

    results = []
    try:
        db = _open_metrics_db()
        cursor = db.cursor()
        query = """
            SELECT
                (timestamp / ?) * ? AS t,
                ROUND(AVG(cpu_percent), 2) AS cpu,
                CAST(AVG(memory_used_bytes) AS INTEGER) AS mem_used,
                CAST(MAX(memory_total_bytes) AS INTEGER) AS mem_total,
                CAST(AVG(disk_used_bytes) AS INTEGER) AS disk_used,
                CAST(MAX(disk_total_bytes) AS INTEGER) AS disk_total
            FROM server_metrics
            WHERE timestamp >= ?
            GROUP BY t
            ORDER BY t ASC
        """
        cursor.execute(query, (step, step, since))
        for row in cursor.fetchall():
            results.append({
                "time": row[0],
                "cpu": row[1] or 0.0,
                "memory_used": row[2] or 0,
                "memory_total": row[3] or 0,
                "disk_used": row[4] or 0,
                "disk_total": row[5] or 0,
            })
        db.close()
    except Exception:
        pass

    if len(results) < 2 and latest:
        count = 10 if time_range == "1h" else 12
        for i in range(count, 0, -1):
            t = now - i * step
            results.append({
                "time": t,
                "cpu": latest["cpu_percent"],
                "memory_used": latest["memory_used_bytes"],
                "memory_total": latest["memory_total_bytes"],
                "disk_used": latest["disk_used_bytes"],
                "disk_total": latest["disk_total_bytes"],
            })
        results.append({
            "time": latest["timestamp"],
            "cpu": latest["cpu_percent"],
            "memory_used": latest["memory_used_bytes"],
            "memory_total": latest["memory_total_bytes"],
            "disk_used": latest["disk_used_bytes"],
            "disk_total": latest["disk_total_bytes"],
        })
        results.sort(key=lambda r: r["time"])

    return {"ok": True, "range": time_range, "step": step, "metrics": results, "latest": latest}


def cmd_health_ping(payload):
    """Direct live health probe of an application endpoint, returning latency in ms."""
    payload = payload or {}
    domain_id = v_domain_id(payload.get("domain_id"))
    state = read_json(app_state_path(domain_id))
    if not isinstance(state, dict):
        raise HelperError("Application is not configured")

    custom_path = payload.get("health_path")
    if isinstance(custom_path, str) and custom_path.startswith("/"):
        state["health_path"] = custom_path
    elif not state.get("health_path"):
        state["health_path"] = "/"

    custom_match = payload.get("health_match")
    if isinstance(custom_match, str):
        state["health_match"] = custom_match

    pw = pwd.getpwnam(str(state.get("sysuser")))
    slots = zd_has_slots(state)
    view = live_view(state) if slots else state
    listener, _det, _code, _par = listener_info(view, pw)

    t0 = time.perf_counter()
    status, detail, code, params = health_check(view, listener, pw, timeout=5)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

    return {
        "ok": True,
        "healthy": status == "healthy",
        "status": status,
        "detail": detail,
        "code": code,
        "params": params,
        "latency_ms": elapsed_ms,
        "checked_at": now_iso(),
    }
