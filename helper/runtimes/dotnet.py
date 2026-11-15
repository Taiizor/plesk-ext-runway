# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- .NET -------------------------------------------------------------------

class DotnetRuntime(Runtime):
    key = "dotnet"
    label = ".NET"
    version_re = r"^\d+\.\d+(\.\d{3})?$"
    hint = ("Official .NET SDKs from Microsoft's release metadata, verified with SHA-512. All SDKs share "
            "/opt/runway/dotnet; a global.json in the project selects a specific SDK.")
    docs_url = "https://learn.microsoft.com/dotnet/core/"
    root = BASE_DIR + "/dotnet"
    public_dirs = ("wwwroot",)
    meta_url = "https://builds.dotnet.microsoft.com/dotnet/release-metadata/"
    shared_files = ("dotnet", "dnx", "LICENSE.txt", "ThirdPartyNotices.txt")

    def rid(self):
        return "linux-x64" if machine_arch() == "x86_64" else "linux-arm64"

    def manifest_path(self, sdk):
        return os.path.join(self.root, ".runway", "installed", sdk + ".json")

    def channels(self, force=False):
        def fetch():
            index = http_json(self.meta_url + "releases-index.json").get("releases-index") or []
            result = []
            for channel in index:
                version = str(channel.get("channel-version") or "")
                sdk = str(channel.get("latest-sdk") or "")
                if channel.get("support-phase") not in ("active", "maintenance", "go-live") \
                        or not re.match(r"^\d+\.\d+$", version) or int(version.split(".")[0]) < 8 \
                        or not re.match(r"^\d+\.\d+\.\d{3}$", sdk):
                    continue
                result.append({"channel": version, "sdk": sdk, "type": str(channel.get("release-type") or "").upper(),
                               "eol": channel.get("eol-date")})
            return result
        return cached_json("dotnet-channels", force, fetch)

    def list_available(self, force=False):
        return [{"id": c["sdk"], "label": ".NET %s (%s) SDK %s" % (c["channel"], c["type"], c["sdk"])}
                for c in self.channels(force)]

    def sdk_versions(self):
        return sorted([n for n in _listdir(self.root + "/sdk") if re.match(r"^\d+\.\d+\.\d{3}$", n)],
                      key=num_key, reverse=True)

    def list_installed(self):
        return [{"id": v, "label": ".NET SDK " + v, "path": os.path.join(self.root, "sdk", v)}
                for v in self.sdk_versions()]

    def resolve(self, version):
        if re.match(r"^\d+\.\d+$", version or ""):
            match = [v for v in self.sdk_versions() if v.startswith(version + ".")]
            if match:
                return match[0]
        return version

    def may_use(self, configured, build):
        return bool(re.match(r"^\d+\.\d+$", configured or "")) and (build or "").startswith(configured + ".")

    def install(self, version, log):
        version = self.check_version(version)
        if re.match(r"^\d+\.\d+$", version):
            channel = next((c for c in self.channels(force=True) if c["channel"] == version), None)
            if not channel:
                raise HelperError(".NET channel %s is not supported" % version)
            sdk = channel["sdk"]
        else:
            sdk = version
        channel_version = ".".join(sdk.split(".")[:2])
        if os.path.isdir(os.path.join(self.root, "sdk", sdk)):
            log.line(".NET SDK %s is already installed." % sdk)
            return
        data = http_json("%s%s/releases.json" % (self.meta_url, channel_version))
        url = sha512 = None
        for rel in data.get("releases") or []:
            for entry in [rel.get("sdk")] + list(rel.get("sdks") or []):
                if not isinstance(entry, dict) or entry.get("version") != sdk:
                    continue
                for item in entry.get("files") or []:
                    if item.get("rid") == self.rid() and str(item.get("name") or "").endswith(".tar.gz"):
                        url, sha512 = item.get("url"), str(item.get("hash") or "").lower()
        if not url or not re.match(r"^[0-9a-f]{128}$", sha512 or ""):
            raise HelperError(".NET SDK %s was not found for %s" % (sdk, self.rid()))
        ensure_dir(self.root)
        work = tempfile.mkdtemp(prefix=".tmp-", dir=self.root)
        try:
            archive = download(https_url(url), os.path.join(work, "sdk.tar.gz"), sha512, log, algo="sha512")
            newer = [v for v in self.sdk_versions() if num_key(v) > num_key(sdk)]
            # The muxer is backward compatible: never replace a newer one with an older one.
            skip = set(["dotnet", "dnx"]) if newer and os.path.isfile(self.root + "/dotnet") else None
            log.line("Extracting archive")
            stage = os.path.join(work, "x")
            os.mkdir(stage, 0o755)
            members = safe_extract(archive, stage, skip=skip)
            chmod_public(stage)
            files = []
            for name in sorted(members):
                src, dst = os.path.join(stage, name), os.path.join(self.root, name)
                if os.path.isdir(src) and not os.path.islink(src):
                    ensure_dir(dst)
                    continue
                files.append(name)
                if os.path.lexists(dst) and "/" in name:
                    continue  # versioned content shared with another SDK of the same runtime
                ensure_dir(os.path.dirname(dst))
                os.rename(src, dst)  # rename: running processes keep the old inode
            ensure_dir(os.path.dirname(self.manifest_path(sdk)), 0o755)
            write_json(self.manifest_path(sdk), {"sdk": sdk, "members": files}, mode=0o644)
            os.chmod(self.root, 0o755)
            proc = run([self.root + "/dotnet", "--list-sdks"], timeout=120, env=root_env({
                "DOTNET_ROOT": self.root, "DOTNET_CLI_HOME": CACHE_DIR + "/dotnet-cli",
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}))
            log.line(proc.stdout.strip() or proc.stderr.strip())
            if sdk not in proc.stdout:
                raise HelperError("dotnet --list-sdks does not show %s" % sdk)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        log.line(".NET SDK %s installed to %s" % (sdk, self.root))

    def remove(self, version):
        sdk = self.resolve(self.check_version(version))
        installed = self.sdk_versions()
        if sdk not in installed:
            raise HelperError(".NET SDK %s is not installed" % sdk)
        others = [v for v in installed if v != sdk]
        if not others:
            shutil.rmtree(self.root)
            return
        manifest = read_json(self.manifest_path(sdk))
        if isinstance(manifest, dict):
            claimed = set(self.shared_files)
            for other in others:
                data = read_json(self.manifest_path(other))
                claimed.update(data.get("members") or [] if isinstance(data, dict) else [])
            parents = set()
            for name in manifest.get("members") or []:
                if not isinstance(name, str) or name in claimed or name.startswith("/") or ".." in name.split("/"):
                    continue
                path = os.path.join(self.root, name)
                if os.path.islink(path) or os.path.isfile(path):
                    os.unlink(path)
                    parent = os.path.dirname(name)
                    while parent:
                        parents.add(parent)
                        parent = os.path.dirname(parent)
            for parent in sorted(parents, key=len, reverse=True):
                try:
                    os.rmdir(os.path.join(self.root, parent))
                except OSError:
                    pass
        shutil.rmtree(os.path.join(self.root, "sdk", sdk), ignore_errors=True)
        remove_quietly(self.manifest_path(sdk))

    def env(self, home, version, app_dir=None):
        rw = os.path.join(home, ".runway", "dotnet")
        return {
            "PATH": [self.root, rw + "/tools"],
            "DOTNET_ROOT": self.root,
            "DOTNET_CLI_HOME": rw,
            "NUGET_PACKAGES": rw + "/nuget/packages",
            "NUGET_HTTP_CACHE_PATH": rw + "/nuget/http-cache",
            "NUGET_PLUGINS_CACHE_PATH": rw + "/nuget/plugins-cache",
            "DOTNET_BUNDLE_EXTRACT_BASE_DIR": rw + "/bundle",
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
            "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
            "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "0",
            "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "1",
            "MSBUILDDISABLENODEREUSE": "1",
            "DOTNET_CLI_UI_LANGUAGE": "en",
        }

    def listen_env(self, state):
        if state.get("listen") == "unix":
            return {"ASPNETCORE_URLS": "http://unix:" + endpoint_socket(state)}
        return {"ASPNETCORE_URLS": "http://127.0.0.1:%d" % int(state["port"])}

    def inspect(self, app_dir):
        names = sorted(_scan_names(app_dir, 2000)[0])
        projects = [n for n in names if n.endswith((".csproj", ".fsproj", ".vbproj")) and RE_REL_PATH.match(n)]
        solutions = [n for n in names if n.endswith((".sln", ".slnx"))]
        prebuilt = []
        for folder in ("publish", "."):
            if folder == "publish" and os.path.islink(os.path.join(app_dir, folder)):
                continue
            for n in (names if folder == "." else _scan_names(os.path.join(app_dir, folder), 2000)[0]):
                if n.endswith(".runtimeconfig.json") and RE_REL_PATH.match(n):
                    prebuilt.append(n[:-len(".runtimeconfig.json")] if folder == "." else "publish/" + n[:-len(".runtimeconfig.json")])
        if not projects and not solutions and not prebuilt:
            return None
        info = {"projects": projects[:20], "solutions": solutions[:20], "prebuilt": sorted(prebuilt)[:20],
                "project": projects[0] if len(projects) == 1 else None, "assembly_name": None,
                "target_framework": None, "self_contained": False}
        if info["project"]:
            text = _read_small(os.path.join(app_dir, info["project"]))
            name = re.search(r"<AssemblyName>\s*([A-Za-z0-9_.-]+)\s*</AssemblyName>", text)
            framework = re.search(r"<TargetFrameworks?>\s*([A-Za-z0-9_.;-]+)\s*</TargetFrameworks?>", text)
            info["assembly_name"] = name.group(1) if name else re.sub(r"\.[a-z]+proj$", "", info["project"])
            info["target_framework"] = framework.group(1) if framework else None
            info["self_contained"] = bool(re.search(r"<SelfContained>\s*true\s*</SelfContained>", text, re.I))
        return info

    def defaults(self, inspect, listen="tcp", toolchain=""):
        info = (inspect or {}).get("dotnet") or {}
        project, name = info.get("project"), info.get("assembly_name")
        if project:
            build = "dotnet publish %s -c Release -o publish --nologo" % project
        elif info.get("prebuilt"):
            build = ""
            name = name or info["prebuilt"][0].replace("publish/", "")
        elif info.get("solutions"):
            build = ""
        else:
            build = "dotnet publish -c Release -o publish --nologo"
        if not name or not re.match(r"^[A-Za-z0-9_.-]+$", name):
            start = ""
        elif info.get("self_contained"):
            start = "./publish/" + name
        elif project or (info.get("prebuilt") or [""])[0].startswith("publish/"):
            start = "dotnet publish/%s.dll" % name
        else:
            start = "dotnet %s.dll" % name
        return {"build_cmd": build, "start_cmd": start}

    def sample(self, listen, toolchain=""):
        sdk = self.resolve(toolchain) if toolchain else (self.sdk_versions() or [""])[0]
        match = re.match(r"^(\d+)\.", sdk or "")
        framework = "net%s.0" % (match.group(1) if match else "10")
        return {"app.csproj": (SAMPLE_DOTNET_PROJECT % framework, 0o640),
                "Program.cs": (SAMPLE_DOTNET, 0o640)}

    def build_deps(self):
        return ["git"]
