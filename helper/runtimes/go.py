# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- Go -------------------------------------------------------------------

class GoRuntime(Runtime):
    key = "go"
    label = "Go"
    version_re = RE_GO_VERSION.pattern
    hint = "Official go.dev release archives, verified with SHA-256."
    docs_url = "https://go.dev/doc/"

    def list_installed(self):
        return [{"id": v, "label": "Go " + v, "path": go_dir(v)} for v in installed_go()]

    def list_available(self, force=False):
        latest_by_minor = {}
        for rel in go_releases(force):
            minor = ".".join(rel["version"].split(".")[:2])
            if minor not in latest_by_minor or version_key(rel["version"]) > version_key(latest_by_minor[minor]):
                latest_by_minor[minor] = rel["version"]
        versions = sorted(latest_by_minor.values(), key=version_key, reverse=True)[:12]
        return [{"id": v, "label": "Go " + v} for v in versions]

    def install(self, version, log):
        job_install_go(version, log)

    def remove(self, version):
        self._remove_dir(GO_ROOT_DIR, self.check_version(version))

    def env(self, home, version, app_dir=None):
        goroot = go_dir(version)
        gopath = os.path.join(home, ".runway", "go")
        return {
            "PATH": [goroot + "/bin", gopath + "/bin"],
            "GOROOT": goroot,
            "GOPATH": gopath,
            "GOMODCACHE": os.path.join(gopath, "pkg", "mod"),
            "GOCACHE": os.path.join(home, ".runway", "cache", "go-build"),
            "GOENV": os.path.join(home, ".runway", "go.env"),
            "GOTOOLCHAIN": "local",
            # Keep the module cache deletable by the customer (FTP / File Manager).
            "GOFLAGS": "-modcacherw",
        }

    def inspect(self, app_dir):
        gomod = os.path.join(app_dir, "go.mod")
        if not os.path.isfile(gomod):
            return None
        text = _read_small(gomod)
        module = re.search(r"^module\s+(\S+)", text, re.M)
        godir = re.search(r"^go\s+(\S+)", text, re.M)
        toolchain = re.search(r"^toolchain\s+go(\S+)", text, re.M)
        return {
            "module": module.group(1) if module else None,
            "go": godir.group(1) if godir else None,
            "toolchain": toolchain.group(1) if toolchain else None,
            "has_main": os.path.isfile(os.path.join(app_dir, "main.go")),
            "has_cmd": os.path.isdir(os.path.join(app_dir, "cmd")),
        }

    def defaults(self, inspect, listen="tcp", toolchain=""):
        return {"build_cmd": "go build -o bin/app .", "start_cmd": "./bin/app"}

    def sample(self, listen, toolchain=""):
        match = re.match(r"^(1\.\d+)", toolchain or "")
        godir = match.group(1) if match else "1.22"
        return {"go.mod": ("module sample\n\ngo %s\n" % godir, 0o640), "main.go": (SAMPLE_GO, 0o640)}

    def build_deps(self):
        return ["git"]
