# Copyright 2026 Taiizor. Licensed under the MIT License.

def ops_actor(value):
    text = value if isinstance(value, str) else "system"
    return RE_CTRL_ANY.sub("", text)[:80] or "system"


def ops_valid_release(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{12}", value):
        raise HelperError("Invalid deployment identifier")
    return value


def ops_new_id():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S-") + os.urandom(6).hex()


def ops_history(domain_id):
    index = read_json(ops_dir(domain_id) + "/history.json", [])
    return index if isinstance(index, list) else []


def ops_history_record(domain_id, record_id):
    record_id = ops_valid_release(record_id)
    record = next((entry for entry in ops_history(domain_id) if entry.get("id") == record_id), None)
    if record is None:
        raise HelperError("Deployment record not found")
    return dict(record)


def ops_begin(state, mode, source, actor):
    options = ops_options(state["domain_id"])
    if not options["history"] and not options["releases"] and not options["notifications"]:
        return None
    return {"id": ops_new_id(), "mode": mode, "source": source, "actor": ops_actor(actor),
            "runtime": state["runtime"], "toolchain": state["toolchain"], "started_at": now_iso(),
            "started_epoch": time.time()}


def ops_finish(state, record, ok, message, job, release=None):
    if record is None:
        return
    domain_id = state["domain_id"]
    options = ops_options(domain_id)
    record = dict(record)
    record.update(state="succeeded" if ok else "failed", finished_at=now_iso(),
                  duration_seconds=round(time.time() - record.pop("started_epoch"), 2),
                  message=(message or "")[:1000], release=release)
    for value in (state.get("env") or {}).values():
        if isinstance(value, str) and len(value) >= 4:
            record["message"] = record["message"].replace(value, "[redacted]")
    if options["history"]:
        path = ops_dir(domain_id)
        ensure_dir(path, 0o700)
        log = tail_file(job_paths(job)[1], 2000, OPS_LOG_BYTES)
        for value in (state.get("env") or {}).values():
            if isinstance(value, str) and len(value) >= 4:
                log = log.replace(value, "[redacted]")
        log = log.encode("utf-8")[-OPS_LOG_BYTES:].decode("utf-8", "ignore")
        write_file_atomic(path + "/" + record["id"] + ".log", log, 0o600)
        index = [record] + ops_history(domain_id)
        for old in index[options["history_limit"]:]:
            remove_quietly(path + "/" + ops_valid_release(old["id"]) + ".log")
        write_json(path + "/history.json", index[:options["history_limit"]])
    ops_event(state, "deploy_succeeded" if ok else "deploy_failed", {"deployment": record["id"],
              "mode": record["mode"], "actor": record["actor"], "duration_seconds": record["duration_seconds"]})


def ops_event(state, event, detail=None):
    """Optional metadata-only audit and notifications; failures cannot break application control."""
    try:
        domain_id = state["domain_id"]
        options = ops_options(domain_id)
        if not options["history"] and not options["notifications"]:
            return
        data = {"id": ops_new_id(), "event": event, "time": now_iso(), "domain": state["domain"],
                "detail": detail or {}}
        if options["history"]:
            ensure_dir(ops_dir(domain_id), 0o700)
            with FileLock("events-%d" % domain_id):
                old = read_json(ops_dir(domain_id) + "/events.json", [])
                write_json(ops_dir(domain_id) + "/events.json", ([data] + (old if isinstance(old, list) else []))[:options["history_limit"] * 5])
        if options["notifications"] and event in options["notification_events"]:
            ops_notify(state, options, data)
    except Exception:
        pass
