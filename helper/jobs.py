# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Jobs (status files + logs)
# ---------------------------------------------------------------------------

def job_unit(job):
    if job == "admin":
        return UNIT_ADMIN_JOB
    match = re.match(r"^deploy-(\d+)$", job)
    if match:
        return UNIT_DEPLOY % int(match.group(1))
    raise HelperError("Unknown job")


def v_job(value):
    if not isinstance(value, str) or not re.match(r"^(admin|deploy-\d{1,10})$", value):
        raise HelperError("Invalid job name")
    return value


def job_set_status(job, **fields):
    ensure_dir(JOBS_DIR, 0o700)
    status_path = job_paths(job)[0]
    status = read_json(status_path, {}) or {}
    status.update(fields)
    status["job"] = job
    status["updated_at"] = now_iso()
    write_json(status_path, status)
    return status


def job_get_status(job):
    status_path, log_path, _ = job_paths(job)
    status = read_json(status_path, None)
    if not status:
        return {"job": job, "state": "none"}
    if status.get("state") in ("queued", "running"):
        active = unit_is_active(job_unit(job))
        if not active:
            # The job may have finished between the read above and the is-active check:
            # re-read, and only mark it failed if nothing was written in the meantime.
            fresh = read_json(status_path, None) or {}
            if fresh.get("updated_at") != status.get("updated_at") or fresh.get("state") != status.get("state"):
                return fresh
            started = status.get("queued_epoch") or 0
            if status.get("state") == "running" or time.time() - started > 20:
                status = job_set_status(job, state="failed", finished_at=now_iso(),
                                        message="The job was interrupted before it could finish.")
    return status


class JobLog(object):
    """Root-owned job log with a size cap."""

    def __init__(self, job, append=False):
        ensure_dir(JOBS_DIR, 0o700)
        self.path = job_paths(job)[1]
        self.fh = open(self.path, "ab" if append else "wb")
        os.chmod(self.path, 0o600)
        self.size = self.fh.tell()
        self.truncated = False

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8", "replace")
        if self.size >= LOG_CAP:
            if not self.truncated:
                self.fh.write(b"\n[log truncated: size limit reached]\n")
                self.truncated = True
            return
        self.fh.write(data)
        self.size += len(data)
        self.fh.flush()

    def line(self, text):
        self.write("[%s] %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), text))

    def close(self):
        self.fh.close()


def stream_process(cmd, log, timeout, env, cwd=None, preexec=None):
    """Runs cmd, streaming combined output to the log. Returns the exit code (124 on timeout)."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        env=env, cwd=cwd, preexec_fn=preexec, start_new_session=True, close_fds=True,
    )
    deadline = time.time() + timeout
    fd = proc.stdout.fileno()
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                log.line("Timed out after %d seconds, terminating." % timeout)
                kill_group(proc)
                return 124
            ready, _, _ = select.select([fd], [], [], min(remaining, 1.0))
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                log.write(chunk)
        return proc.wait(timeout=max(1, deadline - time.time()))
    except subprocess.TimeoutExpired:
        kill_group(proc)
        return 124
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass


def kill_group(proc):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            return
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue
