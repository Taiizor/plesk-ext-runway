# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- web server: which one carries the traffic, its worker generations, reloads ------------------

_PROC_TIME = []


def _proc_clock():
    """(boot time as epoch seconds, clock ticks per second). The boot time comes from
    /proc/uptime (10 ms resolution; btime of /proc/stat is whole seconds, too coarse to compare
    process start times with file modification times)."""
    if not _PROC_TIME:
        try:
            uptime = float((_read_text("/proc/uptime", 256) or "0").split()[0])
        except ValueError:
            uptime = 0.0
        _PROC_TIME.append((time.time() - uptime, float(os.sysconf("SC_CLK_TCK") or 100)))
    return _PROC_TIME[0]


def proc_stat(pid):
    """(ppid, start time as epoch seconds) of a process, or None."""
    data = _read_text("/proc/%d/stat" % pid, 4096)
    if not data or ")" not in data:
        return None
    fields = data.rsplit(")", 1)[1].split()
    try:
        btime, ticks = _proc_clock()
        return int(fields[1]), btime + int(fields[19]) / ticks
    except (IndexError, ValueError):
        return None


def proc_title(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            return fh.read(512).replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def web_traffic_server():
    """(unit, kind) of the web server that carries the domains' traffic: nginx when it runs,
    else Apache; (None, None) when neither runs."""
    for unit, kind in (("nginx.service", "nginx"), ("apache2.service", "apache"), ("httpd.service", "apache")):
        if run(["systemctl", "is-active", unit], timeout=30).stdout.strip() == "active":
            return unit, kind
    return None, None


def web_main_pid(unit):
    main = unit_show([unit], ["MainPID"]).get(unit, {}).get("MainPID", "0")
    try:
        return int(main)
    except ValueError:
        return 0


def web_workers(unit, kind):
    """Worker processes of the web server: [{pid, start, old}], old = an nginx worker that is
    shutting down (Apache children cannot be told apart: old is False)."""
    main = web_main_pid(unit)
    if main <= 1:
        return []
    workers = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        info = proc_stat(pid)
        if not info or info[0] != main:
            continue
        title = proc_title(pid)
        if kind == "nginx":
            if "worker process" not in title:
                continue
            old = "shutting down" in title
        else:
            old = False
        workers.append({"pid": pid, "start": info[1], "old": old})
    return workers


def web_confirmed_at(unit):
    """Time (epoch) before which every configuration file was read by a reload of `unit` that
    web_reload_confirm() confirmed, or 0.0."""
    data = read_json(WEB_RELOADS, {})
    value = data.get(unit) if isinstance(data, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def web_reload_stamp():
    """Touches the stamp file and returns its modification time (0.0 on failure): a file written
    before has an older or equal time, one written afterwards a newer or equal one, on the clock
    of file modification times (which lags time.time() by up to a clock tick)."""
    try:
        with open(WEB_RELOAD_STAMP, "a"):
            pass
        os.utime(WEB_RELOAD_STAMP, None)
        return os.stat(WEB_RELOAD_STAMP).st_mtime
    except OSError:
        return 0.0


def web_record_confirmed(unit, issued):
    """Remembers a confirmed reload of `unit` issued at `issued` (web_reload_stamp(); the caller
    holds the web-reload lock). Only an optimisation: a failure means one more reload later."""
    if not issued:
        return
    try:
        data = read_json(WEB_RELOADS, {})
        data = data if isinstance(data, dict) else {}
        data[unit] = issued
        write_json(WEB_RELOADS, data)
    except OSError:
        pass


def web_effective(unit, kind, since):
    """True when the configuration files changed before `since` (epoch) are active in the web
    server: a reload confirmed by web_reload_confirm() was issued after `since`, the server (its
    main process) started after it, or (nginx) every worker that is not shutting down started
    after it. Apache children of an old generation that still finish long requests (downloads,
    WebSockets) after a graceful restart look like the new ones, and children forked later for
    more load run the configuration of their generation: only the first two count for Apache.
    No web server: True."""
    if not unit:
        return True
    if web_confirmed_at(unit) > since:
        return True
    main = web_main_pid(unit)
    info = proc_stat(main) if main > 1 else None
    if info and info[1] > since:
        return True
    if kind != "nginx":
        return False
    current = [w for w in web_workers(unit, kind) if not w["old"]]
    return bool(current) and all(w["start"] > since for w in current)


def web_config_test(kind):
    """Output of the configuration test of the web server (for failure messages)."""
    if kind == "nginx":
        cmd = ["nginx", "-t"]
    elif shutil.which("apachectl", path=ROOT_PATH):
        cmd = ["apachectl", "-t"]
    else:
        cmd = ["httpd", "-t"]
    try:
        proc = run(cmd, timeout=60)
    except HelperError as exc:
        return str(exc)
    lines = [line for line in (proc.stderr + proc.stdout).splitlines() if line.strip()]
    return " ".join(lines)[-1500:]


def web_reload_confirm(unit, kind, wait=ZD_RELOAD_WAIT):
    """Reloads the web server and waits until its new worker generation is in place: a worker
    that did not exist before, no worker of before that is not shutting down (nginx), and the set
    of current workers unchanged for one second (a later generation, e.g. of Plesk's own reload,
    is adopted). Returns (ok, reason, detail, workers before the reload): reason "reload" when
    the reload was refused (detail: the configuration test; the running configuration stays),
    "unknown" when the systemctl client was killed by a signal (systemd may still carry the
    reload out), "timeout" otherwise. A confirmed reload is remembered (web_effective()).
    Raises HelperError when a systemctl call times out (the outcome is unknown then, too)."""
    before = set(w["pid"] for w in web_workers(unit, kind))
    issued = web_reload_stamp()
    proc = run(["systemctl", "reload", unit], timeout=120)
    if proc.returncode < 0:
        return False, "unknown", "systemctl reload %s ended by signal %d" % (unit, -proc.returncode), before
    if proc.returncode != 0:
        return False, "reload", web_config_test(kind) or (proc.stderr or proc.stdout).strip(), before
    deadline = time.time() + wait
    last = None
    since = 0.0
    while time.time() < deadline:
        workers = web_workers(unit, kind)
        current = frozenset(w["pid"] for w in workers if not w["old"])
        new = current - before
        stale = (current & before) if kind == "nginx" else set()
        if new and not stale:
            if current != last:
                last, since = current, time.time()
            elif time.time() - since >= 1.0:
                web_record_confirmed(unit, issued)
                return True, "", "", before
        else:
            last = None
        time.sleep(0.1)
    return False, "timeout", "no new worker generation of %s within %d s" % (unit, wait), before


def web_reload_nowait(unit):
    if unit:
        run(["systemctl", "reload", unit], timeout=120)


def vhosts_dir():
    for line in (_read_text("/etc/psa/psa.conf", 65536) or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "HTTPD_VHOSTS_D" and RE_SAFE_PATH.match(parts[1]):
            return parts[1].rstrip("/")
    return "/var/www/vhosts"


def generated_config(state, kind):
    """(text, mtime) of the domain's configuration that Plesk generated for nginx or Apache, or
    (None, 0) when it does not exist."""
    domain = state["domain"]
    try:
        domain = domain.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        pass
    name = "nginx.conf" if kind == "nginx" else "httpd.conf"
    directory = os.path.join(vhosts_dir(), "system", domain, "conf")
    # Plesk moves the default site's nginx server blocks into nginx_ip_default.conf,
    # leaving nginx.conf as a comment-only placeholder. Do not use an old default-site
    # file when the normal vhost already contains the active server blocks.
    candidates = (name, "nginx_ip_default.conf") if kind == "nginx" else (name,)
    fallback = (None, 0.0)
    for candidate in candidates:
        try:
            path = os.path.join(directory, candidate)
            st = os.stat(path)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(4 * 1024 * 1024)
            fallback = (text, st.st_mtime)
            if kind != "nginx" or re.search(r"^\s*server\s*\{", text, re.MULTILINE):
                return fallback
        except OSError:
            pass
    return fallback


def pointer_reference(state, kind):
    """The string the switchable snippet of the application's listen mode contains."""
    if state.get("listen") == "unix":
        return link_path(state["domain_id"])
    return "%s/%d.%s[.]conf" % (WEB_DIR, state["domain_id"], "nginx" if kind == "nginx" else "apache")


def config_references(state, needle):
    """True when the domain's generated nginx or Apache configuration contains `needle`."""
    for kind in ("nginx", "apache"):
        text = generated_config(state, kind)[0]
        if text and needle in text:
            return True
    return False
