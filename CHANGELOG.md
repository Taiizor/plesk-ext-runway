# Changelog

All notable changes to Runway are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The Plesk package release number (`-1`, `-2`, ...)
is incremented for packaging-only changes of the same version.

The extension catalog shows `src/CHANGES.md`; keep both files in sync when releasing (see
[docs/RELEASING.md](docs/RELEASING.md)).

## [Unreleased]

### Added

- Static files from a document root inside the application root work without `chmod -R o+rX` in
  the build command: builds and downloads create files that only the subscription can read (umask
  027), so after every successful build or fetch (before the new version starts) and when the
  document root is changed on the Runway page, Runway makes the files and folders there readable
  for the web server (`o+r` for files, `o+rx` for folders), and lets the web server pass the
  folders between the application root and the document root that a build may create anew
  (`.output` of `.output/public`; `o+x` only). Only for a document root strictly inside the
  application root (with symbolic links resolved; never the application root itself, a folder
  above it or one elsewhere), as the system user, without following symbolic links, skipping
  names that start with `.` (a `.htaccess` the build writes there still needs `chmod o+r`), only
  the subscription's own files, read permission only, at most 200,000 entries and 60 seconds per
  run; the deploy log reports what it changed. The helper keeps a copy of the domain's document
  root in the application's state (`document_root` of `app-apply`, the new command `app-docroot`,
  `apps-list`; Reconcile keeps it in line with Plesk); unit and environment files do not change.
  The form's note under *Document root* says so instead of naming a command. README section
  *Static files and the document root*.

## [1.2.0] - 2026-11-13

Feedback from a production server: Runway in every panel view, the application's real memory,
an opt-in health watch with an optional expected response content, and the domain's document root
on the Runway page, so static files can be served from a folder inside the application. One
behaviour change: on systemd 254 and later, applications with a memory or CPU limit get
`MemoryPressureWatch=off` (see *Changed*).

### Added

- **Runway** in the navigation of the administrator's Power User view, of resellers (*Hosting
  Services*) and of the customer panel (customers with the *Runway applications management*
  permission); the Service Provider view keeps its entry under *Server Management*, and the page
  of a subscription gets no Runway tab.
- Runway's mark among the icons of a domain row in *Websites & Domains* (and the administrator's
  domain list) for domains whose Runway application is enabled, like the Node.js and .NET Toolkit
  icons (Plesk 18.0.41 and later). The mark is mid grey, so it stays visible in the dark theme.
- The application's memory without the file cache: `app-status` (`service` and every zero-downtime
  slot) and `apps-list` report `memory_used_bytes` and `memory_cache_bytes` next to
  `memory_bytes` (unchanged: systemd's `MemoryCurrent`), read from the service's cgroup
  (`memory.stat`, cgroup v2 and v1: the file pages no process maps; mapped files such as program
  code and database files stay with the application's memory); `api/overview` adds
  `memoryUsedBytes` and `memoryCacheBytes`, `plesk ext runway --status` shows both. The status
  card and the overview show the application's memory with the file cache below it, and the status
  card suggests static paths when a web application's file cache is large. README section
  *Memory*.
- Health watch (opt-in per application, *Advanced*, off by default): requests the health check
  path every 30 seconds (10-3600) and restarts the application in place after 3 failed checks in a
  row (1-20), for an application that hangs without crashing (systemd restarts a crashed one by
  itself). A check fails without a 2xx or 3xx answer within 5 seconds. No checks in the first 60
  seconds after a start, during a deployment or for stopped applications; at most 3 restarts within
  an hour, then it only reports. The status card shows the failed checks, the last restart and its
  reason, the application log notes every restart, and `plesk ext runway --status` shows the
  watch. One timer, `runway-health.timer`, serves every application with the watch and exists only
  while one has it on. README section *When an application fails* explains what happens on
  crashes, reboots, limits and hangs.
- Expected response content of the health check (opt-in per application, *Advanced*, right below
  the health check path; needs one, never for workers): besides a 2xx or 3xx status, the answer
  must then contain it. A JSON object such as `{"status":"ok"}` must be contained in a JSON answer
  (its keys with equal values and JSON types, nested objects as subsets, spacing and key order do
  not matter); any other text such as `Healthy` must appear in the answer (case-sensitive). At most
  200 characters. The status card, the health watch and the zero-downtime readiness check use it,
  so a new version whose answer does not match never gets traffic. The helper reads at most 64 KiB
  of the answer within the check's timeout (also when it is sent slowly), decodes a chunked answer
  and never puts the answer into a status text; new health codes `http_match`, `body_mismatch`
  and `body_not_json`. Without the setting the check reads the status line only, as before.
  `api/app` config field `healthMatch`, helper state `health_match`, `plesk ext runway --status`
  shows it on the *Health* line.
- The domain page warns, without blocking the save, while the application root is a document root
  of the subscription (`httpdocs`, the folder of a subdomain) or lies inside one; `api/app` adds
  `domain.documentRoot`, `documentRoots`, `appRootDocumentRoot` and `defaultAppRoot`. The stored
  application root also
  counts when a symbolic link puts it into a document root (`app-inspect` and `app-page` take
  `document_roots` and answer `document_root`, resolved as the system user).
  `plesk ext runway --status` prints the same warning.
- The domain's document root on the Runway page (*Advanced*, right above the static paths, for
  every runtime, hidden for workers): the folder the web server serves the static paths from (and
  in path mode the rest of the site), so the application root can stay outside it, e.g. the
  application root `apps/example.com`, the document root `apps/example.com/wwwroot` and the
  static path `/media`. It is Plesk's setting, never stored by Runway: the form shows Plesk's
  current value and a change goes through `plesk bin site --update <domain> -www-root` (Plesk's own
  checks; Plesk creates a missing folder and regenerates the web server configuration). Runway
  validates the path first (relative, no `.`/`..` segment or segment starting with `-`, at most 255
  characters, inside the home directory with symbolic links resolved by the helper as the system
  user: new helper command `docroot-check`) and afterwards lets the web server pass the directories
  on the way (`o+x` where needed, as the system user: `docroot-access`). Customers need Plesk's
  *Hosting settings management* permission in addition to Runway's; without it the field is
  read-only. The form suggests the usual folder of the runtime (`wwwroot`, `dist`, `public`, ...)
  when it exists (inspection field `public_dirs`) and warns in path mode and when the application
  root lies in the chosen document root. `api/app` adds `documentRootAllowed` and
  `documentRootSuggestions`, `api/app/save` accepts `documentRoot` (changed before the settings are
  saved; a request with only `documentRoot` does not restart the application). The page sends the
  document root only when the field was changed (a change made in Plesk meanwhile is never undone)
  and, when nothing else changed, only it: no build, no restart. A full path inside the home
  directory is taken relative to it; folders on the way that the web server cannot pass are named
  in the save message, and `plesk ext runway --status` prints a *Document root* line. Removing an
  application never changes the document root. README section *Static files and the document
  root*.

### Changed

- **Behaviour change** on systemd 254 and later (Ubuntu 24.04, Debian 13, EL 10): the unit of an
  application with a memory or CPU limit gets `MemoryPressureWatch=off`. systemd's default memory
  pressure watch adds a second cgroup mount to the service, and .NET then did not see the limits:
  it sized its heap and its garbage collector heaps for the whole server, grew past the memory
  limit and kept swapping (4 to 13 times slower in a test with a 1 GiB limit). It now keeps its
  heap within 75 % of the limit, so an application that ran above that can get an
  `OutOfMemoryException` instead; raise its limit then. Takes effect when the application restarts
  next; units without memory or CPU limit and older systemd versions are unchanged.
- The hints of *Application root* and *Static paths* say why the application belongs outside the
  document root (the web server can serve its files there, whenever it does not pass a request to
  the application, so sources and settings files with secrets could be downloaded) and that static
  paths are served from the document root, where their files must be.
- The *Memory* fact of the status card, the memory column of the overview and the zero-downtime
  *Versions* row show the application's own memory instead of systemd's `MemoryCurrent`, which
  includes the page cache of every file the application read (an application serving 1 GB of
  media showed 1 GB more).

### Fixed

- Runway had no entry in the navigation of the Power User view (only the Service Provider view's
  `PLACE_ADMIN_NAVIGATION` was used).
- "Restart in place" looked transparent next to the other buttons of the status card.

## [1.1.0] - 2026-11-13

Opt-in zero-downtime deployments and restarts, and two fixes. Applications that do not turn the
new setting on keep the files and the behaviour of 1.0.0.

### Added

- Zero-downtime deployments (opt-in per application, TCP and Unix socket mode): a deployment, a
  restart, a trigger file or a save starts the new version in a second slot
  (`runway-app-<id>-a`/`-b`) next to the running one, waits until it listens and its health check
  path answers (readiness timeout), switches the web server's traffic to it (Unix socket: a
  root-owned link `/run/runway/<id>.sock` is re-pointed atomically; TCP: a root-owned include file
  and a confirmed graceful reload of nginx or Apache), lets requests on the old version finish
  (drain period) and stops it. A new version that does not become ready never gets traffic: it is
  stopped, the old one keeps serving and the deployment fails with the reason. Interrupted switches
  (job stopped, crash, reboot) are completed or rolled back from where the traffic points, by the
  scheduled reconcile and by `runway-converge.service` at boot. Applications without the setting
  keep the files and the behaviour of 1.0.0.
- "Restart in place" (domain page, `api/app/control {op: restart, plain: true}`,
  `plesk ext runway --restart <domain> -plain`) for applications with zero-downtime deployments;
  `--restart` waits for the switch and `--status` shows the slots and a running switch.
- Server settings: *Zero-downtime deployments for customers* (off by default: customers cannot
  turn the setting on until the administrator allows it) and the maximum readiness timeout and
  drain period (120 and 30 seconds by default).
- The domain page shows whether zero-downtime deployments are on, the progress of a running switch
  and both versions during it; the application log merges the journals of both slots.

### Changed

- The root helper connects to a Unix socket in the customer's socket directory (listener and health
  checks) through an `O_PATH` descriptor of the checked file, so a symbolic link swapped in after
  the check can never make it talk to another socket.
- Saving or re-applying an application keeps the port its service uses; the panel's stored copy
  only counts for a new application. The scheduled reconcile stores the helper's port when the two
  differ, so the web server configuration follows the running service.

### Fixed

- The installation checks that `/usr/bin/python3` is 3.8 or newer, the version the root helper
  needs (an older python3 passed the check before). The message names the version found; a
  python3 that fails, prints no version or does not answer within 10 seconds also stops the
  installation. The hint for a missing python3 fits the distribution: `apt-get` on
  Debian/Ubuntu, `dnf` on AlmaLinux/Rocky/RHEL 9 and newer, the requirements on releases whose
  python3 is older than 3.8 (EL 7 and 8, Debian 10, Ubuntu 18.04), otherwise the package manager
  of the distribution.
- Domain page: "Use the default commands of this runtime" seemed to do nothing when the commands
  already were the defaults (for example the stored commands of a sample application, or right
  after a change of runtime or listen mode, which follows the defaults by itself). A confirmation
  next to the button now shows that the default commands were filled in. When no default start
  command is known (.NET with a solution, several projects or no project yet), the button keeps
  the commands and says so instead of clearing them.

## [1.0.0] - 2026-11-12

First public release. Runway evolves from the private "Go & Rust Toolkit" extension; everything
was renamed to Runway (extension id `runway`, units `runway-*`, paths under `/opt/runway`,
`/var/lib/runway`, `/etc/runway`, variables `RUNWAY_*`).

### Added

- Runtime adapters for Go, Rust, Bun, Java (Eclipse Temurin), .NET, Python (uv-managed
  CPython), Ruby (detected: Plesk Ruby extension and system Ruby), PHP (detected Plesk PHP
  handlers plus managed FrankenPHP) and prebuilt binaries.
- Toolchain management: install, update and remove versions from the official sources with
  checksum verification, cached release lists, a build dependencies installer and a live job log.
- Per-domain applications: runtime, toolchain, application directory, build and start commands,
  environment variables (root-only), hardened `runway-app-<id>.service` units.
- Listen modes `tcp` (127.0.0.1 and a port from the server range), `unix`
  (`/run/runway/<id>/app.sock`, reachable only by the web server group) and `none` (workers).
- Proxy modes `web` (whole domain) and `path` (one URL prefix), static paths served by the web
  server, optional health check path.
- Deployments from the panel, the CLI (`plesk ext runway --deploy <domain>`) and Git through the
  trigger files `tmp/deploy.txt` (build + restart) and `tmp/restart.txt` (restart).
- Sample application for every runtime; deployment of a prebuilt binary or archive from an
  HTTPS URL with optional SHA-256 verification.
- React user interface (Plesk UI Library through `@plesk/plesk-ext-sdk`, built with Bun) with
  overview, toolchains, settings and domain pages; JSON API for the frontend.
- Server settings: port range, build timeout, application and build resource limits, maximum
  number of applications per subscription.
- `manage_runway_apps` permission for service plans and subscriptions.
- Built-in updater: Runway checks the latest GitHub release twice a day (setting, on by
  default), shows a newer version on the overview with a link to its release notes and "Update now", and
  upgrades itself in the administrator's background job after verifying the SHA-256 checksum of
  the release (never a downgrade); optional automatic installation (off by default), "Check now"
  on the overview, `plesk ext runway --check-update` and `--update`, API `api/update`. Every
  release also carries the package as `runway.zip`, so
  `plesk bin extension --upgrade-url https://github.com/Taiizor/plesk-ext-runway/releases/latest/download/runway.zip`
  installs or updates in one command.
- Reconciliation with Plesk on domain deletion, rename, system user change and suspension
  (also of customer and reseller accounts), plus a scheduled reconcile every 10 minutes.
- User interface in every Plesk language (32 locales): English and Turkish by hand, the other
  30 machine-translated with a review pass. In the right-to-left languages (Arabic, Hebrew)
  commands, paths, variables and logs stay left-to-right.
- Examples for every runtime in `examples/`, CI (lint, package, end-to-end tests in the official
  Plesk container), CodeQL analysis, Dependabot and tag-based GitHub releases whose notes are
  generated from this file and the merged pull requests.
- `scripts/plesk-dev.sh` and `scripts/plesk-dev.ps1`: a local Plesk test server in Docker
  (start, build and install, prepare the test subscription, run the CI suites).

### Security

Hardening from the pre-release security review (no released version was affected):

- No line of an application unit runs as root any more: the Unix socket directory is created by
  the root helper and, at boot, by `systemd-tmpfiles` (`/etc/tmpfiles.d/runway-<id>.conf`).
  Before, a customer's environment variables (e.g. `LD_PRELOAD`) reached a root
  `ExecStartPre=+` step in socket mode. The loader variables `LD_PRELOAD`, `LD_AUDIT`,
  `GCONV_PATH` and `GLIBC_TUNABLES` are refused in the environment variables (set them in the
  start command); upgrades re-render every unit and strip such lines from units that cannot be
  re-rendered.
- Socket mode: a socket path replaced by a symbolic link (e.g. to another application's socket)
  or another file is detected on every status request, by the scheduled reconcile and after
  deployments; Runway removes it, stops the application and shows "Stopped: socket replaced"
  until it is started again (see SECURITY.md for the remaining window).
- The child processes that inspect customer files run with memory, file size and CPU limits, and
  directory listings are capped (at most 10 000 entries counted), so a directory with millions of
  files cannot exhaust the server.
- Laravel Octane runs with a Runway Caddyfile: Caddy's admin endpoint is off and the site is bound
  to 127.0.0.1 or the socket (Octane's own default listened on every interface and crash-looped
  under the unit's bind restriction).

### Changed

- Socket mode exports only `RUNWAY_SOCKET` (no `PORT`, `HOST`, `LISTEN_ADDR`; the unit denies
  TCP binds there). The port stays reserved for a switch back to TCP.
- **Stop persists**: a stopped application stays stopped across reboots, deployments, trigger
  files and reconciles until Start, Restart, Build & restart or saving the settings. Deployments
  from the CLI, fetches and trigger files build a stopped application without starting it.
- Admin limits are sent only when changed on the domain page: untouched applications keep
  following the server defaults ("Applies to applications without their own limit").
- Texts produced by the helper (runtime hints, job titles, listener and health details) and the
  API client's errors are translated; Turkish terminology unified ("araç zinciri", "Süreç").
- Overview links the application URL (with the mount path, `https://` when the domain has
  SSL/TLS support), shows a customer-specific first step and, on SELinux servers, the SELinux mode;
  Start/Restart are disabled while a build runs; the fetch button needs saved settings; the
  project card shows inspection errors; deployments of a stopped application are titled
  "Build (application stopped)" (or "Fetch …", "Restart skipped …").

### Fixed

- Toolchain channels (Java "21", Python "3.13", .NET "10.0"): builds a channel may use cannot be
  removed, and installs/updates re-render the apps of the runtime.
- System Ruby on Debian/Ubuntu: `bundle` wrapper for the versioned Bundler; no `GEM_PATH`, so the
  bundled gems stay visible; Rails assets through `bundle exec`; `rackup` is TCP only;
  `config/puma.rb` decides the bind.
- Java: any top-level `.java` file with a main method is detected (also `examples/java-hello`);
  Temurin ids sort by version parts (`27.0.1+8` above `27+37`).
- Rust: the `[[bin]]` of `src/main.rs` names the binary.
- Apache-only servers: WebSockets through `upgrade=websocket` (Apache 2.4.47+).
- A trigger file touched during a deployment starts another round; the deploy unit timeout covers
  fetch plus build, and a killed deployment says why.
- Configurations too long for Plesk's domain setting (5000 characters) are refused instead of
  being truncated; a prebuilt-binary app never keeps a hidden build command; a non-text `env`
  value is an error instead of deleting the variables.
- App units start after local databases, and the scheduled reconcile restarts applications that
  systemd gave up on.
- Post-install registers the scheduled task independently of the other steps and reports apps
  that could not be re-rendered.
- `build.py` checks that `package.json` and the helper's `VERSION` match the package; the
  release workflow fails when the tag and `src/meta.xml` differ. CI runs customer-smoke and the
  Go runtime matrix and fails on every shell syntax error.

[Unreleased]: https://github.com/Taiizor/plesk-ext-runway/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/Taiizor/plesk-ext-runway/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/Taiizor/plesk-ext-runway/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Taiizor/plesk-ext-runway/releases/tag/v1.0.0
