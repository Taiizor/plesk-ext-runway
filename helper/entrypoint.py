# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS = {
    "info": cmd_info,
    "runtimes": cmd_runtimes,
    "toolchains": cmd_toolchains,
    "releases": cmd_releases,
    "toolchain-install": cmd_toolchain_install,
    "toolchain-update": cmd_toolchain_update,
    "toolchain-remove": cmd_toolchain_remove,
    "build-deps-install": cmd_build_deps_install,
    "job-status": cmd_job_status,
    "update-status": cmd_update_status,
    "update-check": cmd_update_check,
    "update-install": cmd_update_install,
    "app-apply": cmd_app_apply,
    "app-remove": cmd_app_remove,
    "app-action": cmd_app_action,
    "app-deploy": cmd_app_deploy,
    "app-config": cmd_app_config,
    "app-sample": cmd_app_sample,
    "app-page": cmd_app_page,
    "app-status": cmd_app_status,
    "app-logs": cmd_app_logs,
    "app-inspect": cmd_app_inspect,
    "docroot-check": cmd_docroot_check,
    "docroot-access": cmd_docroot_access,
    "app-docroot": cmd_app_docroot,
    "apps-list": cmd_apps_list,
    "reapply-all": cmd_reapply_all,
    "web-reconfigure": cmd_web_reconfigure,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
}


def emit(obj, code):
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n"
    # Lone surrogates (undecodable file names) would make the output invalid UTF-8.
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.flush()
    sys.exit(code)


def parse_payload(argv):
    """Reads the JSON payload from stdin (preferred: argv is visible to all users via ps)
    or, for manual debugging, from a base64-encoded second argument."""
    if len(argv) >= 3 and argv[2] != "":
        raw = argv[2]
        if len(raw) > MAX_PAYLOAD:
            raise HelperError("Payload too large")
        try:
            text = base64.b64decode(raw.encode("ascii"), validate=True).decode("utf-8")
        except (ValueError, UnicodeError):
            raise HelperError("Malformed payload")
    else:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        text = sys.stdin.read(MAX_PAYLOAD + 1)
        if len(text) > MAX_PAYLOAD:
            raise HelperError("Payload too large")
        if not text.strip():
            return {}
    try:
        payload = json.loads(text)
    except ValueError:
        raise HelperError("Malformed payload")
    if not isinstance(payload, dict):
        raise HelperError("Malformed payload")
    return payload


def main(argv):
    os.umask(0o022)
    os.environ.clear()
    os.environ.update(root_env())
    if os.geteuid() != 0:
        emit({"ok": False, "error": "runway-helper must run as root"}, 1)
    if len(argv) < 2:
        emit({"ok": False, "error": "usage: runway-helper <command> [base64-json]"}, 1)
    command = argv[1]

    # Internal entry points used by systemd units created by this helper.
    if command == "_deploy" and len(argv) == 3:
        internal_deploy(v_domain_id(argv[2]))
        return 0
    if command == "_job" and len(argv) == 3 and argv[2] == "admin":
        internal_admin_job()
        return 0
    if command == "_converge" and len(argv) == 2:
        internal_converge()
        return 0
    if command == "_health" and (len(argv) == 2 or (len(argv) == 3 and argv[2] == "now")):
        internal_health(len(argv) == 3)
        return 0

    handler = COMMANDS.get(command)
    if handler is None:
        emit({"ok": False, "error": "Unknown command: %s" % command}, 1)
    try:
        result = handler(parse_payload(argv))
        response = {"ok": True}
        if isinstance(result, dict):
            response.update(result)
        emit(response, 0)
    except HelperError as exc:
        error = {"ok": False, "error": str(exc)}
        if getattr(exc, "code", None):
            error["code"] = exc.code
        emit(error, 1)
    except Exception as exc:  # noqa: BLE001 - never leak a traceback to the panel as non-JSON
        emit({"ok": False, "error": "Internal error: %s: %s" % (type(exc).__name__, exc)}, 1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
