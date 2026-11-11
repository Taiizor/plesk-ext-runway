# Runway — integration report (Phase 4)

Integration of the four Phase 3 work packages (3a helper, 3b PHP, 3c frontend, 3d repository
hygiene) into one consistent, packaged and verified extension. Test server: Docker container
`grt-plesk` (`plesk/plesk`, Plesk 18.0.82, Ubuntu 24.04.5, systemd 255, Python 3.12.3), panel on
`http://localhost:18880`, subscription `gotest.local` (domain id 1, system user `gotestuser`,
owned by the customer `cust1`), nginx on `172.17.0.2`.

Final package: `dist/runway-1.0.0-1.zip` (built with `python build.py --strict`, verified by
`build.py`; `htdocs/index.php` loads `dist/main.js?v=1.0.0-1.<hash>`).

## 1. Build, lint and packaging

| Check | Result |
|---|---|
| `bun install --frozen-lockfile` | no changes (Bun 1.4.4, no Node.js) |
| `bun run build` | compiled successfully |
| `python build.py --strict` / `--check` | built and verified / source tree OK (only note: no catalog screenshots, now added) |
| `python -m pyflakes src/sbin/runway-helper build.py tests/check_locales.py` | clean |
| Python 3.8 grammar check of the helper (`ast.parse(..., feature_version=(3, 8))`) | clean |
| `bash -n tests/*.sh .github/scripts/*.sh` | clean |
| `python tests/check_locales.py` | 70 server keys, 258 app keys, 2 locales, 0 errors |
| `php -l` (src + examples) in `php:7.4-cli` and `php:8.2-cli` | clean |

## 2. Installation in the container

| Step | Result |
|---|---|
| `plesk bin extension --uninstall runway` | removed: units, `/opt/runway`, `/var/lib/runway`, `/etc/runway`, scheduled task, proxy snippets of `gotest.local` |
| `plesk bin extension --install dist/runway-1.0.0-1.zip` | installed: layout created, helper copy `/opt/runway/bin/runway-helper`, one scheduled task (`reconcile.php`, Plesk's `EVERY_10_MIN`) |
| `plesk bin extension --upgrade` with the same zip (repeated after every fix) | idempotent: still one scheduled task, units re-rendered, no warnings |
| `/var/log/plesk/panel.log` | no PHP errors, warnings or notices from Runway; only the expected "Session token has expired" entries of the CSRF tests of `api-smoke.sh` |

Toolchains other than Go were restored from a backup after the reinstall (uninstall deletes
`/opt/runway`); Go 1.27.4 was installed fresh through the helper (`plesk-e2e.sh prepare`).

## 3. Automated tests

| Suite | Result |
|---|---|
| `tests/helper-smoke.sh` (in the container, through `plesk-e2e.sh smoke`) | 88 passed, 0 failed (incl. bun, python, FrankenPHP, Plesk PHP, system Ruby, Go, Java 21, .NET samples in tcp and unix, worker, fetch, reconcile pause flag) |
| `tests/api-smoke.sh` with `RUNWAY_SMOKE_DEPLOY=1` | 72 passed, 0 failed, 0 skipped |
| `tests/customer-smoke.sh` (new) | 16 passed, 0 failed |
| `tests/runtime-e2e.sh` (new) | 30 passed, 0 failed (17 runtime × listen cases + 5 feature groups) |
| `.github/scripts/plesk-e2e.sh prepare` / `smoke` / `diagnostics` against `grt-plesk` | work locally after the Git Bash path fix (section 5) |

## 4. End-to-end matrix

Through the panel API (`api/app/sample` with `force`, `api/app/save`, `api/app/status`,
`api/app/logs`) and nginx over HTTPS (`curl -k --resolve gotest.local:443:<container ip>`, run
inside the container), health path `/`, every case in a fresh application root:

| Runtime | Listen | Toolchain | Deploy | Health | Response through nginx |
|---|---|---|---|---|---|
| go | tcp | 1.27.4 | succeeded | healthy | Hello from Go go1.27.4 on Runway |
| go | unix | 1.27.4 | succeeded | healthy | Hello from Go go1.27.4 on Runway |
| rust | tcp | stable (1.99.1) | succeeded | healthy | Hello from Rust on Runway |
| rust | unix | stable | succeeded | healthy | Hello from Rust on Runway |
| bun | tcp | latest (1.4.4) | succeeded | healthy | Hello from Bun 1.4.4 on Runway |
| bun | unix | latest | succeeded | healthy | Hello from Bun 1.4.4 on Runway |
| python | tcp | 3.13.18 (uv) | succeeded | healthy | Hello from Python 3.13.18 on Runway |
| python | unix | 3.13.18 | succeeded | healthy | Hello from Python 3.13.18 on Runway |
| php | tcp | plesk-8.4 (`php -S`) | started (no build) | healthy | Hello from PHP 8.4.27 on Runway |
| php | tcp | frankenphp-1.13.5 | started | healthy | Hello from PHP 8.5.12 on Runway |
| php | unix | frankenphp-1.13.5 | started | healthy | Hello from PHP 8.5.12 on Runway |
| php | unix | plesk-8.x | not offered | — | `php -S` cannot use a socket: the UI forces TCP, the API answers a `listen` field error |
| java | tcp | 21.0.13+9 (Temurin) | succeeded | healthy | Hello from Java 21.0.13 on Runway |
| java | unix | 21.0.13+9 | succeeded | healthy | Hello from Java 21.0.13 on Runway |
| dotnet | tcp | 10.0.404 and 11.0.100 | succeeded | healthy | Hello from .NET 10.0.15 / 11.0.0 on Runway |
| dotnet | unix | 10.0.404 and 11.0.100 | succeeded | healthy | Hello from .NET 10.0.15 / 11.0.0 on Runway |
| ruby | tcp | 3.4.9 (Plesk Ruby) | started | healthy | Hello from Ruby 3.4.9 on Runway |
| ruby | unix | 3.4.9 (Plesk Ruby) | started | healthy | Hello from Ruby 3.4.9 on Runway |
| ruby | tcp/unix | system (3.2.3) | helper-smoke | healthy | Hello from Ruby 3.2.3 |

Ruby detection: the Plesk Ruby extension's 3.4.9, 3.3.10, 3.2.10 and the system Ruby
(`/usr/bin/ruby` 3.2.3, id `system`) are all listed. "started" = no build command, the service
is restarted directly and the test waits for the listener.

Features (Go sample on `gotest.local`, `tests/runtime-e2e.sh`):

| Feature | Result |
|---|---|
| Path mode `/api` with static path `/api/static` | `/api/hello` from the app, `/` from the document root (Plesk default page), `/api/static/s.txt` from the document root |
| Web mode with static path `/assets` | `/` from the app, `/assets/a.txt` from the document root |
| `tmp/restart.txt` (touched as the system user) | service restarted (new start time, listener ok) |
| `tmp/deploy.txt` | deploy job `source: trigger file` succeeded |
| Worker (`mode: worker`, `listen: none`) | service active, listener `worker`, no Runway snippet in nginx.conf, site served from the document root |
| `plesk bin subscription --webspace-off` / `--webspace-on` | service stopped (`suspended: true`) / started again, nginx serves the app |
| CLI `--list`, `--status`, `--restart`, `--deploy` | exit 0, `--deploy` waits for "succeeded" |
| Fetch from URL (`api-smoke.sh`, `python3 -m http.server` in the container + `/etc/runway/allow-insecure-fetch`) | job succeeded, binary serves `/api/x` through nginx; wrong SHA-256 fails the job; `http://` without the flag → `url` field error "Only https:// URLs can be downloaded." |
| Sample into a non-empty root without `force` | `force` field error; the drawer shows "Overwrite existing files" and enables Create only when it is checked |
| `maxAppsPerSubscription` | `api-smoke.sh`: enabling a second app of the subscription → `enabled` field error; saving an already enabled app is allowed |

Customer `cust1` (`tests/customer-smoke.sh`, permission toggled with
`subscription_settings -ext_permission_runway_manage_runway_apps`):

| Check | Result |
|---|---|
| Domain page and `api/app` with the permission | allowed; `isAdmin: false`, no limits fields, no toolchain usage lists |
| `api/overview` | only the customer's domains, `server: null` |
| `api/toolchains`, `api/settings`, `api/job`, POST `settings`/`toolchain`/`build-deps` | refused (access denied) |
| `api/app/control restart` | allowed with the permission |
| Admin-only limits in `api/app/save` | ignored for customers (limits unchanged) |
| Without the permission | `api/app` and `api/app/control` → "Access denied.", the domain disappears from the overview; the page shows "Access denied." |

## 5. Fixed in Phase 4

Cross-agent issues from the Phase 3 reports:

1. **Fetch scheme**: PHP accepted `http://` while the helper only downloads `https://`. PHP is now
   https-only with the field error `errorFetchHttps`; `http://` is accepted only when the helper
   reports its root-only test flag (`info` → `fetch_insecure`).
2. **Sample overwrite**: the UI never sent `force`, so a non-empty root failed with a generic
   error. The helper now returns machine-readable error codes (`HelperError(code=...)`, kept
   through `call_as_user` and emitted as `"code"`); PHP maps `not_empty` to the field `force` and
   `unix_unsupported` to `listen`; the drawer asks for "Overwrite existing files" (Create disabled
   until checked) and sends `force`. The non-empty check of the UI ignores `tmp/` like the helper.
3. **Unix sockets with PHP's built-in server**: runtime metadata `unix_toolchain_re` (PHP:
   `^frankenphp-`) and per-listen/per-toolchain defaults (`defaults[rt].variants`) from
   `app-page`. The settings form forces TCP and explains why when the default command cannot use
   a socket; build/start commands now follow changes of runtime, listen mode and toolchain (they
   only followed the runtime before, so switching Python/Ruby/PHP to a socket kept the TCP
   command). The sample drawer hides "Unix socket" when no installed toolchain supports it; the
   helper refuses such a sample, and `api/app/sample` lets the helper pick FrankenPHP instead of a
   configured Plesk PHP for a socket sample.
4. **Stale `main.js` after upgrades**: `build.py` patches the packaged `htdocs/index.php` to
   `dist/main.js?v=<version>-<release>.<sha256 prefix of main.js>`; `--verify` checks the
   reference against the packaged bundle.
5. Stale SDK documentation path in `extension.config.js` fixed; the stray `NUL` file deleted.
6. **DESIGN.md** §5.1, §6, §7, §9, §10 updated to the code (context limits, overview fields,
   `appUrl`, sample/fetch payloads and errors, `app-status` fields incl. `health`,
   `health_detail`, listener `worker`, `app-page` defaults/variants with `unix_supported`,
   toolchain entry fields `kind`/`version`, `releases` answer, error `code`, test switches, CLI
   flags and exit codes, cache buster).
7. **Reconcile vs. helper tests**: `apps-list` reports `reconcile_paused` while the root-only flag
   `/var/lib/runway/pause-reconcile` is younger than one hour; `Modules_Runway_Reconcile` then
   changes nothing (CLI `--reconcile` says so). `helper-smoke.sh` creates/removes the flag (trap)
   and tests that a stale flag is ignored. Documented in DESIGN §7, README, SECURITY.md.
8. **DNS rebinding in fetch**: the download now resolves once per connection and connects to the
   address it checked (custom `http.client` connection factory for http/https, TLS still verifies
   the host name), proxies are disabled, redirects are re-checked. Documented in SECURITY.md and
   DESIGN §7.
9. **README claims**: CLI flags, listen `none`, path mode, sample/fetch and "a failed build does
   not restart the app" were correct. `maxAppsPerSubscription` counts *enabled* applications
   (wording fixed). The Java default start command did **not** use `-XX:MaxRAMPercentage=75`:
   the helper now does (as researched in docs/runtimes/java.md and documented in README and the
   example).

Found during integration:

10. `.github/scripts/plesk-e2e.sh`: `docker cp` failed in Git Bash (`/e/...` path with
    `MSYS_NO_PATHCONV=1`); `ROOT` now uses `pwd -W` when available.
11. `tests/api-smoke.sh` failed 4 checks on a fresh server (CI!): the fetch validation and CLI
    `--list`/`--status` checks assumed a configured app, but the deployment ran last. The deploy
    section now runs first; checks that need an app are skipped when there is none. New check:
    `http://` is refused.
12. `api/overview` sent the server facts (OS, helper version, build tools) to customers (the UI
    only hid them): now administrators only.
13. Deployments started by trigger files kept the queue time of the previous panel job: the
    helper now sets `queued_at`/`queued_epoch` for them.
14. Prebuilt-binary detection listed any file with an executable bit (`README.md`, `go.mod`
    copied from Windows): only ELF binaries and scripts with a shebang count now.
15. Dark theme: Plesk inverts the whole page (`filter: invert(0.9) hue-rotate(180deg)`), which
    turned the dark log viewer light grey; it is inverted back.
16. Secondary texts (toolchain version in the overview, "Not used", "No files", "Nothing
    detected") used the blue `info` intent and looked like links: now `muted`.
17. New tests: `tests/runtime-e2e.sh` (runtime × listen matrix and features through nginx) and
    `tests/customer-smoke.sh` (customer permission checks).
18. `examples/go-hello` printed `127.0.0.1:<PORT>` also in Unix socket mode; it now shows the
    socket it listens on.

## 6. Screenshots

`docs/screenshots/`: admin overview, toolchains (Go, PHP, Ruby tabs), settings, domain page
(basic, advanced, sample drawer, fetch drawer) in the light theme; overview, toolchains, domain
and settings in the dark theme; customer overview, domain, advanced section and "Access denied"
without the permission. Catalog screenshots (1024×768): `src/_meta/screenshots/1.png` (domain
page), `2.png` (toolchains), `3.png` (overview). Captured with headless Chrome (puppeteer-core)
with the trial-license banner hidden.

## 7. Final regression run

One uninterrupted run with the final package (`plesk-e2e.sh smoke`, then `customer-smoke.sh`,
`runtime-e2e.sh`, then `api-smoke.sh` again to restore the Go app of `gotest.local`):

| Suite | Result |
|---|---|
| helper-smoke | 88 passed, 0 failed |
| api-smoke (`RUNWAY_SMOKE_DEPLOY=1`) | 72 passed, 0 failed, 0 skipped (twice) |
| customer-smoke | 16 passed, 0 failed |
| runtime-e2e | 30 passed, 0 failed |

Afterwards the final zip was installed once more with `--upgrade`: the installed helper is
identical to the packaged one, one scheduled task, `gotest.local` answers
`Hello from Go go1.27.4 on unix:/run/runway/1/app.sock (gotest.local via https)` (Go example
in Unix socket mode, health `/healthz` healthy), the customer `cust1` has the permission.

Package: `dist/runway-1.0.0-1.zip`, 416 890 bytes (incl. three catalog screenshots), SHA-256
`d9af78b636ac2f0be85caa185195976363778bda6ca9f64cfa69c453ecc66acb`.

Lesson for test runs on Windows: stopping a background `bash script.sh` from the agent tooling
does not kill the script, and bash reads scripts incrementally, so editing a running script
executes garbage. Two overlapping matrix runs produced spurious failures before this was
understood; the final runs used frozen copies of the scripts.

## 8. Remaining known issues and risks (by severity)

Updated after the Phase 5 review fixes ([REVIEW-REPORT.md](REVIEW-REPORT.md), section 4 is the
same list). The Phase 4 risk "api/app/save does not reject listen: unix with a Plesk PHP and a
custom start command" is unchanged; Phase 5 added the socket-check window and the Octane note.

| Severity | Issue |
|---|---|
| Medium | Socket mode: the socket directory belongs to the customer, so a customer with shell access can re-create a symbolic link to another application's socket between two checks of the helper (status polling while the domain page is open, else up to 10 minutes until the scheduled reconcile). Requests for the customer's own domain could reach the other backend during that window; documented in SECURITY.md. |
| Medium | TCP mode: every local user can connect to `127.0.0.1:<port>` and bypass nginx (by design, documented; Unix sockets are recommended and offered for every runtime except PHP without FrankenPHP). |
| Medium | Cross-tenant access could only be tested with an unknown site id: the trial license of the container allows one domain, so no second subscription could be created. The check (`Access::canManage`: `hasAccessToDomain` + `hasPermission` for every domain action, admin role for admin actions) was reviewed. |
| Low | SELinux enforcing (AlmaLinux/RHEL 9) is untested; README documents the expected boolean/policy and the overview shows the mode. |
| Low | Health checks only report; Reconcile restarts only applications that systemd gave up on (start limit), never stopped ones. |
| Low | Fetch downloads need direct internet access: proxies are disabled on purpose (the public-address check must apply to the real peer). |
| Low | `api/app/save` does not reject `listen: unix` with a Plesk PHP and a custom start command; the UI prevents it, a direct API call would get a failed listener check at deploy time. |
| Low | Laravel Octane runs without Caddy's admin API under Runway: `octane:reload`/`octane:status` do not work (restart the service instead). |
| Low | Opening an extension page by URL keeps Plesk's last subscription context in the breadcrumbs (Plesk behaviour; the navigation entry shows `Home > Extensions > Runway`). |
| Low | The trial license of the container allows neither a second subscription nor the `tr-TR` panel locale: the Turkish UI was checked through the locale files only. |
| Info | `uninstall` deletes every toolchain in `/opt/runway` (several GB re-download); the helper supports `keep_toolchains`, the uninstall script does not use it. |
