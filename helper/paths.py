# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def app_state_path(domain_id):
    return os.path.join(APPS_DIR, "%d.json" % domain_id)


def app_triggers_path(domain_id):
    return os.path.join(APPS_DIR, "%d.triggers.json" % domain_id)


def env_file_path(domain_id, slot=""):
    return os.path.join(ENV_DIR, ("%d-%s.env" % (domain_id, slot)) if slot else ("%d.env" % domain_id))


def app_unit(domain_id, slot=""):
    """Unit of the 1.0 instance (slot "") or of a zero-downtime slot ("a", "b")."""
    return UNIT_SLOT % (domain_id, slot) if slot else UNIT_APP % domain_id


def all_app_units(domain_id):
    return [app_unit(domain_id, slot) for slot in ("",) + SLOTS]


def include_paths(domain_id):
    """Root-owned web server include files of a switchable tcp application (nginx, Apache)."""
    return (os.path.join(WEB_DIR, "%d.nginx.conf" % domain_id), os.path.join(WEB_DIR, "%d.apache.conf" % domain_id))


def job_paths(job):
    return (
        os.path.join(JOBS_DIR, job + ".status.json"),
        os.path.join(JOBS_DIR, job + ".log"),
        os.path.join(JOBS_DIR, job + ".request.json"),
    )


def go_dir(version):
    return os.path.join(GO_ROOT_DIR, version)


def host_arch():
    machine = os.uname().machine
    if machine in ("x86_64", "amd64"):
        return "amd64", "x86_64-unknown-linux-gnu"
    if machine in ("aarch64", "arm64"):
        return "arm64", "aarch64-unknown-linux-gnu"
    raise HelperError("Unsupported CPU architecture: %s" % machine)


def rust_toolchain_dir(toolchain):
    return os.path.join(RUSTUP_HOME, "toolchains", "%s-%s" % (toolchain, host_arch()[1]))
