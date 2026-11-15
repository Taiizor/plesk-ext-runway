# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- Python (uv-managed CPython) ---------------------------------------------

class PythonRuntime(Runtime):
    key = "python"
    label = "Python"
    version_re = r"^3\.\d{1,2}(\.\d{1,2})?$"
    hint = ("CPython builds installed with uv (astral-sh/uv from GitHub, verified with SHA-256). "
            "Apps use a .venv in the application root.")
    docs_url = "https://docs.astral.sh/uv/"
    root = BASE_DIR + "/python"
    public_dirs = ("public",)
    uv_dir = BASE_DIR + "/uv"
    uv = uv_dir + "/uv"

    def dir_for(self, version):
        return "%s/cpython-%s-linux-%s-gnu" % (self.root, version, machine_arch())

    def uv_env(self):
        return root_env({"UV_PYTHON_INSTALL_DIR": self.root, "UV_CACHE_DIR": CACHE_DIR + "/uv",
                         "UV_NO_PROGRESS": "1", "UV_PYTHON_BIN_DIR": self.root + "/bin"})

    def list_installed(self):
        pattern = re.compile(r"^cpython-(3\.\d+\.\d+)-linux-%s-gnu$" % re.escape(machine_arch()))
        result = []
        for name in _listdir(self.root):
            match = pattern.match(name)
            path = os.path.join(self.root, name)
            if match and not os.path.islink(path) and os.path.isfile(path + "/bin/python3"):
                result.append({"id": match.group(1), "label": "Python " + match.group(1), "path": path})
        result.sort(key=lambda item: num_key(item["id"]), reverse=True)
        return result

    def resolve(self, version):
        if re.match(r"^3\.\d+$", version or ""):
            for item in self.list_installed():
                if item["id"].startswith(version + "."):
                    return item["id"]
        return version

    def may_use(self, configured, build):
        return bool(re.match(r"^3\.\d+$", configured or "")) and (build or "").startswith(configured + ".")

    def ensure_uv(self, log, update=False):
        if os.path.isfile(self.uv) and not update:
            return
        rels = [r for r in github_releases("astral-sh/uv", True, per_page=10)
                if not r["prerelease"] and re.match(r"^\d+\.\d+\.\d+$", r["tag"])]
        rels.sort(key=lambda r: num_key(r["tag"]), reverse=True)
        asset = "uv-%s-unknown-linux-gnu.tar.gz" % machine_arch()
        rel = next((r for r in rels if asset in r["assets"]), None)
        if not rel:
            raise HelperError("No uv release with %s found" % asset)
        sha = rel["assets"][asset].get("sha256")
        if not sha and asset + ".sha256" in rel["assets"]:
            sha = (http_get(https_url(rel["assets"][asset + ".sha256"]["url"])).decode("utf-8", "replace").split() or [""])[0]
        if not re.match(r"^[0-9a-fA-F]{64}$", sha or ""):
            raise HelperError("No published checksum for %s" % asset)
        ensure_dir(self.uv_dir)
        work = tempfile.mkdtemp(prefix=".tmp-", dir=self.uv_dir)
        try:
            archive = download(https_url(rel["assets"][asset]["url"]), os.path.join(work, asset), sha, log)
            stage = os.path.join(work, "x")
            os.mkdir(stage, 0o755)
            safe_extract(archive, stage)
            binary = os.path.join(stage, asset[:-len(".tar.gz")], "uv")
            if not os.path.isfile(binary) or os.path.islink(binary):
                raise HelperError("Unexpected uv archive layout")
            os.chown(binary, 0, 0)
            os.chmod(binary, 0o755)
            proc = run([binary, "--version"], env=self.uv_env(), timeout=60)
            if proc.returncode != 0:
                raise HelperError("uv --version failed: %s" % proc.stderr.strip()[-300:])
            os.rename(binary, self.uv)
            log.line("Installed %s to %s" % (proc.stdout.strip(), self.uv))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def list_available(self, force=False):
        if not os.path.isfile(self.uv):
            return [{"id": minor, "label": "Python %s (newest patch; uv is installed first)" % minor}
                    for minor in ("3.14", "3.13", "3.12", "3.11", "3.10")]
        proc = run([self.uv, "python", "list", "--only-downloads", "--output-format", "json"],
                   env=self.uv_env(), timeout=60)
        if proc.returncode != 0:
            raise HelperError("uv python list failed: %s" % proc.stderr.strip()[-300:])
        result = []
        for item in json.loads(proc.stdout or "[]"):
            version = str(item.get("version") or "")
            if item.get("implementation") != "cpython" or item.get("variant") != "default" \
                    or item.get("os") != "linux" or item.get("libc") != "gnu" or item.get("arch") != machine_arch() \
                    or not re.match(r"^3\.\d+\.\d+$", version) or num_key(version)[1] < 9:
                continue
            result.append({"id": version, "label": "Python " + version})
        result.sort(key=lambda item: num_key(item["id"]), reverse=True)
        return result

    def install(self, version, log):
        version = self.check_version(version)
        self.ensure_uv(log)
        log.line("Installing Python %s with uv" % version)
        code = stream_process([self.uv, "python", "install", version, "--no-bin"], log, 1800, self.uv_env(), cwd="/")
        if code != 0:
            raise HelperError("uv python install failed with exit code %d" % code)
        chmod_public(self.root)
        exact = self.resolve(version)
        python = self.dir_for(exact) + "/bin/python3"
        if not os.path.isfile(python):
            raise HelperError("Python %s was not found in %s after the installation" % (version, self.root))
        proc = run([python, "--version"], timeout=60)
        log.line("%s (%s)" % ((proc.stdout or proc.stderr).strip(), python))

    def updatable(self, version):
        return bool(re.match(self.version_re, version or ""))

    def update(self, version, log):
        """Updates uv (which brings new patch releases), then installs the newest patch of the minor."""
        self.ensure_uv(log, update=True)
        self.install(".".join(self.check_version(version).split(".")[:2]), log)

    def remove(self, version):
        version = self.resolve(self.check_version(version))
        if version.count(".") != 2:
            raise HelperError("Python %s is not installed" % version)
        self._remove_dir(self.root, os.path.basename(self.dir_for(version)))
        # Virtual environments reference the minor-version link: re-point it or drop it.
        minor = ".".join(version.split(".")[:2])
        link = self.dir_for(minor)
        if os.path.islink(link):
            remaining = [i["id"] for i in self.list_installed() if i["id"].startswith(minor + ".")]
            remove_quietly(link + ".tmp")
            if remaining:
                os.symlink(self.dir_for(remaining[0]), link + ".tmp")
                os.rename(link + ".tmp", link)
            else:
                os.unlink(link)

    def env(self, home, version, app_dir=None):
        pydir = self.dir_for(self.resolve(version))
        rw = os.path.join(home, ".runway")
        env = {
            "PATH": [pydir + "/bin", self.uv_dir],
            "UV_PYTHON_INSTALL_DIR": self.root,
            "UV_PYTHON": pydir + "/bin/python3",
            "UV_PYTHON_PREFERENCE": "only-managed",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_CACHE_DIR": rw + "/uv",
            "UV_TOOL_DIR": rw + "/uv/tools",
            "UV_TOOL_BIN_DIR": rw + "/uv/bin",
            "UV_PYTHON_BIN_DIR": rw + "/uv/bin",
            "UV_LINK_MODE": "copy",
            "UV_NO_PROGRESS": "1",
            "UV_HTTP_TIMEOUT": "120",
            "PIP_CACHE_DIR": rw + "/pip",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONUNBUFFERED": "1",
        }
        if app_dir:
            env["VIRTUAL_ENV"] = app_dir + "/.venv"
            env["PATH"].insert(0, app_dir + "/.venv/bin")
        return env

    def inspect(self, app_dir):
        found = _files(app_dir, "pyproject.toml", "requirements.txt", "uv.lock", "manage.py", "Procfile",
                       ".python-version", "main.py", "app.py", "api.py", "asgi.py", "wsgi.py", "app/main.py")
        if not found:
            return None
        info = {"pyproject": "pyproject.toml" in found, "requirements": "requirements.txt" in found,
                "uv_lock": "uv.lock" in found, "python_version": None, "app": None, "kind": None,
                "django": None, "script": None}
        if ".python-version" in found:
            match = re.match(r"^\s*(3\.\d+(\.\d+)?)", _read_small(os.path.join(app_dir, ".python-version"), 256))
            info["python_version"] = match.group(1) if match else None
        if "manage.py" in found:
            match = re.search(r"DJANGO_SETTINGS_MODULE['\"],\s*['\"]([\w.]+)['\"]",
                              _read_small(os.path.join(app_dir, "manage.py"), 65536))
            package = match.group(1).split(".")[0] if match else None
            if package and os.path.isfile(os.path.join(app_dir, package, "wsgi.py")):
                info["django"] = package
        for name in ("main.py", "app.py", "api.py", "asgi.py", "wsgi.py", "app/main.py"):
            if name not in found:
                continue
            text = _read_small(os.path.join(app_dir, name), 65536)
            match = re.search(r"^\s*(app|api|application)\s*=\s*(FastAPI|Starlette|Quart|Flask)\(", text, re.M)
            if match:
                info["app"] = "%s:%s" % (name[:-3].replace("/", "."), match.group(1))
                info["kind"] = "wsgi" if match.group(2) == "Flask" else "asgi"
                break
            if not info["script"] and "__main__" in text:
                info["script"] = name
        return info

    def defaults(self, inspect, listen="tcp", toolchain=""):
        info = (inspect or {}).get("python") or {}
        if info.get("uv_lock"):
            build = "uv sync --frozen --no-dev"
        elif info.get("pyproject"):
            build = "uv sync --no-dev"
        elif info.get("requirements"):
            build = "uv venv --allow-existing .venv && uv pip install -r requirements.txt"
        else:
            build = "uv venv --allow-existing .venv"
        unix = listen == "unix"
        gunicorn_bind = "--bind unix:$RUNWAY_SOCKET --umask 0117" if unix else "--bind $HOST:$PORT"
        if info.get("django"):
            start = ".venv/bin/gunicorn %s.wsgi:application %s" % (info["django"], gunicorn_bind)
        elif info.get("app") and info.get("kind") == "asgi":
            start = ".venv/bin/uvicorn %s %s" % (info["app"], "--uds $RUNWAY_SOCKET --forwarded-allow-ips '*'"
                                                 if unix else "--host $HOST --port $PORT")
        elif info.get("app"):
            start = ".venv/bin/gunicorn %s %s" % (info["app"], gunicorn_bind)
        else:
            start = ".venv/bin/python " + (info.get("script") or "app.py")
        return {"build_cmd": build, "start_cmd": start}

    def sample(self, listen, toolchain=""):
        return {"app.py": ("#!/usr/bin/env python3\n" + SAMPLE_PYTHON, 0o640)}

    def build_deps(self):
        return ["cc", "make", "pkg-config"]
