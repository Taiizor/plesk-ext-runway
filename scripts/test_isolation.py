#!/usr/bin/env python3
# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Run Linux contracts offline with read-only sources/tools and bounded scratch storage."""

import os
from pathlib import Path
import signal
import subprocess
import sys


def main():
    if not sys.platform.startswith("linux"):
        raise SystemExit("Run this script on Linux, for example through WSL; Plesk is not required.")
    repo = Path(__file__).resolve().parents[1]
    uid, gid = os.getuid(), os.getgid()
    data = {
        "/etc/passwd": "fixture:x:%d:%d::/scratch/home:/bin/sh\n" % (uid, gid),
        "/etc/group": "fixture:x:%d:\n" % gid,
        "/etc/nsswitch.conf": "passwd: files\ngroup: files\nhosts: files\n",
    }
    fds = []
    argv = ["/usr/bin/prlimit", "--as=1073741824", "--cpu=90", "--nproc=256", "--nofile=1024", "--fsize=67108864",
            "/usr/bin/bwrap", "--unshare-user", "--uid", str(uid), "--gid", str(gid), "--unshare-net",
            "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--new-session", "--die-with-parent", "--cap-drop", "ALL"]
    for path in ("/usr", "/bin", "/lib", "/lib64", "/etc/alternatives", "/etc/ld.so.cache"):
        if os.path.exists(path):
            argv += ["--ro-bind", path, path]
    try:
        for destination, text in data.items():
            fd = os.memfd_create("runway-test-account", 0)
            os.write(fd, text.encode("utf-8"))
            os.lseek(fd, 0, os.SEEK_SET)
            fds.append(fd)
            argv += ["--ro-bind-data", str(fd), destination]
        argv += ["--ro-bind", str(repo), "/repo", "--proc", "/proc", "--dev", "/dev",
                 "--size", "16777216", "--tmpfs", "/run",
                 "--size", "268435456", "--tmpfs", "/scratch", "--dir", "/scratch/home", "--dir", "/scratch/tmp",
                 "--symlink", "/scratch/tmp", "/tmp", "--dir", "/var", "--symlink", "/scratch/tmp", "/var/tmp",
                 "--clearenv", "--setenv", "HOME", "/scratch/home", "--setenv", "TMPDIR", "/scratch/tmp",
                 "--setenv", "LANG", "C.UTF-8",
                 "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
                 "--setenv", "RUNWAY_ISOLATION_FIXTURES", "1", "--chdir", "/repo", "--remount-ro", "/", "--"]
        command = sys.argv[1:] or ["/usr/bin/python3", "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-q"]
        proc = subprocess.Popen(argv + command, pass_fds=fds, start_new_session=True,
                                env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"})
        try:
            return proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise SystemExit("The isolated Linux contracts exceeded their two-minute deadline.")
    finally:
        for fd in fds:
            os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
