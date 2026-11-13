<img src="assets/logo-tile.svg" alt="" width="72" align="right">

# Runway for Plesk

[![CI](https://github.com/Taiizor/plesk-ext-runway/actions/workflows/ci.yml/badge.svg)](https://github.com/Taiizor/plesk-ext-runway/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Taiizor/plesk-ext-runway/actions/workflows/codeql.yml/badge.svg)](https://github.com/Taiizor/plesk-ext-runway/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/Taiizor/plesk-ext-runway)](https://github.com/Taiizor/plesk-ext-runway/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Runway is a Plesk Obsidian extension that runs compiled and long-running applications per domain
**without Docker**: Go, Rust, Bun, Java, .NET, Python, Ruby, PHP or any prebuilt Linux binary.

- The administrator installs toolchains from the panel (official sources, checksums verified).
- Per domain, the administrator or a permitted customer picks a runtime and version, an
  application directory, build and start commands and environment variables.
- The application is built **as the subscription's system user** and runs as a hardened
  **systemd service** on `127.0.0.1:<port>` or on a private Unix socket; nginx proxies the domain
  (or one path of it) to the application, including WebSockets.
- Deployments start from the panel, from the command line, or from Git by touching
  `tmp/deploy.txt` (build + restart) or `tmp/restart.txt` (restart) in the application directory.

Node.js is deliberately not a Runway runtime: Plesk ships its own Node.js support.

## Contents

[Screenshots](#screenshots) · [Features](#features) · [Requirements](#requirements) ·
[Installation](#installation) · [Updating](#updating) · [Quick start](#quick-start) · [Runtimes](#runtimes) ·
[Listen modes](#listen-modes) · [Zero-downtime deployments](#zero-downtime-deployments) · [Memory](#memory) ·
[Deploying with Git](#deploying-with-git) · [Command line](#command-line) · [Configuration reference](#configuration-reference) ·
[How it works](#how-it-works) · [Uninstalling](#uninstalling) · [Development](#development) ·
[License](#license)

## Screenshots

![Overview](docs/screenshots/admin-overview.png)
![Toolchains](docs/screenshots/admin-toolchains.png)
![Domain](docs/screenshots/admin-domain.png)

More in [docs/screenshots](docs/screenshots) (dark theme, customer view, drawers); how they are
made is described in [docs/RELEASING.md](docs/RELEASING.md#screenshots).

## Features

**Administrators**

- Install, update and remove toolchain versions per runtime; release lists are cached for 6 hours
  and the install runs as a background job with a live log.
- One-click installation of build dependencies (C compiler, `pkg-config`, OpenSSL headers and
  related packages) for runtimes that compile native code.
- Server-wide settings: port range, build timeout, default resource limits for applications and
  builds, maximum number of applications per subscription, zero-downtime deployments for
  customers and their time limits.
- Per-application memory, CPU and task limits that customers cannot change.
- An overview of every application on the server with its state.

**Domains** (administrators, and customers with the permission)

- Runtime, toolchain version, application directory, build and start commands with
  project-aware defaults (for example the Cargo package name or the Maven jar).
- Environment variables, stored root-only on the server and never passed on a command line.
- Listen on a TCP port, on a Unix socket, or run a background worker without a proxy.
- Proxy the whole domain or only a path prefix (for example `/api`), let the web server serve
  static folders, and check a health path.
- Start, stop, restart, build and redeploy; live status (state, PID, the application's memory
  apart from the kernel's file cache, restarts, listener check), application journal and build
  log. **Stop persists**: a stopped application stays stopped across reboots, deployments and
  trigger files until it is started again.
- **Create sample app** writes a minimal application for the chosen runtime; prebuilt binaries
  or archives can be fetched from an HTTPS URL (optional SHA-256 check).
- Trigger files for Git and CI deployments.
- Optional **zero-downtime deployments**: the new version starts next to the running one and
  takes over when it is ready; a version that does not become ready never gets traffic.

**Languages**: the interface follows the panel language, in all 32 languages of Plesk. English and
Turkish are written by hand; the other 30 were machine-translated and reviewed, and corrections
from native speakers are welcome (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## Requirements

- Plesk Obsidian **18.0.55** or newer on Linux with **systemd**: Ubuntu 22.04/24.04, Debian 12,
  AlmaLinux/RHEL 9. Developed and tested on Plesk 18.0.82 / Ubuntu 24.04.
- `python3` 3.8+ as `/usr/bin/python3` (present on every Plesk server: `plesk-core` depends on
  it; the installation checks the version) and `/bin/bash`.
- nginx (the Plesk default). Apache-only servers work through `mod_proxy`/`mod_proxy_http`;
  WebSockets through Apache alone need Apache 2.4.47 or newer (`ProxyPass ... upgrade=websocket`,
  emitted only for those versions).
- systemd 249 or newer for the per-port bind restriction (`SocketBindAllow=`); older versions
  work without it.
- Outbound HTTPS from the server to the toolchain sources (go.dev, static.rust-lang.org,
  github.com, api.adoptium.net, builds.dotnet.microsoft.com, ...) and, during builds, to the
  package registries your applications use.
- **SELinux** (AlmaLinux/RHEL in enforcing mode; not tested): nginx/Apache (`httpd_t`) may be
  denied the connection to the applications. TCP mode then needs
  `setsebool -P httpd_can_network_connect on`; Unix socket mode needs a policy that lets
  `httpd_t` connect to the sockets in `/run/runway` (for example a local module built with
  `audit2allow` from the denials in `ausearch -m AVC -c nginx`). The overview's server facts show
  the SELinux mode and warn when it is enforcing.

## Installation

Download `runway-<version>-<release>.zip` from the
[releases](https://github.com/Taiizor/plesk-ext-runway/releases) (or [build it](#building)). To try Runway
without a server, see [Try it in Docker](#try-it-in-docker).

**Command line** (as root on the Plesk server):

```sh
plesk bin extension --install /root/runway-1.0.0-1.zip
# later versions: install or upgrade in one step
plesk bin extension --upgrade /root/runway-1.0.0-1.zip
# or straight from the latest GitHub release (install or upgrade)
plesk bin extension --upgrade-url https://github.com/Taiizor/plesk-ext-runway/releases/latest/download/runway.zip
```

**Panel**: Plesk only offers *Upload Extension* when it is enabled in
`/usr/local/psa/admin/conf/panel.ini` (create the file from `panel.ini.sample` if it does not
exist):

```ini
[ext-catalog]
extensionUpload = true
```

Then use *Extensions > My Extensions > Upload Extension*.

After the installation **Runway** appears in the administrator's navigation (in the Service
Provider view under *Server Management*, in the Power User view as an entry of its own), in the
resellers' navigation (*Hosting Services*) and in every domain's *Dev Tools* (*Websites &
Domains*). Customers see it, in their navigation too, when
their service plan or subscription has the **Runway applications management** permission
(*Service Plans > Permissions*). In *Websites & Domains* a domain whose Runway application is
enabled shows Runway's mark among the icons of its row (a Node.js or .NET icon in a row comes from
Plesk's Node.js or .NET Toolkit extension, which is turned on or off separately for that domain).

## Updating

Plesk only offers updates for extensions from its catalog; Runway is distributed through the
[GitHub releases](https://github.com/Taiizor/plesk-ext-runway/releases), so it updates itself:

- **Built-in updater**: twice a day Runway asks GitHub for its latest release (one HTTPS request
  to `api.github.com`, no data about the server). When a newer version exists, *Runway >
  Overview* shows it with a link to the release notes and an **Update now** button: Runway
  downloads the release, verifies its SHA-256 checksum and upgrades itself in a background job
  (applications keep running), then asks you to reload the page. The *Server* panel shows the
  installed version and the last check, with **Check now**.
- **Settings** (*Runway > Settings > Updates*): *Check for updates twice a day* (on by default)
  and *Install updates automatically* (off by default; installs a new release as soon as a check
  finds it).
- **Command line**:

  ```sh
  plesk ext runway --check-update     # installed and latest version
  plesk ext runway --update           # update to the latest release and wait for the job
  ```

- **One command without the updater** (also for the first installation): the newest release is
  always available as `runway.zip`:

  ```sh
  plesk bin extension --upgrade-url https://github.com/Taiizor/plesk-ext-runway/releases/latest/download/runway.zip
  ```

- **Manually**: download `runway-<version>-<release>.zip` and run
  `plesk bin extension --upgrade <zip>` or upload it under *Extensions > My Extensions > Upload
  Extension* (see [Installation](#installation)).

Updates never downgrade, run for administrators only and keep every application, toolchain and
setting. The trust model of the updater is described in [SECURITY.md](SECURITY.md#updates).

## Quick start

1. *Runway > Toolchains*: install a version of the runtime (for example Go 1.27). Runtimes that
   compile native code (Rust, Ruby gems with extensions, Python packages without wheels) also
   need **Install build dependencies** once.
2. Upload the application into the subscription. The default application directory is
   `apps/<domain>`: outside the document root (`httpdocs`, or the folder of a subdomain), whose
   files the web server serves whenever it does not pass a request to the application
   (application disabled or removed, worker mode, paths outside the URL path of `path` mode,
   static paths; a stopped or failed application answers 502 instead). An application directory
   inside a document root works, but its sources, binaries and settings files with secrets
   (`appsettings.json`, `.env`) can then be downloaded; the domain page and
   `plesk ext runway --status` warn about it, also when a symbolic link puts the directory there.
3. Open the domain's **Runway** page, choose runtime and version, check the build and start
   commands (Runway suggests them from the project files), enable the application and save.
   Runway builds it, starts the service and points the domain at it.

No application yet? **Create sample app** on the domain page, or upload one of the
[examples](examples).

## Runtimes

| Runtime | Toolchain | Detected from | Default build | Default start | Example |
|---|---|---|---|---|---|
| Go | managed: go.dev archives (SHA-256) | `go.mod` | `go build -o bin/app .` | `./bin/app` | [go-hello](examples/go-hello) |
| Rust | managed: rustup (`stable`, `beta`, `nightly`, `1.x.y`) | `Cargo.toml` | `cargo build --release` | `./target/release/<package>` | [rust-hello](examples/rust-hello) |
| Bun | managed: GitHub releases (SHA-256), `latest` channel | `package.json`, `bun.lock` | `bun install` (`--frozen-lockfile` with a lock file) | `bun run start` | [bun-hello](examples/bun-hello) |
| Java | managed: Eclipse Temurin JDK (Adoptium API, SHA-256) | `pom.xml`, `build.gradle(.kts)`, `*.jar`, a top-level `*.java` with `static void main` | Maven/Gradle wrapper, or `javac -d build <File>.java` | `java -jar <detected jar>` or `java -cp build <Class>` | [java-hello](examples/java-hello) |
| .NET | managed: .NET SDK (Microsoft release metadata, SHA-512) | `*.csproj`, `*.sln` | `dotnet publish -c Release -o publish` | `dotnet publish/<assembly>.dll` | [dotnet-hello](examples/dotnet-hello) |
| Python | managed: CPython through `uv` | `pyproject.toml`, `requirements.txt` | `uv venv .venv && uv pip install -r requirements.txt` (`uv sync --frozen` with `uv.lock`) | `.venv/bin/uvicorn`/`gunicorn ...` or `.venv/bin/python app.py` | [python-hello](examples/python-hello), [python-fastapi](examples/python-fastapi) |
| Ruby | detected: Plesk Ruby extension, system Ruby | `Gemfile`, `config.ru` | `bundle install` | `bundle exec puma ...` (`-C config/puma.rb` when present) | [ruby-hello](examples/ruby-hello) |
| PHP | detected: Plesk PHP handlers; managed: FrankenPHP | `composer.json`, `public/index.php`, Laravel Octane | `composer install --no-dev --optimize-autoloader` | `frankenphp php-server ...`, `php artisan octane:frankenphp --caddyfile=.runway/Caddyfile ...` or `php -S ...` | [php-hello](examples/php-hello) |
| Binary | none | executables in the app directory | none | `./app` | |

Notes:

- Toolchains live in `/opt/runway/<runtime>/` (root-owned, read-only for users). Caches
  (Go modules, Cargo registry, Bun, Maven/Gradle, NuGet, uv/pip, gems, Composer) live in
  `~/.runway/` inside the subscription, so they count against its disk quota and the customer
  can delete them.
- **Ruby** has no official prebuilt binaries: install the Plesk Ruby extension (or the
  distribution's `ruby`) and Runway detects it. Debian and Ubuntu ship Bundler of the system Ruby
  only as `bundle3.x`: Runway puts a `bundle` wrapper on the application's `PATH` (and, when no
  Bundler exists at all, the default build installs it into `~/.runway/gems` first). `GEM_HOME`
  is `~/.runway/gems`; the interpreter's bundled gems stay available.
- **PHP**: the PHP built-in server (`php -S`) is TCP only and handles one request at a time;
  install **FrankenPHP** on the toolchains page for Unix sockets, worker mode and Laravel Octane.
  For **Laravel Octane** Runway writes `.runway/Caddyfile` (from Octane's own Caddyfile, rewritten
  before every start) with the Caddy admin endpoint turned off and the site bound to
  `127.0.0.1:$PORT` or the Unix socket, so Octane neither binds every interface nor a second
  (admin) port; `php artisan octane:reload`/`octane:status` therefore do not work (Runway
  restarts the service instead).
- **Java**: give Spring Boot applications at least 384-512 MB of memory and a task limit of
  512 or more; the default start command uses `-XX:MaxRAMPercentage=75`.
- Per-runtime details (version discovery, environment, detection rules, listen options of the
  common frameworks) are in [docs/runtimes](docs/runtimes).

## Listen modes

Every application chooses how the web server reaches it:

| Mode | The application listens on | Variables |
|---|---|---|
| **TCP port** | `127.0.0.1:<port>`, port assigned from the server range | `PORT`, `HOST=127.0.0.1`, `LISTEN_ADDR=127.0.0.1:<port>` |
| **Unix socket** | `/run/runway/<domainId>/app.sock` | `RUNWAY_SOCKET` only: `PORT`, `HOST` and `LISTEN_ADDR` are not set, and the service may not bind any TCP port (`SocketBindDeny=any`) |
| **None (worker)** | nothing: queue consumers, bots, schedulers; no proxy and no listener check | `PORT`, `HOST`, `LISTEN_ADDR` (a port stays reserved) |

`RUNWAY_LISTEN` contains `tcp`, `unix` or `none`; `RUNWAY_APP_ROOT` the application directory.
Check `RUNWAY_SOCKET` first: an application that falls back to `PORT` only when no socket is set
works in both modes. A typical Go program:

```go
if sock := os.Getenv("RUNWAY_SOCKET"); sock != "" {
    ln, err := net.Listen("unix", sock)
    if err != nil {
        log.Fatal(err)
    }
    log.Fatal(http.Serve(ln, handler))
}
log.Fatal(http.ListenAndServe(os.Getenv("LISTEN_ADDR"), handler))
```

> **Security note for shared servers: prefer the Unix socket.** The socket directory belongs to
> the subscription's system user and the web server group (`psaserv`, mode `2750`), so only
> nginx/Apache can connect: other users of the server can neither take over the endpoint nor
> talk to the application directly. In TCP mode the application may only bind its own port
> (`SocketBindAllow=`, systemd 249+) and Runway checks the owner of the listening socket: if
> another user's process holds the port, deployments fail and the status shows it. But any
> local user can connect to `127.0.0.1:<port>`, and processes that Runway does not manage
> (cron jobs, PHP, SSH sessions) could try to grab a port while the application restarts.
> In socket mode Runway checks that `app.sock` is the application's own socket: a symbolic link
> (for example to another application's socket) or any other file is removed and the
> application is stopped until it is started again (state *Stopped: socket replaced*); see
> [SECURITY.md](SECURITY.md) for the remaining window between two checks.

The **proxy mode** decides what nginx forwards: the whole domain (`web`) or one path prefix
(`path`, for example `/api`, the rest stays on the document root). **Static paths** (up to 20
URL prefixes such as `/assets`) are always served by the web server itself from the **document
root**, not from the application directory: `/assets/app.css` is `assets/app.css` in the document
root, so the files must be there. Large files (videos, images, downloads) served this way do not
use the application's memory (see [Memory](#memory)). Let's Encrypt
(`/.well-known/acme-challenge/`) and the Plesk web statistics are never proxied.

## Zero-downtime deployments

By default a deployment restarts the application: the site answers *502 Bad Gateway* while the
new version starts, and a version that crashes on start leaves the site down. With
**Zero-downtime deployments** (domain settings, *Advanced*; for TCP and Unix socket applications,
not for workers) a deployment, a restart, a trigger file and saving the settings work like this
instead:

1. The new version starts in a second instance (a **slot**: `runway-app-<id>-a` or `-b`) next to
   the running one, on its own port or socket (`PORT`, `LISTEN_ADDR` or `RUNWAY_SOCKET` name it;
   `RUNWAY_SLOT` says which slot).
2. Runway waits until it listens and, when a health check path is set, until that path answers
   2xx or 3xx, at most for the **readiness timeout** (default 60 s).
3. The web server's traffic moves to the new version: in **Unix socket** mode by atomically
   re-pointing a root-owned symbolic link (`/run/runway/<id>.sock`, nothing is reloaded); in
   **TCP** mode by rewriting a root-owned include file (`/etc/runway/web/<id>.nginx.conf`) and a
   graceful reload of nginx (or Apache when nginx is off), confirmed by its new worker processes.
4. Requests in flight on the old version may finish for up to the **drain period** (default
   10 s); then the old version stops.

A new version that exits, does not listen or fails its health check in time is stopped; the old
version keeps serving and the deployment is reported as failed with the reason. **Restart in
place** (a button next to *Restart*, `plesk ext runway --restart <domain> -plain`) restarts the
running version the classic way, for example to replace a running but broken instance or to run a
build whose switch failed.

Things to know before turning it on:

- **Both versions run for a short time.** Memory, CPU and task limits apply to each version, so
  the application's usage can double for up to the readiness timeout plus the drain period. Java
  applications should get a memory limit: two JVMs started with `-XX:MaxRAMPercentage=75` and no
  limit both size their heap against the server's memory.
- **The application must tolerate two instances briefly**: database migrations at startup,
  schedulers or cron jobs inside the application, SQLite databases and file locks. Applications
  with an embedded single-writer database or a lock file (bbolt, Badger, LevelDB, Prometheus TSDB,
  SQLite in exclusive mode, pid files) cannot start a second instance: keep the setting off.
- **Listen where Runway tells you.** The application must use `RUNWAY_SOCKET` or `PORT`, not a
  fixed path or port: a configuration that hardcodes `/run/runway/<id>/app.sock` (for example in
  `gunicorn.conf.py`, `config/puma.rb` or a Caddyfile) or a port makes the switch fail.
- **Builds happen in place**, as before: the old version keeps serving while the build replaces
  files under it. Builds that replace files by renaming them are safe (`go build`, `cargo build`).
  Builds that overwrite files a running process uses can disturb the old version until it stops:
  publish .NET applications into a new directory and rename it
  (`dotnet publish -c Release -o publish.new && rm -rf publish.old && { [ ! -d publish ] || mv publish publish.old; } && mv publish.new publish`),
  copy a Java jar to a new name instead of rewriting the running one, and expect interpreted
  applications (Python, Ruby, Bun, PHP) that load modules lazily to see the new dependencies.
- **Long connections** (WebSockets, server-sent events) to the old version are closed when it
  stops; clients reconnect to the new one. In TCP mode an upload that is still running when the
  drain period ends can fail.
- **Unix socket mode is recommended**: its switch needs no web server reload. A TCP switch
  reloads the web server gracefully; if the web server configuration of the server is broken
  elsewhere, the reload fails and the deployment fails with the output of `nginx -t` (the running
  version keeps serving; *Restart in place* runs the new one).

Turning the setting **on** needs no restart of its own: saving switches from the classic
instance to slot `b` once Plesk has regenerated the domain's web server configuration. Turning it
**off** switches back to the classic instance (`runway-app-<id>.service`) the same way, without an
interruption (in TCP mode it may get a new port, which the panel takes over with the next
reconcile, within 10 minutes). Changing the listen mode or the subscription's system user of an
application that uses the setting (also while turning it off) restarts it once, in place, instead
of switching. The status card shows the live slot, the progress of a running
switch and both versions during it; the application log contains both slots' output (each line
names `runway-app-<id>-a` or `-b`).

Customers can turn it on only when the administrator allows it (*Settings*, *Zero-downtime
deployments for customers*); the administrator also caps the readiness timeout (default 120 s)
and the drain period (default 30 s) of every application.

## Memory

The status card and the overview show two figures for a running application:

- **Memory**: the application's own memory: heap, stacks, shared memory, kernel and socket
  buffers, and the files it maps into memory (its program code and libraries, .NET assemblies,
  database files that SQLite or bbolt map).
- **File cache**: the kernel's cache of the other files the application read or wrote. Linux
  charges it to the application's service, so systemd's `MemoryCurrent` (`systemctl status`)
  includes it: an application that serves 1 GB of videos shows about 1 GB more there. The kernel
  frees this cache whenever memory is needed; a memory limit of the application limits the cache
  too, which only means that files are read from disk again, never that the application is
  killed.

An application that serves large static files (videos, images, downloads) can leave them to the
web server: keep them in the document root at their URL path and add the URL prefix to **Static
paths** (domain settings, *Advanced*). The web server (nginx, or Apache) then serves them itself,
and their cache is charged to it instead of the application. The status card suggests this when
the cache is large. In .NET serve files with `app.UseStaticFiles()` or return them as streams
(`PhysicalFile(...)`, `Results.File(path, ...)`, a `FileStream`), not as `byte[]` or
`MemoryStream`: those copy every file into the managed heap, which can grow by gigabytes under
load (up to the garbage collector's heap limit, by default 75 % of the application's memory limit
when it has one).

.NET reads the memory and CPU limits of the application (*Memory*, *CPU* on the domain page) from
its cgroup and sizes its heap and the number of garbage collector heaps by them. On systemd 254
and later (Ubuntu 24.04, Debian 13, EL 10) the unit of an application with such a limit
therefore has `MemoryPressureWatch=off`: the memory pressure watch that systemd turns on by
default adds a second cgroup mount to the service, and .NET then took the whole server for its
own, grew past the limit and kept swapping. An application that ran above 75 % of its limit that
way can now get an `OutOfMemoryException` instead; raise the limit then. The line takes effect
when the application restarts next.

The figures come from the service's cgroup (`memory.stat`). To look at them on the server (with
zero-downtime deployments the unit is `runway-app-<id>-a` or `-b`):

```sh
grep -E '^(anon|file|file_mapped|active_file|inactive_file|shmem) ' \
    "/sys/fs/cgroup$(systemctl show -p ControlGroup --value runway-app-<id>)/memory.stat"
```

The file cache is `active_file + inactive_file - file_mapped`, the memory is `MemoryCurrent` minus
the file cache. With cgroup v1 (older distributions) the file is
`/sys/fs/cgroup/memory<ControlGroup>/memory.stat` and the fields are `total_active_file`,
`total_inactive_file`, `total_mapped_file`, `total_rss`, `total_cache` and `total_shmem`.

## Deploying with Git

Runway watches two trigger files in the application directory (a systemd path unit, active
while the trigger option of the domain is on, which is the default):

| File | Effect |
|---|---|
| `tmp/deploy.txt` | build with the build command, then restart the application |
| `tmp/restart.txt` | restart the application without building |

Any tool that can touch a file deploys: SFTP, `rsync`, SSH from a CI pipeline, or the
**Plesk Git extension**:

1. In *Git*, set the deployment path of the repository to the application directory
   (for example `apps/example.com`).
2. Enable *Additional deployment actions* and enter:

   ```sh
   mkdir -p tmp && touch tmp/deploy.txt
   ```

Every push (automatic deployment) or *Pull updates* (manual) then builds and restarts the
application. The build runs in `runway-deploy-<domainId>.service` as the subscription's user;
its log is on the domain page. When the build fails, the deployment stops before the restart.
A trigger file touched while a deployment runs (two quick pushes) starts another round as soon
as the current one has finished. An application that was stopped with **Stop** is built but
stays stopped.

## Command line

Runway extends the Plesk CLI (`pm_Hook_ApiCli`, administrators only):

```sh
plesk ext runway --list                              # applications and their state
plesk ext runway --status example.com
plesk ext runway --start example.com                 # --stop keeps it stopped
plesk ext runway --restart example.com               # zero-downtime: waits for the switch; -plain restarts in place
plesk ext runway --deploy example.com                # build + restart (a stopped app is only built)
plesk ext runway --enable example.com                # also --disable
plesk ext runway --toolchains                        # installed toolchains per runtime
plesk ext runway --install-toolchain go 1.27.4
plesk ext runway --reconcile                         # converge services with Plesk now
plesk ext runway --check-update                      # ask GitHub for the latest Runway release
plesk ext runway --update                            # update Runway to it (see Updating)
```

## Configuration reference

### Domain settings

| Field | Meaning | Default |
|---|---|---|
| Enabled | build, run and proxy the application | off |
| Runtime | `go`, `rust`, `bun`, `java`, `dotnet`, `python`, `ruby`, `php`, `binary` | |
| Toolchain | installed version of the runtime | |
| Application directory | relative to the subscription's home directory; keep it outside the document roots (the domain page warns) | `apps/<domain>` |
| Listen | `tcp`, `unix`, `none` | per runtime (`tcp` for most) |
| Proxy mode | `web` (whole domain), `path` (one prefix), `worker` (= listen `none`) | `web` |
| Mount path | URL prefix for `path` mode, for example `/api` | |
| Static paths | up to 20 URL prefixes the web server serves from the document root (the files must be there) | |
| Health check path | `GET` with a 2 s timeout, shown as healthy/unhealthy | |
| Build command | runs with `bash -c` in the application directory as the system user | per runtime |
| Start command | runs with `bash -c` in the application directory as the system user | per runtime |
| Trigger files | watch `tmp/deploy.txt` and `tmp/restart.txt` | on |
| Environment variables | `KEY=value` lines; `PORT`, `HOST`, `LISTEN_ADDR`, `HOME`, `USER`, `LOGNAME` and the `RUNWAY_*` variables set by Runway are reserved (except `RUNWAY_SLOT`, which only the units of [zero-downtime](#zero-downtime-deployments) slots get: there Runway's value replaces a variable of that name); the loader variables `LD_PRELOAD`, `LD_AUDIT`, `GCONV_PATH` and `GLIBC_TUNABLES` cannot be set here (put them in the start command, e.g. `LD_PRELOAD=... ./app`) | |
| Memory, CPU, tasks | `MemoryMax`, `CPUQuota`, `TasksMax` of the service; administrators only. Untouched, the application follows the server settings; a value changed on the domain page stays for that application | server settings |
| Zero-downtime deployments | start the new version next to the running one and switch when it is ready (TCP and Unix socket only, see [Zero-downtime deployments](#zero-downtime-deployments)); customers only when the server setting allows it | off |
| Readiness timeout | seconds the new version may take to listen and pass the health check (5 up to the server's maximum) | 60 |
| Drain period | seconds requests in flight may finish on the old version after a switch (0 up to the server's maximum) | 10 |

### Server settings (*Runway > Settings*)

| Setting | Meaning | Default |
|---|---|---|
| Port range | ports assigned to TCP applications | 20000-29999 |
| Build timeout | seconds before a build is stopped | 3600 |
| Memory / CPU / tasks | limits of application services without their own limits (0 = unlimited) | 0 / 0 / 0 |
| Build memory / CPU / tasks | limits of build jobs (the task limit always applies) | 0 / 0 / 4096 |
| Applications per subscription | maximum number of **enabled** applications per subscription, checked when an application is enabled (0 = unlimited) | 0 |
| Check for updates twice a day | ask GitHub for the latest Runway release (see [Updating](#updating)) | on |
| Install updates automatically | install a newer release as soon as a check finds it (requires the check) | off |
| Zero-downtime deployments for customers | customers may turn zero-downtime deployments on (administrators always may) | off |
| Maximum readiness timeout / drain period | upper limits of the two timeouts of every application | 120 / 30 |

### Files on the server

| Item | Location |
|---|---|
| Root helper | `/usr/local/psa/admin/sbin/modules/runway/runway-helper`, stable copy `/opt/runway/bin/runway-helper` used by the units |
| Toolchains | `/opt/runway/<runtime>/...` (`/opt/runway/go/1.27.4`, `/opt/runway/rust/{rustup,cargo}`, `/opt/runway/dotnet`, `/opt/runway/uv/uv`, ...) |
| State, job logs, caches | `/var/lib/runway/{apps,jobs,locks,cache}` (root, 0700); the updater's last check in `/var/lib/runway/cache/update.json` |
| Environment files | `/etc/runway/env/<domainId>.env` (root, 0600) |
| Units | `runway-app-<id>.service`, `runway-deploy-<id>.service`, `runway-deploy-<id>.path`, `runway-job-admin.service`; with zero-downtime deployments the slots `runway-app-<id>-a.service` and `-b.service` (environment files `<id>-a.env`, `<id>-b.env`) and `runway-converge.service` (repairs an interrupted switch at boot) |
| Unix sockets | `/run/runway/<id>/app.sock`; the directory is recreated at boot from `/etc/tmpfiles.d/runway-<id>.conf`. Zero-downtime: `a.sock`, `b.sock` and the root-owned link `/run/runway/<id>.sock` the web server uses |
| Zero-downtime include files (TCP) | `/etc/runway/web/<id>.nginx.conf` and `<id>.apache.conf` (the live port) |
| Per-user caches | `~/.runway/` in the subscription |
| Logs | `/var/log/plesk/panel.log` (PHP), `journalctl -u runway-app-<id>` (applications; with zero-downtime deployments also `-u runway-app-<id>-a -u runway-app-<id>-b`), `/var/lib/runway/jobs/*.log` (builds and toolchain jobs) |

## How it works

```
browser ── Plesk panel (React UI) ── JSON API (PHP, psaadm)
                                          │  JSON on stdin
                                          ▼
                              runway-helper (python3, root)
              ┌──────────────┬────────────┴───────────┬────────────────────┐
              ▼              ▼                        ▼                    ▼
       toolchain jobs   build jobs as the user   app services        nginx/Apache config
       /opt/runway      runway-deploy-<id>       runway-app-<id>     (pm_Hook_WebServer)
```

- **PHP** (running as `psaadm`) validates input, keeps the per-domain configuration in the
  domain settings and calls the root helper with `pm_ApiCli::callSbin`, sending the request as
  JSON on **stdin**: command lines are visible to every user through `ps`.
- **The helper** (python3, standard library only) re-validates every field, renders the units
  and the environment file, drives systemd, installs toolchains in a background job and runs
  builds in `runway-deploy-<id>.service` as the system user with a deadline and limits.
- **nginx** gets one regex `location` per domain from the `pm_Hook_WebServer` hook (the
  technique of Plesk's Docker proxy rules), with exceptions for ACME challenges, web
  statistics and static paths; Apache gets the equivalent `ProxyPass` rules.
- **Reconcile**: Plesk events (domain deletion, rename, system user change, suspension and
  activation, also of whole customer and reseller accounts) and a scheduled task every
  10 minutes converge the services with Plesk.

### Security model

- PHP never runs anything as root directly; the helper trusts nothing it receives.
- Everything that touches customer files (inspecting the project, writing samples, creating
  directories, building) runs in a child process that dropped to the subscription's system
  user, with a deadline and without inherited descriptors, so symlink tricks cannot make root
  read or write foreign files and a customer cannot hang the helper.
- Unit files contain no customer text: the start command reaches `bash -c` through the
  root-only environment file (`ExecStart=/bin/bash -c ${RUNWAY_START_CMD}`), and environment
  values are quoted so they arrive literally. No line of an application unit runs as root, so
  the customer's environment never reaches a root process; loader variables such as
  `LD_PRELOAD` are refused in the environment variables.
- The child processes that inspect customer files have memory, file size and CPU limits, and
  directory listings are capped, so a crafted application directory cannot exhaust the server.
- Services run as the system user with `NoNewPrivileges`, `ProtectSystem=full`, `PrivateTmp`,
  `PrivateDevices`, `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups`,
  `RestrictSUIDSGID`, `RestrictRealtime`, `LockPersonality`, the per-port bind restriction and
  the configured `MemoryMax`/`CPUQuota`/`TasksMax` (with a memory or CPU limit on systemd 254 and
  later also `MemoryPressureWatch=off`, see *Memory*). Builds always have a task limit.
- Suspending a domain, subscription, customer or reseller stops its applications and any
  running build; a deployment re-checks the state before it restarts anything.
- Toolchains are downloaded over HTTPS from the official sources only and verified against the
  checksums those sources publish; archives are extracted without absolute paths, `..` or
  device files.
- Customers need the **Runway applications management** permission. Resource limits can only be
  changed by the administrator and survive the customer removing and re-creating the
  application. Revoking the permission removes access to the page; disable existing
  applications yourself if they must stop.

See [SECURITY.md](SECURITY.md) for the threat model and how to report a vulnerability.

## Uninstalling

Removing the extension (*Extensions > My Extensions*, or
`plesk bin extension --uninstall runway`) stops and deletes all application services and units,
the proxy configuration, the toolchains in `/opt/runway`, `/etc/runway` and all state in
`/var/lib/runway`. **Application files and `~/.runway` caches in the subscriptions are kept.**
Plesk drops an extension's permissions when it is uninstalled: after a reinstall (as opposed to
`plesk bin extension --upgrade`) the **Runway applications management** permission is off for every
plan and subscription, and customers have no access until it is granted again.

## Development

Requirements: [Bun](https://bun.sh) (the only JavaScript runtime needed, no Node.js),
Python 3.8+ and, for the test server, Docker.

### Try it in Docker

The official `plesk/plesk` image runs real systemd, so everything Runway does (services, builds,
nginx) works inside a container. `scripts/plesk-dev.sh` (Linux, macOS, Git Bash on Windows) and
`scripts/plesk-dev.ps1` (PowerShell 7) drive it with the same commands CI uses:

```sh
scripts/plesk-dev.sh up          # start the container and wait for the panel (first run: image download, then a few minutes)
scripts/plesk-dev.sh install     # build dist/runway-<version>-<release>.zip and install or upgrade it (--no-frontend: skip the frontend build)
scripts/plesk-dev.sh login       # one-time administrator login link for http://localhost:18880
scripts/plesk-dev.sh prepare     # subscription gotest.local, customer cust1, Go toolchain, Go sample app
scripts/plesk-dev.sh test        # the CI suites: helper-smoke, api-smoke, customer-smoke, Go part of runtime-e2e
scripts/plesk-dev.sh logs        # panel log and the journal of the Runway units (-f follows the journal)
scripts/plesk-dev.sh shell       # root shell inside the container
scripts/plesk-dev.sh status      # container, extension, Runway units
scripts/plesk-dev.sh down        # remove the container (toolchains and test data are lost)
```

PowerShell: `./scripts/plesk-dev.ps1 up`, `./scripts/plesk-dev.ps1 install -NoFrontend`,
`./scripts/plesk-dev.ps1 logs -Follow` and so on (`prepare` and `test` run the bash test scripts,
on Windows through Git for Windows). The panel answers on http://localhost:18880 (HTTPS on
18443) and the hosted sites on http://localhost:18080 (add `127.0.0.1 gotest.local` to the hosts
file to open the test domain). Environment variables: `CONTAINER` (`runway-plesk`),
`PLESK_IMAGE` (`plesk/plesk:latest`), `PANEL_PORT`, `PANEL_SSL_PORT`, `HTTP_PORT`,
`E2E_RUNTIMES` (`go`), `WAIT_MINUTES` (`25`). The image comes with a trial license (one
subscription, one customer account) and without Ruby.

Behind the scripts is a plain `docker run` with the flags systemd needs:

```sh
docker run -d --name runway-plesk --hostname plesk.runway.test \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock \
  -v /sys/fs/cgroup:/sys/fs/cgroup --cgroupns=host \
  --cap-add SYS_ADMIN --security-opt apparmor=unconfined \
  -p 18880:8880 -p 18443:8443 -p 18080:80 plesk/plesk:latest
docker exec runway-plesk plesk bin admin --get-login-link -relative-url   # open on http://localhost:18880
```

On Windows with Git Bash prefix `docker` commands with `MSYS_NO_PATHCONV=1`.

### Building

```sh
bun install                     # once: @plesk/plesk-ext-sdk (React 18, Plesk UI Library, webpack)
bun run build                   # frontend only -> src/htdocs/index.php + src/htdocs/dist/
bun run dev                     # frontend watch mode
bun run assets                  # after editing assets/logo*.svg: icons, nav logo, row icon, docs/social-preview.png
python build.py                 # frontend build + dist/runway-<version>-<release>.zip (verified)
python build.py --no-frontend   # package the existing frontend build
python build.py --check         # validate the source tree (fails on leftover placeholders)
python build.py --version 1.2.0 # package as another version without editing src/meta.xml
```

Repository layout:

| Path | Content |
|---|---|
| `src/meta.xml`, `src/DESCRIPTION.md`, `src/CHANGES.md`, `src/_meta/` | package metadata, catalog description, changelog, icons and screenshots |
| `src/frontend/` | React sources (plain JavaScript); not packaged |
| `src/htdocs/` | `index.php` and `dist/` are generated by the SDK build (git-ignored) |
| `src/plib/` | PHP: `controllers/ApiController.php` (JSON API), `hooks/`, `library/` (`Modules_Runway_*`), `resources/locales/`, `scripts/` |
| `src/sbin/runway-helper` | the root helper (python3, standard library only, 3.8+) |
| `tests/` | `helper-smoke.sh`, `api-smoke.sh`, `runtime-e2e.sh`, `customer-smoke.sh`, `check_locales.py` |
| `scripts/` | `plesk-dev.sh` and `plesk-dev.ps1`: the local Plesk test server; `render-assets.ts` (`bun run assets`): icons (catalog, Dev Tools, navigation, domain row) and the social preview from `assets/` |
| `assets/` | `logo.svg` (the mark) and `logo-tile.svg` (the mark on its tile), the masters of every rendered icon |
| `examples/` | a minimal application per runtime |
| `docs/` | [DESIGN.md](docs/DESIGN.md) (decisions and contracts), [runtimes/](docs/runtimes), [RELEASING.md](docs/RELEASING.md) |
| `.github/` | CI, CodeQL and release workflows, `scripts/plesk-e2e.sh` (the container driver), Dependabot, issue and pull request templates |

### Tests

```sh
python tests/check_locales.py      # every locale mirrors en-US line for line (keys, placeholders)
scripts/plesk-dev.sh test          # everything CI runs, against the local container
bash tests/api-smoke.sh            # JSON API through the panel (RUNWAY_SMOKE_DEPLOY=1 also deploys)
bash tests/runtime-e2e.sh          # sample app of every runtime, tcp + unix, through nginx; path
                                   # mode, static paths, triggers, worker, suspension, CLI
bash tests/customer-smoke.sh       # customer access with and without the permission (needs the
                                   # customer "cust1" owning gotest.local)
RUNWAY_E2E_RUNTIMES=go bash tests/runtime-e2e.sh   # only the Go part of the matrix (as in CI)
# root helper regression tests (validation, deploy, triggers, hijack detection, socket mode):
docker cp tests/helper-smoke.sh runway-plesk:/root/ && docker exec runway-plesk bash /root/helper-smoke.sh
```

The smoke tests expect a subscription `gotest.local` (system user `gotestuser`) and Go 1.27.4
installed through Runway: `scripts/plesk-dev.sh prepare` (or `.github/scripts/plesk-e2e.sh
prepare`) sets exactly that up. CI runs helper-smoke, api-smoke, customer-smoke and the Go part
of runtime-e2e on every push that changes code and on every pull request (see
[CONTRIBUTING.md](CONTRIBUTING.md)). `helper-smoke.sh` uses the fake domain id 999 and creates
the root-only flag `/var/lib/runway/pause-reconcile` while it runs, so the scheduled reconcile
does not remove its test applications (the flag is honoured for at most one hour). Never edit a
test script while it runs: bash reads scripts incrementally.

## License

[MIT](LICENSE) © 2026 Taiizor
