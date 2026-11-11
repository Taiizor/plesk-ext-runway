# Runtime notes: python (uv-managed CPython)

Status of facts: everything marked **[verified]** was checked on 2026-11-11 against the official
source and/or inside the `grt-plesk` test container (Plesk 18.0.82, Ubuntu 24.04, x86_64, uv 0.13.7,
CPython 3.13.18). Items marked **[unverified]** are documented from memory/docs excerpts and must be
checked by the implementer.

Design summary (DESIGN.md §5.2): Runway installs **uv** once into `/opt/runway/uv/uv` and uses it to
install CPython builds (Astral `python-build-standalone`) into `/opt/runway/python`. Apps get a
virtualenv in the app root (`<app>/.venv`), every cache lives under `~/.runway/`.

---

## 1. Version discovery

### 1a. uv itself (one managed tool, channel "latest")

- Source: GitHub releases of `astral-sh/uv` **[verified]**
  - Latest: `https://api.github.com/repos/astral-sh/uv/releases/latest` (JSON object)
  - All: `https://api.github.com/repos/astral-sh/uv/releases?per_page=20` (JSON array); tags have **no
    `v` prefix** (`"tag_name": "0.13.7"`, published 2026-11-03).
  - Unauthenticated GitHub API limit: 60 requests/hour/IP — cache the answer (6 h per DESIGN).
- Relevant fields per asset (excerpt from the real response) **[verified]**:

```json
{"tag_name": "0.13.7", "published_at": "2026-11-03T02:45:04Z",
 "assets": [
  {"name": "uv-x86_64-unknown-linux-gnu.tar.gz", "size": 16671812,
   "digest": "sha256:c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83",
   "browser_download_url": "https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-unknown-linux-gnu.tar.gz"},
  {"name": "uv-x86_64-unknown-linux-gnu.tar.gz.sha256", "size": 101, "...": "..."},
  {"name": "uv-aarch64-unknown-linux-gnu.tar.gz", "size": 15896996, "...": "..."},
  {"name": "sha256.sum", "size": 1901, "...": "..."},
  {"name": "dist-manifest.json", "size": 46412, "...": "..."}]}
```

- Asset name to use: `uv-<arch>-unknown-linux-gnu.tar.gz` with `<arch>` = `x86_64` | `aarch64`
  (`platform.machine()` gives exactly these strings). musl variants (`-unknown-linux-musl`) exist but
  are not needed on the supported distros.
- Only the newest release is needed (uv is a tool, not a user-facing runtime): show it as channel
  `latest`, store the installed version string from `uv --version`.

### 1b. CPython versions (what the admin picks)

- Source: `uv python list --only-downloads --output-format json` **[verified, uv 0.13.7]**. The list is
  **embedded in the uv binary** ("available Python versions are frozen for each uv release"), so no
  network is needed to list, and updating uv is what brings new patch releases.
- Default output (without `--all-versions`) already shows **only the latest patch per minor** for
  the current platform, but it also contains pre-releases, free-threaded variants, PyPy and GraalPy.
  Text form (`uv python list --only-downloads`) **[verified]**:

```
cpython-3.16.0a1-linux-x86_64-gnu                 <download available>
cpython-3.16.0a1+freethreaded-linux-x86_64-gnu    <download available>
cpython-3.15.2-linux-x86_64-gnu                   <download available>
cpython-3.14.10-linux-x86_64-gnu                  <download available>
cpython-3.13.18-linux-x86_64-gnu                  <download available>
cpython-3.12.16-linux-x86_64-gnu                  <download available>
cpython-3.11.18-linux-x86_64-gnu                  <download available>
cpython-3.10.22-linux-x86_64-gnu                  <download available>
cpython-3.9.25-linux-x86_64-gnu                   <download available>
cpython-3.8.20-linux-x86_64-gnu                   <download available>
pypy-3.12.15-linux-x86_64-gnu                     <download available>
graalpy-3.13.0-linux-x86_64-gnu                   <download available>
```

  JSON form, one element **[verified]**:

```json
{"key": "cpython-3.13.18-linux-x86_64-gnu", "version": "3.13.18",
 "version_parts": {"major": 3, "minor": 13, "patch": 18}, "path": null, "symlink": null,
 "url": "https://releases.astral.sh/github/python-build-standalone/releases/download/20261026/cpython-3.13.18%2B20261026-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
 "os": "linux", "variant": "default", "implementation": "cpython", "arch": "x86_64", "libc": "gnu"}
```

- Filter for `list_available()` (Python):

```python
def available_pythons(uv="/opt/runway/uv/uv"):
    out = run([uv, "python", "list", "--only-downloads", "--output-format", "json"],
              env=root_env({"UV_PYTHON_INSTALL_DIR": PY_DIR, "UV_CACHE_DIR": "/var/lib/runway/cache/uv"}), timeout=60)
    items = []
    for e in json.loads(out):
        if e["implementation"] != "cpython" or e["variant"] != "default":
            continue                                   # no pypy/graalpy/free-threaded
        if e["os"] != "linux" or e["libc"] != "gnu" or e["arch"] != host_arch():
            continue                                   # x86_64 / aarch64 of this host only
        if not re.match(r"^\d+\.\d+\.\d+$", e["version"]):
            continue                                   # drop 3.16.0a1 etc.
        if e["version_parts"]["minor"] < 9:            # EOL floor (3.8 is EOL since 2024-10)
            continue
        items.append({"id": e["version"], "label": "Python %s" % e["version"], "url": e["url"]})
    return items   # ids like "3.13.18", newest first (uv already sorts descending)
```

- `version_re` for the adapter: `^3\.(9|[1-9][0-9])\.\d+$` (exact patch) — also accept `3.13` and let
  `uv python install 3.13` pick the newest patch, but store the exact installed version afterwards.
- Alternative/fallback source (no uv): GitHub releases of `astral-sh/python-build-standalone`
  **[verified]**: tag `20261110`, ~1000 assets, names like
  `cpython-3.13.18+20261110-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz` (35.6 MB; the
  non-stripped `install_only` is 77 MB), `aarch64-unknown-linux-gnu`, plus `x86_64_v2/_v3/_v4`
  optimised variants (do **not** use them: baseline `x86_64` runs on every CPU), musl variants and
  `freethreaded` variants. A `SHA256SUMS` file (142 KB) and the API `digest` field carry the SHA-256.
  Not needed when uv is used.

---

## 2. Download

### 2a. uv tarball **[verified]**

- URL: `https://github.com/astral-sh/uv/releases/download/<tag>/uv-<arch>-unknown-linux-gnu.tar.gz`
- Checksum: sidecar file `<asset>.sha256` whose content is `<hex>  uv-x86_64-unknown-linux-gnu.tar.gz`
  (two spaces, sha256sum format); the aggregate `sha256.sum` uses `<hex> *<name>` lines; the API
  `digest` field is `sha256:<hex>`. All three agree (c5221ff4… for 0.13.7 x86_64).
  Recommended: read `digest` from the JSON already fetched; fall back to the `.sha256` file.
- Size: 16.7 MB (x86_64), 15.9 MB (aarch64). Archive: gzip tar **with a top-level folder**:

```
uv-x86_64-unknown-linux-gnu/
uv-x86_64-unknown-linux-gnu/uv      (37.5 MB, ELF PIE, dynamically linked against glibc)
uv-x86_64-unknown-linux-gnu/uvx
```

- Only `uv` is needed (`uvx` is optional). The binary needs glibc (built "for GNU/Linux 2.6.32");
  on the supported distros (glibc ≥ 2.28) this is fine.

### 2b. CPython via uv **[verified]**

```
UV_PYTHON_INSTALL_DIR=/opt/runway/python UV_CACHE_DIR=/var/lib/runway/cache/uv \
UV_PYTHON_BIN_DIR=/opt/runway/python/bin UV_NO_PROGRESS=1 \
/opt/runway/uv/uv python install 3.13.18 --no-bin
```

- Output: `Downloading cpython-3.13.18-linux-x86_64-gnu (download) (33.8MiB)` … `Installed Python
  3.13.18 in 3.47s` / ` + cpython-3.13.18-linux-x86_64-gnu (python3.13)`.
- uv downloads from `releases.astral.sh` (a mirror of the GitHub release, see the `url` field) and
  installs `install_only_stripped` builds. uv records a SHA-256 per download in its embedded
  manifest and checks it **[unverified: by reading uv source; not reproduced]**. Because Runway
  cannot see that check, `install()` should additionally log the `url` from `uv python list` and
  verify afterwards that `<dir>/bin/python3.X --version` prints the requested version.
- `UV_PYTHON_INSTALL_MIRROR=<base url>` can redirect downloads (same file names) if ever needed.
- Removal: `uv python uninstall 3.13.18` (same env), or `rm -rf` of the version directory **and** the
  minor-version symlink if it points to it.

---

## 3. Install layout and system dependencies

### Layout **[verified]**

```
/opt/runway/uv/uv                                   # from the tarball, 0755 root
/opt/runway/python/                                 # UV_PYTHON_INSTALL_DIR
  .gitignore  .lock  .temp/                         # created by uv (see pitfalls)
  cpython-3.13.18-linux-x86_64-gnu/                 # the real install (105 MB)
    BUILD  bin/  include/  lib/  share/
    bin/{python3.13,python3,python,pip3.13,pip3,pip,python3.13-config,...}
  cpython-3.13-linux-x86_64-gnu -> /opt/runway/python/cpython-3.13.18-linux-x86_64-gnu   # minor symlink
```

- Directory name pattern: `cpython-<major.minor.patch>-linux-<x86_64|aarch64>-gnu`. The minor-version
  symlink is what `uv venv` writes into `pyvenv.cfg` (`home = .../cpython-3.13-linux-x86_64-gnu/bin`),
  which gives "transparent patch upgrades": installing 3.13.19 later re-points the link and all venvs
  follow; **removing the last 3.13.x breaks every venv built with it** (the UI must show "in use").
- `list_installed()`: glob `/opt/runway/python/cpython-*-linux-*-gnu` that are real directories
  (`os.path.islink` false), id = middle part (`3.13.18`), path = `<dir>/bin/python3.13`. Or parse
  `uv python list --only-installed --output-format json` (`path` field) and keep entries whose path
  starts with `/opt/runway/python/`.
- PATH entries for the user: `/opt/runway/python/cpython-<ver>-linux-<arch>-gnu/bin` then
  `/opt/runway/uv`. (`python3`, `python`, `pip` all exist in that `bin`.)
- `uv python install` also creates a `python3.13` symlink in `UV_PYTHON_BIN_DIR` (defaults to
  `~/.local/bin`) unless `--no-bin` is passed — always pass `--no-bin` as root.

### System dependencies **[verified by ldd]**

The build links only against glibc components: `libpthread, libdl, libutil, libm, librt, libc`
(OpenSSL, libffi, sqlite, zlib etc. are statically bundled). python-build-standalone targets glibc
2.17+ **[unverified]**; Ubuntu 22.04 (2.35), Debian 12 (2.36), AlmaLinux 9 (2.34) are fine.
Detection: `ldd --version | head -1` or `os.confstr("CS_GNU_LIBC_VERSION")`. No `libicu` or similar.
Build deps for packages with C extensions (status only): `cc`/`gcc`, `make`, `pkg-config` — most
PyPI packages ship manylinux wheels so this rarely matters.

Permissions: after install run `chmod_public` (root, 0755/0644). uv works as the user against a
read-only install dir **[verified: `uv venv`, `uv pip install`, `uv sync --frozen` succeed with the
whole tree `go-w`, with `.lock` 0644 or even deleted]**. A user trying `uv python install` into it
fails with `Permission denied` **[verified]**, which is the desired behaviour.

---

## 4. Per-user environment (`env(home, version)`)

```python
def env(self, home, version):
    pydir = "/opt/runway/python/cpython-%s-linux-%s-gnu" % (version, host_arch())
    rw = os.path.join(home, ".runway")
    return {
        "PATH": [pydir + "/bin", "/opt/runway/uv"],
        "UV_PYTHON_INSTALL_DIR": "/opt/runway/python",   # so uv finds the managed interpreters
        "UV_PYTHON": pydir + "/bin/python3",             # pin: uv venv/sync/run use this interpreter
        "UV_PYTHON_PREFERENCE": "only-managed",          # never pick /usr/bin/python3 silently
        "UV_PYTHON_DOWNLOADS": "never",                  # users must not download Pythons (would fail anyway)
        "UV_CACHE_DIR": rw + "/uv",                      # wheels/sdists/interpreter cache (76 MB after fastapi+uvicorn+gunicorn)
        "UV_PYTHON_CACHE_DIR": rw + "/uv/python-cache",  # archive cache (only used by uv python install)
        "UV_TOOL_DIR": rw + "/uv/tools", "UV_TOOL_BIN_DIR": rw + "/uv/bin",
        "UV_PYTHON_BIN_DIR": rw + "/uv/bin",
        "UV_LINK_MODE": "copy",                          # see pitfalls (cache and .venv may be on different fs)
        "UV_NO_PROGRESS": "1", "UV_HTTP_TIMEOUT": "120",
        "VIRTUAL_ENV": "<app_root>/.venv",               # uv pip / uv run target it without --python  [verified]
        "PIP_CACHE_DIR": rw + "/pip", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONUNBUFFERED": "1",                         # logs reach journald immediately
        "PYTHONDONTWRITEBYTECODE": "",                   # leave unset: app pyc go into the (writable) app dir
        "XDG_CACHE_HOME": rw + "/cache", "XDG_DATA_HOME": rw + "/data", "XDG_CONFIG_HOME": rw + "/config",
    }
```

- All names above are documented uv/pip variables **[verified against docs.astral.sh/uv/reference/environment]**.
  `UV_PYTHON_PREFERENCE=only-managed` is equivalent to `--managed-python`;
  `UV_PYTHON_DOWNLOADS=never` to `--no-python-downloads`.
- Nothing needs to be writable under `/opt`: with downloads disabled uv never touches
  `UV_PYTHON_INSTALL_DIR` **[verified]**; CPython does not write `__pycache__` into a read-only
  stdlib (it silently skips) — stdlib pyc files are shipped precompiled.
- The `.venv` must live inside the subscription (`<app_root>/.venv`); `uv` resolves the project
  environment from `UV_PROJECT_ENVIRONMENT` or `.venv` in the project dir.

---

## 5. Detection and default commands

`inspect(app_dir)` (runs as the user, `_read_small`, no symlink following) looks for, in order:

| File | Parse | Meaning |
|---|---|---|
| `pyproject.toml` | `[project] name`, `requires-python`, `dependencies` (substring search for `fastapi`, `django`, `flask`, `uvicorn`, `gunicorn`, `starlette`); `[tool.uv]` presence; `uv.lock` next to it | uv project → `uv sync --frozen` |
| `requirements.txt` (also `requirements/*.txt`) | one dep per line, same substring search | pip style → `uv pip install -r` |
| `manage.py` | regex `DJANGO_SETTINGS_MODULE['"],\s*['"]([\w.]+)['"]` → settings module, project package = first segment; confirm `<pkg>/wsgi.py` / `<pkg>/asgi.py` exist | Django |
| `main.py`, `app.py`, `api.py`, `app/main.py`, `asgi.py`, `wsgi.py` | regex `^\s*(app|api|application)\s*=\s*(FastAPI|Flask|Starlette)\(` and `get_wsgi_application|get_asgi_application` | module:attribute for uvicorn/gunicorn |
| `.python-version` | first line, e.g. `3.13` | preferred toolchain |
| `Procfile` | `web:` line | explicit start command (prefer it when present) |

Python 3.8 stdlib has no `tomllib`; parse `pyproject.toml` with a small regex/line parser (only the
`[project]` table, `name = "..."`, `requires-python = "..."`, and the `dependencies = [` list).

`defaults(inspect)`:

| Case | build_cmd | start_cmd (tcp) | start_cmd (unix) |
|---|---|---|---|
| `uv.lock` present | `uv sync --frozen --no-dev` | `.venv/bin/<server…>` as below | idem |
| `pyproject.toml` only | `uv venv .venv && uv pip install -e .` (or `uv sync --no-dev`, which also writes `uv.lock`) | | |
| `requirements.txt` | `uv venv .venv && uv pip install -r requirements.txt` | | |
| FastAPI/Starlette app `main:app` | (above) | `.venv/bin/uvicorn main:app --host $HOST --port $PORT --proxy-headers --forwarded-allow-ips 127.0.0.1` | `.venv/bin/uvicorn main:app --uds $RUNWAY_SOCKET --proxy-headers --forwarded-allow-ips '*'` |
| Django `mysite` | build + `.venv/bin/python manage.py collectstatic --noinput` (only when `STATIC_ROOT` is set; otherwise skip) | `.venv/bin/gunicorn mysite.wsgi:application --bind $HOST:$PORT --workers 2 --umask 0117` | `.venv/bin/gunicorn mysite.wsgi:application --bind unix:$RUNWAY_SOCKET --umask 0117 --workers 2` |
| Flask/WSGI `app:app` | (above) | `.venv/bin/gunicorn app:app --bind $HOST:$PORT` | `.venv/bin/gunicorn app:app --bind unix:$RUNWAY_SOCKET --umask 0117` |
| plain script `app.py` without framework | `uv venv .venv` | `.venv/bin/python app.py` | idem (script reads `RUNWAY_SOCKET`) |

`uv venv .venv` is idempotent (re-creates the env in place) and takes <1 s; `uv sync --frozen --no-dev`
on an up-to-date env took 0.03 s **[verified]**.

### Server flags **[verified from `--help` of uvicorn 0.54 / gunicorn 27.0 / fastapi-cli]**

- **uvicorn**: `--host` (default 127.0.0.1), `--port` (default 8000), `--uds <path>` (unix socket;
  file is created with mode **0666**), `--fd <int>`, `--workers N` (or `$WEB_CONCURRENCY`),
  `--app-dir`, `--root-path`, `--proxy-headers/--no-proxy-headers` (on by default),
  `--forwarded-allow-ips` (default `127.0.0.1,::1`; for a unix socket the client IP is empty, so
  pass `'*'` or the socket path literal), `--log-level`, `--timeout-graceful-shutdown`.
  Every option also exists as `UVICORN_<NAME>` env var (`UVICORN_HOST`, `UVICORN_PORT`, `UVICORN_UDS`…;
  only HOST/PORT are spelled out in the docs, the rest follows the prefix rule) **[docs]**.
  Multiple `--workers` are not supported together with `--uds`? — they are (uvicorn binds once and
  forks) **[unverified]**; keep workers=1 as default.
- **gunicorn**: `-b/--bind` = `HOST:PORT` | `unix:PATH` | `fd://FD`, repeatable; **if `PORT` is in
  the environment and no `--bind` is given, gunicorn binds `0.0.0.0:$PORT`** (config.py `Bind`
  default) — Runway always sets `PORT`, so always pass `--bind` explicitly **[verified in source]**.
  `-m/--umask` affects the unix socket mode (default 0 → socket 0777; `--umask 0117` → `srw-rw----`
  **[verified]**). `-k uvicorn.workers.UvicornWorker` for ASGI apps (still shipped by uvicorn 0.54;
  the `uvicorn-worker` package is the long-term replacement) **[verified]**. `--chdir`, `-w`,
  `--threads`, `--timeout`, `--graceful-timeout`, `--forwarded-allow-ips` (default `127.0.0.1,::1`,
  env `FORWARDED_ALLOW_IPS`), `--access-logfile -`, `--error-logfile -`, `GUNICORN_CMD_ARGS` env.
- **fastapi CLI** (`fastapi run [path]`): `--host` (default **0.0.0.0**), `--port` (env `PORT`,
  default 8000), `--workers`, `--root-path`, `--app`, `--entrypoint/-e`, `--proxy-headers`,
  `--forwarded-allow-ips`; auto-detects `main.py`, `app.py`, `api.py`, `app/main.py`, `app/app.py`,
  `app/api.py` and the object `app`/`api`. **No `--uds` option → tcp only**; for unix mode use
  uvicorn directly. Always pass `--host $HOST` (default is all interfaces).
- **Django** (`gunicorn <pkg>.wsgi:application`, run from the directory holding `manage.py`
  **[verified]**): production needs `DJANGO_SETTINGS_MODULE` (already set by `manage.py`/`wsgi.py`),
  `ALLOWED_HOSTS` containing the domain, `DEBUG=False`, `STATIC_ROOT` + `collectstatic` and the static
  prefix (`/static/`) in Runway `static_paths` so nginx serves it. `SECRET_KEY` via env in `settings.py`
  is the app's business.

---

## 6. Minimal sample app (stdlib only) **[verified on CPython 3.12.3 and 3.13.18, tcp and unix]**

`app.py` (written by `sample()`; listens on `RUNWAY_SOCKET` when set, else `$HOST:$PORT`):

```python
#!/usr/bin/env python3
"""Runway sample app (stdlib only): listens on RUNWAY_SOCKET (unix) or HOST:PORT (tcp)."""
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        body = ("Hello from Python %s (pid %d)\n" % (sys.version.split()[0], os.getpid())).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def address_string(self):
        # client_address is '' on unix sockets; the default implementation would raise IndexError
        addr = self.client_address
        return addr[0] if isinstance(addr, tuple) else "unix"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


class UnixHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_UNIX

    def server_bind(self):
        path = self.server_address
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        self.socket.bind(path)
        os.chmod(path, 0o660)  # nginx connects through the psaserv group
        self.server_name = "localhost"
        self.server_port = 0


def main():
    sock = os.environ.get("RUNWAY_SOCKET")
    if sock:
        httpd = UnixHTTPServer(sock, Handler)
        where = sock
    else:
        host = os.environ.get("HOST", "127.0.0.1")
        port = int(os.environ.get("PORT", "8080"))
        httpd = ThreadingHTTPServer((host, port), Handler)
        where = "%s:%d" % (host, port)
    sys.stderr.write("listening on %s\n" % where)
    sys.stderr.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()


if __name__ == "__main__":
    main()
```

- Files written by `sample()`: `app.py` (above) and a `requirements.txt` that is empty (so the
  generic build command still works). Commands: build `uv venv .venv` (or empty), start
  `.venv/bin/python app.py` (or `python3 app.py`, PATH contains the toolchain).
- Output check: `curl --unix-socket /run/runway/1/app.sock http://localhost/` →
  `Hello from Python 3.13.18 (pid 32758)`; socket shows `srw-rw---- user psaserv`.

Optional FastAPI sample (needs network at build time) **[verified: `uv lock`, `uv sync --frozen
--no-dev`, `uv run --frozen uvicorn main:app --uds …` → `{"hello":"world"}`]**:
`pyproject.toml` with `dependencies = ["fastapi", "uvicorn"]`, `main.py` with `app = FastAPI()`.

---

## 7. Pitfalls and verification commands

- `/opt/runway/python/.lock` is created **0666** by `uv python install`; `chmod_public` may make it
  0644 or remove it — uv as the user still works (it only locks when it might download) **[verified]**.
  Never let `chmod_public` follow the minor-version symlinks twice (they point inside the tree).
- The minor-version symlink (`cpython-3.13-linux-x86_64-gnu`) is what venvs reference. When
  removing a version, re-point or remove the link only if no other 3.13.x remains; show "in use by"
  from the apps' `toolchain` field **and** from `pyvenv.cfg` of their `.venv` (`home =` line).
- `uv venv` without network and with a missing version prints
  `hint: A managed Python download is available for Python 3.11, but Python downloads are set to 'never'`
  **[verified]** — surface this text to the customer (choose an installed toolchain).
- `uv sync` writes `uv.lock`; `--frozen` requires it to exist and be current (else error). Use
  `--frozen` only when `uv.lock` is present, otherwise `uv sync --no-dev` (creates the lock).
- uv caches by hard-linking from `UV_CACHE_DIR` into `.venv`; both are inside the home directory so
  links work, but set `UV_LINK_MODE=copy` if `~/.runway` ever lives on another filesystem (uv only
  warns and falls back to copy; harmless) **[docs]**.
- gunicorn + `PORT` env without `--bind` listens on `0.0.0.0` (see §5) — the listener-uid check of
  the base helper still passes (same uid) but the app would be reachable from outside; defaults
  must always include `--bind`.
- `fastapi run` defaults to `0.0.0.0` as well; always pass `--host $HOST`.
- uvicorn `--uds` creates the socket 0666; gunicorn 0777 unless `--umask 0117`. The socket dir
  `/run/runway/<id>` (2750, group psaserv) already restricts access, so this is cosmetic.
- The uv binary is dynamically linked (glibc); `uv` itself must be run with a sane `HOME` as root
  (it uses `~/.cache` only when `UV_CACHE_DIR` is unset — always set it, also for root jobs:
  `/var/lib/runway/cache/uv`).
- Python writes `.pyc` files next to app sources (writable, fine) and never into `/opt` (read-only,
  silently skipped). `PYTHONUNBUFFERED=1` keeps journald logs timely.
- Memory: a venv with fastapi[standard]+uvicorn+gunicorn is ~60 MB, the uv cache ~76 MB — both
  inside the subscription quota, deletable by the customer (`~/.runway/uv`, `<app>/.venv`).
- Proxy headers: nginx (base `WebConfig`) sends `X-Forwarded-For/Proto`; uvicorn trusts only
  `127.0.0.1`/`::1` by default which matches tcp mode; in unix mode pass `--forwarded-allow-ips '*'`
  (the socket has no peer IP).

Verification commands and expected output **[verified]**:

```
/opt/runway/uv/uv --version                 → uv 0.13.7 (x86_64-unknown-linux-gnu)
/opt/runway/python/cpython-3.13.18-linux-x86_64-gnu/bin/python3.13 --version → Python 3.13.18
UV_PYTHON_INSTALL_DIR=/opt/runway/python /opt/runway/uv/uv python list --only-installed
   → cpython-3.13.18-linux-x86_64-gnu    /opt/runway/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13
     cpython-3.12.3-linux-x86_64-gnu     /usr/bin/python3.12          (system interpreters are listed too)
UV_PYTHON_INSTALL_DIR=/opt/runway/python /opt/runway/uv/uv python dir → /opt/runway/python
cat <app>/.venv/pyvenv.cfg → home = /opt/runway/python/cpython-3.13-linux-x86_64-gnu/bin / version_info = 3.13
<app>/.venv/bin/uvicorn --help | grep -- --uds → "--uds TEXT  Bind to a UNIX domain socket."
curl --unix-socket /run/runway/<id>/app.sock http://localhost/ → 200 from the app
```
