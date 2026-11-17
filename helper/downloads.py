# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Network downloads (toolchains)
# ---------------------------------------------------------------------------

def http_open(request, timeout=HTTP_TIMEOUT, opener=None):
    """Retry transient server errors before a GET response starts, at most three attempts."""
    urlopen = opener.open if opener else urllib.request.urlopen
    for attempt in range(3):
        try:
            return urlopen(request, timeout=timeout)  # nosec - callers validate URLs and redirects
        except urllib.error.HTTPError as exc:
            if exc.code not in (500, 502, 503, 504) or attempt == 2:
                raise
            exc.close()
            time.sleep(2 ** attempt)


def http_get(url, timeout=HTTP_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with http_open(request, timeout=timeout) as resp:
        return resp.read()


def download(url, dest, sha256, log, algo="sha256", limit=None, opener=None):
    """Downloads url to dest and verifies the hex digest `sha256` (computed with `algo`) when given.
    `limit` caps the size in bytes (the download fails above it); `opener` replaces urlopen
    (the updater's opener re-checks redirects)."""
    log.line("Downloading %s" % url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.new(algo)
    total = 0
    too_large = "%s is larger than %d KiB" % (url, (limit or 0) // 1024)
    with http_open(request, opener=opener) as resp, open(dest, "wb") as out:
        length = resp.headers.get("Content-Length") or ""
        if limit is not None and length.isdigit() and int(length) > limit:
            raise HelperError(too_large)
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            out.write(chunk)
            total += len(chunk)
            if limit is not None and total > limit:
                raise HelperError(too_large)
    log.line("Downloaded %.1f MiB" % (total / 1048576.0))
    if sha256 and digest.hexdigest().lower() != sha256.lower():
        raise HelperError("Checksum mismatch for %s" % url)
    if sha256:
        log.line("%s verified" % algo.upper().replace("SHA", "SHA-"))
    return dest


def go_releases(force=False):
    ensure_dir(CACHE_DIR, 0o700)
    cache = os.path.join(CACHE_DIR, "go-releases.json")
    cached = read_json(cache)
    if not force and cached and time.time() - cached.get("fetched", 0) < 6 * 3600:
        return cached["releases"]
    arch = host_arch()[0]
    raw = json.loads(http_get("https://go.dev/dl/?mode=json&include=all").decode("utf-8"))
    releases = []
    for rel in raw:
        if not rel.get("stable"):
            continue
        version = rel.get("version", "")
        for item in rel.get("files", []):
            if item.get("os") == "linux" and item.get("arch") == arch and item.get("kind") == "archive":
                releases.append({
                    "version": version[2:] if version.startswith("go") else version,
                    "filename": item.get("filename"),
                    "sha256": item.get("sha256"),
                    "size": item.get("size"),
                })
                break
    write_json(cache, {"fetched": time.time(), "releases": releases})
    return releases


def version_key(version):
    return [int(part) if part.isdigit() else 0 for part in re.split(r"[.]", re.sub(r"(rc|beta).*$", "", version))]


def rust_latest_stable(force=False):
    ensure_dir(CACHE_DIR, 0o700)
    cache = os.path.join(CACHE_DIR, "rust-stable.json")
    cached = read_json(cache)
    if not force and cached and time.time() - cached.get("fetched", 0) < 6 * 3600:
        return cached["version"]
    text = http_get("https://static.rust-lang.org/dist/channel-rust-stable.toml").decode("utf-8", "replace")
    match = re.search(r'\[pkg\.rust\]\s*\nversion\s*=\s*"(\d+\.\d+\.\d+)', text)
    version = match.group(1) if match else None
    write_json(cache, {"fetched": time.time(), "version": version})
    return version


def _link_inside(name, linkname, hard=False):
    """True when a relative link target stays inside the archive tree."""
    while linkname.startswith("./"):
        linkname = linkname[2:]
    if not linkname or linkname.startswith("/"):
        return False
    target = os.path.normpath(os.path.join("" if hard else os.path.dirname(name), linkname))
    return target != ".." and not target.startswith("../")


def safe_extract(archive, dest, skip=None):
    """Extracts a .tar.gz after checking every member (no absolute paths, no '..', no devices,
    no links leaving the tree). Returns the member names (without a leading './')."""
    names = []
    with tarfile.open(archive, "r:gz") as tar:
        members = []
        for member in tar.getmembers():
            name = member.name
            while name.startswith("./"):
                name = name[2:]
            if name in ("", "."):
                continue
            if name.startswith("/") or ".." in name.split("/") or member.isdev() \
                    or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise HelperError("Refusing to extract suspicious archive member: %s" % name)
            if (member.issym() or member.islnk()) and not _link_inside(name, member.linkname, member.islnk()):
                raise HelperError("Refusing to extract suspicious link: %s" % name)
            if skip and name in skip:
                continue
            member.name = name
            # Toolchains are root-owned: never keep the archive's uid/gid (it may be a customer's).
            member.uid = member.gid = 0
            member.uname = member.gname = "root"
            members.append(member)
            names.append(name.rstrip("/"))
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, members=members, filter="tar")
        else:
            tar.extractall(dest, members=members)  # nosec - members checked above
    return names


def chmod_public(root):
    """Makes a toolchain tree readable/executable by all users and writable only by root."""
    as_root = os.geteuid() == 0
    for dirpath, dirnames, filenames in os.walk(root):
        if as_root:
            os.lchown(dirpath, 0, 0)
        os.chmod(dirpath, 0o755)
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            path = os.path.join(dirpath, name)
            if as_root:
                os.lchown(path, 0, 0)
            if os.path.islink(path):
                continue
            mode = os.stat(path).st_mode
            os.chmod(path, 0o755 if mode & 0o111 else 0o644)
