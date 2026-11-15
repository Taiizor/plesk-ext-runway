# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- Java (Eclipse Temurin) -------------------------------------------------

class JavaRuntime(Runtime):
    key = "java"
    label = "Java"
    version_re = r"^\d{1,2}(\.\d+){0,5}(\+\d+)?$"
    hint = ("Eclipse Temurin JDK builds from the Adoptium API, verified with SHA-256. "
            "Install a major (17, 21, 25) to get its latest build.")
    docs_url = "https://adoptium.net/docs/"
    root = BASE_DIR + "/java"
    api = "https://api.adoptium.net/v3"

    def arch(self):
        return "x64" if machine_arch() == "x86_64" else "aarch64"

    def latest_build(self, major, lts):
        query = urllib.parse.urlencode({"os": "linux", "architecture": self.arch(), "image_type": "jdk",
                                        "vendor": "eclipse"})
        assets = http_json("%s/assets/latest/%d/hotspot?%s" % (self.api, major, query))
        if not isinstance(assets, list) or not assets:
            return None
        asset = assets[0]
        package = asset["binary"]["package"]
        release = str(asset.get("release_name") or "")
        build_id = release[4:] if release.startswith("jdk-") else release
        if not re.match(self.version_re, build_id) or not re.match(r"^[0-9a-fA-F]{64}$", package.get("checksum") or ""):
            return None
        return {"id": build_id, "major": major, "lts": lts or (asset.get("version") or {}).get("optional") == "LTS",
                "release_name": release, "url": https_url(package.get("link")),
                "sha256": package["checksum"].lower(), "size": package.get("size")}

    def builds(self, force=False):
        def fetch():
            info = http_json(self.api + "/info/available_releases")
            lts = [m for m in info.get("available_lts_releases") or [] if isinstance(m, int)]
            majors = set(m for m in lts if m >= 17)
            if isinstance(info.get("most_recent_feature_release"), int):
                majors.add(info["most_recent_feature_release"])
            result = []
            for major in sorted(majors, reverse=True):
                build = self.latest_build(major, major in lts)
                if build:
                    result.append(build)
            return result
        return cached_json("java-temurin", force, fetch)

    def list_available(self, force=False):
        return [{"id": b["id"], "label": "Temurin %s%s" % (b["id"], " (LTS)" if b["lts"] else "")}
                for b in self.builds(force)]

    def list_installed(self):
        result = []
        for name in _listdir(self.root):
            path = os.path.join(self.root, name)
            if not re.match(self.version_re, name) or not os.path.isfile(path + "/bin/java"):
                continue
            release = _read_text(path + "/release")
            lts = "-LTS" in release
            result.append({"id": name, "label": "Temurin %s%s" % (name, " (LTS)" if lts else ""), "path": path})
        result.sort(key=lambda item: java_key(item["id"]), reverse=True)
        return result

    def resolve(self, version):
        if re.match(r"^\d{1,2}$", version or ""):
            for item in self.list_installed():
                if self.may_use(version, item["id"]):
                    return item["id"]
        return version

    def may_use(self, configured, build):
        return bool(re.match(r"^\d{1,2}$", configured or "")) and bool(re.match(r"^%s([.+]|$)" % configured, build or ""))

    def install(self, version, log):
        version = self.check_version(version)
        builds = self.builds(force=True)
        if re.match(r"^\d{1,2}$", version):
            build = next((b for b in builds if str(b["major"]) == version), None) or \
                self.latest_build(int(version), False)
        else:
            build = next((b for b in builds if b["id"] == version), None)
        if not build:
            raise HelperError("Temurin %s is not available (only the latest build of a major can be installed)" % version)
        target = os.path.join(self.root, build["id"])
        if os.path.isfile(target + "/bin/java"):
            log.line("Temurin %s is already installed." % build["id"])
            return
        ensure_dir(self.root)
        work = tempfile.mkdtemp(prefix=".tmp-", dir=self.root)
        try:
            archive = download(build["url"], os.path.join(work, "jdk.tar.gz"), build["sha256"], log)
            log.line("Extracting archive")
            stage = os.path.join(work, "x")
            os.mkdir(stage, 0o755)
            safe_extract(archive, stage)
            tops = [d for d in os.listdir(stage) if os.path.isdir(os.path.join(stage, d))]
            if len(tops) != 1 or not os.path.isfile(os.path.join(stage, tops[0], "bin", "java")):
                raise HelperError("Unexpected archive layout")
            top = os.path.join(stage, tops[0])
            chmod_public(top)
            proc = run([top + "/bin/java", "-version"], timeout=60)
            log.line((proc.stderr or proc.stdout).strip())
            if proc.returncode != 0:
                raise HelperError("java -version failed")
            swap_dir(top, target, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        log.line("Temurin %s installed to %s" % (build["id"], target))

    def remove(self, version):
        self._remove_dir(self.root, self.resolve(self.check_version(version)))

    def env(self, home, version, app_dir=None):
        java_home = os.path.join(self.root, self.resolve(version))
        rw = os.path.join(home, ".runway", "java")
        return {
            "PATH": [java_home + "/bin"],
            "JAVA_HOME": java_home,
            "MAVEN_USER_HOME": rw + "/maven",
            "MAVEN_OPTS": "-Dmaven.repo.local=" + rw + "/m2/repository",
            "GRADLE_USER_HOME": rw + "/gradle",
        }

    def listen_env(self, state):
        if state.get("listen") == "unix":
            return {}
        # Spring Boot and Quarkus bind 0.0.0.0 and their own default ports otherwise.
        port = str(state["port"])
        return {"SERVER_PORT": port, "SERVER_ADDRESS": "127.0.0.1",
                "QUARKUS_HTTP_PORT": port, "QUARKUS_HTTP_HOST": "127.0.0.1"}

    def inspect(self, app_dir):
        found = _files(app_dir, "pom.xml", "build.gradle", "build.gradle.kts", "mvnw", "gradlew")
        top = sorted(_scan_names(app_dir, 500)[0])
        jars = []
        for sub in ("target", "build/libs", "."):
            folder = os.path.join(app_dir, sub)
            if os.path.islink(folder) or not os.path.isdir(folder):
                continue
            for name in (top if sub == "." else sorted(_scan_names(folder, 500)[0])):
                if name.endswith(".jar") and not name.startswith("original-") and not re.search(
                        r"-(plain|sources|javadoc|tests)\.jar$", name):
                    rel = name if sub == "." else sub + "/" + name
                    if RE_REL_PATH.match(rel):
                        jars.append(rel)
        main_java, main_class = self.find_main(app_dir, top)
        if not found and not jars and not main_java:
            return None
        info = {"maven": "pom.xml" in found, "gradle": "build.gradle" in found or "build.gradle.kts" in found,
                "mvnw": "mvnw" in found, "gradlew": "gradlew" in found, "main_java": main_java,
                "main_class": main_class, "jars": jars[:20], "artifact": None}
        if info["maven"]:
            text = _read_small(os.path.join(app_dir, "pom.xml"))
            final = re.search(r"<finalName>\s*([A-Za-z0-9_.-]+)\s*</finalName>", text)
            own = re.sub(r"<(parent|dependencies|dependencyManagement|build|profiles|modules)>.*?</\1>", "", text, flags=re.S)
            artifact = re.search(r"<artifactId>\s*([A-Za-z0-9_.-]+)\s*</artifactId>", own)
            version = re.search(r"<version>\s*([A-Za-z0-9_.+-]+)\s*</version>", own)
            if final:
                info["artifact"] = final.group(1)
            elif artifact:
                info["artifact"] = artifact.group(1) + ("-" + version.group(1) if version else "")
        return info

    def find_main(self, app_dir, names):
        """As the user: the top-level .java source with a "static void main" (Main.java and App.java
        first, at most 20 files read) and its class name (with the package): (file, class) or (None, None)."""
        sources = [n for n in names if re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*\.java$", n)]
        sources.sort(key=lambda n: (n not in ("Main.java", "App.java"), n))
        for name in sources[:20]:
            try:
                text = _read_small(os.path.join(app_dir, name), 262144)
            except (HelperError, OSError):
                continue
            if re.search(r"\bstatic\s+void\s+main\s*\(", text):
                package = re.search(r"^\s*package\s+([A-Za-z_][\w.]*)\s*;", text, re.M)
                return name, (package.group(1) + "." if package else "") + name[:-len(".java")]
        return None, None

    def defaults(self, inspect, listen="tcp", toolchain=""):
        info = (inspect or {}).get("java") or {}
        build = ""
        if info.get("mvnw"):
            build = "sh ./mvnw -q -B -DskipTests package"
        elif info.get("gradlew"):
            build = "sh ./gradlew build -x test --no-daemon"
        elif info.get("main_java") and not info.get("maven") and not info.get("gradle") \
                and re.match(r"^[A-Za-z_$][\w$.]*$", str(info.get("main_class") or "")) \
                and re.match(r"^[A-Za-z_$][\w$]*\.java$", str(info.get("main_java"))):
            return {"build_cmd": "javac -d build " + info["main_java"],
                    "start_cmd": "java -XX:MaxRAMPercentage=75 -cp build " + info["main_class"]}
        jars = [j for j in info.get("jars") or [] if j.startswith(("target/", "build/libs/"))] or info.get("jars") or []
        if jars:
            jar = jars[0]
        elif info.get("artifact"):
            jar = "target/%s.jar" % info["artifact"]
        elif info.get("gradle"):
            jar = "build/libs/app.jar"
        else:
            jar = "app.jar"
        # The JVM sizes its heap from the service's memory limit (MemoryMax); the default of 25 %
        # is too small for typical web frameworks (docs/runtimes/java.md).
        return {"build_cmd": build, "start_cmd": "java -XX:MaxRAMPercentage=75 -jar " + jar}

    def sample(self, listen, toolchain=""):
        return {"Main.java": (SAMPLE_JAVA, 0o640)}

    def build_deps(self):
        return ["git", "unzip"]
