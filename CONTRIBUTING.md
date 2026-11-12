# Contributing to Runway

Thanks for helping! Bug reports, runtime notes, fixes and new runtime adapters are welcome.

## Before you start

- Read [docs/DESIGN.md](docs/DESIGN.md): it holds the decisions, the HTTP API and the helper
  contract. Changes that break a contract update that document in the same pull request.
- Security problems: do **not** open an issue, follow [SECURITY.md](SECURITY.md).
- For larger changes (a new runtime, a new listen or proxy mode) open an issue first so the
  design can be agreed on.

## Tooling

- **Bun** is the only JavaScript runtime and package manager (`bun install`, `bun run`,
  `bunx`); the frontend builds without Node.js.
- **Python 3.8+** for `build.py` and the tests; `pyflakes` for linting.
- **Docker** for the local Plesk test server: `scripts/plesk-dev.sh` (Linux, macOS, Git Bash)
  or `scripts/plesk-dev.ps1` (PowerShell 7), see README, "Try it in Docker".

```sh
bun install
bun run build              # frontend
python build.py            # package: dist/runway-<version>-<release>.zip
```

## Code rules

| Area | Rules |
|---|---|
| `src/sbin/runway-helper` | python3 **3.8+ standard library only** (it runs on the server's system python). Must pass `python -m pyflakes` and `ast.parse(..., feature_version=(3, 8))`. Every privileged action re-validates its input; anything touching customer files runs through the drop-privileges child (`call_as_user`). Keep the security invariants listed in DESIGN section 4. |
| `src/plib/` | PHP **7.4 and 8.x** compatible, no Composer dependencies, class prefix `Modules_Runway_`. Files start with `<?php`, have no closing `?>` and no BOM. User-visible strings come from the locale files. |
| `src/frontend/` | React with plain JavaScript (no TypeScript), components from `@plesk/plesk-ext-sdk` (Plesk UI Library). Files with JSX import `createElement` from `react`. Never `window.confirm`: use the ui-library `Dialog`. Arabic and Hebrew panels are right-to-left: show code (paths, commands, variables, logs) through `Mono`, `dir="ltr"` inputs or `LogOutput`, and runtime names, versions and other mixed-direction values through `isolate()` / `runtimeName()` of `lib/format.js`; use logical CSS properties (`marginInlineStart`) instead of left/right. |
| Locales | `en-US` is the reference; every Plesk locale (32 files: `<locale>.php` loader, `server/<locale>.php`, `app/<locale>.php`) has identical keys and placeholders: `python tests/check_locales.py`. The translations other than English and Turkish were produced by machine translation with a review pass; corrections from native speakers are welcome (label `locales`). |
| Everything | English comments and documentation, LF line endings, MIT license header where files have one. No leftover `TODO`/`FIXME` markers or template placeholders in shipped files: `python build.py --check` fails on them. |

## Tests

Run what your change touches. CI runs the lint and packaging checks, `helper-smoke.sh`,
`api-smoke.sh`, `customer-smoke.sh` and the Go part of `runtime-e2e.sh` on every pull request
and on every push that changes code (pushes that only change `docs/`, root-level `*.md` files or
`LICENSE` skip CI); the full runtime matrix of `runtime-e2e.sh` needs every toolchain and runs
locally:

```sh
python -m pyflakes src/sbin/runway-helper build.py tests/check_locales.py
python build.py --check
python tests/check_locales.py
scripts/plesk-dev.sh test                     # everything CI runs, against the local container
bash tests/api-smoke.sh                       # against the local Plesk container
bash tests/runtime-e2e.sh                     # every runtime's sample app through nginx (local only)
bash tests/customer-smoke.sh                  # customer permission checks
docker cp tests/helper-smoke.sh runway-plesk:/root/ && docker exec runway-plesk bash /root/helper-smoke.sh
```

CI (`.github/workflows/ci.yml`):

1. **Lint**: pyflakes, Python 3.8 grammar check of the helper, `bash -n`, locale keys, the
   frontend build, `build.py --check`, `php -l` with PHP 7.4 and 8.2.
2. **Package**: `python build.py --strict`, uploads the zip as the `runway-package` artifact.
3. **End-to-end**: three parallel jobs, each starting `plesk/plesk` with systemd, installing
   the zip, creating the subscription `gotest.local` and (when the license allows customer
   accounts) its owner `cust1` and installing Go through Runway; then *helper* runs
   `tests/helper-smoke.sh` with `RUNWAY_SMOKE_SELF_UPDATE=1` (its self-update section then also
   upgrades the installed extension to a repackaged release+1 through the built-in updater; that
   cannot be undone, so leave it off locally unless the container is thrown away afterwards:
   `plesk-e2e.sh start` recreates it; its zero-downtime section also checks that applications
   without the setting get the same files as from the 1.0.0 helper, which `plesk-e2e.sh smoke`
   takes from the `v1.0.0` tag), *panel* runs `tests/api-smoke.sh` (with a real deployment) and
   `tests/customer-smoke.sh` (skipped without the customer), *runtime* runs
   `tests/runtime-e2e.sh` for Go (`RUNWAY_E2E_RUNTIMES=go`). `.github/scripts/plesk-e2e.sh` does
   the same on your machine: `start`, `install dist/<zip>`, `prepare`, `smoke`, `stop`
   (`SMOKE_SUITES=helper,api,customer,runtime` picks the suites; `scripts/plesk-dev.sh` wraps
   it: `up`, `install`, `prepare`, `test`, `down`).

CodeQL (`.github/workflows/codeql.yml`) analyses the helper, the frontend and the workflows on
every push and pull request that changes code; its findings are under *Security > Code
scanning*. Dependabot
keeps the GitHub Actions and the frontend dependencies current (`.github/dependabot.yml`).

When you change behaviour, extend `tests/helper-smoke.sh` (helper), `tests/api-smoke.sh` (API)
or `tests/runtime-e2e.sh` (runtimes, web server) and, for UI changes, check the four pages in the
panel in the light and the dark theme (no console errors).

## Adding a runtime

1. Write `docs/runtimes/<key>.md` (version discovery, download and checksums, install layout,
   per-user environment, detection, defaults, listen modes, minimal sample) following the
   existing files.
2. Add the adapter class to the `RUNTIMES` registry of the helper (interface in DESIGN 5.1);
   PHP and the UI pick up the metadata from the `runtimes` command.
3. Add `examples/<key>-hello`, a row to the README runtime table and helper smoke tests.

## Pull requests

- One topic per pull request, with a description of what changed and how it was tested
  (container, Plesk version, OS); the pull request template asks for both.
- Add an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md), or label the pull
  request `skip-changelog` when nothing user-visible changes.
- Do not commit generated files (`src/htdocs/index.php`, `src/htdocs/dist/`, `dist/`,
  `node_modules/`).
- Pull requests are squash-merged into `develop` once the Lint, Package and End-to-end checks
  are green, so the title should be a good one-line summary: it becomes the commit subject.

## Labels

Area labels (`helper`, `php`, `frontend`, `locales`, `packaging`, `tests`, `examples`,
`documentation`, `ci`) are added to pull requests automatically from the files they change
(`.github/labeler.yml`; labels are never removed automatically). The maintainer sets the type
label, which also decides the category of the change in the generated release notes
(`.github/release.yml`): `breaking change`, `security`, `enhancement`, `bug`, `runtime`,
`documentation`, `dependencies` (Dependabot). Bug reports, feature requests and runtime
proposals get `needs triage` from their issue template.

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
