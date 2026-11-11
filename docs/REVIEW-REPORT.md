# Runway — review report (Phase 5)

Fixes of the adversarial pre-release review: 44 confirmed findings (`C0`–`C43`), 4 findings added
by the verifiers (`E0`–`E3`) and 1 undecided finding (`U0`), implemented as decided per finding.
Test server: Docker container `grt-plesk` (Plesk 18.0.82, Ubuntu 24.04, systemd 255, Apache
2.4.58), the same as in Phase 4 ([INTEGRATION-REPORT.md](INTEGRATION-REPORT.md)). Version 1.0.0
is unreleased, so the changes are part of the 1.0.0 notes (CHANGELOG.md "Security", "Changed",
"Fixed"; src/CHANGES.md).

## 1. Findings and status

Severity as confirmed by the review. "Test" names the regression check (HS = tests/helper-smoke.sh,
API = tests/api-smoke.sh, CS = tests/customer-smoke.sh, E2E = tests/runtime-e2e.sh).

| ID | Sev. | Finding | Status | Test |
|---|---|---|---|---|
| C0 | critical | Customer env (`LD_PRELOAD`) reached the root `ExecStartPre=+install` of unix-mode units | **fixed**: no `+`/`!` Exec line in any unit; `/run/runway/<id>` created by the helper (`prepare_start()`, O_NOFOLLOW descriptors, re-applies owner/mode) on every start path and by `/etc/tmpfiles.d/runway-<id>.conf` at boot (+ `runway.conf` for `/run/runway`), removed with the app or when leaving unix mode, uninstall removes all; loader variables refused in PHP and helper; upgrade drops stored loader variables and strips root Exec lines from units it cannot re-render; verified by hand (stop + `rm -rf /run/runway/1` + `--start`, and the boot path via `systemd-tmpfiles --create` + `systemctl start`) | HS (no `+`/`!` line, dir owner/mode, tmpfiles, recreate after removal, LD_* refused, old state upgrade), API (LD_* refused) |
| C1 | high | Unbounded directory listings in the user child, no rlimits | **fixed**: `RLIMIT_AS` 512 MiB, `RLIMIT_FSIZE` 64 MiB, `RLIMIT_CPU` deadline + 5 s after `drop_privileges()`; `os.scandir` loops with caps (80 shown / 500 Java / 2000 .NET + binary, 10 000 counted, `more`) | HS (20 000 files: 10 000 counted, `more`, within the deadline) |
| C2 | high | Laravel Octane default crash-looped (admin endpoint bind denied) | **fixed** as decided, verified for real: Laravel 13 + Octane 2.24 + FrankenPHP 1.13.5 through nginx, tcp and unix (`/` and `/up` 200, health ok) | HS (defaults, generated Caddyfile), E2E (optional `RUNWAY_E2E_OCTANE_ROOT`) |
| E0 | medium | Octane bound all interfaces | **fixed** with C2 (`bind 127.0.0.1`; `ss`: `127.0.0.1:20000` only, no admin listener) | E2E (Octane tcp listener) |
| E1 | medium | Customer can replace `app.sock` with a symlink to another app's socket | **fixed** (detection + containment) as decided; residual window documented in SECURITY.md | HS (symlink → `tampered`, removed, unit stopped + disabled, journal note, apps-list removes a re-created link, Start clears it) |
| C3 | medium | Channel ids (Java `21`, Python `3.13`) vs. toolchain remove | **fixed**: `may_use()` blocks removal of any build a configured channel may use; install/update re-render the apps of the runtime | HS (Java build used through its major cannot be removed) |
| C4 | medium | System Ruby without `bundle` | **fixed**: `bundle`/`bundler` wrappers for `/usr/bin/bundle<X.Y>` on PATH; `gem install --no-document bundler` in the default build only without any Bundler | HS (`bundle install` with the system Ruby) |
| C5 | medium | Config JSON > 5000 chars silently truncated | **fixed**: measured (≤ 4500 characters, error on the longest sent field) and lower caps (appRoot 255, build 1500, start 1000, health 255, static paths 1000 total) | API (too long, static paths total) |
| C6 + E2 | medium/low | Hidden build command of a prebuilt binary; inline errors of hidden fields | **fixed**: form sends `''`, `App::update()` blanks it, error list follows the rendered fields | API (binary keeps no build command) |
| C7 | medium | Unix mode exported `PORT`/`HOST`/`LISTEN_ADDR` | **fixed differently in one detail**: no `PORT`/`HOST`/`LISTEN_ADDR` in unix mode, port kept in the state; `RUNWAY_LISTEN` stays `unix` (not `unix:<path>`): the documented contract (`tcp`, `unix`, `none`) and every check compare it with `unix`, and the path is already in `RUNWAY_SOCKET` | HS (env file in unix mode) |
| C8 | medium | No WebSockets through Apache | **fixed**: `upgrade=websocket` inside `<IfVersion >= 2.4.47>`, plain `ProxyPass` otherwise | API (httpd.conf + `apache2ctl -t`), E2E (real handshake: 101 through nginx and through Apache on 127.0.0.1:7080) |
| C9 | medium | Trigger touched during a deployment was lost | **fixed**: up to 3 rounds while the trigger mtimes moved; without time left a transient `runway-redeploy-<id>` timer starts the deploy unit again | HS (two touches → two build rounds) |
| C10 + C15 | low | Deploy unit timeout too small for fetch + build; silent kill | **fixed**: `TimeoutStartSec = min(1800, bt) + bt + 300`; SIGTERM handler writes the reason | HS (timeout value; stopped deployment says why) |
| C11 | low | `GEM_PATH` hid the bundled gems | **fixed** (no `GEM_PATH`); docs/runtimes/ruby.md corrected | HS |
| C12 | low | Java GA id sorted above its update | **fixed** (`java_key`: feature, interim, update, patch, build) | unit check in the container |
| C13 | low | `rackup` default offered unix | **fixed** (`unix_supported: false`) | HS |
| C14 | low | Rails build via `bin/rails`, leading ` && ` | **fixed** (`bundle exec rails assets:precompile`, joined only after a step) | HS |
| C16 + C38 | low | Java detection only `Main.java`; java-hello undetected | **fixed**: any top-level `*.java` with `static void main` (Main/App first, ≤ 20 files, package-aware class); example and its README use the suggested commands | HS |
| C17 | low | Rust ignored `[[bin]]` for `src/main.rs` | **fixed** (bin of `src/main.rs`, else the single bin, else the package; both TOML parsers record paths) | HS |
| C18 + C43 | low | post-install: task registration in the same try; install errors discarded | **fixed**: task registered first in its own try, per-domain try/catch, helper `errors` printed and logged (exit 0) | HS (reapply-all reports per-app errors) |
| C19 | low | Non-string `env` wiped the variables | **fixed** (`errorInvalidValue` on `env`) | API |
| C20 | low | Project card showed "empty" on inspection errors | **fixed** (unavailable + error text) | browser check |
| C21 | low | Detected runtimes hid the release error/Reload | **fixed differently in one detail**: the "Installable versions" panel shows when the list has entries *or* loading it failed (always rendering it would show an empty install control for Ruby, which has nothing installable) | browser check |
| C22 | low | Admin save pinned the limits | **fixed**: limits sent only when changed; hints "Applies to applications without their own limit" | browser check |
| C23 | low | API client errors in English | **fixed** (`Common.requestFailed`, `Common.unexpectedResponse` through the page's translate) | check_locales |
| C24 | low | Helper texts English only | **fixed**: `hint_key`/`install_help_key`, job `title_key` + `title_params`, `listener_code`/`health_code` + params, translated with English fallback; helper errors stay English | check_locales, browser check |
| C25 + C26 | low | Turkish terminology | **fixed**: "araç zinciri" everywhere (server locale, meta.xml), "Süreç", "URL yolu", "FrankenPHP sürümü", `Overview.state.failed` = "Başarısız"; "arka plan işçisi" kept (already used consistently everywhere); both tr-TR files re-read and smoothed | check_locales |
| C27 | low | "(1 files)" | **fixed** (`messageSampleWrittenOne`) | API (single-file sample message) |
| C28 | low | Overview linked the site root in path mode | **fixed** (`appUrl`; no link for workers) | CS (appUrl present), browser check |
| C29 | low | Customers told to use Toolchains | **fixed** (`Overview.emptyStep1Customer`) | browser check |
| C30 | low | Fetch offered before the first save | **fixed** (disabled + hint) | browser check |
| C31 | low | Start/Restart during a build | **fixed** (disabled + hint) | browser check |
| C32 | low | Help: LISTEN_ADDR without "(TCP mode)" | **fixed** (help texts per mode) | check_locales |
| C33 | low | `started_at` unparsable outside UTC | **fixed** (`systemctl show` with `TZ=UTC`, `started_iso`) | browser check |
| C34 | low | Sample toast ignored `buildError`/build log | **fixed** (same handling as save) | browser check |
| C35 + E3 | low | CI `bash -n` loop never failed; `**.md` skipped packaged markdown | **fixed** (loop with exit code; `paths` filter excludes only `docs/**`, root `*.md`, `LICENSE`) | workflow YAML parsed |
| C36 | low | CONTRIBUTING claimed suites CI never ran | **fixed**: CI driver creates `cust1` in `prepare` when the license allows it and runs customer-smoke (skipped otherwise) and the Go part of runtime-e2e (`RUNWAY_E2E_RUNTIMES=go`); CONTRIBUTING lists the exact suites | Go part measured below |
| C37 | low | Screenshot names in RELEASING/README | **fixed** (real file names; README shows three screenshots) | — |
| C39 | low | ruby-hello README vs. `-b` default | **fixed** (`config/puma.rb` → no `-b`) | HS |
| C40 | low | Versions not checked | **fixed**: `build.py` compares `package.json` and the helper's `VERSION` with the package; release fails on tag/meta mismatch | `build.py --check` with a wrong `VERSION` fails |
| C41 | low | Apps failed for good after the start limit (DB not up at boot) | **fixed**: `After=… mariadb.service mysql.service postgresql.service`; the scheduled reconcile runs `recover` (reset-failed + start) for enabled, not suspended, not stopped apps systemd gave up on. **Detection differs from the decision's wording**: systemd 255 keeps `Result=exit-code` when *automatic* restarts hit the limit (verified), so `apps-list` reports `start_limit_hit` = failed and (`Result=start-limit-hit` or `NRestarts` ≥ 10) | HS (detection, recover, never for stopped apps) |
| C42 | low | Stop was not persisted | **fixed** as decided: Stop = `disable --now` + `stopped`; Start/Restart/"Build & restart"/save clear it; CLI deploys, fetches and trigger files build but do not start; reconcile never starts it; UI hint "stays stopped until you start it" | HS, API, CS, E2E (CLI) |
| U0 | low | SELinux on EL9 untested | **documented** as decided (README Requirements, SECURITY checklist) + server fact with a warning when enforcing; **not tested** (no EL9 host available) | — |

No finding was left unfixed.

## 2. Notes on the implementation

- **C0**: `prepare_start(state, pw)` is the one place that prepares a start: socket directory
  (and removal of a stale socket of a previous system user), plus runtime hooks (Octane's
  Caddyfile). It runs in `app-apply` (when it starts the unit), `app-action start|restart|recover`,
  the deploy job before its restart and, for directories only, in `install`/`reapply-all`. A
  plain `systemctl start` by an administrator works after a reboot (tmpfiles); after manually
  deleting `/run/runway/<id>` use `plesk ext runway --start` or `systemd-tmpfiles --create`.
- **E1**: containment removes the entry as root through a directory descriptor (unlink never
  follows a link) before *and* after stopping the unit, and a link that reappears while the app is
  marked tampered is removed again at every check. A tampered app is also `stopped`.
- **C1**: the file-size limit is 4 × 500 MB for the fetch child (downloads and extraction); the CPU
  limit follows each call's deadline.
- **C2**: Octane probes the HTTP and the admin port with `fsockopen()` on 127.0.0.1 before it
  starts; `--admin-port=$PORT` makes both probes hit the application's own (free) port, and in
  unix mode `--host=localhost` skips the probe. The Caddyfile is generated from the project's own
  Octane stub (fallback: a copy of the 2.24 stub). `octane:reload`/`octane:status` need the admin
  API and are documented as unavailable.
- **C42**: "Build & restart" in the panel sends `start: true` (explicit start); the CLI's
  `--deploy`, fetches and trigger files do not.
- The Turkish panel UI could not be opened in grt-plesk (the trial license does not allow the
  `tr-TR` locale); Turkish strings were checked with `check_locales.py`, `php -l` and by reading.

## 3. Test results

Final run with the final package (section 5), installed with `plesk bin extension --upgrade` (no
uninstall), suites one after another from frozen copies. A pre-final run of the same build
through `.github/scripts/plesk-e2e.sh smoke` (the CI path: helper-smoke, api-smoke, customer-smoke,
Go matrix) was green except the new Apache WebSocket check, which asked Apache's plain HTTP vhost
(it redirects to HTTPS); the check now uses the HTTPS vhost on 127.0.0.1:7081.

| Suite | Result |
|---|---|
| tests/helper-smoke.sh | 133 passed, 0 failed (88 before Phase 5; 45 new checks) |
| tests/api-smoke.sh (`RUNWAY_SMOKE_DEPLOY=1`) | 83 passed, 0 failed, 0 skipped (twice; 72 before) |
| tests/customer-smoke.sh | 20 passed, 0 failed (16 before) |
| tests/runtime-e2e.sh, Go part (`RUNWAY_E2E_RUNTIMES=go`, what CI runs) | 20 passed, 0 failed in 102 s (also passed through `plesk-e2e.sh smoke` in the pre-final run) |
| tests/runtime-e2e.sh, full matrix + Laravel Octane + features | 38 passed, 0 failed (30 before): 17 runtime × listen cases, path/static/triggers/worker/suspend, CLI incl. Stop persistence, WebSocket 101 through nginx and Apache, Octane tcp + unix |
| tests/check_locales.py | 74 server keys, 303 app keys, 2 locales, 0 warnings, 0 errors |
| lint: `bun install --frozen-lockfile`, `bun run build`, pyflakes, Python 3.8 grammar, `bash -n`, `php -l` 7.4 + 8.2 (29 files) | clean |
| `python build.py --strict`, `--check`, `--verify` | OK |
| browser (headless Chrome): overview, toolchains (PHP tab), settings, domain (running, stopped, advanced, drawers) | rendered, no console errors |

## 4. Remaining known risks

Kept in sync with [INTEGRATION-REPORT.md](INTEGRATION-REPORT.md) section 8.

| Severity | Risk |
|---|---|
| Medium | Socket mode: the socket directory belongs to the customer, so a customer with shell access can re-create a symbolic link to another application's socket between two checks (at most the status polling interval with the page open, else up to 10 minutes). Requests for the customer's own domain could reach the other backend during that window. Documented in SECURITY.md. |
| Medium | TCP mode: every local user can connect to `127.0.0.1:<port>` and bypass nginx (by design, documented). |
| Medium | Cross-tenant access was only tested with an unknown site id (the trial license allows one subscription). |
| Low | SELinux enforcing (AlmaLinux/RHEL 9) is untested; README documents the expected booleans/policy. |
| Low | Health checks only report; Reconcile restarts only applications that systemd gave up on. |
| Low | Fetch downloads need direct internet access (no proxies on purpose). |
| Low | `api/app/save` does not reject `listen: unix` with a Plesk PHP and a custom start command (the UI prevents it; the deploy reports a missing listener). |
| Low | Laravel Octane under Runway has no admin API: `octane:reload`/`octane:status` do not work (restart the service). |
| Low | Opening an extension page by URL keeps Plesk's last subscription context in the breadcrumbs (Plesk behaviour). |
| Low | The trial license of the container allows neither a second subscription nor the `tr-TR` panel locale: the Turkish UI was checked through the locale files only. |
| Info | `uninstall` deletes every toolchain in `/opt/runway`; the helper supports `keep_toolchains`, the uninstall script does not use it. |

## 5. Package

First final package (verified independently, see section 6 for the current one):
`dist/runway-1.0.0-1.zip`, 435 452 bytes, SHA-256
`be63affee6ae608a70bb94445e25f7c195c97e716111a9030f5055d7724cd473` (`python build.py --strict`,
`--verify` OK). Installed in grt-plesk with `--upgrade`: the installed helper is identical to the
packaged one, one scheduled reconcile task, no Runway errors in `/var/log/plesk/panel.log`, no unit
with a root Exec line. Afterwards `gotest.local` runs the Go example in Unix socket mode again
(health `/healthz` healthy). Screenshots refreshed: `docs/screenshots/admin-settings.png`,
`admin-settings-dark.png`, `admin-domain-advanced.png`, `customer-domain-advanced.png` (changed
hints); the catalog screenshots `src/_meta/screenshots/` look the same and were kept.

## 6. Post-verification fixes

An independent verification of the package above on a fresh uninstall → install path confirmed
every claim of this report (helper-smoke 133, api-smoke 83, customer-smoke 20, runtime-e2e 38, all
passed; the package was byte-reproducible) and found five low nits, fixed afterwards:

1. **Title of deployments of a stopped application.** They kept "Build & restart" although nothing
   restarts. The helper now chooses the title when the job starts: `deploy_build_only` "Build
   (application stopped)", `deploy_restart_skipped` "Restart skipped (application stopped)",
   `deploy_fetch_only` "Fetch (application stopped)" (translated in both app locales); the fetch
   drawer says that a stopped application is only updated (and built). helper-smoke checks the
   title keys of a restart, a build and the following "Build & restart" (`deploy_restart`).
2. **DESIGN §5.2 Ruby row** still named `GEM_PATH`: now `GEM_HOME` only (no `GEM_PATH`).
3. **DESIGN §10 and §2**: CI's e2e job runs helper-smoke, api-smoke, customer-smoke and the Go part
   of runtime-e2e; the layout lists `tests/customer-smoke.sh` and `tests/runtime-e2e.sh` and no
   longer the non-existent `src/var/README` (locale loaders described as they are).
4. **Permission after a reinstall**: README "Uninstalling" says that Plesk drops the extension's
   permissions on uninstall, so after a reinstall (unlike `--upgrade`) customers need the
   **Runway applications management** permission granted again. SECURITY.md has no matching
   section and was not changed.
5. **https links**: the Plesk API has `pm_Domain::hasSsl()` ("SSL support for web hosting";
   checked by reflection on Plesk 18.0.82, used with a `method_exists` guard). `url` and `appUrl`
   of `api/overview`, `api/app` and the CLI now use `https://` when it is true, and the domain
   page's "Open site" link uses `appUrl`. api-smoke compares the overview URL with the
   subscription's "SSL/TLS support" setting. While checking the overview, the server fact
   "SELinux" was found to show an empty "—" row on servers without SELinux; it is now shown only
   when SELinux is present.

Checks: `bun run build`, `python build.py --strict` / `--check` / `--verify`, check_locales
(74 server keys, 306 app keys, 0 errors), pyflakes, Python 3.8 grammar, `bash -n`, `php -l` 7.4 and
8.2 (29 files): clean. Installed with `--upgrade` in grt-plesk (installed helper identical to the
packaged one), then from frozen copies, one after another:

| Suite | Result |
|---|---|
| tests/helper-smoke.sh | 135 passed, 0 failed (2 new title checks) |
| tests/api-smoke.sh (`RUNWAY_SMOKE_DEPLOY=1`) | 84 passed, 0 failed, 0 skipped (1 new https check) |
| tests/customer-smoke.sh | 20 passed, 0 failed |

runtime-e2e was not repeated: neither WebConfig, nginx/Apache snippets nor unit rendering changed.
Afterwards `gotest.local` serves the Go example in Unix socket mode again (`/healthz` healthy) and
`cust1` has the permission. The screenshots in `docs/screenshots/` still show the `http://` link in
the overview; nothing else of the captured pages changed.

Current package: `dist/runway-1.0.0-1.zip`, 436 059 bytes, SHA-256
`9198db1d77968507cc38bbbebf74a30094bb3523f67ba85e0183527a6a07c87d`.
