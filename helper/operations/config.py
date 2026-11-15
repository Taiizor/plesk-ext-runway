# Copyright 2026 Taiizor. Licensed under the MIT License.

OPS_CONFIG_DIR = CONF_DIR + "/operations"
OPS_DATA_DIR = STATE_DIR + "/operations"
OPS_LOG_BYTES = 256 * 1024
OPS_EVENTS = ("deploy_succeeded", "deploy_failed", "health_restart", "health_paused", "app_start", "app_stop")


def ops_defaults():
    return {"history": False, "history_limit": 20, "diagnostics": False, "preflight": False,
            "min_free_mb": 256, "releases": False, "release_limit": 3, "release_max_mb": 2048,
            "shared_paths": [], "exclude_paths": [".git", ".runway"], "notifications": False,
            "notification_url": "", "notification_secret": "",
            "notification_events": ["deploy_failed", "health_restart", "health_paused"],
            "backup": False, "backup_secrets": False, "restore_start": False}


def ops_config_path(domain_id):
    return "%s/%d.json" % (OPS_CONFIG_DIR, v_domain_id(domain_id))


def ops_dir(domain_id):
    return "%s/%d" % (OPS_DATA_DIR, v_domain_id(domain_id))


def ops_options(domain_id):
    result = ops_defaults()
    stored = read_json(ops_config_path(domain_id), {})
    if isinstance(stored, dict):
        result.update({key: value for key, value in stored.items() if key in result})
    return result


def ops_bool(value, name):
    if not isinstance(value, bool):
        raise HelperError("%s must be a boolean" % name)
    return value


def ops_paths(value, name):
    if not isinstance(value, list) or len(value) > 20:
        raise HelperError("%s must contain at most 20 relative paths" % name)
    result = []
    for path in value:
        if not isinstance(path, str) or len(path) > 255 or not RE_REL_PATH.fullmatch(path) \
                or any(part in (".", "..") for part in path.split("/")):
            raise HelperError("Invalid relative path in %s" % name)
        if path not in result:
            result.append(path)
    if sum(map(len, result)) > 1024:
        raise HelperError("%s paths are too long" % name)
    return result


def ops_validate(values, previous=None):
    if not isinstance(values, dict):
        raise HelperError("Invalid operations settings")
    result = ops_defaults()
    if isinstance(previous, dict):
        result.update({key: value for key, value in previous.items() if key in result})
    unknown = set(values) - set(result) - {"clear_notification_secret"}
    if unknown:
        raise HelperError("Unknown operations setting: %s" % sorted(unknown)[0])
    for key in ("history", "diagnostics", "preflight", "releases", "notifications", "backup", "backup_secrets", "restore_start"):
        if key in values:
            result[key] = ops_bool(values[key], key)
    for key, lo, hi in (("history_limit", 1, 200), ("min_free_mb", 0, 1048576),
                        ("release_limit", 2, 20), ("release_max_mb", 1, 1048576)):
        if key in values:
            if not isinstance(values[key], (int, str)) or isinstance(values[key], bool) \
                    or not re.fullmatch(r"[0-9]+", str(values[key])):
                raise HelperError("Invalid %s" % key)
            result[key] = v_int(values[key], lo, hi, key)
    for key in ("shared_paths", "exclude_paths"):
        if key in values:
            result[key] = ops_paths(values[key], key)
    for path in result["shared_paths"]:
        if path.split("/")[0] in (".git", ".runway", "tmp"):
            raise HelperError("A shared path cannot contain Runway or Git control files")
        if any(path != other and (path.startswith(other + "/") or other.startswith(path + "/"))
               for other in result["shared_paths"]):
            raise HelperError("Shared paths cannot contain one another")
        if any(path == other or path.startswith(other + "/") or other.startswith(path + "/")
               for other in result["exclude_paths"]):
            raise HelperError("Shared and excluded paths cannot overlap")
    if "notification_url" in values:
        url = values["notification_url"]
        if not isinstance(url, str) or len(url) > 2048:
            raise HelperError("Invalid notification URL")
        result["notification_url"] = url.strip()
    if result["notification_url"]:
        check_fetch_url(result["notification_url"], False, resolve=False)
        try:
            address = ipaddress.ip_address(urllib.parse.urlsplit(result["notification_url"]).hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise HelperError("Notification endpoints must use public addresses")
    if result["notifications"] and not result["notification_url"]:
        raise HelperError("Notifications need an HTTPS endpoint")
    if "clear_notification_secret" in values:
        ops_bool(values["clear_notification_secret"], "clear_notification_secret")
    if "notification_secret" in values and not isinstance(values["notification_secret"], str):
        raise HelperError("Invalid notification secret")
    if values.get("clear_notification_secret") is True:
        result["notification_secret"] = ""
    if values.get("notification_secret"):
        secret = values["notification_secret"]
        if not isinstance(secret, str) or not 16 <= len(secret) <= 256 or RE_CTRL_ANY.search(secret):
            raise HelperError("The notification signing secret must contain 16 to 256 characters")
        result["notification_secret"] = secret
    if "notification_events" in values:
        events = values["notification_events"]
        if not isinstance(events, list) or any(event not in OPS_EVENTS for event in events):
            raise HelperError("Invalid notification event selection")
        result["notification_events"] = list(dict.fromkeys(events))
    return result


def ops_public_options(options):
    result = dict(options)
    result["notification_secret"] = ""
    result["has_notification_secret"] = bool(options.get("notification_secret"))
    return result


def ops_save(domain_id, values):
    options = ops_validate(values, ops_options(domain_id))
    ensure_dir(OPS_CONFIG_DIR, 0o700)
    write_json(ops_config_path(domain_id), options)
    return ops_public_options(options)


def ops_context(payload):
    domain_id = v_domain_id((payload or {}).get("domain_id"))
    state, pw = load_app_state(domain_id)
    return domain_id, state, pw, ops_options(domain_id)


def ops_summary(domain_id, options=None):
    options = options or ops_options(domain_id)
    return {"options": ops_public_options(options), "history": ops_history(domain_id) if options["history"] else [],
            "events": read_json(ops_dir(domain_id) + "/events.json", []) if options["history"] else [],
            "releases": ops_release_list(domain_id) if options["releases"] else [],
            "notification": read_json(ops_dir(domain_id) + "/notification.json", None)}


def cmd_operations(payload):
    if (payload or {}).get("action") == "validate-import":
        ops_check_import(payload.get("backup"), payload.get("restore_secrets") is True)
        return {"valid": True}
    domain_id, state, pw, options = ops_context(payload)
    action = payload.get("action", "status")
    if action == "save":
        with FileLock("deploy-%d" % domain_id):
            if unit_is_active(UNIT_DEPLOY % domain_id):
                raise HelperError("A deployment is already running for this application")
            ops_save(domain_id, payload.get("options"))
            write_file_atomic(os.path.join(UNIT_DIR, UNIT_DEPLOY % domain_id), render_deploy_service(state), 0o644)
            systemctl("daemon-reload", check=True)
        return ops_summary(domain_id)
    if action == "status":
        return ops_summary(domain_id, options)
    if action == "history":
        if not options["history"]:
            raise HelperError("Deployment history is disabled")
        record = ops_history_record(domain_id, payload.get("id"))
        record["log"] = tail_file(ops_dir(domain_id) + "/" + record["id"] + ".log", 1000, OPS_LOG_BYTES)
        return record
    if action == "diagnostics":
        if not options["diagnostics"]:
            raise HelperError("Diagnostics are disabled")
        return ops_diagnostics(state, pw, options)
    if action == "rollback":
        if not options["releases"]:
            raise HelperError("Release management is disabled")
        with FileLock("deploy-%d" % domain_id):
            if unit_is_active(UNIT_DEPLOY % domain_id):
                raise HelperError("A deployment is already running for this application")
            release = ops_valid_release(payload.get("id"))
            ops_require_release(domain_id, release)
            return start_deploy_job(domain_id, "rollback", state["stopped"], release=release,
                                    actor=ops_actor(payload.get("actor")))
    if action == "clear-releases":
        with FileLock("deploy-%d" % domain_id):
            if options["releases"] or not state["stopped"] or unit_is_active(UNIT_DEPLOY % domain_id) \
                    or any(unit_is_active(unit) for unit in existing_app_units(domain_id)):
                raise HelperError("Turn off release management and stop the application before clearing releases")
            ops_clear_releases(state, pw)
            write_units(state, pw)
            systemctl("daemon-reload", check=True)
        return ops_summary(domain_id)
    if action == "export":
        return ops_export(state, options)
    if action == "import":
        return ops_import(state, pw, payload.get("backup"), payload.get("restore_secrets") is True)
    raise HelperError("Unknown operations action")


def ops_remove_metadata(domain_id):
    """Only root-owned extension metadata is removed; user application/release files are preserved."""
    remove_quietly(ops_config_path(domain_id))
    path = ops_dir(domain_id)
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
