# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Toolchains
# ---------------------------------------------------------------------------

def installed_go():
    result = []
    try:
        names = os.listdir(GO_ROOT_DIR)
    except OSError:
        return result
    for name in names:
        if RE_GO_VERSION.match(name) and os.path.isfile(os.path.join(GO_ROOT_DIR, name, "bin", "go")):
            result.append(name)
    return sorted(result, key=version_key, reverse=True)


def installed_rust():
    result = []
    triple = host_arch()[1]
    base = os.path.join(RUSTUP_HOME, "toolchains")
    try:
        names = os.listdir(base)
    except OSError:
        return result
    for name in names:
        if not name.endswith("-" + triple):
            continue
        toolchain = name[: -len(triple) - 1]
        rustc = os.path.join(base, name, "bin", "rustc")
        if RE_RUST_TOOLCHAIN.match(toolchain) and os.path.isfile(rustc):
            version = ""
            try:
                version = run([rustc, "--version"], timeout=20).stdout.strip()
            except HelperError:
                pass
            result.append({"name": toolchain, "version": version})
    return sorted(result, key=lambda item: item["name"])


def toolchain_installed(runtime, toolchain):
    rt = RUNTIMES.get(runtime)
    if not toolchain or rt is None or rt.toolchain == "none":
        return True
    return rt.is_installed(toolchain)


def toolchains_in_use():
    used = dict((key, {}) for key in RUNTIME_KEYS)
    for state in iter_app_states():
        runtime = state.get("runtime")
        if runtime in used and state.get("toolchain"):
            used[runtime].setdefault(state["toolchain"], []).append(state.get("domain"))
    return used


def rust_env():
    return root_env({
        "RUSTUP_HOME": RUSTUP_HOME,
        "CARGO_HOME": RUSTUP_CARGO_HOME,
        "RUSTUP_INIT_SKIP_PATH_CHECK": "yes",
        "PATH": RUSTUP_CARGO_HOME + "/bin:" + ROOT_PATH,
    })


def rustup_bin():
    return os.path.join(RUSTUP_CARGO_HOME, "bin", "rustup")


def job_install_go(version, log):
    if not RE_GO_VERSION.match(version or ""):
        raise HelperError("Invalid Go version")
    target = go_dir(version)
    if os.path.isfile(os.path.join(target, "bin", "go")):
        log.line("Go %s is already installed." % version)
        return
    release = next((r for r in go_releases(force=True) if r["version"] == version), None)
    if not release:
        raise HelperError("Go %s is not available for this architecture" % version)
    ensure_dir(GO_ROOT_DIR)
    work = tempfile.mkdtemp(prefix=".install-", dir=GO_ROOT_DIR)
    try:
        archive = download("https://dl.google.com/go/" + release["filename"],
                           os.path.join(work, release["filename"]), release["sha256"], log)
        log.line("Extracting archive")
        extract_to = os.path.join(work, "x")
        os.mkdir(extract_to, 0o755)
        safe_extract(archive, extract_to)
        if not os.path.isfile(os.path.join(extract_to, "go", "bin", "go")):
            raise HelperError("Unexpected archive layout")
        if os.path.exists(target):
            shutil.rmtree(target)
        os.rename(os.path.join(extract_to, "go"), target)
        chmod_public(target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    proc = run([os.path.join(target, "bin", "go"), "version"], env=root_env({"GOTOOLCHAIN": "local", "GOCACHE": "/tmp/runway-go-cache"}), timeout=60)
    log.line(proc.stdout.strip() or proc.stderr.strip())
    log.line("Go %s installed to %s" % (version, target))


def ensure_rustup(log):
    if os.path.isfile(rustup_bin()):
        return
    triple = host_arch()[1]
    url = "https://static.rust-lang.org/rustup/dist/%s/rustup-init" % triple
    sha = http_get(url + ".sha256").decode("utf-8").split()[0]
    ensure_dir(RUST_ROOT_DIR)
    work = tempfile.mkdtemp(prefix=".install-", dir=RUST_ROOT_DIR)
    try:
        init = download(url, os.path.join(work, "rustup-init"), sha, log)
        os.chmod(init, 0o700)
        log.line("Installing rustup to %s" % RUST_ROOT_DIR)
        code = stream_process([init, "-y", "--no-modify-path", "--default-toolchain", "none", "--profile", "minimal"],
                              log, 900, rust_env())
        if code != 0:
            raise HelperError("rustup-init failed with exit code %d" % code)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    run([rustup_bin(), "set", "auto-self-update", "disable"], env=rust_env(), timeout=60)
    run([rustup_bin(), "set", "profile", "minimal"], env=rust_env(), timeout=60)


def job_install_rust(toolchain, log):
    if not RE_RUST_TOOLCHAIN.match(toolchain or ""):
        raise HelperError("Invalid Rust toolchain")
    ensure_rustup(log)
    log.line("Installing Rust toolchain '%s'" % toolchain)
    code = stream_process([rustup_bin(), "toolchain", "install", toolchain, "--profile", "minimal", "--no-self-update"],
                          log, 3600, rust_env())
    if code != 0:
        raise HelperError("rustup toolchain install failed with exit code %d" % code)
    chmod_public(RUST_ROOT_DIR)
    proc = run([os.path.join(rust_toolchain_dir(toolchain), "bin", "rustc"), "--version"], timeout=60)
    log.line(proc.stdout.strip())


def job_update_rust(toolchain, log):
    if toolchain not in ("stable", "beta") and not toolchain.startswith("nightly"):
        raise HelperError("Only channel toolchains (stable, beta, nightly) can be updated")
    job_install_rust(toolchain, log)
    code = stream_process([rustup_bin(), "update", toolchain, "--no-self-update"], log, 3600, rust_env())
    if code != 0:
        raise HelperError("rustup update failed with exit code %d" % code)
    chmod_public(RUST_ROOT_DIR)


def job_build_deps(log):
    if shutil.which("apt-get", path=ROOT_PATH):
        env = root_env({"DEBIAN_FRONTEND": "noninteractive"})
        code = stream_process(["apt-get", "update"], log, 900, env)
        if code != 0:
            raise HelperError("apt-get update failed")
        code = stream_process(["apt-get", "install", "-y", "--no-install-recommends",
                               "build-essential", "pkg-config", "libssl-dev", "cmake", "git", "unzip",
                               "zlib1g-dev", "libgmp-dev", "libyaml-dev", "libffi-dev"], log, 1800, env)
    elif shutil.which("dnf", path=ROOT_PATH):
        # strict=0: packages missing from the enabled repositories (e.g. CRB) are skipped.
        code = stream_process(["dnf", "install", "-y", "--setopt=strict=0", "gcc", "gcc-c++", "make",
                               "pkgconf-pkg-config", "openssl-devel", "cmake", "git", "unzip", "zlib-devel",
                               "gmp-devel", "libyaml-devel", "libffi-devel"], log, 1800, root_env())
    else:
        raise HelperError("No supported package manager (apt-get or dnf) found")
    if code != 0:
        raise HelperError("Package installation failed with exit code %d" % code)


def build_deps_status():
    return {name: bool(shutil.which(name, path=ROOT_PATH)) for name in ("cc", "pkg-config", "cmake", "git")}
