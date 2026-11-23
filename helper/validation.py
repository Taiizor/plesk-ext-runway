# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def v_int(value, lo, hi, name):
    if isinstance(value, bool):
        raise HelperError("Invalid %s" % name)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HelperError("Invalid %s" % name)
    if number < lo or number > hi:
        raise HelperError("%s must be between %d and %d" % (name, lo, hi))
    return number


def v_domain_id(value):
    return v_int(value, 1, 2 ** 31 - 1, "domain_id")


def v_domain_name(value):
    if not isinstance(value, str) or not RE_DOMAIN.match(value) or value.startswith(("-", ".")):
        raise HelperError("Invalid domain name")
    return value


def v_sysuser(value):
    if not isinstance(value, str) or not RE_SYSUSER.match(value):
        raise HelperError("Invalid system user")
    try:
        pw = pwd.getpwnam(value)
    except KeyError:
        raise HelperError("System user '%s' does not exist" % value)
    if pw.pw_uid < 1000 or pw.pw_uid == 65534:
        raise HelperError("Refusing to run applications as privileged user '%s'" % value)
    if not pw.pw_dir or not pw.pw_dir.startswith("/") or pw.pw_dir == "/":
        raise HelperError("System user '%s' has no usable home directory" % value)
    return pw


def v_app_root(value, home):
    """Validates an application root given RELATIVE to the system user's home directory.

    The home directory always comes from the passwd database, never from the caller,
    so the resulting absolute path can only point inside the subscription.
    Returns (relative, absolute)."""
    if not isinstance(value, str):
        raise HelperError("Invalid application root")
    value = value.strip().strip("/")
    if not value or len(value) > 512 or not RE_REL_PATH.match(value):
        raise HelperError("Application root must be a path inside the subscription home "
                          "(allowed characters: letters, digits, . _ - @ + /)")
    if any(part in (".", "..") for part in value.split("/")):
        raise HelperError("Application root must not contain '.' or '..' segments")
    home = os.path.normpath(home)
    absolute = home + "/" + value
    if os.path.normpath(absolute) != absolute or not RE_SAFE_PATH.match(absolute):
        raise HelperError("Invalid application root")
    return value, absolute


def v_toolchain(runtime, value):
    value = value.strip() if isinstance(value, str) else ("" if value is None else str(value))
    rt = RUNTIMES.get(runtime)
    if rt is None or rt.toolchain == "none" or value == "":
        return ""
    if rt.version_re and re.match(rt.version_re, value):
        return value
    raise HelperError("Invalid %s toolchain version '%s'" % (runtime, value[:64]))


def v_url_prefix(value, name):
    value = value.strip() if isinstance(value, str) else ""
    if len(value) > 200 or not RE_URL_PREFIX.match(value) or any(part in (".", "..") for part in value.split("/")):
        raise HelperError("Invalid %s '%s' (expected a path like /api)" % (name, value[:64]))
    return value


def v_static_paths(value):
    if value in (None, "", []):
        return []
    if not isinstance(value, list) or len(value) > MAX_STATIC_PATHS:
        raise HelperError("Invalid static paths (at most %d)" % MAX_STATIC_PATHS)
    result = []
    for item in value:
        path = v_url_prefix(item, "static path")
        if path not in result:
            result.append(path)
    return result


def v_health_path(value):
    value = value.strip() if isinstance(value, str) else ""
    if value and not RE_HEALTH_PATH.match(value):
        raise HelperError("Invalid health check path")
    return value


def v_health_match(value, health_path):
    """The expected response content of the health check (docs/DESIGN.md section 7): "" (off), a
    JSON object (text that starts with "{") or any other text, at most HEALTH_MATCH_MAX characters
    without control characters. Forced off without a health path (workers have none)."""
    if not health_path or value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise HelperError("Invalid expected response content")
    value = value.strip(HEALTH_MATCH_TRIM)
    if len(value) > HEALTH_MATCH_MAX:
        raise HelperError("The expected response content is longer than %d characters" % HEALTH_MATCH_MAX)
    if RE_CTRL_UNICODE.search(value):
        raise HelperError("The expected response content contains line breaks or control characters")
    if value.startswith("{") and health_json_object(value) is None:
        raise HelperError("The expected response content starts with { but is not a valid JSON object")
    return value


def v_command(value, name, allow_empty, allow_newlines):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise HelperError("Invalid %s" % name)
    value = value.replace("\r\n", "\n").strip()
    if not value and not allow_empty:
        raise HelperError("The %s must not be empty" % name)
    if len(value) > 4000:
        raise HelperError("The %s is too long" % name)
    pattern = RE_CTRL_BUT_NL if allow_newlines else RE_CTRL_ANY
    if pattern.search(value):
        raise HelperError("The %s contains control characters%s" % (name, "" if allow_newlines else " or line breaks"))
    return value


def v_env(value):
    if value in (None, "", []):
        return {}
    if not isinstance(value, dict) or len(value) > 200:
        raise HelperError("Invalid environment variables")
    result = {}
    for key, val in value.items():
        if not isinstance(key, str) or not RE_ENV_KEY.match(key):
            raise HelperError("Invalid environment variable name '%s'" % key)
        if key in RESERVED_ENV or key.startswith("RUNWAY_ISOLATION_"):
            raise HelperError("Environment variable %s is managed by Runway" % key)
        if key in LOADER_ENV:
            raise HelperError("Environment variable %s cannot be set here; put it in the start command" % key)
        if not isinstance(val, str):
            val = str(val)
        if len(val) > 8192 or RE_CTRL_ANY.search(val.replace("\t", " ")):
            raise HelperError("Value of %s contains line breaks or control characters" % key)
        result[key] = val
    return result


def validate_app(payload):
    if not isinstance(payload, dict):
        raise HelperError("Invalid payload")
    pw = v_sysuser(payload.get("sysuser"))
    enabled = bool(payload.get("enabled"))
    runtime = payload.get("runtime")
    if runtime not in RUNTIME_KEYS:
        raise HelperError("Invalid runtime")
    limits = payload.get("limits") or {}
    build_limits = payload.get("build_limits") or {}
    listen = payload.get("listen") or "tcp"
    if listen not in LISTEN_MODES:
        raise HelperError("Invalid listen mode")
    mode = payload.get("mode") or ("worker" if listen == "none" else "web")
    if mode not in APP_MODES:
        raise HelperError("Invalid application mode")
    if mode == "worker" or listen == "none":
        # A worker has no listener and nothing is proxied to it (a port is still reserved).
        mode, listen = "worker", "none"
    port_range = payload.get("port_range") or [20000, 29999]
    if not isinstance(port_range, (list, tuple)) or len(port_range) != 2:
        raise HelperError("Invalid port range")
    pmin = v_int(port_range[0], 1024, 65535, "port range start")
    pmax = v_int(port_range[1], pmin, 65535, "port range end")
    app_root, app_dir = v_app_root(payload.get("app_root"), pw.pw_dir)
    health_path = v_health_path(payload.get("health_path")) if listen != "none" else ""
    state = {
        "version": 1,
        "domain_id": v_domain_id(payload.get("domain_id")),
        "domain": v_domain_name(payload.get("domain")),
        "sysuser": pw.pw_name,
        "app_root": app_root,
        "app_dir": app_dir,
        "runtime": runtime,
        "toolchain": v_toolchain(runtime, payload.get("toolchain")),
        "build_cmd": v_command(payload.get("build_cmd"), "build command", True, True),
        "start_cmd": v_command(payload.get("start_cmd"), "start command", not enabled, False),
        "env": v_env(payload.get("env")),
        "port": v_int(payload.get("port", 0) or 0, 0, 65535, "port"),
        "port_range": [pmin, pmax],
        "enabled": enabled,
        # The domain (or its subscription) is suspended/disabled in Plesk: keep the
        # configuration but do not run the service.
        "suspended": bool(payload.get("suspended")),
        # Stopped by the user (Stop) or by Runway (tampered socket path): the service stays
        # stopped (also across reboots, deployments and reconciles) until an explicit start.
        "stopped": bool(payload.get("stopped")),
        "tampered": bool(payload.get("tampered")),
        "tampered_at": str(payload.get("tampered_at") or "")[:40],
        "tampered_detail": str(payload.get("tampered_detail") or "")[:300],
        "auto_deploy": bool(payload.get("auto_deploy", True)),
        "build_timeout": v_int(payload.get("build_timeout", 3600), 60, 6 * 3600, "build timeout"),
        "limits": {
            "memory_mb": v_int(limits.get("memory_mb", 0) or 0, 0, 1024 * 1024, "memory limit"),
            "cpu_percent": v_int(limits.get("cpu_percent", 0) or 0, 0, 100 * 256, "CPU limit"),
            "tasks": v_int(limits.get("tasks", 0) or 0, 0, 1000000, "tasks limit"),
        },
        "build_limits": {
            "memory_mb": v_int(build_limits.get("memory_mb", 0) or 0, 0, 1024 * 1024, "build memory limit"),
            "cpu_percent": v_int(build_limits.get("cpu_percent", 0) or 0, 0, 100 * 256, "build CPU limit"),
            "tasks": v_int(build_limits.get("tasks", 0) or 0, 0, 1000000, "build tasks limit"),
        },
        "listen": listen,
        "mode": mode,
        "mount_path": v_url_prefix(payload.get("mount_path"), "mount path") if mode == "path" else "",
        "static_paths": v_static_paths(payload.get("static_paths")),
        # The domain's document root as the panel sent it last (docs/DESIGN.md section 6): the deploy
        # job makes the files in it readable for the web server when it lies inside the application
        # root (open_public_files). Workers serve nothing. Never rendered into a file.
        "document_root": v_state_document_root(payload.get("document_root"), pw.pw_dir) if listen != "none" else "",
        "health_path": health_path,
        # Expected response content (opt-in): the health check also reads the body; nothing to
        # check without a health path (workers have none).
        "health_match": v_health_match(payload.get("health_match"), health_path),
        # Health watch (opt-in): restarts the application when its health path keeps failing;
        # nothing to watch without a health path (workers have none).
        "health_watch": bool(payload.get("health_watch")) and bool(health_path),
        "health_interval": v_int(_or_default(payload.get("health_interval"), HEALTH_WATCH_INTERVAL_DEFAULT), 10, 3600,
                                 "health check interval"),
        "health_failures": v_int(_or_default(payload.get("health_failures"), HEALTH_WATCH_FAILURES_DEFAULT), 1, 20,
                                 "failed health checks"),
        # Zero-downtime deployments (docs/DESIGN.md section 12): workers have nothing to switch.
        "zero_downtime": bool(payload.get("zero_downtime")) and listen != "none",
        "ready_timeout": v_int(_or_default(payload.get("ready_timeout"), ZD_READY_DEFAULT), 5, 900, "readiness timeout"),
        "drain_seconds": v_int(_or_default(payload.get("drain_seconds"), ZD_DRAIN_DEFAULT), 0, 300, "drain period"),
    }
    if state["port"] and state["port"] < 1024:
        raise HelperError("Port must be 1024 or higher")
    if state["tampered"]:
        state["stopped"] = True
    isolation = isolation_options(state["domain_id"])
    if isolation["enabled"] and isolation["network"] == "offline" and listen == "tcp":
        raise HelperError("Offline isolation requires Unix socket mode or a worker")
    state.update(helper_fields({}))
    return state, pw


def _or_default(value, default):
    return default if value is None or value == "" else value


# State fields that only the helper writes (never taken from a payload): the live slot, the slot
# ports, the time of the last switch, a pending plain restart and the intent record of a switch.
HELPER_FIELDS = ("slot", "port_a", "port_b", "switched_at", "restart_plain", "switch")


def helper_fields(stored):
    """The helper-owned fields of a stored state, validated (defaults for a 1.0 state)."""
    stored = stored if isinstance(stored, dict) else {}

    def port(key):
        value = stored.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and 1024 <= value <= 65535 else 0

    intent = stored.get("switch")
    if not (isinstance(intent, dict) and intent.get("from") in ("",) + SLOTS and intent.get("to") in ("",) + SLOTS
            and intent.get("from") != intent.get("to")):
        intent = None
    else:
        intent = {"from": intent["from"], "to": intent["to"], "phase": str(intent.get("phase") or "")[:20],
                  "started_epoch": float(intent.get("started_epoch") or 0) if isinstance(intent.get("started_epoch"), (int, float)) else 0.0}
    return {
        "slot": stored.get("slot") if stored.get("slot") in SLOTS else "",
        "port_a": port("port_a"),
        "port_b": port("port_b"),
        "switched_at": str(stored.get("switched_at") or "")[:40],
        "restart_plain": bool(stored.get("restart_plain")),
        "switch": intent,
    }


def stored_port(stored):
    """The port of a stored state, or 0 (no state, or not a valid port). app-apply keeps it over
    the panel's copy: the running service uses it, and a switch back to the 1.0 unit may have
    given it a new one that the panel has not stored yet (docs/DESIGN.md section 12.8)."""
    value = stored.get("port") if isinstance(stored, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and 1024 <= value <= 65535 else 0


def load_app_state(domain_id):
    state = read_json(app_state_path(domain_id))
    if not isinstance(state, dict):
        raise HelperError("Application #%d is not configured" % domain_id)
    # Re-validate: the state file is root-owned, but be strict anyway.
    validated, pw = validate_app(state)
    validated["port"] = state.get("port", 0)
    validated.update(helper_fields(state))
    return validated, pw
