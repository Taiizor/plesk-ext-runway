# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Running code as the hosting customer
# ---------------------------------------------------------------------------

def drop_privileges(pw):
    os.setgroups([])
    os.initgroups(pw.pw_name, pw.pw_gid)
    os.setgid(pw.pw_gid)
    os.setuid(pw.pw_uid)
    if os.getuid() != pw.pw_uid or os.geteuid() != pw.pw_uid:
        raise OSError("failed to drop privileges")


def _close_inherited_fds(keep):
    """Closes every descriptor except stdio (re-pointed to /dev/null) and `keep`, so a child
    that the customer stops (SIGSTOP) can never pin a root lock or the panel's stdout pipe."""
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    try:
        fds = [int(name) for name in os.listdir("/proc/self/fd")]
    except OSError:
        fds = list(range(3, 1024))
    for fd in fds:
        if fd > 2 and fd != keep:
            try:
                os.close(fd)
            except OSError:
                pass


def _limit_child(timeout, fsize):
    """Caps memory, file size and CPU time of a child that runs as the customer, so a crafted
    application root (millions of files, huge project files) cannot exhaust the server."""
    for limit, value in ((resource.RLIMIT_AS, CHILD_MEMORY), (resource.RLIMIT_FSIZE, fsize),
                         (resource.RLIMIT_CPU, int(timeout) + 5)):
        resource.setrlimit(limit, (value, value))


def call_as_user(pw, func, *args, **kwargs):
    """Runs func(*args) in a forked child that has become `pw`. Returns its JSON-able result.

    The child can be signalled by the customer once it runs with their uid, so the parent
    never waits for it without a deadline and kills it when the deadline passes. The child runs
    with resource limits (address space, file size, CPU time; keyword "fsize" raises the file
    size limit for downloads)."""
    timeout = kwargs.get("timeout", CHILD_TIMEOUT)
    fsize = kwargs.get("fsize", CHILD_FSIZE)
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        code = 0
        try:
            os.close(rfd)
            _close_inherited_fds(wfd)
            drop_privileges(pw)
            _limit_child(timeout, fsize)
            os.umask(0o027)
            os.environ.clear()
            os.environ.update({"HOME": pw.pw_dir, "PATH": USER_PATH, "LANG": "C.UTF-8"})
            os.chdir(pw.pw_dir if os.path.isdir(pw.pw_dir) else "/")
            result = {"ok": True, "result": func(*args)}
        except HelperError as exc:
            result = {"ok": False, "error": str(exc), "code": getattr(exc, "code", None)}
        except BaseException as exc:  # noqa: BLE001 - report anything to the parent
            result = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            code = 1
        try:
            data = json.dumps(result).encode("utf-8")
            view = memoryview(data)
            while view:
                written = os.write(wfd, view)
                view = view[written:]
        finally:
            os._exit(code)
    os.close(wfd)
    chunks = []
    size = 0
    failed = None
    deadline = time.time() + timeout
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                failed = "Timed out while running as %s" % pw.pw_name
                break
            ready, _, _ = select.select([rfd], [], [], min(remaining, 1.0))
            if not ready:
                continue
            chunk = os.read(rfd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > 8 * 1024 * 1024:
                failed = "Too much output while running as %s" % pw.pw_name
                break
    finally:
        os.close(rfd)
        if failed:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        os.waitpid(pid, 0)
    if failed:
        raise HelperError(failed)
    try:
        result = json.loads(b"".join(chunks).decode("utf-8"))
    except ValueError:
        raise HelperError("Internal error while running as %s" % pw.pw_name)
    if not result.get("ok"):
        code = result.get("code")
        raise HelperError(result.get("error") or "Unknown error", code=code if isinstance(code, str) else None)
    return result.get("result")


def _user_prepare_app_root(app_root):
    os.makedirs(app_root, mode=0o750, exist_ok=True)
    os.makedirs(os.path.join(app_root, "tmp"), mode=0o750, exist_ok=True)
    return True


def _read_small(path, limit=256 * 1024):
    # O_NONBLOCK + S_ISREG: a FIFO or device swapped in for go.mod must not block or be read.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise HelperError("%s is not a regular file" % os.path.basename(path))
        data = b""
        while len(data) < limit:
            chunk = os.read(fd, limit - len(data))
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8", "replace")
    finally:
        os.close(fd)


def _user_trigger_mtimes(app_dir):
    """Runs as the customer: root never resolves paths inside the customer's directories."""
    result = {}
    tmp = os.path.join(app_dir, "tmp")
    if os.path.islink(tmp):
        return {"deploy": None, "restart": None}
    for key, rel in (("deploy", TRIGGER_DEPLOY), ("restart", TRIGGER_RESTART)):
        try:
            result[key] = os.lstat(os.path.join(app_dir, rel)).st_mtime
        except OSError:
            result[key] = None
    return result


def _parse_cargo_toml(text):
    info = {"package": None, "bins": [], "bin_paths": {}, "workspace": False}
    try:
        import tomllib  # Python 3.11+
        data = tomllib.loads(text)
        pkg = data.get("package") or {}
        info["package"] = pkg.get("name")
        for item in data.get("bin", []):
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                info["bins"].append(item["name"])
                if isinstance(item.get("path"), str):
                    info["bin_paths"][item["name"]] = item["path"]
        info["workspace"] = "workspace" in data
        return info
    except Exception:  # noqa: BLE001 - fall back to a tolerant line parser
        pass
    section = None
    current = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            section = line.strip("[] ").strip()
            current = None
            if section == "workspace":
                info["workspace"] = True
            continue
        match = re.match(r'^(name|path)\s*=\s*"([^"]+)"', line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if section == "package" and key == "name" and not info["package"]:
            info["package"] = value
        elif section == "bin" and key == "name":
            current = value
            info["bins"].append(value)
            if "" in info["bin_paths"]:
                info["bin_paths"][value] = info["bin_paths"].pop("")
        elif section == "bin" and key == "path":
            info["bin_paths"][current if current else ""] = value
    info["bin_paths"].pop("", None)
    return info


def _scan_names(path, keep, count_cap=LIST_COUNT_CAP, skip=()):
    """As the user: at most `keep` entry names of a directory (directory order), the number of
    entries seen (stops counting at count_cap) and whether more exist. Never materialises the
    whole listing, so a directory with millions of entries costs neither memory nor much time.
    A missing or unreadable directory yields ([], 0, False)."""
    names = []
    count = 0
    more = False
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.name in skip:
                    continue
                if count >= count_cap:
                    more = True
                    break
                count += 1
                if len(names) < keep:
                    names.append(entry.name)
    except OSError:
        return [], 0, False
    return names, count, more


def v_document_roots(value, home):
    """Document roots of a webspace (app-inspect, app-page: relative to the home directory, like
    an application root) as [(relative, absolute)]; invalid entries are dropped, at most 50."""
    roots = []
    for item in value[:50] if isinstance(value, list) else []:
        try:
            roots.append(v_app_root(item, home))
        except HelperError:
            continue
    return roots


def v_document_root(value, home):
    """The document root a domain should get (docroot-check, docroot-access), relative to the home
    directory: the rules of an application root, at most 255 characters, and no segment may start
    with "-" (the panel passes the path to Plesk's command line). Returns (relative, absolute)."""
    rel, absolute = v_app_root(value, home)
    if len(rel) > 255 or any(part.startswith("-") for part in rel.split("/")):
        raise HelperError("Invalid document root")
    return rel, absolute


def v_state_document_root(value, home):
    """The document_root of an application state (app-apply, app-docroot): the domain's document
    root as the panel sent it last, relative to the home directory and validated like
    v_document_root. Anything else (missing, empty, invalid) is "" (unknown). Only the step that
    makes the files in it readable for the web server uses it (open_public_files); unit and
    environment files never depend on it."""
    if not isinstance(value, str) or not value.strip().strip("/"):
        return ""
    try:
        return v_document_root(value, home)[0]
    except HelperError:
        return ""


def _relative_to(path, root):
    return path[len(root.rstrip("/")) + 1:]


def _user_check_document_root(path, home):
    """Runs as the customer, before the panel changes a document root: the path (inside the home
    directory as text) must stay inside it once the customer's symbolic links are resolved
    (os.path.realpath; the home directory itself is not a document root), and an existing path
    must be a directory. A missing directory is fine: Plesk creates it, with its parents, as
    <user>:psaserv 0750 (docs/DESIGN.md section 7). Returns {exists, real}."""
    real_home = os.path.realpath(home)
    real = os.path.realpath(path)
    if not real.startswith(real_home.rstrip("/") + "/"):
        raise HelperError("The document root leads outside the home directory", code="docroot_outside")
    exists = os.path.lexists(path)
    if exists and not os.path.isdir(path):
        raise HelperError("The document root exists but is not a directory", code="docroot_not_dir")
    return {"exists": exists, "real": _relative_to(real, real_home)}


def _user_open_document_root(path, home, web_gid):
    """Runs as the customer, after Plesk changed the document root: every directory below the home
    directory down to the document root (its real path) that the web server group cannot pass (no
    group web server with g+x, no o+x) gets the search permission for others (o+x, never read), so
    that the web server reaches the document root through application roots that Runway created
    (0750, group psacln). Plesk's own directories (group psaserv) stay as they are; directories of
    other owners are reported, never changed; nothing is followed (O_NOFOLLOW on the real path).
    Returns {changed, blocked} (relative paths)."""
    real_home = os.path.realpath(home).rstrip("/")
    real = os.path.realpath(path)
    if not real.startswith(real_home + "/"):
        raise HelperError("The document root leads outside the home directory", code="docroot_outside")
    changed, blocked = [], []
    current = real_home
    for part in _relative_to(real, real_home).split("/"):
        current = current + "/" + part
        try:
            fd = os.open(current, _DIR_FLAGS)
        except OSError:
            blocked.append(_relative_to(current, real_home))
            break
        try:
            st = os.fstat(fd)
            if (st.st_gid == web_gid and st.st_mode & stat.S_IXGRP) or st.st_mode & stat.S_IXOTH:
                continue
            if st.st_uid != os.getuid():
                blocked.append(_relative_to(current, real_home))
                continue
            os.fchmod(fd, stat.S_IMODE(st.st_mode) | stat.S_IXOTH)
            changed.append(_relative_to(current, real_home))
        finally:
            os.close(fd)
    return {"changed": changed, "blocked": blocked}


def _open_dir_below(root, rel, on_way=None):
    """A descriptor of the directory root/rel, reached from root one directory at a time with
    O_NOFOLLOW, so no component of rel can be a symbolic link. on_way(fd), when given, is called
    with the descriptor of every directory strictly between root and root/rel. Raises OSError."""
    fd = os.open(root, _DIR_FLAGS)
    parts = rel.split("/")
    for index, part in enumerate(parts):
        try:
            child = os.open(part, _DIR_FLAGS, dir_fd=fd)
        finally:
            os.close(fd)
        fd = child
        if on_way is not None and index < len(parts) - 1:
            try:
                on_way(fd)
            except BaseException:
                os.close(fd)
                raise
    return fd


def _public_file(dir_fd, name, listed, uid):
    """Adds the read permission for others to a regular file of the user through a descriptor of the
    file itself (O_NOFOLLOW: a symbolic link swapped in after the listing is never followed), only
    while it is still the listed file. A file its owner cannot read cannot be opened and stays as it
    is. Returns True when the mode changed."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY, dir_fd=dir_fd)
    except OSError:
        return False
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_mode & stat.S_IROTH \
                or (st.st_dev, st.st_ino) != (listed.st_dev, listed.st_ino):
            return False
        os.fchmod(fd, stat.S_IMODE(st.st_mode) | stat.S_IROTH)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _user_open_public_files(app_root, document_root, max_entries, seconds, web_gid=-1):
    """Runs as the customer (after a build/fetch, a document root change, and periodic checks):
    makes the files in the document root readable for the web server (nginx and Apache, group
    psaserv), which cannot read what builds and fetches create with
    umask 027 (files 0640, directories 0750, group psacln). Only when the document root's real path
    lies strictly inside the application root's real path (os.path.realpath): equal to it or a
    parent of it would expose the sources and settings files, and a document root elsewhere is none
    of Runway's business; None then, and for a missing document root.

    The walk never follows a symbolic link: the document root is reached from the application root
    one O_NOFOLLOW directory at a time, every directory is read through its own descriptor, and
    links inside are skipped (counted, never changed: chmod would follow them). Entries whose name
    starts with "." are skipped (directories with everything below them). Only the user's own
    entries change, and only by the read permission for others: directories that the owner can read
    and search get o+rx, regular files o+r (through a descriptor of the file itself, see
    _public_file); no write bit, no group, nothing removed. Bounded by max_entries entries, `seconds`
    and PUBLIC_FILES_DEPTH levels: the walk stops at a bound and reports truncated (the rest stays
    as it is, on every run: each run walks from the start).

    The directories between the application root and the document root (".output" of
    ".output/public": builds often remove and create them anew, 0750 psacln) get the search
    permission for others where the web server group (web_gid) cannot pass them, as docroot-access
    does: own directories only, o+x only (never the read bit, also for names that start with "."),
    through the descriptor of the descent. The application root itself and the directories above it
    stay as they are (docroot-access covers them when the document root changes).
    Returns {changed, skipped_links, truncated, passable} (passable: directories on the way that got
    o+x)."""
    try:
        real_app = os.path.realpath(app_root).rstrip("/")
        real_doc = os.path.realpath(document_root)
    except (OSError, ValueError):
        return None
    if not real_app or not real_doc.startswith(real_app + "/") or not os.path.lexists(real_doc):
        return None
    uid = os.getuid()
    result = {"changed": 0, "skipped_links": 0, "truncated": False, "passable": 0}

    def pass_through(dir_fd):
        # A directory on the way: o+x when it is the user's and the web server group cannot pass it.
        try:
            st = os.fstat(dir_fd)
            if st.st_uid != uid or (st.st_gid == web_gid and st.st_mode & stat.S_IXGRP) or st.st_mode & stat.S_IXOTH:
                return
            os.fchmod(dir_fd, stat.S_IMODE(st.st_mode) | stat.S_IXOTH)
            result["passable"] += 1
        except OSError:
            pass

    try:
        top = _open_dir_below(real_app, _relative_to(real_doc, real_app), pass_through)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HelperError("The document root %s cannot be opened: %s" % (document_root, exc.strerror or exc))
    deadline = time.monotonic() + seconds
    stack = []

    def enter(dir_fd):
        # o+rx for a directory of the user that its owner can read and search, then list it.
        try:
            st = os.fstat(dir_fd)
            if st.st_uid == uid and st.st_mode & 0o500 == 0o500 and st.st_mode & 0o005 != 0o005:
                os.fchmod(dir_fd, stat.S_IMODE(st.st_mode) | 0o005)
                result["changed"] += 1
        except OSError:
            pass
        try:
            stack.append((dir_fd, os.scandir(dir_fd)))
        except OSError:
            os.close(dir_fd)

    seen = 0
    try:
        enter(top)
        while stack:
            dir_fd, entries = stack[-1]
            try:
                entry = next(entries, None)
            except OSError:
                entry = None
            if entry is None:
                stack.pop()
                entries.close()
                os.close(dir_fd)
                continue
            seen += 1
            if seen > max_entries or time.monotonic() > deadline:
                result["truncated"] = True
                break
            if entry.name.startswith("."):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode):
                result["skipped_links"] += 1
            elif stat.S_ISDIR(st.st_mode):
                if len(stack) >= PUBLIC_FILES_DEPTH:
                    result["truncated"] = True
                    continue
                try:
                    child = os.open(entry.name, _DIR_FLAGS, dir_fd=dir_fd)
                except OSError:
                    continue
                enter(child)
            elif stat.S_ISREG(st.st_mode) and st.st_uid == uid and not st.st_mode & stat.S_IROTH:
                if _public_file(dir_fd, entry.name, st, uid):
                    result["changed"] += 1
    finally:
        for dir_fd, entries in stack:
            entries.close()
            os.close(dir_fd)
    return result


def _user_document_root(app_root, roots):
    """Runs as the customer: the document root (the relative path of an entry of `roots`) that
    the application root lies in once symbolic links are resolved, or None. The panel compares the
    configured paths as text; this also finds an application root that a link puts into a
    document root (apps/api -> ../httpdocs/api) and a document root that is a link to the
    application root (httpdocs -> releases/current): the web server follows links of the same
    owner, so it serves those files as well."""
    try:
        real = os.path.realpath(app_root)
        for rel, absolute in roots:
            root = os.path.realpath(absolute)
            if real == root or real.startswith(root.rstrip("/") + "/"):
                return rel
    except (OSError, ValueError):
        pass
    return None


def _user_public_dirs(app_root):
    """Runs as the customer: per runtime, the candidate document roots of Runtime.public_dirs that
    are real directories directly inside the application root (lstat: a symbolic link never counts),
    in the runtime's order. One lstat per distinct name, no recursion."""
    found = {}
    for name in set(name for rt in RUNTIMES.values() for name in rt.public_dirs):
        try:
            found[name] = stat.S_ISDIR(os.lstat(os.path.join(app_root, name)).st_mode)
        except (OSError, ValueError):
            found[name] = False
    return dict((key, [name for name in rt.public_dirs if found.get(name)]) for key, rt in RUNTIMES.items())


def _user_inspect_app_root(app_root, document_roots=()):
    """Runs as the customer: generic facts plus the detection result of every runtime adapter,
    the document root (of `document_roots`, see v_document_roots) the application root lies in
    with symbolic links resolved, and the candidate document roots inside it (public_dirs)."""
    info = {"exists": os.path.isdir(app_root), "entries": [],
            "triggers": {"deploy": False, "restart": False},
            "document_root": _user_document_root(app_root, document_roots) if document_roots else None,
            "public_dirs": dict((key, []) for key in RUNTIME_KEYS)}
    for key in RUNTIME_KEYS:
        info[key] = None
    if not info["exists"]:
        return info
    if not os.access(app_root, os.R_OK | os.X_OK):
        raise HelperError("The application root %s cannot be read by the system user" % app_root)
    info["public_dirs"] = _user_public_dirs(app_root)
    names, count, more = _scan_names(app_root, LIST_KEEP_ROOT)
    entries = sorted(name.encode("utf-8", "surrogateescape").decode("utf-8", "replace") for name in names)
    info["entry_count"] = count
    info["more"] = more
    info["entries"] = entries[:80]
    for key, rt in RUNTIMES.items():
        try:
            info[key] = rt.inspect(app_root)
        except Exception as exc:  # noqa: BLE001 - one broken project file must not hide the rest
            info.setdefault("inspect_errors", {})[key] = str(exc)[:300]
    info["triggers"]["deploy"] = os.path.exists(os.path.join(app_root, TRIGGER_DEPLOY))
    info["triggers"]["restart"] = os.path.exists(os.path.join(app_root, TRIGGER_RESTART))
    return info
