# Copyright 2026 Taiizor. Licensed under the MIT License.

def ops_release_state(domain_id):
    value = read_json(ops_dir(domain_id) + "/releases.json", {})
    return value if isinstance(value, dict) else {}


def ops_release_list(domain_id):
    data = ops_release_state(domain_id)
    slots = data.get("slots") or {}
    state = read_json(app_state_path(domain_id), {}) or {}
    active = slots.get(state.get("slot") or "")
    return [dict(entry, active=entry.get("id") == active)
            for entry in reversed(data.get("records") or []) if entry.get("state") == "ready"]


def ops_require_release(domain_id, release):
    entry = next((item for item in ops_release_list(domain_id) if item.get("id") == release), None)
    if entry is None:
        raise HelperError("The selected release is not available")
    return entry


def ops_release_path(pw, domain_id, release):
    return "%s/.runway/releases/%d/%s" % (pw.pw_dir.rstrip("/"), domain_id, ops_valid_release(release))


def ops_execution_state(state):
    """Select a root-recorded release only at execution boundaries, leaving the source state intact."""
    if state.get("_release_dir"):
        return dict(state, app_dir=state["_release_dir"])
    data = ops_release_state(state["domain_id"])
    if data.get("source") != state["app_dir"] or data.get("sysuser") != state["sysuser"]:
        return state
    release = (data.get("slots") or {}).get(state.get("_slot") or "")
    if not release:
        return state
    pw = v_sysuser(state["sysuser"])
    return dict(state, app_dir=ops_release_path(pw, state["domain_id"], release))


def _user_release_base(home, domain_id, create=False):
    """Retain a no-follow descriptor through every component of the per-user release directory."""
    fd = os.open(home, _DIR_FLAGS)
    try:
        for name in (".runway", "releases", str(domain_id)):
            if create:
                try:
                    os.mkdir(name, 0o750, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _ops_skip(path, skipped):
    return any(path == item or path.startswith(item + "/") for item in skipped)


def _ops_walk_frame(source_fd, dest_fd, prefix):
    try:
        return (os.scandir(source_fd), source_fd, dest_fd, prefix)
    except BaseException:
        os.close(source_fd)
        if dest_fd is not None:
            os.close(dest_fd)
        raise


def _ops_close_frame(frame):
    listing, source_fd, dest_fd, _prefix = frame
    listing.close()
    os.close(source_fd)
    if dest_fd is not None:
        os.close(dest_fd)


def _user_copy_release_file(source_fd, dest_fd, name, st, deadline):
    src = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_fd)
    try:
        actual = os.fstat(src)
        if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (st.st_dev, st.st_ino):
            raise HelperError("A release source changed during preparation")
        dst = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      0o750 if st.st_mode & 0o111 else 0o640, dir_fd=dest_fd)
        try:
            copied = 0
            while True:
                block = os.read(src, 1024 * 1024)
                if not block:
                    break
                copied += len(block)
                if copied > st.st_size or time.monotonic() > deadline:
                    raise HelperError("A release source grew or exceeded its copy deadline")
                view = memoryview(block)
                while view:
                    view = view[os.write(dst, view):]
            if copied != st.st_size:
                raise HelperError("A release source changed during preparation")
        finally:
            os.close(dst)
    finally:
        os.close(src)


def _user_release_walk(source, skipped, max_bytes, deadline, copy_to=None, allow_links=False):
    """Depth-first descriptor walk: shared trees and build-generated symlink targets are never visited."""
    total, entries = 0, 0
    source_fd = os.open(source, _DIR_FLAGS)
    try:
        dest_fd = os.open(copy_to, _DIR_FLAGS) if copy_to else None
    except BaseException:
        os.close(source_fd)
        raise
    stack = [_ops_walk_frame(source_fd, dest_fd, "")]
    try:
        while stack:
            listing, source_fd, dest_fd, prefix = stack[-1]
            try:
                entry = next(listing)
            except StopIteration:
                _ops_close_frame(stack.pop())
                continue
            entries += 1
            if entries > 100000 or time.monotonic() > deadline:
                raise HelperError("The release tree exceeds its entry or time limit")
            name, rel = entry.name, prefix + entry.name
            if _ops_skip(rel, skipped):
                continue
            st = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode):
                if len(stack) >= 64:
                    raise HelperError("The release tree exceeds its directory depth limit")
                if dest_fd is not None:
                    os.mkdir(name, 0o750, dir_fd=dest_fd)
                child = os.open(name, _DIR_FLAGS, dir_fd=source_fd)
                try:
                    target = os.open(name, _DIR_FLAGS, dir_fd=dest_fd) if dest_fd is not None else None
                except BaseException:
                    os.close(child)
                    raise
                stack.append(_ops_walk_frame(child, target, rel + "/"))
            elif stat.S_ISREG(st.st_mode) or (allow_links and copy_to is None and stat.S_ISLNK(st.st_mode)):
                total += st.st_size
                if total > max_bytes:
                    raise HelperError("Application files exceed the release size limit; configure shared/excluded paths")
                if dest_fd is not None:
                    _user_copy_release_file(source_fd, dest_fd, name, st, deadline)
            elif stat.S_ISLNK(st.st_mode):
                raise HelperError("Release sources contain a symbolic link: %s; exclude it or declare it shared" % rel)
            else:
                raise HelperError("Release sources contain an unsupported file type: %s" % rel)
    finally:
        for frame in reversed(stack):
            _ops_close_frame(frame)
    return {"bytes": total, "entries": entries}


def _user_prepare_release(home, domain_id, app_dir, release, options):
    base = _user_release_base(home, domain_id, True)
    try:
        target = ops_release_path(SimpleNamespace(pw_dir=home), domain_id, release)
        real_source = os.path.realpath(app_dir)
        if not real_source.startswith(os.path.realpath(home).rstrip("/") + "/"):
            raise HelperError("Application sources leave the subscription home")
        if os.path.commonpath([real_source, os.path.realpath(target)]) == real_source:
            raise HelperError("Release storage cannot be inside the application source directory")
        skipped = options["shared_paths"] + options["exclude_paths"] + ["tmp"]
        deadline = time.monotonic() + 180
        result = _user_release_walk(app_dir, skipped, options["release_max_mb"] * 1024 * 1024, deadline)
        available = shutil.disk_usage(home).free
        if available < result["bytes"] + options["min_free_mb"] * 1024 * 1024:
            raise HelperError("Insufficient free space for a release and the configured reserve")
        os.mkdir(release, 0o750, dir_fd=base)
        _user_release_walk(app_dir, skipped, options["release_max_mb"] * 1024 * 1024, deadline, target)
        return dict(result, path=target)
    finally:
        os.close(base)


def _user_shared_links(app_dir, release_dir, paths, runtime):
    home = os.path.realpath(os.path.expanduser("~"))
    # call_as_user fixes HOME; real path checks are repeated before each declared shared path.
    for rel in paths:
        source = app_dir + "/" + rel
        if not os.path.realpath(source).startswith(home.rstrip("/") + "/"):
            raise HelperError("A shared directory leaves the subscription home")
        if not os.path.exists(source):
            os.makedirs(source, mode=0o750, exist_ok=True)
        if not os.path.isdir(source):
            raise HelperError("A shared path must be a directory: %s" % rel)
        destinations = [release_dir + "/" + rel]
        if runtime == "dotnet" and os.path.isdir(release_dir + "/publish"):
            destinations.append(release_dir + "/publish/" + rel)
        for target in destinations:
            parent = os.path.dirname(target)
            if not os.path.realpath(parent).startswith(os.path.realpath(release_dir).rstrip("/") + "/") \
                    and os.path.realpath(parent) != os.path.realpath(release_dir):
                raise HelperError("A release build replaced a shared-path parent with a symbolic link")
            os.makedirs(parent, mode=0o750, exist_ok=True)
            if os.path.lexists(target):
                if os.path.isdir(target) and not os.path.islink(target):
                    try:
                        os.rmdir(target)
                    except OSError:
                        raise HelperError("The build wrote into a shared path: %s; move those versioned files outside the shared directory" % rel)
                else:
                    raise HelperError("The build replaced a shared path: %s" % rel)
            os.symlink(source, target)


def _user_remove_release(home, domain_id, release):
    try:
        base = _user_release_base(home, domain_id)
    except FileNotFoundError:
        return
    try:
        # Python's Linux rmtree uses directory descriptors and never follows a symlink at the leaf.
        if not shutil.rmtree.avoids_symlink_attacks:
            raise HelperError("This Python cannot safely remove release directories")
        fd_path = "/proc/self/fd/%d/%s" % (base, ops_valid_release(release))
        if os.path.islink(fd_path):
            raise HelperError("A release directory was replaced with a symbolic link")
        try:
            shutil.rmtree(fd_path)
        except FileNotFoundError:
            if os.path.lexists(fd_path):
                raise
    finally:
        os.close(base)


def ops_prepare_release(state, pw, options, release):
    copied = call_as_user(pw, _user_prepare_release, pw.pw_dir, state["domain_id"], state["app_dir"], release,
                          options, timeout=210, fsize=options["release_max_mb"] * 1024 * 1024)
    # A customer can interfere with its unprivileged child. Never use a child-returned path in
    # root-rendered unit files: the parent computes the only permitted execution path itself.
    path = ops_release_path(pw, state["domain_id"], release)
    if not isinstance(copied, dict) or any(type(copied.get(key)) is not int for key in ("bytes", "entries")) \
            or not 0 <= copied["bytes"] <= options["release_max_mb"] * 1024 * 1024 or not 0 <= copied["entries"] <= 100000:
        raise HelperError("Invalid release preparation result")
    result = {"path": path, "bytes": copied["bytes"], "entries": copied["entries"]}
    return dict(state, _release_dir=path), result


def ops_stage_release(state, release, target=None):
    domain_id = state["domain_id"]
    data = ops_release_state(domain_id)
    if not data and not release:
        return None
    if data.get("source") not in (None, state["app_dir"]) or data.get("sysuser") not in (None, state["sysuser"]):
        raise HelperError("Application identity changed; disable release mode and remove the old release records first")
    previous = json.loads(json.dumps(data))
    data.update(source=state["app_dir"], sysuser=state["sysuser"])
    if target is None:
        target = (state.get("slot") or "") if state["stopped"] else (zd_target(state) if zd_has_slots(state) else "")
    target = target if target is not None else ""
    slots = data.setdefault("slots", {})
    if release:
        slots[target] = ops_valid_release(release)
    else:
        slots.pop(target, None)
    ensure_dir(ops_dir(domain_id), 0o700)
    write_json(ops_dir(domain_id) + "/releases.json", data)
    return previous


def ops_release_result(state, pw, options, release, previous, ok, created, switched=False):
    if previous is None:
        return
    path = ops_dir(state["domain_id"]) + "/releases.json"
    data = ops_release_state(state["domain_id"])
    if not ok:
        # After an ambiguous reload both slots can still carry traffic. Retain the candidate and
        # its mapping until convergence; never delete code from underneath a running process.
        slots, old_slots = data.get("slots") or {}, previous.get("slots") or {}
        changed = [slot for slot in set(slots) | set(old_slots) if slots.get(slot) != old_slots.get(slot)]
        current = read_json(app_state_path(state["domain_id"]), {}) or {}
        if switched and (any(unit_is_active(app_unit(state["domain_id"], slot)) for slot in changed)
                         or (current.get("slot") or "") in changed or read_pointer_slot(state) in changed):
            if created and release:
                data.setdefault("records", []).append(ops_release_record(state, release))
                write_json(path, data)
            return False
        for slot in changed:
            if unit_is_active(app_unit(state["domain_id"], slot)):
                systemctl("stop", app_unit(state["domain_id"], slot), check=True, timeout=120)
        if not switched and state.get("slot") and not current.get("slot"):
            # A plain restart retired the slots: restore the old code in the classic unit.
            active = (previous.get("slots") or {}).get(state["slot"])
            previous = dict(previous, slots={"": active} if active else {})
        write_json(path, previous)
        if created and release:
            try:
                call_as_user(pw, _user_remove_release, pw.pw_dir, state["domain_id"], release, timeout=120)
            except Exception:
                pass
        return True
    if release and created:
        records = data.setdefault("records", [])
        records.append(ops_release_record(state, release))
    protected = set((data.get("slots") or {}).values())
    records = data.get("records") or []
    keep = set(item["id"] for item in records[-options["release_limit"]:]) | protected
    retained = []
    for item in records:
        if item["id"] in keep:
            retained.append(item)
        else:
            try:
                call_as_user(pw, _user_remove_release, pw.pw_dir, state["domain_id"], item["id"], timeout=120)
            except Exception:
                retained.append(item)
    data["records"] = retained
    write_json(path, data)
    return False


def ops_release_record(state, release):
    return {"id": release, "state": "ready", "created_at": now_iso(),
            "runtime": state["runtime"], "toolchain": state["toolchain"],
            "start_hash": hashlib.sha256(state["start_cmd"].encode()).hexdigest()}


def ops_retire_slots(state, preserve_classic=False):
    data = ops_release_state(state["domain_id"])
    if not data or data.get("source") != state["app_dir"] or data.get("sysuser") != state["sysuser"]:
        return
    slots = data.setdefault("slots", {})
    if state.get("slot") and not preserve_classic:
        active = slots.get(state["slot"])
        if active:
            slots[""] = active
        else:
            slots.pop("", None)
    for slot in SLOTS:
        slots.pop(slot, None)
    write_json(ops_dir(state["domain_id"]) + "/releases.json", data)


def ops_clear_releases(state, pw):
    data = ops_release_state(state["domain_id"])
    if data.get("sysuser") not in (None, pw.pw_name):
        raise HelperError("The release records belong to a different system user; remove that user's files separately")
    identifiers = set((data.get("slots") or {}).values()) | {item["id"] for item in data.get("records") or []}
    for release in identifiers:
        call_as_user(pw, _user_remove_release, pw.pw_dir, state["domain_id"], ops_valid_release(release), timeout=120)
    remove_quietly(ops_dir(state["domain_id"]) + "/releases.json")
