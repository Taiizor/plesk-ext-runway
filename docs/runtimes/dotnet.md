# Runway runtime notes: .NET

Status: researched 2026-11-11. **[verified]** = checked against learn.microsoft.com or executed
inside the `grt-plesk` container (Ubuntu 24.04, x86_64) with .NET SDK 10.0.404 / runtime 10.0.15.
**[unverified]** = from memory/secondary sources. Refines the `dotnet` row of DESIGN.md §5.2.

Headline facts: the release metadata lists channels with `support-phase` and `release-type`; as of
today 11.0 (STS, released 2026-11-10) and 10.0 (LTS) are `active`, 9.0 and 8.0 reached EOL on
2026-11-10. SDK tarballs have **no top-level folder** and are extracted into the shared root
`/opt/runway/dotnet` where several versions coexist. Kestrel binds unix sockets through
`ASPNETCORE_URLS=http://unix:/path` (works with no code change), removes the socket on graceful
shutdown but does **not** remove a stale one. Runtime needs `libstdc++`, `libgcc`, ICU (or
invariant mode), OpenSSL; `libcoreclr.so` requires glibc >= 2.27.

## 1. Version discovery

### 1.1 `releases-index.json` [verified]

```
GET https://builds.dotnet.microsoft.com/dotnet/release-metadata/releases-index.json
```

Top-level keys: `$schema`, `releases-index` (array), `signature`. Entries (newest first), real
excerpt from 2026-11-11:

```json
{"releases-index": [
 {"channel-version": "11.0", "latest-release": "11.0.0",  "latest-release-date": "2026-11-10", "security": true,
  "latest-runtime": "11.0.0",  "latest-sdk": "11.0.100", "product": ".NET", "support-phase": "active",
  "release-type": "sts", "eol-date": "2028-11-14",
  "releases.json": "https://builds.dotnet.microsoft.com/dotnet/release-metadata/11.0/releases.json",
  "supported-os.json": "https://builds.dotnet.microsoft.com/dotnet/release-metadata/11.0/supported-os.json"},
 {"channel-version": "10.0", "latest-release": "10.0.15", "latest-release-date": "2026-11-10", "security": true,
  "latest-runtime": "10.0.15", "latest-sdk": "10.0.404", "product": ".NET", "support-phase": "active",
  "release-type": "lts", "eol-date": "2028-11-14", "releases.json": ".../10.0/releases.json", "supported-os.json": "..."},
 {"channel-version": "9.0", "latest-release": "9.0.23", "latest-sdk": "9.0.321", "support-phase": "eol", "release-type": "sts", "eol-date": "2026-11-10", "...": "..."},
 {"channel-version": "8.0", "latest-release": "8.0.34", "latest-sdk": "8.0.428", "support-phase": "eol", "release-type": "lts", "eol-date": "2026-11-10", "...": "..."},
 {"channel-version": "7.0", "...": "eol"}, {"channel-version": "6.0", "...": "eol"}, "... down to 1.0"
]}
```

Observed `support-phase` values: `active`, `eol`; the schema also defines `preview`, `go-live`,
`maintenance` **[unverified list]**. `release-type` is `lts` or `sts`. Older entries may lack
`supported-os.json`; `product` is `.NET` or `.NET Core`.

What to show: channels with `support-phase` in `{"active", "maintenance", "go-live"}` (today: 11.0
and 10.0); label `.NET 10.0 (LTS) - SDK 10.0.404, EOL 2028-11-14`. Optionally list `eol` channels
greyed out (customers may still need 8.0 for a while) but never `preview`.

### 1.2 Channel `releases.json` [verified]

```
GET https://builds.dotnet.microsoft.com/dotnet/release-metadata/10.0/releases.json
```

Top-level: `channel-version`, `latest-release`, `latest-release-date`, `latest-release-security`,
`latest-runtime`, `latest-sdk`, `support-phase`, `release-type`, `eol-date`, `lifecycle-policy`,
`releases` (array, newest first), `signature`. Each release:

```json
{"release-date": "2026-11-10", "release-version": "10.0.15", "security": true,
 "cve-list": [{"cve-id": "CVE-2026-114146", "cve-url": "https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2026-114146"}, "..."],
 "release-notes": "https://github.com/dotnet/core/blob/main/release-notes/10.0/10.0.15/10.0.15.md",
 "runtime": {"version": "10.0.15", "version-display": "10.0.15", "vs-version": "...", "files": [
    {"name": "dotnet-runtime-linux-x64.tar.gz", "rid": "linux-x64",
     "url": "https://builds.dotnet.microsoft.com/dotnet/Runtime/10.0.15/dotnet-runtime-10.0.15-linux-x64.tar.gz",
     "hash": "a90177d7...318a"}, "..."]},
 "sdk": {"version": "10.0.404", "version-display": "10.0.404", "runtime-version": "10.0.15",
         "csharp-version": "14.0", "fsharp-version": "10.0", "vb-version": "17.13", "vs-version": "18.11.4", "files": [
    {"name": "dotnet-sdk-linux-arm64.tar.gz",    "rid": "linux-arm64",    "url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.404/dotnet-sdk-10.0.404-linux-arm64.tar.gz",    "hash": "3533a386...8f11"},
    {"name": "dotnet-sdk-linux-musl-x64.tar.gz", "rid": "linux-musl-x64", "url": ".../dotnet-sdk-10.0.404-linux-musl-x64.tar.gz", "hash": "..."},
    {"name": "dotnet-sdk-linux-x64.tar.gz",      "rid": "linux-x64",      "url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.404/dotnet-sdk-10.0.404-linux-x64.tar.gz",
     "hash": "577d0eb17fec33d029104c5c63a1ab0accc3e28776274abef2218dbac5af18d2109b5406d26b31d76f5c245215e3ba0926a94c20246c672c41847c9e1eb1dc50"}]},
 "sdks": [{"version": "10.0.404", "...": "..."}, {"version": "10.0.115", "...": "..."}],
 "aspnetcore-runtime": {"version": "10.0.15", "version-aspnetcoremodule": ["20.0.26302.15"], "files": ["..."]},
 "windowsdesktop": {"...": "..."}}
```

- `sdk` = the primary (highest feature band) SDK of the release; `sdks[]` lists every SDK band
  released that day (10.0.404 and 10.0.115 here). Runway installs `sdk` (the highest band); offer
  the lower bands only if a project's `global.json` demands it (rare).
- `files[].hash` = **SHA-512 hex (128 chars)** **[verified: matches `sha512sum`]**. Some older
  entries use upper-case hex -> compare case-insensitively.
- RID names: `linux-x64`, `linux-arm64` (not `aarch64`), `linux-musl-x64`, `linux-musl-arm64`.
- The URL is `https://builds.dotnet.microsoft.com/dotnet/Sdk/<sdk-version>/dotnet-sdk-<sdk-version>-<rid>.tar.gz`
  (redirects possible; follow them). Size: 243,138,887 bytes for 10.0.404 linux-x64 **[verified]**.

Ids: SDK versions `10.0.404` (`x.y.znn`: feature band `z`, patch `nn`). Also accept a bare channel
`10.0` (resolves to `latest-sdk`). `version_re = r"^\d+\.\d+(\.\d{3})?$"`. Channels could serve as
update channels (`update("10.0")` installs the new `latest-sdk`, keeps the old one); otherwise
`HelperError`.

```python
import json, os, urllib.request

META = "https://builds.dotnet.microsoft.com/dotnet/release-metadata/"
UA = {"User-Agent": "runway-helper/1.0"}

def _get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)

def dotnet_rid():
    return {"x86_64": "linux-x64", "aarch64": "linux-arm64", "arm64": "linux-arm64"}[os.uname().machine]

def dotnet_available(include_eol=False):
    idx = _get_json(META + "releases-index.json")["releases-index"]
    out = []
    for ch in idx:
        phase = ch.get("support-phase")
        if phase == "preview" or (phase == "eol" and not include_eol) or not ch.get("latest-sdk"):
            continue
        if ch.get("product") != ".NET" or tuple(int(x) for x in ch["channel-version"].split(".")) < (8, 0):
            continue
        out.append({"id": ch["latest-sdk"], "channel": ch["channel-version"],
                    "label": ".NET %s (%s) SDK %s" % (ch["channel-version"], ch["release-type"].upper(), ch["latest-sdk"]),
                    "eol": ch.get("eol-date"), "phase": phase, "releases_json": ch["releases.json"]})
    return out

def dotnet_sdk_file(releases_json_url, sdk_version, rid):
    """Return (url, sha512) of the SDK tarball for one SDK version."""
    data = _get_json(releases_json_url)
    for rel in data["releases"]:
        for sdk in [rel.get("sdk")] + list(rel.get("sdks") or []):
            if sdk and sdk.get("version") == sdk_version:
                for f in sdk.get("files", []):
                    if f.get("rid") == rid and f["name"].endswith(".tar.gz"):
                        return f["url"], f["hash"].lower()
    raise RuntimeError("SDK %s not found for %s" % (sdk_version, rid))
```

Alternative checksum file: `https://builds.dotnet.microsoft.com/dotnet/checksums/<runtime-version>-sha.txt`
(sha512sum format) **[verified docs]**; not needed since the JSON has the hash.

## 2. Download and archive layout

- Archive: gzip tar whose members are prefixed `./` and have **no top-level folder** **[verified]**:

```
./dotnet                                   # muxer/host executable (ELF, dynamic)
./dnx                                      # script: `dotnet dnx` tool runner (SDK 10+)
./LICENSE.txt ./ThirdPartyNotices.txt
./host/fxr/10.0.15/libhostfxr.so
./sdk/10.0.404/...                          # the SDK (MSBuild, Roslyn, NuGet, templates engine)
./sdk-manifests/10.0.100/...                # workload manifests of the feature band
./shared/Microsoft.NETCore.App/10.0.15/     # base runtime (libcoreclr.so, System.*.dll)
./shared/Microsoft.AspNetCore.App/10.0.15/  # ASP.NET Core shared framework
./packs/Microsoft.NETCore.App.Ref/10.0.15/  # reference assemblies
./packs/Microsoft.AspNetCore.App.Ref/10.0.15/
./packs/Microsoft.NETCore.App.Host.linux-x64/10.0.15/   # apphost for this RID only
./templates/10.0.15/
```

- Extraction: directly into `/opt/runway/dotnet` (`tar --no-same-owner`, equivalent in Python:
  do not chown; root-owned, `chmod_public`). "Different versions of .NET can be extracted to the same
  folder, which coexist side-by-side" **[verified docs]**. `dotnet` and `host/fxr/<ver>` are
  overwritten when a newer SDK is extracted; that is expected (the muxer is backward compatible).
  Extract the newest version last, or re-extract the muxer from the newest when removing a version.
- Safe-tar: strip the leading `./`, reject `..`/absolute, allow regular files, dirs and the few
  relative symlinks (none observed in 10.0.404 **[unverified for other versions]**); preserve modes
  (the `dotnet` muxer and `*.so` must be 0755/0644 as shipped; `dotnet --info` fails with
  "Permission denied" if executed from a `noexec` mount such as `/tmp` in the Plesk container
  **[verified]**).
- Per-version removal: record the member list at install time in
  `/opt/runway/dotnet/.runway/installed/<sdk-version>.json` (`{"sdk": "10.0.404", "runtime": "10.0.15", "members": [...]}`)
  and on `remove(version)` delete only the members not claimed by another installed SDK (two SDKs of
  the same channel share `shared/*/<runtime>`, `host/fxr/<runtime>`, `packs/*/<runtime>`,
  `templates/<runtime>` and `sdk-manifests/<band>`). Never delete `dotnet` itself while any SDK
  remains. `list_installed()` = `os.listdir("/opt/runway/dotnet/sdk")` (or `dotnet --list-sdks`).

## 3. Install layout, PATH, system dependencies

```
/opt/runway/dotnet/dotnet              -> on PATH; DOTNET_ROOT=/opt/runway/dotnet
/opt/runway/dotnet/sdk/<sdk-version>/  -> one dir per installed SDK
```

Verified command outputs (10.0.404):

```
$ dotnet --version
10.0.404
$ dotnet --list-sdks
10.0.404 [/opt/runway/dotnet/sdk]
$ dotnet --list-runtimes
Microsoft.AspNetCore.App 10.0.15 [/opt/runway/dotnet/shared/Microsoft.AspNetCore.App]
Microsoft.NETCore.App 10.0.15 [/opt/runway/dotnet/shared/Microsoft.NETCore.App]
```

`dotnet --version`/`--info` need a writable `DOTNET_CLI_HOME` (first-run sentinel) - when the
helper verifies an install as root use `DOTNET_CLI_HOME=/var/lib/runway/cache/dotnet-cli`
(plus `DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1`). `dotnet --version` without a global.json
prints the highest installed SDK; with an unsatisfiable `global.json` in cwd it prints a
misleading "The command could not be loaded, possibly because: * You intended to execute a .NET
application: The application '--version' does not exist ..." **[verified]** -> run it from a
neutral directory.

Native dependencies:

| Library | Who needs it | Ubuntu 24.04 package | Ubuntu 22.04 | AlmaLinux/RHEL 9 | Detect |
|---|---|---|---|---|---|
| glibc >= 2.27 | `libcoreclr.so` (`GLIBC_2.27` symbols) **[verified objdump]**; muxer 2.16 | libc6 | libc6 | glibc | `ldd --version` |
| libstdc++ / libgcc_s | muxer, coreclr (ldd) **[verified]** | libstdc++6, libgcc-s1 | same | libstdc++, libgcc | `ldconfig -p \| grep libstdc++.so.6` |
| ICU (`libicuuc`, `libicui18n`) | globalization, dlopen'ed at runtime **[verified strings]**; or `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` | libicu74 | libicu70 | libicu | `ldconfig -p \| grep -E 'libicuuc\.so\.[0-9]+'` (any version) |
| OpenSSL (`libssl.so.3`/`1.1`) | TLS/crypto, dlopen'ed **[verified strings list 1.1/1.0.2/10; 3 expected]** | libssl3t64 | libssl3 | openssl-libs | `ldconfig -p \| grep -E 'libssl\.so\.(3\|1\.1)'` |
| `libgssapi_krb5.so.2` | only Kerberos/NTLM auth, dlopen'ed **[verified strings]** | libgssapi-krb5-2 | same | krb5-libs | optional |
| zlib | .NET 8 only (9+ bundles it) **[verified docs]** | zlib1g | zlib1g | zlib | optional |
| `libbrotli1` | listed for Ubuntu 26.04 (.NET 11?) **[verified docs list, reason unverified]** | - | - | - | optional |
| ca-certificates, tzdata | HTTPS, time zones | ca-certificates, tzdata | same | same | `/etc/ssl/certs/ca-certificates.crt` |

Official per-distro lists **[verified docs]**: Ubuntu 24.04 `ca-certificates libc6 libgcc-s1
libgssapi-krb5-2 libicu74 libssl3t64 libstdc++6 tzdata zlib1g`; Ubuntu 22.04 `... libicu70 libssl3 ...`;
RHEL/CentOS Stream `glibc libgcc ca-certificates openssl-libs libstdc++ libicu tzdata krb5-libs`
(+ `zlib` for .NET 8). Debian 12: `libicu72`, `libssl3` **[unverified]**. The Plesk container already
had libicu74, libssl3, libgssapi_krb5 and libstdc++6 **[verified]**, so `dotnet --info` and the sample
worked without installing anything. `build-deps-install` for dotnet = ICU (+ libssl, libgssapi) via
apt/dnf.

Disk: ~0.9-1.1 GB per SDK unpacked **[unverified, tarball is 243 MB]**.

## 4. Per-user environment (`env(home, version)`)

```python
import os

def env(self, home, version):
    root = "/opt/runway/dotnet"
    rw = os.path.join(home, ".runway", "dotnet")
    return {
        "PATH": [root],
        "DOTNET_ROOT": root,                                  # apphosts find the runtime [verified: ./publish/app works]
        "DOTNET_CLI_HOME": rw,                                # first-run sentinels, .nuget/NuGet/NuGet.Config, local tools [verified writes]
        "NUGET_PACKAGES": os.path.join(rw, "nuget", "packages"),          # global-packages (default ~/.nuget/packages) [verified docs]
        "NUGET_HTTP_CACHE_PATH": os.path.join(rw, "nuget", "http-cache"), # default ~/.local/share/NuGet/http-cache or v3-cache [verified docs]
        "NUGET_PLUGINS_CACHE_PATH": os.path.join(rw, "nuget", "plugins-cache"),
        "DOTNET_BUNDLE_EXTRACT_BASE_DIR": os.path.join(rw, "bundle"),     # single-file apps extract here [verified docs, default unverified]
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
        "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",        # no dev cert in ~/.dotnet/corefx/cryptography [verified docs]
        "DOTNET_ADD_GLOBAL_TOOLS_TO_PATH": "0",
        "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "1",     # no background manifest downloads [verified docs]
        "MSBUILDDISABLENODEREUSE": "1",                       # no lingering MSBuild worker nodes after a build [unverified]
        "DOTNET_CLI_UI_LANGUAGE": "en",                       # English build logs
        # listen mode (set by the helper when rendering the unit, see 5.3):
        # tcp:  "ASPNETCORE_URLS": "http://%s:%s" % (host, port)
        # unix: "ASPNETCORE_URLS": "http://unix:%s" % socket_path
        # optional: "ASPNETCORE_FORWARDEDHEADERS_ENABLED": "true"  # trust X-Forwarded-* from nginx [unverified]
        # optional: "DOTNET_gcServer": "0"                      # workstation GC for small apps (ASP.NET defaults to server GC)
        # optional: "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1" # only when ICU is missing (env beats runtimeconfig in .NET 9+ [verified docs])
    }
```

Writes still landing in `$HOME` (inside the subscription, acceptable) **[verified]**:
`~/.local/share/NuGet/Migrations/` (marker), `~/.dotnet/corefx/Runtime/SharedMemory/` (runtime
named-mutex storage) and, for file-based apps, `~/.local/share/dotnet/runfile/<app>-<hash>/`
(build cache). NuGet's scratch dir is `/tmp/NuGetScratch<user>` (`NUGET_SCRATCH`) - private under
`PrivateTmp`. `HOME` must be set (the base's units do it). Nothing is ever written under `/opt`:
`dotnet publish` of the sample completed with the root read-only tree **[verified]**.

GC/memory (**[verified docs]**): `System.GC.Server` in `runtimeconfig.json` (true for the Web SDK)
<-> env `DOTNET_gcServer=0/1`; inside a cgroup limit the heap hard limit defaults to 75 % of the
limit (`DOTNET_GCHeapHardLimitPercent`, hex); `DOTNET_GCConserveMemory=0-9`. Which wins when env
and runtimeconfig disagree for GC settings is **[unverified]** (docs state env precedence only for
globalization settings).

## 5. Detection and defaults

### 5.1 Files (`inspect`, as the user)

| File | Parse | Result |
|---|---|---|
| `*.csproj` / `*.fsproj` / `*.vbproj` (root, then one level down) | XML (SDK-style has no namespace; legacy uses `http://schemas.microsoft.com/developer/msbuild/2003`): `Project@Sdk` (`Microsoft.NET.Sdk.Web` web, `Microsoft.NET.Sdk.Worker` worker, `Microsoft.NET.Sdk` console), `PropertyGroup/OutputType` (`Exe`; Web SDK implies Exe), `TargetFramework` (`net10.0`) or `TargetFrameworks`, `AssemblyName` (default = file stem), `SelfContained`, `RuntimeIdentifier`, `PublishAot`, `InvariantGlobalization`, `UseAppHost` | assembly name, web vs worker, required runtime major |
| `*.sln` / `*.slnx` | regex `Project\(...\) = "Name", "path\\to\\X.csproj"` (`.sln`), XML `<Project Path="..."/>` (`.slnx`) | pick the single `Sdk.Web` project; several candidates -> ask the user |
| `global.json` | JSON `sdk.version`, `sdk.rollForward` (default `patch` when a version is given) **[verified docs]** | warn if no installed SDK satisfies it (see 7) |
| `Directory.Build.props`, `Directory.Packages.props`, `nuget.config` | presence | hints only |
| `publish/<Name>.runtimeconfig.json` or `*.runtimeconfig.json` in root (prebuilt upload) | JSON: `runtimeOptions.tfm` (`net10.0`), `runtimeOptions.frameworks[]{name, version}` (older: single `framework`), `includedFrameworks` (self-contained), `configProperties` | AssemblyName = file stem; start `dotnet <stem>.dll` when `frameworks` present else `./<stem>` |
| `*.deps.json`, `<stem>.dll`, `<stem>` (apphost, ELF) | presence | prebuilt detection |
| `*.cs` with `#:` directives and no project file (`#:sdk Microsoft.NET.Sdk.Web`) | first lines | file-based app (SDK >= 10.0.100) **[verified docs]** |
| `appsettings.json` | presence (do not parse) | ASP.NET Core hint; `Kestrel:Endpoints` inside would override `ASPNETCORE_URLS` **[unverified precedence]** |

### 5.2 Default commands

```python
import shlex

def defaults(self, info):
    proj = info.get("project")                       # relative path to the chosen .csproj, may be None
    name = info.get("assembly_name")                 # AssemblyName or project stem
    if info.get("prebuilt"):                         # *.runtimeconfig.json uploaded
        build = ""
    elif info.get("file_based"):                     # app.cs with #: directives
        build = "dotnet publish %s -c Release -o publish" % shlex.quote(info["file_based"])  # needs `#:property PublishAot=false` (see 7)
    elif proj:
        build = "dotnet publish %s -c Release -o publish --nologo" % shlex.quote(proj)
    elif info.get("sln"):
        build = ""                                   # ambiguous: user picks the project
    else:
        build = "dotnet publish -c Release -o publish --nologo"
    if not name:
        start = ""
    elif info.get("self_contained"):
        start = "./publish/%s" % name                # apphost + bundled runtime (needs network at publish time for the runtime pack)
    else:
        start = "dotnet publish/%s.dll" % name       # framework-dependent [verified]
    return {"build_cmd": build, "start_cmd": start}
```

- `dotnet publish` defaults to `Release` for `net8.0+` targets **[verified docs]**; `-c Release`
  is kept for older TFMs and clarity. `-o publish` puts the output in `<app root>/publish/`
  (`app`, `app.dll`, `app.deps.json`, `app.runtimeconfig.json`, `app.pdb`, `web.config`,
  `app.staticwebassets.endpoints.json`, `wwwroot/` when present) **[verified]**. Build of the
  sample: 3.6 s warm, restore needs no network when there are no `PackageReference`s **[verified]**.
- The apphost `./publish/<name>` also works for framework-dependent apps because `DOTNET_ROOT` is
  set **[verified]**, but `dotnet <name>.dll` is independent of exec bits and `noexec` mounts, so it
  is the default. Self-contained publish (`-r linux-x64 --self-contained`) downloads
  `Microsoft.NETCore.App.Runtime.linux-x64` / `Microsoft.AspNetCore.App.Runtime.linux-x64` from
  nuget.org at publish time **[unverified]**.
- Generated `runtimeconfig.json` references `Microsoft.NETCore.App 10.0.0` and
  `Microsoft.AspNetCore.App 10.0.0`; the host rolls forward to the installed 10.0.15 (default
  `rollForward: Minor`) **[verified by running]**. An app targeting `net9.0` therefore needs a 9.x
  runtime installed (i.e. an SDK of channel 9.0); `TargetFramework` tells which channel the admin
  must install.

### 5.3 Listen modes

| Mode | Env set by Runway | Kestrel behaviour |
|---|---|---|
| tcp | `ASPNETCORE_URLS=http://127.0.0.1:$PORT` (plus `PORT`, `HOST`) | binds that address **[verified]**. Default without any config: `http://localhost:5000` **[verified]**. `ASPNETCORE_HTTP_PORTS=$PORT` is a lower-priority alternative but binds `*` (all interfaces) **[verified docs]** - do not use. Semicolon separates several URLs. |
| unix | `ASPNETCORE_URLS=http://unix:$RUNWAY_SOCKET` | binds the unix socket with no code change **[verified: `Now listening on: http://unix:/root/.../dn2.sock`]**; created `srwxrwx---` under `UMask=0007`; removed on SIGTERM (`Application is shutting down...`) **[verified]**; **not** removed if stale -> `Failed to bind to address http://unix:/path: address already in use` and the process aborts **[verified]**; the unit's `ExecStartPre=/bin/rm -f` covers this. Code equivalent: `builder.WebHost.ConfigureKestrel(o => o.ListenUnixSocket(path))` (overrides URLs). |
| none | - | workers (`Microsoft.NET.Sdk.Worker`, `IHostedService`) |

`UseUrls()` / `Listen*()` in app code override `ASPNETCORE_URLS` ("Listen endpoints override
UseUrls") **[verified docs]**; `Kestrel:Endpoints` in `appsettings.json` also override **[unverified]**.
`DOTNET_URLS` is the generic-host spelling of the same key **[unverified]**; Runway sets only
`ASPNETCORE_URLS`. Non-ASP.NET servers (`HttpListener`) are TCP-only.

## 6. Minimal sample app

Two files (a project file is unavoidable before .NET 10). `app.csproj` - set `TargetFramework`
from the chosen toolchain's channel (`net10.0` for SDK 10.x, `net11.0` for 11.x) **[verified]**:

```xml
<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <InvariantGlobalization>true</InvariantGlobalization>
    <AssemblyName>app</AssemblyName>
    <RootNamespace>app</RootNamespace>
  </PropertyGroup>
</Project>
```

`Program.cs` **[verified in tcp (PORT), unix (RUNWAY_SOCKET), ASPNETCORE_URLS-only, stale-socket and SIGTERM scenarios]**:

```csharp
var builder = WebApplication.CreateBuilder(args);

var socket = Environment.GetEnvironmentVariable("RUNWAY_SOCKET");
var port = Environment.GetEnvironmentVariable("PORT");
if (!string.IsNullOrEmpty(socket))
{
    if (File.Exists(socket)) File.Delete(socket); // stale socket from a crash: Kestrel does not unlink it itself
    builder.WebHost.ConfigureKestrel(o => o.ListenUnixSocket(socket));
}
else if (!string.IsNullOrEmpty(port))
{
    var host = Environment.GetEnvironmentVariable("HOST");
    builder.WebHost.UseUrls($"http://{(string.IsNullOrEmpty(host) ? "127.0.0.1" : host)}:{port}");
}
// otherwise ASPNETCORE_URLS (e.g. http://unix:/run/runway/1/app.sock) or Kestrel's default http://localhost:5000 applies

var app = builder.Build();
app.MapGet("/", () => $"Hello from Runway (.NET {Environment.Version})\n");
app.MapGet("/{*path}", (string path) => $"Hello from Runway (.NET {Environment.Version}) /{path}\n");
app.Run();
```

Commands: build `dotnet publish -c Release -o publish`, start `dotnet publish/app.dll`.
Test: `curl --unix-socket /run/runway/<id>/app.sock http://localhost/` -> `Hello from Runway (.NET 10.0.15)`.

Single-file variant for SDK >= 10.0.100 (`app.cs`, no project file) **[verified with `dotnet run app.cs`]**:

```csharp
#:sdk Microsoft.NET.Sdk.Web
#:property PublishAot=false
#:property InvariantGlobalization=true
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();                      // listens on ASPNETCORE_URLS
app.MapGet("/", () => "Hello from a file-based app\n");
app.Run();
```

`dotnet publish app.cs -o publish` then `dotnet publish/app.dll` **[publish of a file-based app
not re-verified; `dotnet run app.cs` verified, build cache in `~/.local/share/dotnet/runfile/`]**.
File-based apps publish as Native AOT by default, which needs `clang` and `zlib1g-dev`; the
`PublishAot=false` directive avoids that **[verified docs]**. `dotnet run app.cs` must not be used
as a start command (it rebuilds and two instances race on the build cache **[verified docs]**).

## 7. Pitfalls and verification

- `dotnet --version` -> `10.0.404` (stdout, exit 0) **[verified]**; use it after install with
  `DOTNET_CLI_HOME` pointing to a root-owned scratch dir, from a directory without `global.json`.
- ICU missing -> `Couldn't find a valid ICU package installed on the system` at startup; fix by
  installing libicu or `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` (env has priority over
  runtimeconfig since .NET 9 **[verified docs]**). The sample sets `InvariantGlobalization` so it
  runs even without ICU.
- glibc: `libcoreclr.so` needs `GLIBC_2.27` **[verified]** -> Ubuntu 22.04+/Debian 12/RHEL 8+ fine.
- `global.json` with `rollForward` default (`patch`) demands the exact feature band: `9.0.100`
  cannot be satisfied by SDK 10.0.404 and the muxer fails with the confusing "The command could not
  be loaded..." **[verified]**. `inspect` should compare `sdk.version` with installed SDKs using the
  documented rules (`patch`: same `x.y.z`, patch `>=`; `latestFeature`: same `x.y`; `latestMajor`:
  any `>=`) and show "install SDK channel 9.0 or edit global.json".
- Memory: ASP.NET Core uses **server GC** by default (`System.GC.Server: true` in the generated
  runtimeconfig **[verified]**) and DATAS (dynamic heap count) since .NET 9; a hello-world idles at
  ~50-80 MB RSS **[unverified]**. Under `MemoryMax` the GC caps itself at 75 % of the limit
  **[verified docs]**; `DOTNET_gcServer=0` or `DOTNET_GCConserveMemory=5` reduce footprint for
  small sites.
- Build resources: `dotnet publish` (MSBuild + Roslyn) needs ~0.5-1 GB RAM and leaves MSBuild
  worker nodes and `VBCSCompiler` alive for minutes unless `MSBUILDDISABLENODEREUSE=1` and
  `-p:UseSharedCompilation=false` are used **[unverified]**; the deploy unit's control group kills
  them anyway when the unit stops.
- `dotnet publish` output must not be served by nginx: keep `publish/` outside `httpdocs`
  (the app root is a separate directory in Runway).
- `publish/web.config` is for IIS; harmless on Linux.
- `appsettings.Production.json` is read by default (`ASPNETCORE_ENVIRONMENT` unset = `Production`
  **[unverified]**); set `ASPNETCORE_ENVIRONMENT=Production` explicitly in the unit for clarity.
- Behind nginx, apps generating absolute URLs need forwarded headers:
  `ASPNETCORE_FORWARDEDHEADERS_ENABLED=true` enables `UseForwardedHeaders` without code
  **[unverified; known from the official Docker images]**.
- Kestrel's unix socket: nginx must be in the socket's group (Plesk's `nginx` user is in `psaserv`
  **[verified]**) and the socket dir `2750 sysuser:psaserv` + `UMask=0007` yield `srwxrwx---`.
- Runtime roll-forward only within the major: an app built for `net9.0` does not run on a 10.x-only
  install (`You must install or update .NET to run this application ... Framework 'Microsoft.NETCore.App', version '9.0.0'`)
  **[unverified wording]**; `inspect` maps `TargetFramework` -> required channel.
- EOL: 8.0 and 9.0 reached end of support on 2026-11-10 **[verified index]**; show `eol-date` in
  the toolchains UI and keep installing them only on explicit request.
- `dotnet` writes nothing under `/opt/runway/dotnet` at run time, but `dotnet workload install`
  would (and fails as non-root) - workloads (MAUI, wasm-tools) are out of scope; the
  `DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=1` setting stops the advertising-manifest download.
