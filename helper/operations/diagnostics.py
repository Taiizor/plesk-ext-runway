# Copyright 2026 Taiizor. Licensed under the MIT License.

def _user_source_checks(app_dir, home):
    real = os.path.realpath(app_dir)
    return {"exists": os.path.isdir(app_dir), "writable": os.access(app_dir, os.W_OK),
            "inside_home": real.startswith(os.path.realpath(home).rstrip("/") + "/")}


def ops_diagnostics(state, pw, options):
    source = call_as_user(pw, _user_source_checks, state["app_dir"], pw.pw_dir)
    checks = [{"key": "source", "ok": source["exists"] and source["inside_home"]},
              {"key": "writable", "ok": source["writable"]}]
    installed = not state["toolchain"] or toolchain_installed(state["runtime"], state["toolchain"])
    checks.append({"key": "toolchain", "ok": installed})
    free = shutil.disk_usage(pw.pw_dir).free
    checks.append({"key": "disk", "ok": free >= options["min_free_mb"] * 1024 * 1024,
                   "free_mb": free // (1024 * 1024), "required_mb": options["min_free_mb"]})
    if options["releases"]:
        checks.append({"key": "release_size", "ok": None, "limit_mb": options["release_max_mb"],
                       "shared_paths": options["shared_paths"]})
    status = app_status(state["domain_id"], state)
    service = status.get("service") or {}
    return {"schema": 1, "checked_at": now_iso(), "runtime": state["runtime"], "toolchain": state["toolchain"],
            "checks": checks, "ready": all(item["ok"] is not False for item in checks),
            "service": {key: service.get(key) for key in ("active_state", "sub_state", "result", "restarts", "memory_used_bytes")},
            "listener": status.get("listener"), "health": status.get("health"),
            "stopped": state["stopped"], "suspended": state["suspended"]}


def ops_preflight(state, pw, options):
    if not options["diagnostics"] or not options["preflight"]:
        return
    result = ops_diagnostics(state, pw, options)
    failed = [item["key"] for item in result["checks"] if item["ok"] is False]
    if failed:
        raise HelperError("Preflight checks failed: %s" % ", ".join(failed))
