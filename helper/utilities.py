# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def root_env(extra=None):
    env = {"PATH": ROOT_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/root"}
    if extra:
        env.update(extra)
    return env


def _ignore_sigterm():
    signal.signal(signal.SIGTERM, signal.SIG_IGN)


def run(cmd, check=False, timeout=120, env=None, input_text=None):
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            input=input_text,
            timeout=timeout,
            env=env if env is not None else root_env(),
            universal_newlines=True,
            errors="replace",
            # Inside the critical section of a zero-downtime switch the deploy job defers SIGTERM
            # (_TERM); systemd sends it to every process of the deploy unit, so its children (e.g.
            # "systemctl reload nginx") ignore it too and finish what the switch depends on.
            preexec_fn=_ignore_sigterm if _TERM["critical"] else None,
        )
    except FileNotFoundError:
        raise HelperError("Command not found: %s" % cmd[0])
    except subprocess.TimeoutExpired:
        raise HelperError("Command timed out: %s" % " ".join(cmd[:3]))
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise HelperError("%s failed (exit %d): %s" % (" ".join(cmd[:3]), proc.returncode, msg[-2000:]))
    return proc


def ensure_dir(path, mode=0o755):
    os.makedirs(path, mode=mode, exist_ok=True)
    os.chmod(path, mode)


def write_file_atomic(path, content, mode=0o644):
    """Writes a root-owned file atomically. Only used for root-owned directories."""
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.rename(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path, data, mode=0o600):
    write_file_atomic(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", mode)


def remove_quietly(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def tail_file(path, max_lines=300, max_bytes=512 * 1024):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read()
    except OSError:
        return ""
    lines = data.decode("utf-8", "replace").splitlines()
    return "\n".join(lines[-max_lines:])


class FileLock(object):
    def __init__(self, name):
        ensure_dir(LOCK_DIR, 0o700)
        self.path = os.path.join(LOCK_DIR, name + ".lock")
        self.fh = None

    def acquire(self, blocking=True, timeout=LOCK_TIMEOUT):
        self.fh = open(self.path, "a")
        deadline = time.time() + timeout
        while True:
            try:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if not blocking or time.time() >= deadline:
                    self.fh.close()
                    self.fh = None
                    return False
                time.sleep(0.2)

    def release(self):
        if self.fh:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None

    def __enter__(self):
        if not self.acquire(True):
            raise HelperError("Another operation is still in progress. Please try again in a moment.")
        return self

    def __exit__(self, *exc):
        self.release()
