# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- Bun ------------------------------------------------------------------

class BunRuntime(Runtime):
    key = "bun"
    label = "Bun"
    version_re = r"^(latest|\d+\.\d+\.\d+)$"
    hint = ("Official oven-sh/bun releases from GitHub, verified with SHASUMS256.txt. "
            "'latest' is a channel that can be updated later.")
    docs_url = "https://bun.sh/docs"
    root = BASE_DIR + "/bun"
    public_dirs = ("dist", "public")

    def target(self):
        if machine_arch() == "aarch64":
            return "aarch64"
        flags = cpu_flags()
        if flags and "sse4_2" not in flags:
            raise HelperError("Bun needs a CPU with SSE4.2")
        # The baseline build runs on CPUs without AVX2 (older hosts, some virtual CPUs).
        return "x64" if not flags or "avx2" in flags else "x64-baseline"

    def list_installed(self):
        result = []
        for name in _listdir(self.root):
            path = os.path.join(self.root, name)
            if not re.match(self.version_re, name) or not os.path.isfile(path + "/bin/bun"):
                continue
            label = "Bun " + name
            if name == "latest":
                label = "Bun latest (%s)" % (_read_text(path + "/.version") or "?")
            result.append({"id": name, "label": label, "path": path})
        result.sort(key=lambda item: (item["id"] == "latest", num_key(item["id"])), reverse=True)
        return result

    def releases(self, force=False):
        result = []
        for rel in github_releases("oven-sh/bun", force, per_page=60):
            match = re.match(r"^bun-v(\d+\.\d+\.\d+)$", rel["tag"])
            if not match or rel["prerelease"] or "SHASUMS256.txt" not in rel["assets"] \
                    or "bun-linux-x64.zip" not in rel["assets"]:
                continue
            result.append({"version": match.group(1), "assets": rel["assets"]})
        result.sort(key=lambda r: num_key(r["version"]), reverse=True)
        return result

    def list_available(self, force=False):
        rels = self.releases(force)
        if not rels:
            return []
        return [{"id": "latest", "label": "latest (channel, currently %s)" % rels[0]["version"]}] + \
            [{"id": r["version"], "label": "Bun " + r["version"]} for r in rels[:10]]

    def install(self, version, log, replace=False):
        version = self.check_version(version)
        target_dir = os.path.join(self.root, version)
        if os.path.isfile(target_dir + "/bin/bun") and not replace:
            log.line("Bun %s is already installed." % version)
            return
        rels = self.releases(force=True)
        rel = (rels[0] if rels else None) if version == "latest" else \
            next((r for r in rels if r["version"] == version), None)
        if not rel:
            raise HelperError("Bun %s was not found in the release list" % version)
        target = self.target()
        asset = "bun-linux-%s.zip" % target
        if asset not in rel["assets"]:
            raise HelperError("Bun %s has no %s build" % (rel["version"], target))
        ensure_dir(self.root)
        # Not /tmp: it may be mounted noexec, and the binary is executed for verification.
        work = tempfile.mkdtemp(prefix=".tmp-", dir=self.root)
        try:
            sums = parse_shasums(http_get(https_url(rel["assets"]["SHASUMS256.txt"]["url"])).decode("utf-8", "replace"))
            sha = sums.get(asset) or rel["assets"][asset].get("sha256")
            if not sha:
                raise HelperError("No published checksum for %s" % asset)
            archive = download(https_url(rel["assets"][asset]["url"]), os.path.join(work, asset), sha, log)
            stage = os.path.join(work, "stage")
            os.makedirs(stage + "/bin", 0o755)
            member = "bun-linux-%s/bun" % target
            with zipfile.ZipFile(archive) as zf:
                if member not in zf.namelist():
                    raise HelperError("Unexpected archive layout (no %s)" % member)
                with zf.open(member) as src, open(stage + "/bin/bun", "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
            os.chmod(stage + "/bin/bun", 0o755)  # zipfile does not restore Unix modes
            os.symlink("bun", stage + "/bin/bunx")
            write_text(stage + "/.target", target + "\n")
            if version == "latest":
                write_text(stage + "/.version", rel["version"] + "\n")
            chmod_public(stage)
            proc = run([stage + "/bin/bun", "--version"], timeout=60,
                       env=root_env({"BUN_INSTALL": work + "/home", "DO_NOT_TRACK": "1"}))
            if proc.returncode != 0 or proc.stdout.strip() != rel["version"]:
                raise HelperError("bun --version failed: %s" % (proc.stderr or proc.stdout).strip()[-500:])
            log.line("bun --version: %s (%s build)" % (proc.stdout.strip(), target))
            swap_dir(stage, target_dir, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        log.line("Bun %s installed to %s" % (version, target_dir))

    def updatable(self, version):
        return version == "latest"

    def update(self, version, log):
        if not self.updatable(version):
            Runtime.update(self, version, log)
        self.install(version, log, replace=True)

    def remove(self, version):
        self._remove_dir(self.root, self.check_version(version))

    def env(self, home, version, app_dir=None):
        rw = os.path.join(home, ".runway", "bun")
        return {
            "PATH": [os.path.join(self.root, version, "bin"), rw + "/bin"],
            "BUN_INSTALL": rw,
            "BUN_INSTALL_CACHE_DIR": rw + "/cache",
            "BUN_RUNTIME_TRANSPILER_CACHE_PATH": rw + "/transpiler-cache",
            "DO_NOT_TRACK": "1",
            "NO_COLOR": "1",
        }

    def inspect(self, app_dir):
        entry = (_files(app_dir, "index.ts", "index.js", "server.ts", "server.js", "src/index.ts", "src/index.js")
                 or [None])[0]
        if not os.path.isfile(os.path.join(app_dir, "package.json")):
            return {"package": False, "entry": entry} if entry else None
        pkg = _json_file(os.path.join(app_dir, "package.json"))
        scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
        main = _safe_rel(pkg.get("module")) or _safe_rel(pkg.get("main"))
        return {
            "package": True,
            "name": str(pkg.get("name") or "")[:100],
            "start_script": isinstance(scripts.get("start"), str),
            "build_script": isinstance(scripts.get("build"), str),
            "lockfile": (_files(app_dir, "bun.lock", "bun.lockb") or [None])[0],
            "entry": main if main and os.path.isfile(os.path.join(app_dir, main)) else entry,
        }

    def defaults(self, inspect, listen="tcp", toolchain=""):
        info = (inspect or {}).get("bun") or {}
        build = ""
        if info.get("package"):
            build = "bun install --frozen-lockfile" if info.get("lockfile") else "bun install"
            if info.get("build_script"):
                build += " && bun run build"
        start = "bun run start" if info.get("start_script") else "bun run " + (_safe_rel(info.get("entry")) or "index.ts")
        return {"build_cmd": build, "start_cmd": start}

    def sample(self, listen, toolchain=""):
        return {"package.json": (SAMPLE_BUN_PACKAGE, 0o640), "index.ts": (SAMPLE_BUN, 0o640)}

    def build_deps(self):
        return ["git"]
