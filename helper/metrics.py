# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Metrics & Resource Monitoring (SQLite Time-Series: CPU, Memory, Disk, Network)
# ---------------------------------------------------------------------------

import sqlite3

METRICS_DB_PATH = STATE_DIR + "/metrics.sqlite"
_CPU_PREV_FILE = CACHE_DIR + "/cpu_prev.json"
METRICS_INTERVAL = 60
METRICS_MIN_INTERVAL = 10
METRIC_PROPS = ["ActiveState", "MainPID", "ActiveEnterTimestampMonotonic", "MemoryCurrent",
                "CPUUsageNSec", "NRestarts", "ControlGroup", "IPIngressBytes", "IPEgressBytes",
                "IOReadBytes", "IOWriteBytes"]


def unit_disk_counters(info):
    """systemd counters with a cgroup fallback for older systemd and cgroup v1 hosts."""
    counters = [memory_value(info.get(key)) for key in ("IOReadBytes", "IOWriteBytes")]
    if all(value is not None for value in counters):
        return counters
    group = info.get("ControlGroup", "")
    if not group or not RE_CONTROL_GROUP.match(group) or any(part in (".", "..") for part in group.split("/")):
        return counters
    for path, unified in (("/sys/fs/cgroup" + group + "/io.stat", True),
                          ("/sys/fs/cgroup/blkio" + group + "/blkio.throttle.io_service_bytes_recursive", False),
                          ("/sys/fs/cgroup/blkio" + group + "/blkio.io_service_bytes_recursive", False)):
        try:
            with open(path, "r") as stream:
                text = stream.read(1024 * 1024)
        except OSError:
            continue
        totals = [0, 0]
        for line in text.splitlines():
            fields = line.split()
            if not fields or not re.match(r"^\d+:\d+$", fields[0]):
                continue
            if unified:
                for field in fields[1:]:
                    key, separator, value = field.partition("=")
                    if separator and key in ("rbytes", "wbytes") and value.isdigit():
                        totals[0 if key == "rbytes" else 1] += int(value)
            elif len(fields) == 3 and fields[1] in ("Read", "Write") and fields[2].isdigit():
                totals[0 if fields[1] == "Read" else 1] += int(fields[2])
        return totals
    return counters


def metric_rate(current, previous, elapsed):
    """Unknown, reset and warm-up counters are gaps, not zero throughput."""
    if current is None or previous is None or elapsed <= 0 or current < previous:
        return None
    return round((current - previous) / elapsed, 2)


def server_disk_counters():
    """Count whole leaf block devices once, excluding partitions and stacked mapper/RAID views."""
    counters = {}
    try:
        devices = os.listdir("/sys/block")
        for device in devices:
            if device.startswith(("loop", "ram", "zram")):
                continue
            base = "/sys/block/" + device
            if os.listdir(base + "/slaves"):
                continue
            text = _read_text(base + "/stat", 4096)
            fields = text.split() if text else []
            if len(fields) < 7 or not fields[2].isdigit() or not fields[6].isdigit():
                return None
            # Linux block statistics always express sectors in 512-byte units.
            counters[device] = [int(fields[2]) * 512, int(fields[6]) * 512]
    except OSError:
        return None
    return counters or None


def sync_metrics_units(enabled=True):
    """Collect even when the panel is closed; install/upgrade and uninstall own the timer."""
    service_path = os.path.join(UNIT_DIR, UNIT_METRICS)
    timer_path = os.path.join(UNIT_DIR, UNIT_METRICS_TIMER)
    if not enabled:
        systemctl("disable", "--now", UNIT_METRICS_TIMER)
        systemctl("stop", UNIT_METRICS)
        remove_quietly(timer_path)
        remove_quietly(service_path)
        systemctl("daemon-reload")
        systemctl("reset-failed", UNIT_METRICS, UNIT_METRICS_TIMER)
        return
    service = "\n".join([
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]", "Description=Runway: collect server and application metrics", "",
        "[Service]", "Type=oneshot", "ExecStart=%s _metrics" % HELPER_COPY,
        "TimeoutStartSec=300", "",
    ])
    timer = "\n".join([
        "# Managed by the Plesk Runway extension. Manual changes will be overwritten.",
        "[Unit]", "Description=Runway: resource metrics every minute", "",
        "[Timer]", "OnActiveSec=15", "OnUnitActiveSec=%d" % METRICS_INTERVAL,
        "AccuracySec=1", "", "[Install]", "WantedBy=timers.target", "",
    ])
    changed = write_unit_file(service_path, service)
    changed = write_unit_file(timer_path, timer) or changed
    if changed:
        systemctl("daemon-reload", check=True)
    if changed or not unit_enabled(UNIT_METRICS_TIMER) or not unit_is_active(UNIT_METRICS_TIMER):
        systemctl("enable", "--now", UNIT_METRICS_TIMER, check=True)


def metric_app_units(domain_id, state):
    """Include both deployment slots while they consume resources."""
    if state.get("slot") in SLOTS or state.get("zero_downtime"):
        return all_app_units(domain_id)
    return [app_unit(domain_id)]


def collect_metric_samples():
    """Serialize counter baselines across the timer and concurrent panel requests."""
    with FileLock("metrics"):
        latest = _record_server_metric_sample()
        states = list(iter_app_states())
        units = list(dict.fromkeys(unit for state in states
                                  for unit in metric_app_units(int(state["domain_id"]), state)))
        shown = unit_show(units, METRIC_PROPS)
        samples = []
        errors = []
        for state in states:
            domain_id = int(state["domain_id"])
            try:
                samples.append(_record_app_metric_sample(domain_id, state, shown))
            except Exception as exc:  # noqa: BLE001 - a broken app must not stop other samples
                errors.append("#%d: %s" % (domain_id, exc))
        db = _open_metrics_db()
        try:
            with db:
                cutoff = int(time.time()) - 14 * 86400
                db.execute("DELETE FROM app_metrics WHERE timestamp < ?", (cutoff,))
                db.execute("DELETE FROM server_metrics WHERE timestamp < ?", (cutoff,))
        finally:
            db.close()
        summary = None if errors else {
            key: round(sum(sample[key] for sample in samples), 2)
            for key in ("cpu_percent", "memory_used_bytes", "disk_bytes", "net_rate")
        }
        if summary is not None:
            for key in ("disk_read_rate", "disk_write_rate"):
                values = [sample[key] for sample in samples]
                summary[key] = None if any(value is None for value in values) else round(sum(values), 2)
        return {"latest": latest, "project_summary": summary, "errors": errors}


def internal_metrics():
    result = collect_metric_samples()
    if result["errors"]:
        raise HelperError("Metrics collection failed: " + "; ".join(result["errors"]))


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
                net_bytes INTEGER NOT NULL DEFAULT 0,
                net_rate REAL NOT NULL DEFAULT 0.0,
                restarts INTEGER NOT NULL,
                disk_read_rate REAL,
                disk_write_rate REAL,
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
                disk_total_bytes INTEGER NOT NULL,
                net_rx_rate REAL NOT NULL DEFAULT 0.0,
                net_tx_rate REAL NOT NULL DEFAULT 0.0,
                disk_read_rate REAL,
                disk_write_rate REAL
            );
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_server_metrics_time ON server_metrics (timestamp);")
    # Preserve old samples; throughput before this upgrade remains unknown (NULL).
    with db:
        for table, extra in (("app_metrics", (("net_bytes", "INTEGER NOT NULL DEFAULT 0"),
                                               ("net_rate", "REAL NOT NULL DEFAULT 0.0"))),
                             ("server_metrics", (("net_rx_rate", "REAL NOT NULL DEFAULT 0.0"),
                                                  ("net_tx_rate", "REAL NOT NULL DEFAULT 0.0")))):
            columns = {row[1] for row in db.execute("PRAGMA table_info(%s)" % table)}
            for col, definition in extra + (("disk_read_rate", "REAL"), ("disk_write_rate", "REAL")):
                if col not in columns:
                    db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, definition))
    return db


def _fast_dir_size(path):
    now = time.time()
    # Helpers are short-lived processes; an in-memory cache cannot reduce repeated du calls.
    cache_path = os.path.join(CACHE_DIR, "disk-%s.json" % hashlib.sha256(path.encode("utf-8")).hexdigest())
    cached = read_json(cache_path)
    if isinstance(cached, dict) and 0 <= now - cached.get("time", 0) < 120:
        return cached["bytes"]
    if not os.path.exists(path):
        return 0
    try:
        proc = subprocess.run(["du", "-sk", path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
        out = proc.stdout.decode("utf-8", "replace").split()
        if out and out[0].isdigit():
            size = int(out[0]) * 1024
            ensure_dir(CACHE_DIR, 0o700)
            write_json(cache_path, {"time": now, "bytes": size})
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
    with FileLock("metrics"):
        return _record_app_metric_sample(domain_id, state)


def _record_app_metric_sample(domain_id, state=None, shown=None):
    if state is None:
        raw = read_json(app_state_path(domain_id))
        state = raw if isinstance(raw, dict) else {}
    if not state:
        return None

    now = int(time.time())
    db = _open_metrics_db()
    try:
        row = db.execute("""SELECT timestamp, cpu_percent, memory_bytes, memory_used_bytes,
                            disk_bytes, net_bytes, net_rate, restarts, disk_read_rate, disk_write_rate FROM app_metrics
                            WHERE domain_id = ? AND timestamp > ? ORDER BY timestamp DESC LIMIT 1""",
                         (domain_id, now - METRICS_MIN_INTERVAL)).fetchone()
    finally:
        db.close()
    if row and row[0] <= now:
        return dict(zip(("timestamp", "cpu_percent", "memory_bytes", "memory_used_bytes", "disk_bytes",
                         "net_bytes", "net_rate", "restarts", "disk_read_rate", "disk_write_rate"), row))

    units = metric_app_units(domain_id, state)
    if shown is None:
        shown = unit_show(units, METRIC_PROPS)
    cpu_prev = _load_cpu_prev()
    memory = {"memory_bytes": 0, "memory_used_bytes": 0}
    restarts = 0
    total_net_bytes = 0
    cpu_percent = 0.0
    net_rate = 0.0
    disk_rates = [0.0, 0.0]
    for unit in units:
        info = shown.get(unit, {})
        if not info:
            raise HelperError("Unable to read metrics for %s" % unit)
        prev_key = "metrics_" + unit
        active = info.get("ActiveState") == "active"
        if not active:
            cpu_prev.pop(prev_key, None)
            continue
        for key, value in unit_memory(info).items():
            if key in memory:
                memory[key] += value or 0
        counter = lambda key: memory_value(info.get(key)) or 0
        raw_cpu_nsec = counter("CPUUsageNSec")
        raw_net = counter("IPIngressBytes") + counter("IPEgressBytes")
        io = unit_disk_counters(info)
        total_net_bytes += raw_net
        restarts += counter("NRestarts")
        instance = "%s:%s" % (info.get("MainPID"), info.get("ActiveEnterTimestampMonotonic"))
        prev_entry = cpu_prev.get(prev_key)
        same_instance = isinstance(prev_entry, list) and len(prev_entry) >= 4 and prev_entry[3] == instance
        if same_instance:
            dt = now - prev_entry[0]
            if dt > 0:
                cpu_percent += max(0.0, (raw_cpu_nsec - prev_entry[1]) / (dt * 1e9) * 100.0)
                net_rate += max(0.0, (raw_net - prev_entry[2]) / dt)
        for i, value in enumerate(io):
            previous = prev_entry[4 + i] if same_instance and len(prev_entry) == 6 else None
            rate = metric_rate(value, previous, now - prev_entry[0] if same_instance else 0)
            disk_rates[i] = disk_rates[i] + rate if disk_rates[i] is not None and rate is not None else None
        cpu_prev[prev_key] = [now, raw_cpu_nsec, raw_net, instance] + io
    _save_cpu_prev(cpu_prev)
    cpu_percent = min(100.0 * (os.cpu_count() or 1), cpu_percent)
    # Stopping an application does not remove its files.
    disk_bytes = _fast_dir_size(state.get("app_dir", ""))

    try:
        db = _open_metrics_db()
        with db:
            db.execute("""
                INSERT OR REPLACE INTO app_metrics
                (domain_id, timestamp, cpu_percent, memory_bytes, memory_used_bytes, disk_bytes, net_bytes, net_rate, restarts,
                 disk_read_rate, disk_write_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (domain_id, now, round(cpu_percent, 2), memory.get("memory_bytes") or 0,
                  memory.get("memory_used_bytes") or 0, disk_bytes, total_net_bytes, round(net_rate, 2), restarts,
                  disk_rates[0], disk_rates[1]))
    finally:
        db.close()

    return {
        "timestamp": now,
        "cpu_percent": round(cpu_percent, 2),
        "memory_bytes": memory.get("memory_bytes") or 0,
        "memory_used_bytes": memory.get("memory_used_bytes") or 0,
        "disk_bytes": disk_bytes,
        "net_bytes": total_net_bytes,
        "net_rate": round(net_rate, 2),
        "restarts": restarts,
        "disk_read_rate": disk_rates[0],
        "disk_write_rate": disk_rates[1],
    }


def record_server_metric_sample():
    """Records server-wide CPU, memory, disk and network usage."""
    with FileLock("metrics"):
        return _record_server_metric_sample()


def _record_server_metric_sample():
    now = int(time.time())
    db = _open_metrics_db()
    try:
        row = db.execute("""SELECT timestamp, cpu_percent, memory_used_bytes, memory_total_bytes,
                            disk_used_bytes, disk_total_bytes, net_rx_rate, net_tx_rate, disk_read_rate, disk_write_rate
                            FROM server_metrics WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 1""",
                         (now - METRICS_MIN_INTERVAL,)).fetchone()
    finally:
        db.close()
    if row and row[0] <= now:
        return dict(zip(("timestamp", "cpu_percent", "memory_used_bytes", "memory_total_bytes",
                         "disk_used_bytes", "disk_total_bytes", "net_rx_rate", "net_tx_rate",
                         "disk_read_rate", "disk_write_rate"), row))
    cpu_percent = 0.0

    # CPU from /proc/stat
    cpu_prev = _load_cpu_prev()
    try:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        parts = [float(x) for x in line.split()[1:8]]
        total_time = sum(parts)
        idle_time = parts[3] + (parts[4] if len(parts) > 4 else 0)
        prev_entry = cpu_prev.get("server")
        if prev_entry and isinstance(prev_entry, list) and len(prev_entry) == 2:
            prev_total, prev_idle = prev_entry
            diff_total = total_time - prev_total
            diff_idle = idle_time - prev_idle
            if diff_total > 0:
                cpu_percent = max(0.0, min(100.0, (1.0 - diff_idle / diff_total) * 100.0))
        cpu_prev["server"] = [total_time, idle_time]
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

    # Network from /proc/net/dev
    net_rx_rate = 0.0
    net_tx_rate = 0.0
    try:
        rx_total = 0
        tx_total = 0
        with open("/proc/net/dev", "r") as f:
            for line in f:
                if ":" in line:
                    iface, stats = line.split(":", 1)
                    iface = iface.strip()
                    if iface != "lo":
                        parts = stats.split()
                        if len(parts) >= 9:
                            rx_total += int(parts[0])
                            tx_total += int(parts[8])
        prev_net = cpu_prev.get("server_net")
        if prev_net and isinstance(prev_net, list) and len(prev_net) == 3:
            p_time, p_rx, p_tx = prev_net
            dt = now - p_time
            if dt > 0:
                net_rx_rate = max(0.0, (rx_total - p_rx) / dt)
                net_tx_rate = max(0.0, (tx_total - p_tx) / dt)
        cpu_prev["server_net"] = [now, rx_total, tx_total]
    except Exception:
        pass

    io = server_disk_counters()
    previous_io = cpu_prev.get("server_io")
    disk_rates = [None, None]
    if io is not None:
        if isinstance(previous_io, dict) and set(previous_io.get("devices", {})) == set(io):
            elapsed = now - previous_io["timestamp"]
            for i in range(2):
                rates = [metric_rate(values[i], previous_io["devices"][device][i], elapsed)
                         for device, values in io.items()]
                if all(rate is not None for rate in rates):
                    disk_rates[i] = round(sum(rates), 2)
        cpu_prev["server_io"] = {"timestamp": now, "devices": io}
    else:
        cpu_prev.pop("server_io", None)

    _save_cpu_prev(cpu_prev)

    try:
        db = _open_metrics_db()
        with db:
            db.execute("""
                INSERT OR REPLACE INTO server_metrics
                (timestamp, cpu_percent, memory_used_bytes, memory_total_bytes, disk_used_bytes, disk_total_bytes, net_rx_rate, net_tx_rate,
                 disk_read_rate, disk_write_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (now, round(cpu_percent, 2), mem_used, mem_total, disk_used, disk_total, round(net_rx_rate, 2), round(net_tx_rate, 2),
                  disk_rates[0], disk_rates[1]))
    finally:
        db.close()

    return {
        "timestamp": now,
        "cpu_percent": round(cpu_percent, 2),
        "memory_used_bytes": mem_used,
        "memory_total_bytes": mem_total,
        "disk_used_bytes": disk_used,
        "disk_total_bytes": disk_total,
        "net_rx_rate": round(net_rx_rate, 2),
        "net_tx_rate": round(net_tx_rate, 2),
        "disk_read_rate": disk_rates[0],
        "disk_write_rate": disk_rates[1],
    }


def cmd_app_metrics(payload):
    payload = payload or {}
    domain_id = v_domain_id(payload.get("domain_id"))
    time_range = payload.get("range", "1h")
    if time_range not in ("1h", "24h", "7d"):
        time_range = "1h"

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
    db = _open_metrics_db()
    try:
        cursor = db.cursor()
        query = """
            SELECT
                (timestamp / ?) * ? AS t,
                ROUND(AVG(cpu_percent), 2) AS cpu,
                CAST(AVG(memory_bytes) AS INTEGER) AS mem,
                CAST(AVG(memory_used_bytes) AS INTEGER) AS mem_used,
                CAST(MAX(disk_bytes) AS INTEGER) AS disk,
                ROUND(AVG(net_rate), 2) AS net_rate,
                MAX(net_bytes) AS net_bytes,
                MAX(restarts) AS restarts,
                ROUND(AVG(disk_read_rate), 2) AS disk_read_rate,
                ROUND(AVG(disk_write_rate), 2) AS disk_write_rate,
                MAX(cpu_percent) AS cpu_peak,
                MAX(memory_used_bytes) AS memory_used_peak,
                MAX(memory_bytes) AS memory_peak,
                MAX(net_rate) AS net_rate_peak,
                MAX(disk_read_rate) AS disk_read_rate_peak,
                MAX(disk_write_rate) AS disk_write_rate_peak
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
                "net_rate": row[5] or 0.0,
                "net_bytes": row[6] or 0,
                "restarts": row[7] or 0,
                "disk_read_rate": row[8],
                "disk_write_rate": row[9],
                "cpu_peak": row[10],
                "memory_used_peak": row[11],
                "memory_peak": row[12],
                "net_rate_peak": row[13],
                "disk_read_rate_peak": row[14],
                "disk_write_rate_peak": row[15],
            })
    finally:
        db.close()

    return {"ok": True, "range": time_range, "step": step, "metrics": results, "latest": latest,
            "start_time": since - since % step, "end_time": now}


def cmd_server_metrics(payload):
    payload = payload or {}
    time_range = payload.get("range", "1h")
    if time_range not in ("1h", "24h", "7d"):
        time_range = "1h"

    collected = collect_metric_samples()
    latest = collected["latest"]
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
    db = _open_metrics_db()
    try:
        cursor = db.cursor()
        query = """
            SELECT
                (timestamp / ?) * ? AS t,
                ROUND(AVG(cpu_percent), 2) AS cpu,
                CAST(AVG(memory_used_bytes) AS INTEGER) AS mem_used,
                CAST(MAX(memory_total_bytes) AS INTEGER) AS mem_total,
                CAST(AVG(disk_used_bytes) AS INTEGER) AS disk_used,
                CAST(MAX(disk_total_bytes) AS INTEGER) AS disk_total,
                ROUND(AVG(net_rx_rate), 2) AS net_rx_rate,
                ROUND(AVG(net_tx_rate), 2) AS net_tx_rate,
                ROUND(AVG(disk_read_rate), 2) AS disk_read_rate,
                ROUND(AVG(disk_write_rate), 2) AS disk_write_rate
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
                "net_rx_rate": row[6] or 0.0,
                "net_tx_rate": row[7] or 0.0,
                "disk_read_rate": row[8],
                "disk_write_rate": row[9],
            })
    finally:
        db.close()

    return {"ok": True, "range": time_range, "step": step, "metrics": results, "latest": latest,
            "project_summary": collected["project_summary"], "collection_errors": collected["errors"],
            "start_time": since - since % step, "end_time": now}


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
