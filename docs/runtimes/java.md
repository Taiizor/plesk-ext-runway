# Runway runtime notes: Java (Eclipse Temurin)

Status: researched 2026-11-11. **[verified]** = checked against the Adoptium API/official docs or
executed inside the `grt-plesk` container (Ubuntu 24.04, x86_64) with Temurin 21.0.13+9.
**[unverified]** = from memory/secondary sources; check before relying on it. Refines the `java`
row of DESIGN.md §5.2.

Key facts in one paragraph: the Adoptium v3 API returns the newest GA build per major with a
SHA-256 in the JSON; the tarball has a top-level folder `jdk-<release>/`; the JDK runs on a bare
Ubuntu 24.04 with no extra packages; Java 16+ can listen on a unix socket with
`UnixDomainSocketAddress` (sample verified), Spring Boot/Quarkus can too but only with extra code or
config, so Runway's `default_listen` for Java should be `tcp`. The JVM's default heap is 25 % of
the cgroup memory limit, so start commands should pass `-XX:MaxRAMPercentage=75`.

## 1. Version discovery

### 1.1 Majors: `/v3/info/available_releases` [verified]

```
GET https://api.adoptium.net/v3/info/available_releases
```

```json
{
  "available_lts_releases": [8, 11, 17, 21, 25],
  "available_releases": [8, 11, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27],
  "most_recent_feature_release": 27,
  "most_recent_feature_version": 28,
  "most_recent_lts": 25,
  "tip_version": 28
}
```

What to show: LTS majors `>= 17` (17, 21, 25) plus `most_recent_feature_release` when it is not
an LTS (27, 6-month support) - i.e. `sorted({m for m in lts if m >= 17} | {most_recent_feature_release})`.
8 and 11 are kept out of the default list (old TLS/HTTP stacks, no `UnixDomainSocketAddress`);
accept them when typed explicitly.

### 1.2 Latest build per major: `/v3/assets/latest/{major}/hotspot` [verified]

```
GET https://api.adoptium.net/v3/assets/latest/21/hotspot?os=linux&architecture=x64&image_type=jdk&vendor=eclipse
```

Response: JSON **array** (one element per matching binary; with these filters exactly one):

```json
[{
  "release_name": "jdk-21.0.13+9",
  "release_link": "https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.13%2B9",
  "vendor": "eclipse",
  "version": {"build": 9, "major": 21, "minor": 0, "security": 13, "optional": "LTS",
              "openjdk_version": "21.0.13+9-LTS", "semver": "21.0.13+9.0.LTS"},
  "binary": {
    "os": "linux", "architecture": "x64", "image_type": "jdk", "jvm_impl": "hotspot",
    "heap_size": "normal", "project": "jdk", "updated_at": "2026-10-22T12:07:52Z",
    "scm_ref": "jdk-21.0.13+9_adopt",
    "package": {
      "name": "OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz",
      "link": "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz",
      "checksum": "d7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c",
      "checksum_link": ".../OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz.sha256.txt",
      "signature_link": ".../OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz.sig",
      "metadata_link": ".../OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz.json",
      "size": 207858352,
      "download_count": 1691519
    }
  }
}]
```

Parameters (from the OpenAPI spec **[verified]**): `architecture` in
`x64, x86, x32, ppc64, ppc64le, s390x, aarch64, arm, sparcv9, riscv64`; `image_type` in
`jdk, jre, testimage, debugimage, staticlibs, sources, sbom, jmods`; `os` in
`linux, windows, mac, solaris, aix, alpine-linux`; `vendor` = `eclipse` (default);
`jvm_impl` = `hotspot`; `heap_size` in `normal, large`; `project` in `jdk, valhalla, ...`.
Arch mapping: `x86_64 -> x64`, `aarch64 -> aarch64`. Use `os=linux` (glibc); `alpine-linux` is musl.

Verified examples: 21 aarch64 -> `OpenJDK21U-jdk_aarch64_linux_hotspot_21.0.13_9.tar.gz`
(205,995,218 bytes); 25 x64 -> `jdk-25.0.5+8`, `OpenJDK25U-jdk_x64_linux_hotspot_25.0.5_8.tar.gz`
(141,341,188 bytes). JDK 25 is smaller because the JDK no longer ships `jmods` by default
**[unverified reason]**.

### 1.3 Older builds of a major (optional, for pinning)

- `GET /v3/assets/feature_releases/21/ga?architecture=x64&heap_size=normal&image_type=jdk&jvm_impl=hotspot&os=linux&page=0&page_size=20&project=jdk&sort_method=DEFAULT&sort_order=DESC&vendor=eclipse`
  -> array of releases, each `{release_name, release_type, timestamp, vendor, version_data{major, minor, security, build, semver, openjdk_version, optional}, binaries[]{architecture, os, image_type, jvm_impl, heap_size, project, package{name, link, checksum, size}, ...}}`
  **[verified]**. Note the key is `version_data` here (not `version`). `page_size` max 20.
- `GET /v3/info/release_names?...&release_type=ga&version=%5B21%2C22%29` -> `{"releases": ["jdk-21.0.13+9", "jdk-21.0.12.1+1", "jdk-21.0.12+8", ...]}` **[verified]** (`version` is a Maven range, URL-encoded `[21,22)`).
- `GET /v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse` -> `307` redirect to the GitHub
  asset **[verified]**; handy for curl, but Runway must use the JSON to get the checksum.

### 1.4 Ids and regex

Use the Temurin release id without the `jdk-` prefix: `21.0.13+9` (`release_name[4:]`), label
`Temurin 21.0.13+9 (LTS)` when `version.optional == "LTS"`. Install requests may be a bare major
(`21`) which resolves to the latest GA build, or a full id. `+` is legal in directory names (the
tarball's own top-level folder uses it) and in systemd env files; URL-encode it as `%2B` only when
building API URLs. `version_re = r"^\d{1,2}(\.\d+){0,3}(\+\d+)?$"` - accepts `21`, `21.0.13+9`,
`8.0.432+6`, `17.0.13+11`. There are no channels, so `update()` raises `HelperError`
("install the newer build, then remove the old one").

```python
import json, os, urllib.parse, urllib.request

API = "https://api.adoptium.net/v3"
UA = {"User-Agent": "runway-helper/1.0", "Accept": "application/json"}

def _get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)

def temurin_arch():
    return {"x86_64": "x64", "aarch64": "aarch64", "arm64": "aarch64"}[os.uname().machine]

def temurin_available():
    info = _get_json(API + "/info/available_releases")
    majors = sorted({m for m in info["available_lts_releases"] if m >= 17} | {info["most_recent_feature_release"]})
    out = []
    for major in reversed(majors):
        assets = _get_json(API + "/assets/latest/%d/hotspot?%s" % (major, urllib.parse.urlencode(
            {"os": "linux", "architecture": temurin_arch(), "image_type": "jdk", "vendor": "eclipse"})))
        if not assets:
            continue
        a = assets[0]
        lts = a["version"].get("optional") == "LTS" or major in info["available_lts_releases"]
        out.append({"id": a["release_name"][4:], "label": "Temurin %s%s" % (a["release_name"][4:], " (LTS)" if lts else ""),
                    "url": a["binary"]["package"]["link"], "sha256": a["binary"]["package"]["checksum"],
                    "size": a["binary"]["package"]["size"], "filename": a["binary"]["package"]["name"],
                    "release_name": a["release_name"]})
    return out
```

No API key is needed; a rate limit was not observed (**[unverified]** whether one exists) -
still cache 6 h.

## 2. Download

- URL: `binary.package.link` (GitHub release asset under `github.com/adoptium/temurin<major>-binaries`).
  Name pattern `OpenJDK<major>U-jdk_<arch>_linux_hotspot_<ver>_<build>.tar.gz` (dots of the version,
  `_` before the build number). Follows one or two redirects to `objects.githubusercontent.com`.
- Checksum: SHA-256 hex in `binary.package.checksum` **[verified equal to sha256sum]**; the same
  value lives in `<asset>.sha256.txt` (`checksum_link`, format `<sha256>  <filename>`). `.sig` is a
  GPG signature (not verified by Runway).
- Size: 208 MB (21), 206 MB (21 aarch64), 141 MB (25). Expect ~1.5x unpacked **[unverified]**.
- Archive layout **[verified]**: gzip tar with ONE top-level directory equal to `release_name`:

```
jdk-21.0.13+9/
  bin/      java javac jar jshell jcmd jfr jlink jpackage keytool ... (32 tools)
  conf/ include/ jmods/ legal/ lib/ man/ NOTICE release
```

  `lib/server/libjvm.so` and `lib/server/classes.jsa` (CDS archive, "sharing" in `java -version`)
  are inside. Extract with `strip_components=1` into `/opt/runway/java/<id>/`. Temurin tarballs
  contain regular files and directories; keep the base's safe-tar policy (reject absolute paths,
  `..`, devices; allow only relative symlinks that stay inside the tree, there may be none).
  Preserve modes (tarfile does); Python >= 3.12 can use `extractall(filter="data")`.
- The `release` file (key=value, quoted) identifies an installed JDK for `list_installed`
  **[verified excerpt]**:

```
IMPLEMENTOR="Eclipse Adoptium"
IMPLEMENTOR_VERSION="Temurin-21.0.13+9"
JAVA_RUNTIME_VERSION="21.0.13+9-LTS"
JAVA_VERSION="21.0.13"
JAVA_VERSION_DATE="2026-10-20"
LIBC="gnu"
OS_ARCH="x86_64"
```

## 3. Install layout, PATH, system dependencies

```
/opt/runway/java/<id>/            # JAVA_HOME, e.g. /opt/runway/java/21.0.13+9
/opt/runway/java/<id>/bin/java    # on PATH
```

Dependencies (checked with `ldd` on `bin/java`, `lib/server/libjvm.so`, `lib/libjava.so`,
`lib/libnet.so`, `lib/libnio.so`, `lib/libzip.so` **[verified]**): only glibc components
(`libc`, `libm`, `libdl`, `libpthread`, `librt`) and `libjli.so` from the JDK itself. zlib is
bundled. Highest glibc symbol versions: launcher `GLIBC_2.2.5`, libjvm `GLIBC_2.15` **[verified]**
-> every supported distro qualifies. `java -version` works on the stock Plesk container without
installing anything **[verified]**.

Optional runtime packages (only when apps use `java.desktop`: image generation, PDF/JasperReports,
charts) **[unverified, standard knowledge]**: Debian/Ubuntu `fontconfig libfreetype6 fonts-dejavu-core`;
RHEL/Alma `fontconfig freetype dejavu-sans-fonts`. Detection for the status page:
`ldconfig -p | grep -q 'libfreetype.so.6'` and `fc-list` existence. Headless mode is automatic
without a display (`-Djava.awt.headless=true` can be added to be explicit).

Build dependencies: the JDK contains `javac`, `jar`, `jlink`, `jpackage`; it does **not** contain
Maven or Gradle. Projects must ship the Maven Wrapper (`mvnw`) or Gradle Wrapper (`gradlew`), which
download their distribution on first use (network). `build_deps()` for Java can report `mvn` and
`gradle` on PATH as informational, plus `git` and `unzip` (Gradle wrapper needs `unzip`
**[unverified]**).

Resource facts **[verified]**: `UseContainerSupport=true` and `MaxRAMPercentage=25` are the
defaults; with `systemd-run -p MemoryMax=512M java -XX:MaxRAMPercentage=75 -XshowSettings:vm` the
JVM reports `Max. Heap Size (Estimated): 371.25M`, i.e. the cgroup v2 limit of the unit is honoured.
`java.io.tmpdir` = `/tmp` (private under `PrivateTmp=yes`); `user.home` comes from the passwd entry
(not from `$HOME`) **[verified: `-XshowSettings:properties`]**.

## 4. Per-user environment (`env(home, version)`)

```python
import os

def env(self, home, version):
    jh = "/opt/runway/java/%s" % version
    rw = os.path.join(home, ".runway", "java")
    return {
        "PATH": [jh + "/bin"],
        "JAVA_HOME": jh,
        # Maven: wrapper distributions (default ~/.m2/wrapper) [verified docs: MAVEN_USER_HOME]
        "MAVEN_USER_HOME": os.path.join(rw, "maven"),
        # Maven local repository (default ~/.m2/repository): system property via MAVEN_OPTS
        # [unverified: widely used CI idiom; MAVEN_OPTS is passed to the JVM by mvn/mvnw]
        "MAVEN_OPTS": "-Dmaven.repo.local=%s" % os.path.join(rw, "m2", "repository"),
        # Gradle: caches/, wrapper/dists/, daemon/, jdks/ [verified docs]
        "GRADLE_USER_HOME": os.path.join(rw, "gradle"),
        # Runway listen mode -> framework conventions (see 5.3)
        # tcp:  "SERVER_PORT": port, "SERVER_ADDRESS": host (Spring Boot relaxed binding [verified docs for SERVER_PORT])
        #       "QUARKUS_HTTP_PORT": port, "QUARKUS_HTTP_HOST": host (MicroProfile Config env mapping [unverified])
    }
```

Notes:
- DESIGN says "`~/.m2` stays in home": that is acceptable (it is inside the subscription), but the
  `MAVEN_OPTS` line above moves the repository under `~/.runway` so one `rm -rf ~/.runway` frees
  everything. If a customer sets `MAVEN_OPTS` in the app env, the later value wins (env file order).
  `MAVEN_ARGS` (Maven >= 3.9) is an alternative for CLI flags **[unverified]**.
- `JAVA_TOOL_OPTIONS` / `JDK_JAVA_OPTIONS` are deliberately NOT set globally: every JVM (including
  Maven/Gradle daemons) would inherit them and print `Picked up JAVA_TOOL_OPTIONS: ...` on stderr.
  Memory flags go into the start command instead.
- Gradle daemon: the deploy unit kills leftover processes when it ends (control group), but to avoid
  a 3-hour idle daemon holding memory use `--no-daemon` in the default build command.
- Gradle toolchain auto-provisioning (`java { toolchain { languageVersion = ... } }`) downloads
  JDKs into `GRADLE_USER_HOME/jdks` when the requested version is not found; add
  `-Porg.gradle.java.installations.auto-download=false` only as a hint **[unverified]**.
- Read-only `/opt`: the JDK needs no writable files (CDS archive is pre-generated); `~/.java/`
  (`java.util.prefs`) is created only by apps that use Preferences.

## 5. Detection and defaults

### 5.1 Files (`inspect`, as the user, `_read_small` with caps)

| File | What to parse | Result |
|---|---|---|
| `pom.xml` | XML, namespace `http://maven.apache.org/POM/4.0.0`: `artifactId`, `version` (fallback `parent/version`), `packaging` (default `jar`), `build/finalName`, `modules/module` (multi-module), plugins: `spring-boot-maven-plugin`, `quarkus-maven-plugin`, `maven-shade-plugin`, `maven-assembly-plugin`; `<properties>` for `${revision}` / `${project.version}` interpolation | jar name `target/<finalName or artifactId-version>.jar` |
| `mvnw` + `.mvn/wrapper/maven-wrapper.properties` (`distributionUrl=`) | presence; file does not need the exec bit (`sh ./mvnw`) | build with wrapper |
| `build.gradle` / `build.gradle.kts` | regex: `version\s*=\s*['"]([^'"]+)['"]`, plugin ids `org.springframework.boot`, `io.quarkus`, `application` | jar in `build/libs/` |
| `settings.gradle(.kts)` | `rootProject.name\s*=\s*['"]([^'"]+)['"]`; `include(...)` -> multi-project | base name of the jar |
| `gradlew` + `gradle/wrapper/gradle-wrapper.properties` | presence | build with wrapper |
| `target/*.jar`, `build/libs/*.jar`, `*.jar` (root) | list; exclude `*-sources.jar`, `*-javadoc.jar`, `*-tests.jar`, `*-plain.jar` (Gradle/Spring Boot plain archive), `original-*.jar`, `*.jar.original`; prefer the one whose `META-INF/MANIFEST.MF` has `Main-Class:` (zipfile, read <= 64 KB) | executable jar |
| `target/quarkus-app/quarkus-run.jar` | presence | Quarkus fast-jar **[verified docs]**: needs the whole `quarkus-app/` dir (`lib/`, `app/`, `quarkus/`) |
| `*-runner.jar` | presence | Quarkus uber-jar **[verified docs: `-runner` suffix]** |
| `*.java` in root containing `static void main` | regex (`Main.java`, `App.java` first, at most 20 files) | Runway 1.0: `javac -d build <File>.java` / `java -XX:MaxRAMPercentage=75 -cp build <package.Class>`; alternative single-file launch `java App.java` (JDK 11+; multi-file from 22) |
| `Procfile` / `system.properties` (`java.runtime.version=21`) | optional, Heroku convention **[unverified]** | hint which major to install |
| `src/main/resources/application.properties|yml` | presence (do not parse deeply) | Spring Boot hint; `server.port` inside is overridden by env/CLI (CLI > env > file **[verified docs]**) |

Multi-module Maven / multi-project Gradle: do not guess the jar; return `modules` and let the UI
show "set the start command manually".

### 5.2 Default commands

```python
import shlex

def defaults(self, info):
    build = ""
    if info.get("mvnw"):
        build = "sh ./mvnw -q -B -DskipTests package"
    elif info.get("gradlew"):
        build = "sh ./gradlew --no-daemon -q build -x test"
    elif info.get("pom") and info.get("mvn_on_path"):
        build = "mvn -q -B -DskipTests package"            # only if the admin installed Maven
    elif info.get("gradle_build") and info.get("gradle_on_path"):
        build = "gradle --no-daemon -q build -x test"
    jar = info.get("jar")                                   # resolved as in 5.1, relative path
    if info.get("quarkus_app"):
        jar = "target/quarkus-app/quarkus-run.jar"
    if jar:
        start = "java -XX:MaxRAMPercentage=75 -jar %s" % shlex.quote(jar)
    elif info.get("single_file"):
        start = "java %s" % shlex.quote(info["single_file"])    # recompiles at every start; fine for tiny apps
    else:
        start = ""
    return {"build_cmd": build, "start_cmd": start}
```

`-DskipTests` compiles tests but does not run them; `-Dmaven.test.skip=true` also skips compiling
them (faster, but breaks builds that need test-jars). `-B` = batch mode (no ANSI progress), `-q` =
quiet. For Spring Boot with Gradle `build` already runs `bootJar`.

### 5.3 Listen modes

tcp (default for Java):

| Framework | Takes the port from | Verified? |
|---|---|---|
| Spring Boot | `SERVER_PORT` env (relaxed binding of `server.port`), `SERVER_ADDRESS` for `server.address`; or `--server.port=$PORT --server.address=$HOST` as program args (highest precedence) | `SERVER_PORT`/precedence **[verified docs]**; `SERVER_ADDRESS` follows the same documented rule **[not re-verified]** |
| Quarkus | `QUARKUS_HTTP_PORT`, `QUARKUS_HTTP_HOST` env, or `-Dquarkus.http.port=$PORT -Dquarkus.http.host=$HOST` | property names **[verified: all-config]**; env mapping **[unverified]**; prod default host `0.0.0.0` **[unverified]** |
| Micronaut | `MICRONAUT_SERVER_PORT`, `MICRONAUT_SERVER_HOST` | **[unverified]** |
| Javalin / Ktor / Vert.x / Helidon / plain `HttpServer` | app code must read `PORT` and `HOST` | - |

Recommendation: in tcp mode Runway exports `SERVER_PORT=$PORT`, `SERVER_ADDRESS=$HOST`,
`QUARKUS_HTTP_PORT=$PORT`, `QUARKUS_HTTP_HOST=$HOST` next to `PORT`/`HOST`, so `java -jar app.jar`
works unchanged for the two big frameworks. Keep `HOST=127.0.0.1`: Spring Boot and Quarkus bind
`0.0.0.0` by default **[Spring Boot: verified docs for server.address semantics only; Quarkus: unverified]**.

unix (`RUNWAY_SOCKET`):

- Plain Java 16+: `ServerSocketChannel.open(StandardProtocolFamily.UNIX).bind(UnixDomainSocketAddress.of(path))`
  **[verified with the sample]**. `com.sun.net.httpserver.HttpServer` is TCP-only (`InetSocketAddress`).
  Binding fails if the file exists -> `Files.deleteIfExists` first (the unit also runs `rm -f`).
- Spring Boot (embedded Tomcat 10.0+/10.1+, Java 16+): no property; a bean
  `WebServerFactoryCustomizer<TomcatServletWebServerFactory>` with
  `factory.addConnectorCustomizers(c -> c.setProperty("unixDomainSocketPath", System.getenv("RUNWAY_SOCKET")))`
  **[Tomcat attribute verified in Tomcat docs; Spring Boot wiring from secondary sources, unverified]**.
  Tomcat refuses to start if the socket file exists and applies the umask (`UMask=0007` -> group
  connectable) **[verified Tomcat docs]**. `server.port` is still needed (`server.port=-1` disables
  the TCP connector but Boot may still require a port value) **[unverified]**.
- Quarkus (JVM mode only, not native): `quarkus.http.domain-socket=$RUNWAY_SOCKET`,
  `quarkus.http.domain-socket-enabled=true`, `quarkus.vertx.prefer-native-transport=true`,
  `quarkus.http.host-enabled=false` (drop the TCP listener) and the dependency
  `io.netty:netty-transport-native-epoll:linux-x86_64` **[verified docs]** (aarch64 classifier
  `linux-aarch_64` **[unverified]**). Env form `QUARKUS_HTTP_DOMAIN_SOCKET` **[verified all-config]**.
- Therefore: `default_listen = "tcp"`; the UI hint says unix mode needs app support.

Socket facts **[verified with the sample]**: created `srwxrwx---` under `UMask=0007`; removed by
a shutdown hook on SIGTERM.

## 6. Minimal sample app

JDK only, no dependencies. Needs Java 21+ because of `Thread.ofPlatform()`; for Java 17 replace
that line with `new Thread(() -> handle(c)).start();`.

`App.java` **[verified in tcp, unix, stale-socket and SIGTERM scenarios with Temurin 21.0.13]**:

```java
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.StandardProtocolFamily;
import java.net.UnixDomainSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.ServerSocketChannel;
import java.nio.channels.SocketChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import com.sun.net.httpserver.HttpServer;

public class App {
    static final byte[] BODY = ("Hello from Runway (Java " + System.getProperty("java.version") + ")\n")
        .getBytes(StandardCharsets.UTF_8);

    public static void main(String[] args) throws Exception {
        String sock = System.getenv("RUNWAY_SOCKET");
        if (sock != null && !sock.isEmpty()) { serveUnix(sock); return; }
        String host = System.getenv().getOrDefault("HOST", "127.0.0.1");
        int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "8080"));
        HttpServer server = HttpServer.create(new InetSocketAddress(host, port), 64);
        server.createContext("/", ex -> {
            ex.getResponseHeaders().add("Content-Type", "text/plain; charset=utf-8");
            ex.sendResponseHeaders(200, BODY.length);
            try (OutputStream os = ex.getResponseBody()) { os.write(BODY); }
        });
        server.start();
        System.out.println("listening on http://" + host + ":" + port);
    }

    // Minimal HTTP/1.1 responder on a unix socket (HttpServer cannot bind to one).
    static void serveUnix(String path) throws Exception {
        Path p = Path.of(path);
        Files.deleteIfExists(p);                                   // stale socket from a crash
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try { Files.deleteIfExists(p); } catch (IOException e) { }
        }));
        try (ServerSocketChannel server = ServerSocketChannel.open(StandardProtocolFamily.UNIX)) {
            server.bind(UnixDomainSocketAddress.of(p));
            System.out.println("listening on unix:" + path);
            while (true) {
                SocketChannel c = server.accept();
                Thread.ofPlatform().daemon().start(() -> handle(c));
            }
        }
    }

    static void handle(SocketChannel c) {
        try (c) {
            ByteBuffer in = ByteBuffer.allocate(8192);
            StringBuilder req = new StringBuilder();
            while (c.read(in) > 0) {                               // read until end of headers
                in.flip(); req.append(StandardCharsets.ISO_8859_1.decode(in)); in.clear();
                if (req.indexOf("\r\n\r\n") >= 0) break;
            }
            String head = "HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: "
                + BODY.length + "\r\nConnection: close\r\n\r\n";
            c.write(ByteBuffer.wrap(head.getBytes(StandardCharsets.ISO_8859_1)));
            c.write(ByteBuffer.wrap(BODY));
        } catch (IOException e) {
            // connection closed by peer
        }
    }
}
```

Commands: build `javac -d out App.java` (0.6 s **[verified]**), start `java -cp out App`.
Alternative without build: `java App.java` (source launcher, compiles at every start, ~1-2 s
**[verified working]**). Test: `curl --unix-socket /run/runway/<id>/app.sock http://localhost/`.

## 7. Pitfalls and verification

- `java -version` prints to **stderr** **[verified]**:

```
openjdk version "21.0.13" 2026-10-20 LTS
OpenJDK Runtime Environment Temurin-21.0.13+9 (build 21.0.13+9-LTS)
OpenJDK 64-Bit Server VM Temurin-21.0.13+9 (build 21.0.13+9-LTS, mixed mode, sharing)
```

  `javac -version` -> `javac 21.0.13` (stdout). Install-time check: run
  `/opt/runway/java/<id>/bin/java -version` and compare `Temurin-<id>` in stderr; also read the
  `release` file. The binaries must not be executed from a `noexec` mount (`/tmp` is `noexec` in the
  Plesk container **[verified]**) -> extract under `/opt/runway/java/.tmp-<id>` and rename.
- Memory: the JVM heap defaults to 25 % of `MemoryMax` **[verified]**; Spring Boot apps need a limit
  of at least 384-512 MB and `-XX:MaxRAMPercentage=75`. Beyond the heap the JVM uses metaspace,
  code cache and thread stacks (~1 MB each): leave 25 % headroom, which is what 75 % does.
- Threads: Tomcat's default pool is 200 threads + JVM/GC threads -> the unit's `TasksMax` must be
  >= 512 for Spring Boot (`tasks` setting); with the base default the app may fail with
  `OutOfMemoryError: unable to create native thread`.
- Startup time: Spring Boot 3-10 s, Quarkus < 2 s; the `health_path` check should tolerate a slow
  first response; `TimeoutStartSec` is irrelevant for `Type=simple`.
- `-XX:+UseContainerSupport` reads cgroup v2 limits (JDK 11.0.16+/17+); `CPUQuota` -> fewer
  `availableProcessors()`, which also shrinks default GC/thread pools (good).
- First Maven/Gradle build downloads hundreds of MB into `~/.runway/java/...`; the deploy deadline
  (`buildTimeout`) and `buildMemoryMb` (Gradle easily needs 1 GB) must allow it; both wrappers need
  outbound HTTPS.
- Uploaded `mvnw`/`gradlew` often lose the exec bit (FTP): the defaults call `sh ./mvnw`.
- Gradle leaves a daemon; the default uses `--no-daemon`. Maven leaves nothing.
- The `original-*.jar` / `*.jar.original` (Spring Boot repackage) and `-plain.jar` (Gradle) are not
  executable: never pick them.
- Java prints nothing when the main class is a Spring Boot fat jar started with the wrong working
  directory (`application.properties` lookups are relative to cwd); the unit's `WorkingDirectory`
  is the app root, which matches `java -jar target/app.jar`.
- Temurin update cadence: quarterly CPU releases (Jan/Apr/Jul/Oct) **[unverified]**; new builds
  appear as new ids in the list, old ones stay installed until removed; `in_use` must block removal.
- Prefer JDK over JRE images: the JRE cannot run `mvnw`'s compile step (`javac` missing) and is only
  ~30 % smaller.
