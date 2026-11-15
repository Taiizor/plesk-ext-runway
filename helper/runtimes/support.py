# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Runtime adapters (docs/DESIGN.md section 5). RUNTIMES (end of this section) is the single
# source of truth for runtime metadata, toolchains, environments, detection and samples.
# Methods documented "as the user" run inside call_as_user (dropped privileges).
# ---------------------------------------------------------------------------

RELEASE_CACHE_TTL = 6 * 3600
COMPOSER_BIN_DIR = BASE_DIR + "/composer/bin"
COMPOSER_PHARS = ("/usr/lib/plesk-9.0/composer.phar", "/usr/lib64/plesk-9.0/composer.phar",
                  "/usr/local/psa/var/modules/composer/composer.phar")


def _listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def _read_text(path, limit=8192):
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.read(limit).strip()
    except OSError:
        return ""


def write_text(path, content, mode=0o644):
    with open(path, "w") as fh:
        fh.write(content)
    os.chmod(path, mode)


def num_key(value):
    return [int(part) for part in re.findall(r"\d+", value or "")]


def java_key(value):
    """Sort key of Temurin ids: (feature, interim, update, patch, build), missing parts = 0, so the
    GA "27+37" sorts below its update "27.0.1+8" (num_key would rank [27, 37] above [27, 0, 1, 8])."""
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?(?:\.\d+)*(?:\+(\d+))?$", value or "")
    if not match:
        return (-1,) + tuple(num_key(value))
    return tuple(int(part or 0) for part in match.groups())


def machine_arch():
    machine = os.uname().machine
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    raise HelperError("Unsupported CPU architecture: %s" % machine)


def cpu_flags():
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("flags"):
                    return set(line.split(":", 1)[1].split())
    except OSError:
        pass
    return set()


def http_json(url, headers=None, timeout=HTTP_TIMEOUT, limit=32 * 1024 * 1024, opener=None):
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    request = urllib.request.Request(url, headers=hdrs)
    with (opener.open if opener else urllib.request.urlopen)(request, timeout=timeout) as resp:  # nosec - fixed https URLs
        return json.loads(resp.read(limit).decode("utf-8"))


def cached_json(name, force, fetch):
    """Release metadata cached for 6 hours. A failed refresh serves the stale copy if any."""
    ensure_dir(CACHE_DIR, 0o700)
    path = os.path.join(CACHE_DIR, name + ".json")
    cached = read_json(path)
    if not force and isinstance(cached, dict) and time.time() - cached.get("fetched", 0) < RELEASE_CACHE_TTL:
        return cached.get("data")
    try:
        data = fetch()
    except Exception:  # noqa: BLE001
        if isinstance(cached, dict) and cached.get("data"):
            return cached["data"]
        raise
    write_json(path, {"fetched": time.time(), "data": data})
    return data


def github_releases(repo, force=False, per_page=30):
    """Published releases of a GitHub repository (newest first) with their Linux assets.
    The unauthenticated API needs a User-Agent and allows 60 requests per hour: cached 6 h."""
    def fetch():
        try:
            raw = http_json("https://api.github.com/repos/%s/releases?per_page=%d" % (repo, per_page),
                            {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise HelperError("GitHub API rate limit reached (60 requests per hour); try again later")
            raise
        result = []
        for rel in raw if isinstance(raw, list) else []:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            assets = {}
            for asset in rel.get("assets") or []:
                name = str(asset.get("name") or "")
                if "linux" not in name and not name.lower().startswith(("sha", "checksum")):
                    continue
                digest = str(asset.get("digest") or "")
                assets[name] = {"url": asset.get("browser_download_url"), "size": asset.get("size"),
                                "sha256": digest[7:].lower() if digest.startswith("sha256:") else None}
            result.append({"tag": str(rel.get("tag_name") or ""), "prerelease": bool(rel.get("prerelease")),
                           "published": str(rel.get("published_at") or "")[:10], "assets": assets})
        return result
    return cached_json("github-" + repo.replace("/", "-"), force, fetch)


def parse_shasums(text):
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.match(r"^[0-9a-fA-F]{64}$", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def https_url(url):
    if not isinstance(url, str) or not url.startswith("https://") or RE_CTRL_ANY.search(url) or " " in url:
        raise HelperError("Unexpected download URL in the release metadata")
    return url


def swap_dir(stage, target, work):
    """Moves a staged toolchain into place; a previous one is moved into `work` (deleted later)."""
    if os.path.lexists(target):
        os.rename(target, os.path.join(work, ".old"))
    os.rename(stage, target)


def _which_status(names):
    return dict((name, bool(shutil.which(name, path=ROOT_PATH))) for name in names)


def _files(app_dir, *names):
    """As the user: the names (relative paths) that exist as files in app_dir."""
    return [name for name in names if os.path.isfile(os.path.join(app_dir, name))]


def _json_file(path):
    try:
        data = json.loads(_read_small(path))
    except (ValueError, HelperError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _safe_rel(value):
    return value if isinstance(value, str) and len(value) <= 200 and RE_REL_PATH.match(value) \
        and ".." not in value.split("/") else None


def ensure_composer_wrapper():
    """composer on PATH for PHP apps: a wrapper around Plesk's composer.phar."""
    phar = next((p for p in COMPOSER_PHARS if os.path.isfile(p)), None)
    if not phar:
        return
    content = ("#!/bin/sh\n# Managed by the Plesk Runway extension: Plesk's composer.phar with the php on PATH.\n"
               "exec php %s \"$@\"\n" % phar)
    path = COMPOSER_BIN_DIR + "/composer"
    if _read_text(path) == content.strip():
        return
    ensure_dir(os.path.dirname(COMPOSER_BIN_DIR))
    ensure_dir(COMPOSER_BIN_DIR)
    write_file_atomic(path, content, 0o755)
