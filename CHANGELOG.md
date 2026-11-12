# Changelog

All notable changes to Runway are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The Plesk package release number (`-1`, `-2`, ...)
is incremented for packaging-only changes of the same version.

The extension catalog shows `src/CHANGES.md`; keep both files in sync when releasing (see
[docs/RELEASING.md](docs/RELEASING.md)).

## [Unreleased]

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

[Unreleased]: https://github.com/Taiizor/plesk-ext-runway/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Taiizor/plesk-ext-runway/releases/tag/v1.0.0
