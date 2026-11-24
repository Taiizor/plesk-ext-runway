# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Application isolation (all runtimes, builds and deployment slots)
# ---------------------------------------------------------------------------

ISOLATION_CONFIG_DIR = CONF_DIR + "/isolation"
ISOLATION_BWRAP = "/usr/bin/bwrap"
ISOLATION_MANAGED_BWRAP = BIN_DIR + "/bwrap"
ISOLATION_SYSTEM_PATHS = (
    "/usr/bin", "/usr/sbin", "/usr/lib", "/usr/lib64", "/usr/libexec", "/usr/share",
    "/usr/local/bin", "/usr/local/sbin", "/usr/local/lib", "/usr/local/share", "/bin", "/sbin", "/lib", "/lib64",
    "/etc/alternatives", "/etc/ssl/certs", "/etc/pki/tls/certs", "/etc/pki/ca-trust",
    "/etc/ld.so.cache", "/etc/hosts", "/etc/resolv.conf", "/etc/localtime", "/etc/timezone",
    "/etc/services", "/etc/protocols", "/etc/gai.conf", "/etc/os-release", "/etc/mime.types",
)
ISOLATION_BUILD_PATHS = ("/usr/include", "/usr/local/include")
ISOLATION_RUNTIME_PATHS = {
    "go": (BASE_DIR + "/go",), "rust": (BASE_DIR + "/rust",), "bun": (BASE_DIR + "/bun",),
    "java": (BASE_DIR + "/java",), "dotnet": (BASE_DIR + "/dotnet",),
    "python": (BASE_DIR + "/python", BASE_DIR + "/uv"),
    "ruby": ("/opt/plesk/ruby", BASE_DIR + "/ruby", "/etc/gemrc"),
    "php": (BASE_DIR + "/frankenphp", BASE_DIR + "/composer", "/opt/plesk/php", "/etc/php.ini", "/etc/php.d"),
    "binary": (),
}


def isolation_defaults():
    return {"enabled": False, "network": "shared", "writable_paths": ["tmp", "logs", "storage", "uploads"], "socket_paths": []}


def isolation_config_path(domain_id):
    return "%s/%d.json" % (ISOLATION_CONFIG_DIR, v_domain_id(domain_id))


def isolation_validate(value):
    if not isinstance(value, dict) or set(value) - {"enabled", "network", "writable_paths", "socket_paths"}:
        raise HelperError("Invalid isolation settings")
    result = isolation_defaults()
    result.update(value)
    if not isinstance(result["enabled"], bool) or result["network"] not in ("shared", "offline"):
        raise HelperError("Invalid isolation settings")
    result["writable_paths"] = ops_paths(result["writable_paths"], "writable_paths")
    for path in result["writable_paths"]:
        if path.split("/")[0] in (".git", ".runway"):
            raise HelperError("Isolation writable paths cannot include Git or Runway control files")
    sockets = result["socket_paths"]
    if not isinstance(sockets, list) or len(sockets) > 8:
        raise HelperError("Isolation allows at most eight explicit Unix socket paths")
    for path in sockets:
        if not isinstance(path, str) or len(path) > 255 or not RE_SAFE_PATH.fullmatch(path) \
                or not path.startswith(("/run/", "/var/run/")) or any(part in ("", ".", "..") for part in path[1:].split("/")):
            raise HelperError("An isolated Unix socket must have an absolute path below /run")
    result["socket_paths"] = list(dict.fromkeys(sockets))
    return result


def isolation_options(domain_id):
    stored = read_json(isolation_config_path(domain_id))
    # A malformed existing policy must never silently turn protection off.
    if stored is None and not os.path.lexists(isolation_config_path(domain_id)):
        return isolation_defaults()
    return isolation_validate(stored)


def _isolation_check_bwrap(path):
    st = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o6022 or not st.st_mode & 0o111:
        raise HelperError("The isolation executable must be root-owned, non-setuid and not writable by other users")
    version = run([path, "--version"], timeout=10)
    match = re.fullmatch(r"bubblewrap\s+(\d+\.\d+(?:\.\d+)?)", version.stdout.strip())
    if version.returncode or not match or version_key(match.group(1)) < [0, 10]:
        raise HelperError("Application isolation requires bubblewrap 0.10 or newer")
    result = run([path, "--help"], timeout=10)
    if result.returncode or any(flag not in result.stdout for flag in ("--ro-bind-fd", "--bind-fd", "--seccomp")):
        raise HelperError("The installed bubblewrap lacks the required isolation features")
    return match.group(1)


def _isolation_bwrap_details():
    failures = []
    # Prefer maintained distribution packages; never replace a package-owned executable.
    for path in (ISOLATION_BWRAP, ISOLATION_MANAGED_BWRAP):
        try:
            return {"path": path, "version": _isolation_check_bwrap(path)}
        except OSError:
            pass
        except HelperError as exc:
            failures.append(str(exc))
    reason = failures[0] if failures else "Application isolation requires bubblewrap 0.10 or newer"
    raise HelperError(reason + ". Install isolation dependencies from Toolchains.")


def isolation_backend():
    backend = _isolation_bwrap_details()
    _isolation_seccomp_library()
    return backend["path"]


def _isolation_seccomp_library():
    import ctypes
    try:
        library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
        for name in ("seccomp_init", "seccomp_release", "seccomp_syscall_resolve_name", "seccomp_rule_add_array", "seccomp_export_bpf"):
            getattr(library, name)
        return library
    except (OSError, AttributeError):
        raise HelperError("Application isolation requires the system libseccomp2 library")


def _isolation_seccomp_fd():
    """Deny further namespace entry/creation without needing writable /proc/sys. Compile for
    the native supported ABI through libseccomp; clone3 returns ENOSYS for libc's clone fallback."""
    import ctypes
    import errno
    import platform
    if platform.machine() not in ("x86_64", "aarch64"):
        raise HelperError("Application isolation supports x86_64 and aarch64 Linux")
    library = _isolation_seccomp_library()

    class Comparison(ctypes.Structure):
        _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_uint), ("mask", ctypes.c_uint64), ("value", ctypes.c_uint64)]

    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Comparison)]
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    context = library.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW; other ABIs fail closed by default.
    if not context:
        raise HelperError("Cannot initialize the isolation syscall filter")
    fd = None
    try:
        for name, error, comparison in (("unshare", errno.EPERM, None), ("setns", errno.EPERM, None),
                                        ("clone3", errno.ENOSYS, None),
                                        ("clone", errno.EPERM, Comparison(0, 7, 0x10000000, 0x10000000))):
            number = library.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number < 0 or library.seccomp_rule_add_array(context, 0x50000 | error, number,
                                                           1 if comparison is not None else 0,
                                                           ctypes.byref(comparison) if comparison is not None else None) < 0:
                raise HelperError("Cannot compile the isolation syscall filter")
        fd = os.memfd_create("runway-isolation-syscalls", 0)
        if library.seccomp_export_bpf(context, fd) < 0:
            raise HelperError("Cannot export the isolation syscall filter")
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise
    finally:
        library.seccomp_release(context)


def isolation_home(state, pw):
    return "%s/.runway/isolation/%d/home" % (pw.pw_dir.rstrip("/"), state["domain_id"])


def isolation_environment_home(state, pw):
    return isolation_home(state, pw) if isolation_options(state["domain_id"])["enabled"] else pw.pw_dir


def isolation_limits(state, build=False):
    limits = state.get("build_limits" if build else "limits") or {}
    if not isolation_options(state["domain_id"])["enabled"]:
        return limits
    return {"memory_mb": limits.get("memory_mb") or 1024, "cpu_percent": limits.get("cpu_percent") or 100,
            "tasks": limits.get("tasks") or 1024}


def _isolation_relative(path, home):
    if not isinstance(path, str) or not path.startswith(home.rstrip("/") + "/"):
        raise HelperError("An isolation mount must stay inside the subscription home")
    relative = path[len(home.rstrip("/")) + 1:]
    if not RE_REL_PATH.fullmatch(relative) or any(part in ("", ".", "..") for part in relative.split("/")):
        raise HelperError("Invalid isolation mount path")
    return relative


def _isolation_open(home, relative, create=False):
    """Pin customer directories without following any component, including a swapped parent."""
    fd = os.open(home, _DIR_FLAGS)
    try:
        for part in relative.split("/"):
            if part in ("", ".", "..") or "/" in part:
                raise HelperError("Invalid isolation directory")
            if create:
                try:
                    os.mkdir(part, 0o750, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        if os.fstat(fd).st_uid != os.getuid():
            raise HelperError("An isolation directory must belong to the application user")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _user_isolation_prepare(app_dir, home, domain_id, writable_paths, shared_paths):
    relative = _isolation_relative(app_dir, home)
    app_fd = _isolation_open(home, relative)
    os.close(app_fd)
    private = ".runway/isolation/%d/home" % domain_id
    os.close(_isolation_open(home, private, create=True))
    for path in writable_paths:
        # Release shared paths are mounted separately; never descend through their symlinks.
        if any(path == item or path.startswith(item + "/") for item in shared_paths):
            continue
        os.close(_isolation_open(home, relative + "/" + path, create=True))


def isolation_prepare(state, pw, options=None):
    options = isolation_options(state["domain_id"]) if options is None else options
    if not options["enabled"]:
        return
    isolation_backend()
    if options["network"] == "offline" and state.get("listen") == "tcp":
        raise HelperError("Offline isolation requires Unix socket mode or a worker")
    effective = ops_execution_state(state)
    shared = ops_options(state["domain_id"])["shared_paths"] if effective["app_dir"] != pw.pw_dir.rstrip("/") + "/" + state["app_root"] else []
    call_as_user(pw, _user_isolation_prepare, effective["app_dir"], pw.pw_dir, state["domain_id"],
                 options["writable_paths"], shared)


def isolation_plan(state, pw, command, build=False, options=None):
    options = isolation_options(state["domain_id"]) if options is None else options
    return {"domain_id": state["domain_id"], "app_dir": state["app_dir"], "source_dir": pw.pw_dir.rstrip("/") + "/" + state["app_root"],
            "home": pw.pw_dir, "sysuser": state["sysuser"], "runtime": state["runtime"], "build": bool(build), "command": command,
            "socket_dir": socket_dir(state["domain_id"]) if state.get("listen") == "unix" and not build else "",
            "options": options, "shared_paths": ops_options(state["domain_id"])["shared_paths"]}


def _isolation_socket_fd(path):
    canonical = "/run/" + path[len("/var/run/"):] if path.startswith("/var/run/") else path
    parts = canonical[1:].split("/")
    parent = os.open("/", _DIR_FLAGS)
    try:
        for part in parts[:-1]:
            child = os.open(part, _DIR_FLAGS, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(parts[-1], os.O_PATH | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    if not stat.S_ISSOCK(os.fstat(fd).st_mode):
        os.close(fd)
        raise HelperError("An isolated service path must be a Unix socket, never a file or symlink")
    return fd


def _user_isolation_probe(plan):
    args, fds = isolation_bwrap_args(plan, os.getuid(), os.getgid())
    try:
        result = subprocess.run(args, pass_fds=fds, capture_output=True, text=True, timeout=15,
                                env={"PATH": USER_PATH, "HOME": plan["home"], "LANG": "C.UTF-8"})
        if result.returncode:
            raise HelperError("Cannot create the isolation environment: %s" % result.stderr.strip()[:1000])
    finally:
        for fd in fds:
            os.close(fd)


def isolation_probe(state, pw, options):
    plan = isolation_plan(ops_execution_state(state), pw, ["/bin/true"], options=options)
    call_as_user(pw, _user_isolation_probe, plan, timeout=25)


def isolation_command(state, pw, command, build=False):
    if not isolation_options(state["domain_id"])["enabled"]:
        return command
    # Commands may contain secrets. Unit files and argv are public; receive the command through
    # the private service environment or the build child's environment instead.
    plan = isolation_plan(state, pw, None, build)
    encoded = base64.b64encode(json.dumps(plan, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return [HELPER_COPY, "_isolate", encoded]


def isolation_outer_environment(environment, command):
    """Bootstrap with trusted variables only: loader/OpenSSL/Python settings take effect inside
    the sandbox, never while starting its Python wrapper or bubblewrap. Split private payloads
    below Linux's per-environment-string limit; no secret is sent through argv or unit text."""
    raw = json.dumps({"environment": environment, "command": command}, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    if len(raw) > 512 * 1024:
        raise HelperError("The isolated environment and command exceed 512 KiB")
    encoded = base64.b64encode(raw).decode("ascii")
    chunks = [encoded[index:index + 48000] for index in range(0, len(encoded), 48000)]
    result = {"PATH": USER_PATH, "HOME": environment["HOME"], "LANG": "C.UTF-8", "RUNWAY_ISOLATION_PARTS": str(len(chunks))}
    result.update({"RUNWAY_ISOLATION_DATA_%d" % index: chunk for index, chunk in enumerate(chunks)})
    return result


def isolation_bwrap_args(plan, uid, gid):
    """Run only after dropping privileges. Mount descriptors are consumed and closed by bwrap."""
    if plan["runtime"] not in ISOLATION_RUNTIME_PATHS or not isinstance(plan["build"], bool):
        raise HelperError("Invalid isolation execution plan")
    options = isolation_validate(plan["options"])
    if not options["enabled"]:
        raise HelperError("An isolation execution plan cannot disable protection")
    home, app_dir = plan["home"], plan["app_dir"]
    relative = _isolation_relative(app_dir, home)
    private_rel = ".runway/isolation/%d/home" % v_domain_id(plan["domain_id"])
    if relative == private_rel or relative.startswith(private_rel + "/") or private_rel.startswith(relative + "/"):
        raise HelperError("The application directory overlaps its private isolation home")
    args = [isolation_backend(), "--unshare-user", "--uid", str(uid), "--gid", str(gid),
            "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try", "--new-session",
            "--die-with-parent", "--cap-drop", "ALL"]
    args += ["--hostname", "runway-%d" % plan["domain_id"]]
    if options["network"] == "offline":
        args.append("--unshare-net")
    system_paths = ISOLATION_SYSTEM_PATHS + (ISOLATION_BUILD_PATHS if plan["build"] else ())
    for path in system_paths + ISOLATION_RUNTIME_PATHS[plan["runtime"]] + (BIN_DIR,):
        if os.path.exists(path):
            args += ["--ro-bind", path, path]
    if plan["runtime"] == "php":
        for version in _listdir("/etc/php"):
            if re.fullmatch(r"\d+\.\d+", version):
                for suffix in ("cli", "mods-available"):
                    path = "/etc/php/%s/%s" % (version, suffix)
                    if os.path.isdir(path):
                        args += ["--ro-bind", path, path]
    # Synthetic account databases avoid exposing the server's other identities and NSS sockets.
    fds = []

    def data_file(value, destination):
        fd = os.memfd_create("runway-isolation", 0)
        os.write(fd, value.encode("utf-8"))
        os.lseek(fd, 0, os.SEEK_SET)
        fds.append(fd)
        args.extend(["--ro-bind-data", str(fd), destination])

    def mount(fd, destination, writable):
        fds.append(fd)
        args.extend(["--bind-fd" if writable else "--ro-bind-fd", str(fd), destination])

    try:
        filter_fd = _isolation_seccomp_fd()
        fds.append(filter_fd)
        args += ["--seccomp", str(filter_fd)]
        username = plan["sysuser"]
        if not isinstance(username, str) or not RE_SYSUSER.fullmatch(username):
            raise HelperError("Invalid isolated user identity")
        data_file("%s:x:%d:%d::%s:/bin/bash\n" % (username, uid, gid, home + "/" + private_rel), "/etc/passwd")
        data_file("%s:x:%d:\n" % (grp.getgrgid(gid).gr_name, gid), "/etc/group")
        data_file("passwd: files\ngroup: files\nhosts: files dns\n", "/etc/nsswitch.conf")
        # Only this unit's cgroup is visible; runtimes must still discover their CPU/memory caps.
        for line in _read_text("/proc/self/cgroup", 32768).splitlines():
            fields = line.split(":", 2)
            if len(fields) != 3 or not fields[2].startswith("/") or "/../" in fields[2] + "/":
                continue
            controllers = fields[1]
            source = "/sys/fs/cgroup" + ("/" + controllers if controllers else "") + fields[2].rstrip("/")
            target = "/sys/fs/cgroup" + ("/" + controllers if controllers else "")
            if os.path.isdir(source):
                mount(os.open(source, _DIR_FLAGS), target, False)
        mount(_isolation_open(home, relative), app_dir, plan["build"])
        mount(_isolation_open(home, private_rel, create=True), home + "/" + private_rel, True)
        shared = ops_paths(plan["shared_paths"], "shared_paths")
        source_rel = _isolation_relative(plan["source_dir"], home)
        if app_dir != plan["source_dir"]:
            for path in shared:
                writable = plan["build"] or path in options["writable_paths"]
                mount(_isolation_open(home, source_rel + "/" + path), plan["source_dir"] + "/" + path, writable)
        if not plan["build"]:
            for path in options["writable_paths"]:
                shared_root = next((item for item in shared if path == item or path.startswith(item + "/")), None)
                if shared_root and app_dir != plan["source_dir"]:
                    if path != shared_root:
                        mount(_isolation_open(home, source_rel + "/" + path), plan["source_dir"] + "/" + path, True)
                    continue
                mount(_isolation_open(home, relative + "/" + path), app_dir + "/" + path, True)
        if plan["socket_dir"]:
            expected = socket_dir(plan["domain_id"])
            if plan["socket_dir"] != expected:
                raise HelperError("Invalid isolated socket directory")
            fd = os.open(expected, _DIR_FLAGS)
            if os.fstat(fd).st_uid != uid:
                os.close(fd)
                raise HelperError("The isolated socket directory has the wrong owner")
            mount(fd, expected, True)
        for path in options["socket_paths"]:
            mount(_isolation_socket_fd(path), path, False)
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/var/tmp"]
        environment = plan.get("environment")
        if environment is not None:
            if not isinstance(environment, dict) or len(environment) > 300:
                raise HelperError("Invalid isolated environment")
            args.append("--clearenv")
            for key, value in environment.items():
                if not isinstance(key, str) or not RE_ENV_KEY.fullmatch(key) or not isinstance(value, str) or "\x00" in value:
                    raise HelperError("Invalid isolated environment variable")
                args += ["--setenv", key, value]
        args += [
                 "--setenv", "HOME", home + "/" + private_rel, "--setenv", "TMPDIR", "/tmp",
                 "--chdir", app_dir, "--remount-ro", "/", "--"] + plan["command"]
        return args, fds
    except BaseException:
        for fd in fds:
            os.close(fd)
        raise


def internal_isolate(encoded):
    """Unprivileged entry point: it never reads root state or acquires helper privileges."""
    if os.getuid() == 0 or os.getuid() != os.geteuid() or len(encoded) > 65536:
        raise HelperError("Application isolation must run as the unprivileged application user")
    plan = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    count = v_int(os.environ.get("RUNWAY_ISOLATION_PARTS"), 1, 20, "isolation payload parts")
    encoded_environment = "".join(os.environ["RUNWAY_ISOLATION_DATA_%d" % index] for index in range(count))
    if len(encoded_environment) > 700000:
        raise HelperError("The isolated environment payload is too large")
    private = json.loads(base64.b64decode(encoded_environment, validate=True).decode("utf-8"))
    command = private["command"]
    if not isinstance(command, list) or not command or len(command) > 64 \
            or any(not isinstance(value, str) or "\x00" in value for value in command):
        raise HelperError("Invalid isolated command")
    plan["command"] = command
    plan["environment"] = private["environment"]
    account = pwd.getpwuid(os.getuid())
    if plan["home"] != account.pw_dir or plan["sysuser"] != account.pw_name:
        raise HelperError("The isolation home does not match the current user")
    isolation_backend()
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise HelperError("Cannot prevent privilege escalation inside the isolation environment")
    args, fds = isolation_bwrap_args(plan, os.getuid(), os.getgid())
    try:
        # bwrap's --args accepts options, not the child command. Keep both environment values
        # and the real command in that private descriptor; a fixed Python trampoline restores
        # the command only after entering the namespace, then removes its transport variable.
        options = args[1:len(args) - len(command) - 1]
        options += ["--setenv", "RUNWAY_ISOLATION_COMMAND", base64.b64encode(json.dumps(command).encode("utf-8")).decode("ascii")]
        trampoline = ("import base64,json,os; command=json.loads(base64.b64decode(os.environ.pop('RUNWAY_ISOLATION_COMMAND'))); "
                      "os.execvpe(command[0],command,os.environ)")
        argument_fd = os.memfd_create("runway-isolation-arguments", 0)
        fds.append(argument_fd)
        os.write(argument_fd, b"\x00".join(value.encode("utf-8") for value in options) + b"\x00")
        os.lseek(argument_fd, 0, os.SEEK_SET)
        for name in os.listdir("/proc/self/fd"):
            fd = int(name)
            if fd > 2 and fd not in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
        for fd in fds:
            os.set_inheritable(fd, True)
        os.execv(args[0], [args[0], "--args", str(argument_fd), "--", "/usr/bin/python3", "-I", "-c", trampoline])
    finally:
        for fd in fds:
            os.close(fd)


def cmd_isolation(payload):
    payload = payload or {}
    domain_id = v_domain_id(payload.get("domain_id"))
    state, pw = load_app_state(domain_id)
    action = payload.get("action", "status")
    if action == "save":
        options = isolation_validate(payload.get("options"))
        if options["enabled"]:
            isolation_backend()
            if options["network"] == "offline" and state["listen"] == "tcp":
                raise HelperError("Offline isolation requires Unix socket mode or a worker")
        lock = deploy_lock(domain_id, "Wait for the current deployment before changing isolation")
        try:
            state, pw = load_app_state(domain_id)
            if options["enabled"] and options["network"] == "offline" and state["listen"] == "tcp":
                raise HelperError("Offline isolation requires Unix socket mode or a worker")
            if state.get("switch"):
                zd_converge_locked(state, pw)
                state, pw = load_app_state(domain_id)
            if options == isolation_options(domain_id):
                return cmd_isolation({"domain_id": domain_id})
            isolation_prepare(state, pw, options)
            if options["enabled"]:
                if state.get("listen") == "unix":
                    ensure_socket_dir(domain_id, pw)
                isolation_probe(state, pw, options)
            # Stop every old slot before changing policy: no old unconfined process may remain.
            systemctl("stop", *existing_app_units(domain_id), check=True, timeout=120)
            try:
                ensure_dir(ISOLATION_CONFIG_DIR, 0o700)
                write_json(isolation_config_path(domain_id), options)
                write_units(state, pw)
                systemctl("daemon-reload", check=True)
                if state["enabled"] and not state["suspended"]:
                    # Dependencies and global tools may live in the private per-app home. Populate
                    # it through the isolated build; a stopped app is built but stays stopped.
                    start_deploy_job(domain_id, "build", state["stopped"], actor=payload.get("actor", "panel"))
            except Exception:
                update_state_flags(domain_id, stopped=True)
                systemctl("stop", *existing_app_units(domain_id), timeout=120)
                raise
        finally:
            lock.release()
    elif action != "status":
        raise HelperError("Invalid isolation operation")
    try:
        isolation_backend()
        available, reason = True, ""
    except HelperError as exc:
        available, reason = False, str(exc)
    return {"options": isolation_options(domain_id), "available": available, "reason": reason}
