# Runway runtime notes: Bun

Status: researched 2026-11-11. Facts marked **[verified]** were checked against the official docs
(bun.com/docs) or executed inside the `grt-plesk` container (Ubuntu 24.04, x86_64, glibc 2.39) with
Bun 1.4.4. Facts marked **[unverified]** come from memory or secondary sources and must be checked
before relying on them. This refines the `bun` row of DESIGN.md §5.2.

Summary of what changed versus the DESIGN row:

- Since recent releases Bun ships **one x64 binary** (targets Nehalem/SSE4.2, picks AVX2/AVX-512 code
  paths at runtime). `bun-linux-x64-baseline.zip` still exists in every release but is an **alias**
  of the same build (same size ± bytes) **[verified: docs + release assets 1.4.4]**. Older pinned
  versions did ship a distinct baseline build, so keep the AVX2 probe + `-baseline` fallback: it is
  harmless on new releases and required on old ones.
- Bun does **not** unlink a stale unix socket before listening (`EADDRINUSE`) and removes the socket
  only on a clean `server.stop()`/exit **[verified]**. The base unit already runs
  `ExecStartPre=/bin/rm -f <socket>`, and the sample below also unlinks defensively.

## 1. Version discovery

Source: GitHub Releases of `oven-sh/bun`. Tags are `bun-v<major>.<minor>.<patch>`; there is also a
rolling `canary` release (prerelease) which must be ignored.

### 1.1 REST API (needs `User-Agent`, 60 requests/hour unauthenticated) [verified]

```
GET https://api.github.com/repos/oven-sh/bun/releases?per_page=100
Accept: application/vnd.github+json
User-Agent: runway-helper/1.0 (+https://github.com/<org>/plesk-ext-runway)
```

Response: JSON array, newest first. Page 1 (100 items) currently spans `bun-v1.4.4` .. `bun-v1.0.27`,
so one page is enough for "newest 10". Rate-limit headers seen: `x-ratelimit-limit: 60`,
`x-ratelimit-remaining: 53` -> cache the result (6 h per DESIGN) and surface `error` on 403/429.
Excerpt of one element (fields the helper needs):

```json
{
  "tag_name": "bun-v1.4.4",
  "name": "Bun v1.4.4",
  "draft": false,
  "prerelease": false,
  "published_at": "2026-10-22T10:11:32Z",
  "assets": [
    {"name": "bun-linux-x64.zip",          "size": 51794595,
     "browser_download_url": "https://github.com/oven-sh/bun/releases/download/bun-v1.4.4/bun-linux-x64.zip",
     "digest": "sha256:bf8ccbfb2b0b80159e0f9a6d15c55317add8077534dbc6130a3edb52fccb395c"},
    {"name": "bun-linux-x64-baseline.zip", "size": 51794559, "digest": "sha256:e0446eb5..."},
    {"name": "bun-linux-aarch64.zip",      "size": 51644673, "digest": "sha256:baa6bb36..."},
    {"name": "SHASUMS256.txt",             "size": 3431},
    {"name": "SHASUMS256.txt.asc"}
  ]
}
```

Linux asset names in a release (1.4.4): `bun-linux-x64.zip`, `bun-linux-x64-baseline.zip`,
`bun-linux-aarch64.zip`, `bun-linux-x64-musl.zip`, `bun-linux-x64-musl-baseline.zip`,
`bun-linux-aarch64-musl.zip`, plus `-profile` (debug symbols) and `-android` variants, `SHASUMS256.txt`,
`SHASUMS256.txt.asc`. Runway only needs the glibc builds (Plesk distros are glibc).

`GET https://api.github.com/repos/oven-sh/bun/releases/latest` returns the newest non-prerelease,
non-draft release (same shape) **[verified]**. The `/tags` endpoint is useless (sorted
lexically, returns `v0.1.1` first) **[verified]**.

### 1.2 API-free fallback for the `latest` channel [verified]

`HEAD https://github.com/oven-sh/bun/releases/latest/download/bun-linux-x64.zip` answers
`302 Location: https://github.com/oven-sh/bun/releases/download/bun-v1.4.4/bun-linux-x64.zip`.
The tag can be parsed from the `Location` header with no API rate limit:

```python
import re, urllib.error, urllib.request

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # stop: we only want the Location header

def bun_latest_tag():
    url = "https://github.com/oven-sh/bun/releases/latest/download/bun-linux-x64.zip"
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "runway-helper/1.0"})
    try:
        opener.open(req, timeout=20)
    except urllib.error.HTTPError as e:         # 302 surfaces as HTTPError here
        loc = e.headers.get("Location", "")
        m = re.search(r"/download/(bun-v\d+\.\d+\.\d+)/", loc)
        if m:
            return m.group(1)
        raise
    raise RuntimeError("no redirect from releases/latest")
```

### 1.3 Filtering and what to show

```python
import json, re, urllib.request

TAG_RE = re.compile(r"^bun-v(\d+)\.(\d+)\.(\d+)$")

def bun_available(limit=10):
    req = urllib.request.Request(
        "https://api.github.com/repos/oven-sh/bun/releases?per_page=100",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "runway-helper/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        releases = json.load(r)
    out = []
    for rel in releases:
        m = TAG_RE.match(rel.get("tag_name", ""))
        if not m or rel.get("draft") or rel.get("prerelease"):
            continue
        names = {a["name"] for a in rel.get("assets", [])}
        if "bun-linux-x64.zip" not in names or "SHASUMS256.txt" not in names:
            continue                      # release still uploading or broken
        ver = "%s.%s.%s" % m.groups()
        out.append({"id": ver, "label": "Bun " + ver, "published": rel["published_at"][:10]})
    out.sort(key=lambda v: tuple(int(x) for x in v["id"].split(".")), reverse=True)
    return [{"id": "latest", "label": "latest (channel, currently %s)" % out[0]["id"]}] + out[:limit]
```

Version/channel regex for the adapter: `version_re = r"^(latest|\d+\.\d+\.\d+)$"`. `latest` is a
channel: `install("latest")` resolves the tag at install time and records the concrete version in
`/opt/runway/bun/latest/.version`; `update("latest")` re-resolves and swaps the directory.

## 2. Download

URL pattern (all **[verified]**):

```
https://github.com/oven-sh/bun/releases/download/bun-v<ver>/bun-linux-<target>.zip
https://github.com/oven-sh/bun/releases/download/bun-v<ver>/SHASUMS256.txt
<target> = x64 | x64-baseline | aarch64        (musl variants exist, not needed)
```

- Archive: ZIP (store/deflate) with a **top-level folder named like the asset stem**:
  `bun-linux-x64/` (mode 0755) and `bun-linux-x64/bun` (mode 0755, 107,308,936 bytes for 1.4.4)
  **[verified]**. Nothing else is inside.
- Size: `bun-linux-x64.zip` = 51,794,595 bytes (1.4.4); aarch64 51,644,673 bytes **[verified]**.
- Checksum: `SHASUMS256.txt`, format `<sha256 hex>  <asset name>` (two spaces), one line per
  asset **[verified]**:

```
baa6bb36f51d6e58561e02bbea825038a9df454f673d6d776e8bbf86f8c7850e  bun-linux-aarch64.zip
e0446eb55995772eb9894bebae9a6be368d985a8b9271ee124486f9946eedd76  bun-linux-x64-baseline.zip
bf8ccbfb2b0b80159e0f9a6d15c55317add8077534dbc6130a3edb52fccb395c  bun-linux-x64.zip
```

  The API's `assets[].digest` (`sha256:<hex>`) carries the same value and can be used as a
  cross-check when the API was used **[verified]**. `SHASUMS256.txt.asc` is a GPG signature (not
  verified by Runway; python stdlib has no OpenPGP).

```python
def parse_shasums(text):
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            sums[parts[1]] = parts[0]
    return sums
```

- Extraction with `zipfile`: Python does not restore Unix modes, so `chmod 0o755` the binary after
  extraction. Safe-extract rules: exactly one regular file expected (`<stem>/bun`), reject anything
  else, reject absolute paths / `..`. Extract into a temp dir **under `/opt/runway/bun/`** (not
  `/tmp`: in the test container `/tmp` is mounted `noexec`, so `bun --version` from `/tmp` fails
  with "Permission denied" **[verified]**).

## 3. Install layout and system requirements

```
/opt/runway/bun/<ver>/bin/bun          # the binary (root:root 0755)
/opt/runway/bun/<ver>/bin/bunx -> bun  # symlink; bun acts as `bun x` when argv[0] is "bunx" [unverified; official installer creates it]
/opt/runway/bun/<ver>/.target          # "x64" | "x64-baseline" | "aarch64" (for update/repair)
/opt/runway/bun/latest/.version        # for the channel install only: "1.4.4"
```

PATH entry: `/opt/runway/bun/<ver>/bin`. `chmod_public` the tree; Bun never writes next to its
executable (**do not** run `bun upgrade`: it would try to replace the root-owned binary).

System requirements:

| Requirement | Value | How to detect |
|---|---|---|
| CPU x86_64 | SSE4.2 mandatory (Nehalem+ / Bulldozer+); AVX2 optional on current builds **[verified docs]** | `flags` line of `/proc/cpuinfo` contains `sse4_2`; `avx2` selects the non-baseline asset (see below) |
| CPU aarch64 | any ARMv8 **[unverified]** | `platform.machine() == "aarch64"` |
| glibc | >= 2.17 **[verified: docs; `objdump -T` max symbol version GLIBC_2.17]** | `ldd --version` (first line) or `os.confstr("CS_GNU_LIBC_VERSION")` |
| Kernel | works on 3.10+, 5.6+ recommended **[verified docs]** | `os.uname().release` |
| Shared libs | only libc, libpthread, libdl, libm (ldd) **[verified]** | nothing to install |
| `unzip` | not needed (python `zipfile`) | - |

Asset selection:

```python
import platform

def cpu_flags():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("flags"):
                    return set(line.split(":", 1)[1].split())
    except OSError:
        pass
    return set()

def bun_target():
    m = platform.machine()
    if m in ("aarch64", "arm64"):
        return "aarch64"
    if m != "x86_64":
        raise RuntimeError("unsupported CPU architecture: " + m)
    flags = cpu_flags()
    if flags and "sse4_2" not in flags:
        raise RuntimeError("Bun needs a CPU with SSE4.2")
    # current releases: -baseline is an alias of the same build; old releases: a real
    # non-AVX2 build. Probing keeps both cases correct.
    return "x64" if "avx2" in flags else "x64-baseline"
```

Disk: ~108 MB per installed version.

## 4. Per-user environment (`env(home, version)`)

All writes of Bun go under `BUN_INSTALL` when it is set; the global package cache defaults to
`$BUN_INSTALL/install/cache` **[verified]**, global installs to `$BUN_INSTALL/install/global` and
their bins to `$BUN_INSTALL/bin` (bunfig keys `install.globalDir` / `install.globalBinDir`
**[verified docs]**; env names `BUN_INSTALL_GLOBAL_DIR` / `BUN_INSTALL_BIN` **[unverified]**).
Without any variable Bun uses `~/.bun/install/cache` **[verified]**.

```python
import os

def env(self, home, version):
    bin_dir = "/opt/runway/bun/%s/bin" % version
    rw = os.path.join(home, ".runway", "bun")
    return {
        "PATH": [bin_dir, os.path.join(rw, "bin")],
        "BUN_INSTALL": rw,                                          # ~/.runway/bun
        "BUN_INSTALL_CACHE_DIR": os.path.join(rw, "cache"),         # ~/.runway/bun/cache  [verified: `bun pm cache` prints it]
        "BUN_RUNTIME_TRANSPILER_CACHE_PATH": os.path.join(rw, "transpiler-cache"),  # default is a platform cache dir [verified docs]; files > ~50 KB only [unverified]
        "DO_NOT_TRACK": "1",                                        # no crash-report upload [verified docs]
        "NO_COLOR": "1",                                            # plain journald logs [verified docs]
        # TMPDIR: leave unset; systemd PrivateTmp gives the service its own /tmp.
    }
```

Nothing is needed for a read-only `/opt`: Bun has no on-disk state next to the binary. `HOME` must be
set (the base already sets it for `User=` services). Optional: `NODE_ENV=production` makes Bun load
`.env.production` instead of `.env.development` (see §7, `.env` auto-loading).

## 5. Detection (`inspect(app_dir)`, runs as the user) and defaults

Files to look at (sizes capped, no symlink following):

| File | Parse | Use |
|---|---|---|
| `package.json` | JSON: `name`, `scripts.start`, `scripts.build`, `scripts.dev`, `main`, `module`, `type`, `workspaces`, `packageManager`, `trustedDependencies` | start/build commands, entry file |
| `bun.lock` (text, default since 1.2) / `bun.lockb` (binary, legacy) **[verified docs]** | presence only | `--frozen-lockfile` |
| `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml` | presence | hint: Bun migrates npm lockfiles on install **[unverified]**; no frozen install |
| `bunfig.toml` | presence (TOML parsing not in stdlib < 3.11; do not parse) | hint only |
| entry candidates | `index.ts`, `index.js`, `server.ts`, `server.js`, `app.ts`, `app.js`, `main.ts`, `src/index.ts`, `src/server.ts`, plus `package.json` `module`/`main` | start command when no `scripts.start` |
| `node_modules/` | presence | status "installed" |
| `tsconfig.json` | presence | none (Bun transpiles TS on the fly, no type-check **[verified docs]**) |

Default commands (`defaults(inspect)`):

```python
def defaults(self, info):
    pkg = info.get("package") or {}
    scripts = pkg.get("scripts") or {}
    frozen = info.get("has_bun_lock")            # bun.lock or bun.lockb
    build = "bun install --frozen-lockfile" if frozen else "bun install"
    if "build" in scripts:
        build += " && bun run build"              # suggestion: DESIGN lists only the install step
    if "start" in scripts:
        start = "bun run start"
    elif info.get("entry"):
        start = "bun run %s" % info["entry"]      # e.g. bun run index.ts (TS runs directly)
    else:
        start = ""
    return {"build_cmd": build, "start_cmd": start}
```

Notes:
- `bun install --production` implies `--frozen-lockfile` and skips devDependencies **[verified docs]**;
  not used by default because many `build` scripts need devDependencies.
- Lifecycle scripts (`postinstall`) of dependencies are **not** run unless listed in
  `trustedDependencies` **[verified docs]**: surface this in the UI hint when a build fails.
- `bun run start` runs the script through `bash`/`sh` **[verified docs]**; if the script says
  `node server.js` and Node is absent, use `bun --bun run start` (Bun shims `node`)
  **[verified docs for --bun]**. Offer it as an alternative in the hint; keep `bun run start` as
  the default (matches DESIGN).
- `bun run <name>` prefers a package.json script over a file with the same name; `bun <name>`
  prefers the file **[verified docs]**. Defaults always use `bun run`.
- Entry detection must not run user code: just stat the candidate files.

Listen modes:

| Mode | Env from Runway | How apps pick it up |
|---|---|---|
| tcp | `PORT`, `HOST=127.0.0.1`, `LISTEN_ADDR` | `Bun.serve()` default port is `$BUN_PORT`, then `$PORT`, then `$NODE_PORT`, else 3000 **[verified docs]**; default hostname is `0.0.0.0` so apps must set `hostname: process.env.HOST`. Express/Hono/Elysia apps read `PORT` by convention. |
| unix | `RUNWAY_SOCKET` | `Bun.serve({ unix: process.env.RUNWAY_SOCKET, fetch })` **[verified]**. Elysia: `app.listen({ unix })` **[unverified]**; Hono on Bun: `export default { unix, fetch }` **[unverified]**; `node:http` `server.listen("/path.sock")` under Bun **[unverified]** -> document "tcp only" for anything not verified. |
| none | - | worker scripts (queues, bots) |

Socket facts **[verified]**: with the unit's `UMask=0007` Bun creates `srwxrwx---` (nginx is in
`psaserv`, group of the socket dir); an existing socket file makes `Bun.serve` throw
`EADDRINUSE` (no automatic unlink); `server.stop()`/normal exit removes the file.

## 6. Minimal sample app (no dependencies)

`server.ts` **[verified in tcp and unix mode with Bun 1.4.4]**:

```ts
import { existsSync, unlinkSync } from "node:fs";

const socket = process.env.RUNWAY_SOCKET;
// Stale socket from a crash: Bun does not unlink it itself (EADDRINUSE otherwise).
if (socket && existsSync(socket)) unlinkSync(socket);

const server = Bun.serve({
  ...(socket
    ? { unix: socket }
    : { hostname: process.env.HOST || "127.0.0.1", port: Number(process.env.PORT || 3000) }),
  fetch(req: Request) {
    return new Response(`Hello from Runway (Bun ${Bun.version}) ${new URL(req.url).pathname}\n`, {
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  },
});

const stop = () => {
  server.stop(true);
  if (socket) { try { unlinkSync(socket); } catch {} }
  process.exit(0);
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
console.log(socket ? `listening on unix:${socket}` : `listening on http://${server.hostname}:${server.port}`);
```

`package.json`:

```json
{
  "name": "runway-sample",
  "private": true,
  "type": "module",
  "scripts": { "start": "bun run server.ts" }
}
```

Commands: build `bun install` (creates an empty `bun.lock`; may be left empty), start
`bun run start` (or `bun run server.ts`). Test: `curl --unix-socket /run/runway/<id>/app.sock http://localhost/`
or `curl http://127.0.0.1:$PORT/`.

## 7. Pitfalls and verification

- `bun --version` -> `1.4.4`; `bun --revision` -> `1.4.4+38afee6c8` **[verified]**. Use `--version`
  for `list_installed` labels (exit 0, stdout one line). `bun pm cache` prints the cache dir
  **[verified]** (useful for a support page).
- GitHub API without `User-Agent` returns 403; with 60 req/h per IP the toolchains page must use the
  6 h cache and the `releases/latest` redirect trick for the `latest` channel.
- `/tmp` may be `noexec` (true in the Plesk container) -> never execute a freshly extracted binary
  from `/tmp`; install-time verification (`bun --version`) must run from `/opt/runway/bun/...`.
- `zipfile` drops the executable bit -> `chmod 0755`.
- `.env` auto-loading: Bun loads `.env`, `.env.<NODE_ENV>`, `.env.local` from the working directory
  **[verified docs]**; whether they override variables already in the environment is
  **[unverified]** (dotenv convention: existing env wins). Runway's secrets go into the unit env
  file; tell users `--no-env-file` exists if they need to disable this.
- Memory: a hello-world server idles at roughly 30-60 MB RSS **[unverified]**; `bun --smol` trades
  speed for a smaller heap **[verified docs]**. Default `memoryMb` limits of the base are fine.
- `Bun.serve` closes idle connections after 10 s by default (`idleTimeout`, max 255) **[verified docs]**;
  irrelevant behind nginx but matters for long polling.
- `bun install` needs network to `registry.npmjs.org` from the deploy unit (as the user); the
  cache under `~/.runway/bun/cache` makes repeated installs offline-capable for the same versions.
- Node compatibility: most npm packages work, native addons (`.node`) mostly do too; packages that
  spawn `node` need `--bun` or an installed Node.js **[unverified]**.
- `bun upgrade` / `bun upgrade --canary` must not be used by customers (root-owned binary; it fails
  with a permission error) - the toolchains page is the only way to change versions.
- Baseline/AVX2: if an installed version was fetched as `x64-baseline` and the CPU changes (migration
  to a newer host), nothing breaks; the reverse (non-baseline binary of an *old* version on a CPU
  without AVX2) crashes with `Illegal instruction` at start -> `.target` lets `toolchains` warn.
