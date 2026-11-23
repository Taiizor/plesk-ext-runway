# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# System dependencies: local checks and missing-package installation
# ---------------------------------------------------------------------------

BUILD_PACKAGES = {
    "apt-get": ("build-essential", "pkg-config", "libssl-dev", "cmake", "git", "unzip",
                "zlib1g-dev", "libgmp-dev", "libyaml-dev", "libffi-dev"),
    "dnf": ("gcc", "gcc-c++", "make", "pkgconf-pkg-config", "openssl-devel", "cmake", "git", "unzip",
            "zlib-devel", "gmp-devel", "libyaml-devel", "libffi-devel"),
}


def dependency_manager(required=True):
    for manager in ("apt-get", "dnf"):
        if shutil.which(manager, path=ROOT_PATH):
            return manager
    if required:
        raise HelperError("No supported package manager (apt-get or dnf) found")
    return None


def dependency_versions(manager):
    """Read the local package database; never refresh or contact a repository here."""
    command = (["dpkg-query", "-W", "-f=${binary:Package}\t${Status}\t${Version}\\n"] if manager == "apt-get"
               else ["rpm", "-qa", "--qf", "%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}\\n"])
    result = run(command, check=True, timeout=60)
    installed = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if manager == "apt-get":
            if len(parts) != 3 or not parts[1].endswith(" ok installed"):
                continue
            name, version = parts[0], parts[2]
        elif len(parts) == 2:
            name, version = parts
        else:
            continue
        if name and version:
            installed[name] = version
    return installed


def dependency_version(installed, package):
    # Foreign-architecture headers alone do not satisfy native builds.
    return installed.get(package) or installed.get(package + ":" + host_arch()[0])


def dependency_refresh(manager, log):
    if manager == "apt-get":
        if stream_process([manager, "update"], log, 900, root_env({"DEBIAN_FRONTEND": "noninteractive"})):
            raise HelperError("apt-get update failed")


def dependency_apt_guard(upgrade):
    # APT runs this protocol-2 hook under its package locks, before unpacking anything.
    # The earlier simulation gives a readable error; this also catches changes since that plan.
    return """#!/usr/bin/python3 -I
# Copyright 2026 Taiizor. Licensed under the MIT License.
import sys
allowed = %s
if sys.stdin.readline().strip() != 'VERSION 2':
    sys.exit('Unsupported APT dependency transaction protocol')
for line in sys.stdin:
    if not line.strip():
        break
for line in sys.stdin:
    fields = line.split()
    if len(fields) != 5:
        sys.exit('Invalid APT dependency transaction')
    name, old, direction, new, action = fields
    if action == '**REMOVE**' or (old != '-' and name not in allowed and action != '**CONFIGURE**'):
        sys.exit('Keeping installed package ' + name + '; update system packages separately, then retry')
""" % json.dumps(list(upgrade))


def dependency_install(manager, packages, log, upgrade=()):
    """Keep compatible installed packages, including transitive dependencies."""
    installed = dependency_versions(manager)
    wanted = []
    for package in packages:
        version = dependency_version(installed, package)
        if version and package not in upgrade:
            log.line("%s %s is already installed; keeping the installed version" % (package, version))
        else:
            wanted.append(package)
            log.line(("Updating incompatible %s %s" % (package, version)) if version
                     else "Installing missing package %s" % package)
    if not wanted:
        log.line("All requested packages are already installed; no package operation is needed")
        return
    env = root_env({"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C"})
    if manager == "apt-get":
        command = [manager, "install", "-y", "--no-install-recommends", "--no-remove"]
        if not upgrade:
            command.append("--no-upgrade")
        plan = run(command + ["--simulate"] + wanted, check=True, timeout=120, env=env)
        for line in plan.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            operation, name = parts[:2]
            if operation == "Remv" or (operation == "Inst" and dependency_version(installed, name)
                                        and name.split(":", 1)[0] not in upgrade):
                raise HelperError("Installing dependencies would change installed package %s. "
                                  "Update system packages separately, then retry." % name)
        # Use the toolchain directory: hosting servers commonly mount /tmp with noexec.
        ensure_dir(BIN_DIR, 0o755)
        with tempfile.TemporaryDirectory(prefix=".dependencies-", dir=BIN_DIR) as directory:
            guard = directory + "/check-transaction"
            with open(guard, "x", encoding="utf-8") as output:
                output.write(dependency_apt_guard(upgrade))
            os.chmod(guard, 0o700)
            command += ["-o", "DPkg::Pre-Install-Pkgs::=" + guard,
                        "-o", "DPkg::Tools::Options::%s::Version=2" % guard,
                        "-o", "DPkg::Tools::Options::%s::InfoFD=0" % guard]
            code = stream_process(command + wanted, log, 1800, env)
    else:
        command = [manager, "install", "-y", "--setopt=install_weak_deps=False", "--setopt=obsoletes=False"]
        # Exclusions filter available packages, so installed dependencies still satisfy requirements.
        # Do not use strict=0: missing development headers must fail, rather than report success.
        command += ["--exclude=" + name for name in sorted(installed) if name not in upgrade]
        code = stream_process(command + wanted, log, 1800, env)
    if code:
        raise HelperError("Dependency installation failed (exit %d). "
                          "Resolve repository/dependency conflicts separately, then retry." % code)
    after = dependency_versions(manager)
    missing = [name for name in packages if not dependency_version(after, name)]
    if missing:
        raise HelperError("Packages are still missing after installation: " + ", ".join(missing))
    for name in wanted:
        log.line("Installed %s %s" % (name, dependency_version(after, name)))

