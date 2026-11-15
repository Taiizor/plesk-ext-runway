# Copyright 2026 Taiizor. Licensed under the MIT License.

def ops_export(state, options):
    if not options["backup"]:
        raise HelperError("Recovery backup is disabled")
    config = dict(options)
    if not options["backup_secrets"]:
        config.update(notification_url="", notification_secret="", notifications=False)
    bundle = {"schema": 1, "created_at": now_iso(), "operations": config,
              "environment_included": options["backup_secrets"]}
    if options["backup_secrets"]:
        bundle["environment"] = state.get("env") or {}
    if len(json.dumps(bundle, ensure_ascii=False).encode("utf-8")) > 480 * 1024:
        raise HelperError("Recovery data exceeds its size limit; omit secrets or reduce environment values")
    return {"bundle": bundle}


def ops_check_import(bundle, restore_secrets=False):
    if not isinstance(bundle, dict) or bundle.get("schema") != 1:
        raise HelperError("Unsupported recovery bundle")
    config = bundle.get("operations")
    if not isinstance(config, dict):
        raise HelperError("Recovery settings are missing")
    config = dict(config)
    if not restore_secrets:
        config.update(notification_url="", notification_secret="", notifications=False)
    config = ops_validate(config)
    environment = v_env(bundle["environment"]) if restore_secrets and "environment" in bundle else None
    return config, environment


def ops_import(state, pw, bundle, restore_secrets=False):
    if not ops_options(state["domain_id"])["backup"]:
        raise HelperError("Recovery backup is disabled")
    config, environment = ops_check_import(bundle, restore_secrets)
    with FileLock("deploy-%d" % state["domain_id"]):
        if unit_is_active(UNIT_DEPLOY % state["domain_id"]) or any(unit_is_active(unit) for unit in existing_app_units(state["domain_id"])):
            raise HelperError("Stop the application and wait for deployments to finish before restoring settings")
        if environment is not None:
            with FileLock("ports"):
                current = read_json(app_state_path(state["domain_id"]))
                if not isinstance(current, dict):
                    raise HelperError("Application configuration disappeared during restore")
                current["env"] = environment
                write_json(app_state_path(state["domain_id"]), current)
        ensure_dir(OPS_CONFIG_DIR, 0o700)
        write_json(ops_config_path(state["domain_id"]), config)
    return {"restored": True, "environment_restored": environment is not None}
