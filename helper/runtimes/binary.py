# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- Prebuilt binary -----------------------------------------------------------

def _is_program(path):
    """True for an ELF binary or a script with a shebang line (files copied from Windows often
    carry the executable bit, e.g. README.md). Never follows symbolic links or blocks on FIFOs."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return False
        head = os.read(fd, 4)
    except OSError:
        return False
    finally:
        os.close(fd)
    return head == b"\x7fELF" or head[:2] == b"#!"


class BinaryRuntime(Runtime):
    key = "binary"
    label = "Prebuilt binary"
    toolchain = "none"
    version_re = ""
    hint = "Upload an executable compiled for Linux (or fetch it from a URL) and set the start command."
    supports_build = False

    def inspect(self, app_dir):
        executables = []
        for name in sorted(_scan_names(app_dir, 2000)[0]):
            try:
                st = os.lstat(os.path.join(app_dir, name))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and st.st_mode & 0o100 and not name.startswith(".") and RE_REL_PATH.match(name)                     and _is_program(os.path.join(app_dir, name)):
                executables.append(name)
        return {"executables": executables[:20]} if executables else None

    def defaults(self, inspect, listen="tcp", toolchain=""):
        executables = ((inspect or {}).get("binary") or {}).get("executables") or []
        name = "app" if "app" in executables or not executables else executables[0]
        return {"build_cmd": "", "start_cmd": "./" + name}

    def sample(self, listen, toolchain=""):
        return {"app": ("#!/usr/bin/python3\n" + SAMPLE_PYTHON, 0o750)}
