# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Application isolation dependencies (administrator background job)
# ---------------------------------------------------------------------------

ISOLATION_SOURCE_VERSION = "0.13.1"
ISOLATION_SOURCE_SHA256 = "0e85c8702248b8dd64144f594147553650cdd0e4c951690345faace79c217c4d"
ISOLATION_SOURCE_URL = "https://github.com/containers/bubblewrap/releases/download/v%s/bubblewrap-%s.tar.xz" % (
    ISOLATION_SOURCE_VERSION, ISOLATION_SOURCE_VERSION)


def isolation_dependencies_status():
    result = {"available": False, "bubblewrap": False, "libseccomp": False, "version": "", "path": "", "reason": ""}
    errors = []
    try:
        result.update(_isolation_bwrap_details())
        result["bubblewrap"] = True
    except HelperError as exc:
        errors.append(str(exc))
    try:
        _isolation_seccomp_library()
        result["libseccomp"] = True
    except HelperError as exc:
        errors.append(str(exc))
    result["available"] = result["bubblewrap"] and result["libseccomp"]
    result["reason"] = " ".join(errors)
    return result


def _isolation_repository_supported(manager):
    """Do not install an obsolete package just because the executable has the right name."""
    if manager == "apt-get":
        result = run(["apt-cache", "policy", "bubblewrap"], timeout=60, env=root_env({"LC_ALL": "C"}))
        candidates = re.findall(r"^\s*Candidate:\s*(\S+)", result.stdout, re.MULTILINE)
    else:
        result = run(["dnf", "-q", "list", "--showduplicates", "bubblewrap"], timeout=120,
                     env=root_env({"LC_ALL": "C"}))
        candidates = re.findall(r"^\s*bubblewrap\.\S+\s+(\S+)", result.stdout, re.MULTILINE)
    if result.returncode:
        return False
    for candidate in candidates:
        match = re.match(r"^(?:\d+:)?(\d+)\.(\d+)", candidate)
        if match and tuple(map(int, match.groups())) >= (0, 10):
            return True
    return False


def _isolation_publish_binary(source):
    """Validate the private build before atomically publishing a root-owned executable."""
    ensure_dir(BIN_DIR, 0o755)
    fd, temporary = tempfile.mkstemp(prefix=".bwrap-", dir=BIN_DIR)
    try:
        with os.fdopen(fd, "wb") as target:
            with open(source, "rb") as built:
                content = built.read(16 * 1024 * 1024 + 1)
            if not content.startswith(b"\x7fELF") or len(content) > 16 * 1024 * 1024:
                raise HelperError("The bubblewrap build did not produce a bounded ELF executable")
            target.write(content)
            target.flush()
            os.fchmod(target.fileno(), 0o700)
            os.fsync(target.fileno())
        version = _isolation_check_bwrap(temporary)
        if version != ISOLATION_SOURCE_VERSION:
            raise HelperError("The bubblewrap build returned an unexpected version")
        os.chmod(temporary, 0o755)
        os.replace(temporary, ISOLATION_MANAGED_BWRAP)
    finally:
        remove_quietly(temporary)


def _isolation_build_bwrap(manager, log):
    packages = (["build-essential", "pkg-config", "meson", "ninja-build", "libcap-dev"] if manager == "apt-get"
                else ["gcc", "make", "pkgconf-pkg-config", "meson", "ninja-build", "libcap-devel"])
    dependency_install(manager, packages, log)
    ensure_dir(BASE_DIR)
    work = tempfile.mkdtemp(prefix=".isolation-install-", dir=BASE_DIR)
    try:
        archive = download(ISOLATION_SOURCE_URL, work + "/bubblewrap.tar.xz", ISOLATION_SOURCE_SHA256,
                           log, limit=4 * 1024 * 1024)
        extracted = work + "/source"
        os.mkdir(extracted, 0o700)
        safe_extract(archive, extracted)
        source = extracted + "/bubblewrap-" + ISOLATION_SOURCE_VERSION
        if not os.path.isfile(source + "/meson.build"):
            raise HelperError("Unexpected bubblewrap source archive layout")
        build = work + "/build"
        for name in ("home", "tmp"):
            os.mkdir(work + "/" + name, 0o700)
        env = root_env({"HOME": work + "/home", "TMPDIR": work + "/tmp"})
        log.line("Building the verified bubblewrap %s release" % ISOLATION_SOURCE_VERSION)
        command = ["meson", "setup", build, source, "--buildtype=release", "-Dman=disabled", "-Dtests=false",
                   "-Dbash_completion=disabled", "-Dzsh_completion=disabled", "-Dselinux=auto"]
        if stream_process(command, log, 180, env) or stream_process(["ninja", "-C", build, "-j", "2"], log, 600, env):
            raise HelperError("bubblewrap compilation failed; the previous executable was kept")
        _isolation_publish_binary(build + "/bwrap")
        log.line("Installed bubblewrap %s to %s" % (ISOLATION_SOURCE_VERSION, ISOLATION_MANAGED_BWRAP))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def job_isolation_deps(log):
    current = isolation_dependencies_status()
    if current["available"]:
        log.line("Compatible bubblewrap %s and libseccomp are already installed; keeping installed versions" % current["version"])
        return
    manager = dependency_manager()
    dependency_refresh(manager, log)
    if not current["libseccomp"]:
        dependency_install(manager, ["libseccomp2" if manager == "apt-get" else "libseccomp"], log)
    current = isolation_dependencies_status()
    if not current["bubblewrap"] and _isolation_repository_supported(manager):
        dependency_install(manager, ["bubblewrap"], log, upgrade=("bubblewrap",))
        current = isolation_dependencies_status()
    if not current["bubblewrap"]:
        log.line("The system package does not provide the required version; using Runway's managed executable")
        _isolation_build_bwrap(manager, log)
    final = isolation_dependencies_status()
    if not final["available"]:
        raise HelperError(final["reason"] or "Isolation dependencies are not available after installation")
    log.line("Isolation dependencies ready: bubblewrap %s, libseccomp" % final["version"])
    log.line("Application policies are unchanged. Kernel/container settings must permit unprivileged user namespaces.")
