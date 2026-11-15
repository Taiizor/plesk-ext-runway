# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Fetch mode: download a prebuilt binary or an archive into the application root
# ---------------------------------------------------------------------------

def fetch_insecure_allowed():
    try:
        st = os.lstat(FETCH_INSECURE_FLAG)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == 0


def check_fetch_url(url, allow_insecure, resolve=True):
    """https only; with resolve, every address of the host must be public (no loopback, private,
    link-local or reserved ranges), so customers cannot reach internal services. This early check
    gives a clear error; the connection itself goes through _pinned_connect, which checks the
    addresses again and connects to exactly the address it checked (no DNS-rebinding window)."""
    if not isinstance(url, str) or not url or len(url) > 2048 or RE_CTRL_ANY.search(url) or " " in url:
        raise HelperError("Invalid download URL")
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        raise HelperError("Invalid download URL")
    if parts.scheme != "https" and not (allow_insecure and parts.scheme == "http"):
        raise HelperError("Only https:// URLs can be fetched")
    if not parts.hostname or "@" in parts.netloc:
        raise HelperError("Invalid download URL (no host name, or credentials in the URL)")
    if not resolve or allow_insecure:
        return
    _public_addresses(parts.hostname, port or 443)


def _public_addresses(host, port):
    """getaddrinfo() of host, refusing the whole answer when any address is not public."""
    try:
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise HelperError("Cannot resolve %s: %s" % (host, exc))
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise HelperError("Refusing to download from a non-public address (%s)" % address)
    return infos


def _pinned_connector(allow_insecure):
    """socket.create_connection replacement for http.client: resolves the host once, checks every
    address and connects to one of the checked addresses. TLS still verifies the certificate
    against the host name (SNI), only the address lookup is pinned."""
    def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
        if allow_insecure:
            return socket.create_connection(address, timeout, source_address)
        host, port = address[0], address[1]
        last = None
        for family, socktype, proto, _canon, sockaddr in _public_addresses(host, port):
            sock = None
            try:
                sock = socket.socket(family, socktype, proto)
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                if source_address:
                    sock.bind(source_address)
                sock.connect(sockaddr)
                return sock
            except OSError as exc:
                last = exc
                if sock is not None:
                    sock.close()
        raise last if last is not None else OSError("Cannot connect to %s" % host)
    return connect


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allow_insecure):
        urllib.request.HTTPSHandler.__init__(self, context=ssl.create_default_context())
        self.allow_insecure = allow_insecure

    def https_open(self, req):
        connector = _pinned_connector(self.allow_insecure)

        def factory(host, **kwargs):
            conn = http.client.HTTPSConnection(host, **kwargs)
            conn._create_connection = connector
            return conn
        return self.do_open(factory, req, context=self._context)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    """Plain http:// is only reachable with the root-only test flag (check_fetch_url)."""

    def __init__(self, allow_insecure):
        urllib.request.HTTPHandler.__init__(self)
        self.allow_insecure = allow_insecure

    def http_open(self, req):
        if not self.allow_insecure:
            raise HelperError("Only https:// URLs can be fetched")
        connector = _pinned_connector(self.allow_insecure)

        def factory(host, **kwargs):
            conn = http.client.HTTPConnection(host, **kwargs)
            conn._create_connection = connector
            return conn
        return self.do_open(factory, req)


class _FetchRedirect(urllib.request.HTTPRedirectHandler):
    """Re-checks every redirect target with check_fetch_url."""

    def __init__(self, allow_insecure):
        urllib.request.HTTPRedirectHandler.__init__(self)
        self.allow_insecure = allow_insecure

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_fetch_url(newurl, self.allow_insecure)
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def v_fetch(value):
    if not isinstance(value, dict):
        raise HelperError("Invalid fetch request")
    url = str(value.get("url") or "").strip()
    sha = str(value.get("sha256") or "").strip().lower()
    if sha and not re.match(r"^[0-9a-f]{64}$", sha):
        raise HelperError("Invalid SHA-256 checksum (64 hexadecimal digits)")
    filename = str(value.get("filename") or "").strip()
    if filename and not RE_FETCH_NAME.match(filename):
        raise HelperError("Invalid file name")
    check_fetch_url(url, fetch_insecure_allowed(), resolve=False)
    return {"url": url, "sha256": sha, "extract": bool(value.get("extract")), "filename": filename,
            "build": bool(value.get("build"))}


def fetch_file_name(state, url):
    """A single downloaded file replaces ./<name> of the start command, else keeps the URL's
    file name, else becomes 'app'."""
    match = re.match(r"^\./([A-Za-z0-9_+-][A-Za-z0-9._+-]{0,127})(\s|$)", state.get("start_cmd") or "")
    if match:
        return match.group(1)
    name = os.path.basename(urllib.parse.urlsplit(url).path)
    return name if RE_FETCH_NAME.match(name) else "app"


def fetch_into_app(state, pw, spec, log):
    if not spec["extract"] and not spec["filename"]:
        spec["filename"] = fetch_file_name(state, spec["url"])
    log.line("Fetching %s as %s" % (spec["url"], pw.pw_name))
    result = call_as_user(pw, _user_fetch, state["app_dir"], spec, fetch_insecure_allowed(),
                          timeout=min(FETCH_TIMEOUT, state["build_timeout"]), fsize=4 * FETCH_MAX_BYTES)
    for message in result.get("messages") or []:
        log.line(message)


def _user_fetch(app_dir, spec, allow_insecure):
    """Runs as the customer: downloads spec["url"] into the application root (500 MB cap), verifies
    the SHA-256 when given, then saves it as an executable file or extracts the archive."""
    check_fetch_url(spec["url"], allow_insecure)
    # No proxies (the address check must apply to the real peer), pinned address lookups and a
    # scheme/address re-check of every redirect target.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHTTPSHandler(allow_insecure),
                                         _PinnedHTTPHandler(allow_insecure), _FetchRedirect(allow_insecure))
    request = urllib.request.Request(spec["url"], headers={"User-Agent": USER_AGENT})
    fd, tmp = tempfile.mkstemp(prefix=".runway-fetch-", dir=app_dir)
    messages = []
    digest = hashlib.sha256()
    total = 0
    limit = "The download is larger than %d MB" % (FETCH_MAX_BYTES // 1048576)
    try:
        with os.fdopen(fd, "wb") as out:
            with opener.open(request, timeout=HTTP_TIMEOUT) as resp:
                final_url = resp.geturl()
                length = resp.headers.get("Content-Length") or ""
                if length.isdigit() and int(length) > FETCH_MAX_BYTES:
                    raise HelperError(limit)
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > FETCH_MAX_BYTES:
                        raise HelperError(limit)
                    digest.update(chunk)
                    out.write(chunk)
        sha = digest.hexdigest()
        messages.append("Downloaded %.1f MiB from %s" % (total / 1048576.0, final_url))
        if spec.get("sha256"):
            if sha != spec["sha256"]:
                raise HelperError("SHA-256 mismatch: expected %s, got %s" % (spec["sha256"], sha))
            messages.append("SHA-256 verified")
        else:
            messages.append("SHA-256 %s (not verified: no checksum given)" % sha)
        if spec.get("extract"):
            with open(tmp, "rb") as fh:
                magic = fh.read(4)
            if magic[:2] == b"\x1f\x8b":
                count = _user_extract_tar(tmp, app_dir)
            elif magic == b"PK\x03\x04":
                count = _user_extract_zip(tmp, app_dir)
            else:
                raise HelperError("Unsupported archive format (expected .tar.gz or .zip)")
            messages.append("Extracted %d entries into %s" % (count, app_dir))
        else:
            dest = os.path.join(app_dir, spec["filename"])
            if os.path.islink(dest) or os.path.isdir(dest):
                raise HelperError("%s is a directory or a symbolic link" % spec["filename"])
            os.chmod(tmp, 0o750)
            os.rename(tmp, dest)
            tmp = None
            messages.append("Saved as %s (executable)" % spec["filename"])
    finally:
        if tmp:
            remove_quietly(tmp)
    return {"messages": messages, "bytes": total, "sha256": sha}


def _unsafe_archive_path(name):
    """Member names that could leave the extraction directory: absolute, with ".." segments or
    backslashes (the shape of this check is also what CodeQL's TarSlip query recognises)."""
    return name.startswith("/") or "\\" in name or ".." in name.split("/")


def _user_extract_tar(archive, dest):
    with tarfile.open(archive, "r:*") as tar:
        members = []
        total = 0
        for member in tar:
            name = member.name
            while name.startswith("./"):
                name = name[2:]
            if name in ("", "."):
                continue
            member.name = name
            if _unsafe_archive_path(member.name):
                raise HelperError("Refusing to extract suspicious archive member: %s" % name[:200])
            if member.isdev() or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise HelperError("Refusing to extract suspicious archive member: %s" % name[:200])
            if (member.issym() or member.islnk()) and not _link_inside(name, member.linkname, member.islnk()):
                raise HelperError("Refusing to extract a link that leaves the archive: %s" % name[:200])
            total += max(member.size, 0)
            if len(members) >= 100000 or total > 4 * FETCH_MAX_BYTES:
                raise HelperError("The archive is too large to extract")
            members.append(member)
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, members=members, filter="data")
        else:
            tar.extractall(dest, members=members)  # nosec - members checked above
    return len(members)


def _user_extract_zip(archive, dest):
    count = 0
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > 100000 or sum(info.file_size for info in infos) > 4 * FETCH_MAX_BYTES:
            raise HelperError("The archive is too large to extract")
        for info in infos:
            if _unsafe_archive_path(info.filename):
                raise HelperError("Refusing to extract suspicious archive member: %s" % info.filename[:200])
        for info in infos:
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                continue  # symbolic links are not restored from zip archives
            path = zf.extract(info, dest)
            if not info.is_dir() and mode & 0o111:
                os.chmod(path, 0o750)  # zipfile does not restore Unix modes
            count += 1
    return count
