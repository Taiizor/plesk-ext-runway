# Copyright 2026 Taiizor. Licensed under the MIT License.

# ---------------------------------------------------------------------------
# Built-in updater (docs/DESIGN.md section 7): the extension is distributed through GitHub
# releases, so Plesk never offers updates for it. update-check reads releases/latest of
# UPDATE_REPO (cached), the "self-update" admin job downloads the versioned zip, verifies it
# against the release's SHA256SUMS and runs "plesk bin extension --upgrade".
# ---------------------------------------------------------------------------

def read_update_source():
    """The test-only release source: first line of UPDATE_SOURCE_FLAG, or None. Its content
    decides where root downloads packages from, so the file is only honoured while it and
    CONF_DIR are owned by root and writable by nobody else."""
    try:
        st = os.lstat(UPDATE_SOURCE_FLAG)
        parent = os.lstat(CONF_DIR)
    except OSError:
        return None
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022
            or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_mode & 0o022):
        return None
    lines = _read_text(UPDATE_SOURCE_FLAG, 4096).splitlines()
    return lines[0].strip() if lines and lines[0].strip() else None


def update_source():
    """The release source: GitHub, or the test-only source ("custom").
    {api, asset_base, page_base, custom, exact, insecure}: with GitHub (exact) an asset URL must
    be exactly <asset_base><tag>/<name> and the release page <page_base><tag>; with the test
    source both must lie below its scheme://host:port/ and end in /<tag>/<name> or /<tag>.
    insecure: redirects may lead to http:// (test source while FETCH_INSECURE_FLAG exists)."""
    custom = read_update_source()
    if custom is None:
        return {"api": UPDATE_API, "asset_base": UPDATE_ASSET_PREFIX, "page_base": UPDATE_PAGE_PREFIX,
                "custom": None, "exact": True, "insecure": False}
    insecure = fetch_insecure_allowed()
    allowed = ("https", "http") if insecure else ("https",)
    try:
        parts = urllib.parse.urlsplit(custom)
        valid = parts.port is None or parts.port > 0  # .port raises ValueError for a bad port
    except ValueError:
        parts, valid = None, False
    if (not valid or len(custom) > 2048 or RE_CTRL_ANY.search(custom) or " " in custom
            or parts.scheme not in allowed or not parts.hostname or "@" in parts.netloc):
        raise HelperError("The update source in %s is not a valid %s URL"
                          % (UPDATE_SOURCE_FLAG, " or ".join(allowed)))
    origin = "%s://%s/" % (parts.scheme, parts.netloc)
    return {"api": custom, "asset_base": origin, "page_base": origin, "custom": custom, "exact": False,
            "insecure": insecure}


def _update_url(value, source, what, tag, name=None):
    """A URL of the release answer: an asset `name` of the release `tag`, or (no name) the
    release page. It must have the scheme and host of the source, no query, fragment,
    percent-escape, backslash or whitespace, no empty, "." or ".." path segment, and its path
    must be exactly <base path><tag>[/<name>] (GitHub) or lie below the test source's origin and
    end in /<tag>[/<name>]. Plain string prefixes are not enough: dot segments would escape."""
    base = urllib.parse.urlsplit(source["asset_base"] if name else source["page_base"])
    tail = "%s/%s" % (tag, name) if name else tag
    try:
        parts = urllib.parse.urlsplit(value) if isinstance(value, str) else None
    except ValueError:
        parts = None
    path = parts.path if parts is not None else ""
    if source["exact"]:
        path_ok = path == base.path + tail
    else:
        path_ok = path.startswith(base.path) and path.endswith("/" + tail)
    if (parts is None or not path_ok or len(value) > 2048 or RE_CTRL_ANY.search(value)
            or re.search(r"[\s?#%\\]", value) or parts.scheme != base.scheme or parts.netloc != base.netloc
            or any(segment in ("", ".", "..") for segment in path.split("/")[1:])):
        raise HelperError("The release has an unexpected %s URL" % what)
    return value


class _UpdateRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects of the updater's requests: https:// only (http:// only for the test source
    while FETCH_INSECURE_FLAG exists), at most UPDATE_MAX_REDIRECTS hops. The default handler
    would also follow http:// and ftp:// targets, which would void the HTTPS promise for the
    package and for SHA256SUMS alike."""
    max_redirections = UPDATE_MAX_REDIRECTS

    def __init__(self, insecure):
        urllib.request.HTTPRedirectHandler.__init__(self)
        self.insecure = insecure

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        scheme = urllib.parse.urlsplit(newurl).scheme
        if scheme != "https" and not (self.insecure and scheme == "http"):
            raise HelperError("The release source redirected to a URL that is not https://: %s"
                              % RE_CTRL_ANY.sub("", newurl)[:200])
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def update_opener(source):
    """urllib opener of the updater (API answer and downloads): redirects are re-checked."""
    return urllib.request.build_opener(_UpdateRedirect(source["insecure"]))


def update_key(version, release):
    """Comparable (X, Y, Z, R) tuple of a version "X.Y.Z" and a package release R."""
    return tuple(int(part) for part in version.split(".")) + (int(release),)


def parse_update_full(value):
    """("X.Y.Z", R) of "X.Y.Z-R"."""
    match = RE_UPDATE_FULL.match(value) if isinstance(value, str) else None
    if not match:
        raise HelperError("Invalid version (expected X.Y.Z-R)")
    return match.group(1), int(match.group(2))


def parse_meta_xml(data):
    """(version, release, id) of a meta.xml document."""
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, ValueError):
        raise HelperError("meta.xml cannot be parsed")
    version = (root.findtext("version") or "").strip()
    release = (root.findtext("release") or "").strip()
    if not RE_UPDATE_VERSION.match(version) or not re.match(r"^\d{1,6}$", release):
        raise HelperError("meta.xml has no valid version and release")
    return version, int(release), (root.findtext("id") or "").strip()


def installed_version():
    """(version, release) of the installed extension from Plesk's copy of its meta.xml; the
    helper's VERSION and release 0 when it cannot be read."""
    try:
        with open(INSTALLED_META, "rb") as fh:
            version, release, _ = parse_meta_xml(fh.read(UPDATE_META_MAX))
        return version, release
    except (OSError, HelperError):
        return VERSION, 0


def read_package_meta(path):
    """(version, release, id) from meta.xml of an extension package (zip)."""
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("meta.xml")
            if info.file_size > UPDATE_META_MAX:
                raise HelperError("meta.xml of the package is too large")
            data = archive.read(info)
    except HelperError:
        raise
    except KeyError:
        raise HelperError("The package has no meta.xml")
    except Exception as exc:  # noqa: BLE001 - zipfile raises many types for broken archives
        raise HelperError("The package is not a valid zip archive: %s" % exc)
    return parse_meta_xml(data)


def parse_update_release(raw, source):
    """The validated release of a releases/latest answer, or None for a draft or prerelease:
    {tag, version, release, full, html_url, published_at, zip: {name, url, size}, sums_url}.
    The release notes (body) are not kept."""
    if not isinstance(raw, dict):
        raise HelperError("Unexpected answer from the release source")
    if raw.get("draft") or raw.get("prerelease"):
        return None
    tag = raw.get("tag_name")
    match = RE_UPDATE_TAG.match(tag) if isinstance(tag, str) else None
    if not match:
        raise HelperError("The latest release has an unexpected tag: %s" % str(tag)[:64])
    tag_version, tag_release = match.group(1), match.group(2)
    packages = []
    sums_url = None
    assets = raw.get("assets")
    for asset in assets if isinstance(assets, list) else []:
        name = asset.get("name") if isinstance(asset, dict) else None
        if not isinstance(name, str):
            continue
        found = RE_UPDATE_ZIP.match(name)
        if found and found.group(1) == tag_version and (tag_release is None or int(found.group(2)) == int(tag_release)):
            packages.append((found, asset))
        elif name == "SHA256SUMS":
            sums_url = _update_url(asset.get("browser_download_url"), source, "checksum", tag, name)
    if len(packages) != 1:
        raise HelperError("The latest release %s has no package runway-%s-<release>.zip that matches its tag"
                          % (tag, tag_version))
    if not sums_url:
        raise HelperError("The latest release %s has no SHA256SUMS file" % tag)
    found, asset = packages[0]
    size = asset.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > UPDATE_ZIP_MAX:
        raise HelperError("The package of the latest release %s has an unexpected size" % tag)
    published = raw.get("published_at")
    version, release = found.group(1), int(found.group(2))
    return {
        "tag": tag,
        "version": version,
        "release": release,
        "full": "%s-%d" % (version, release),
        "html_url": _update_url(raw.get("html_url"), source, "release page", tag),
        "published_at": published[:40] if isinstance(published, str) else None,
        "zip": {"name": asset["name"], "size": size,
                "url": _update_url(asset.get("browser_download_url"), source, "download", tag, asset["name"])},
        "sums_url": sums_url,
    }


def fetch_update_release(source):
    """The validated latest release; None when none is published yet (HTTP 404) or when it is a
    draft or prerelease. Other failures raise HelperError."""
    try:
        raw = http_json(source["api"], {"Accept": "application/vnd.github+json"}, timeout=UPDATE_API_TIMEOUT,
                        limit=1024 * 1024, opener=update_opener(source))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code in (403, 429):
            raise HelperError("GitHub API rate limit reached; try again later")
        raise HelperError("The release source answered HTTP %d" % exc.code)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        raise HelperError("The release source cannot be reached: %s" % (getattr(exc, "reason", None) or exc))
    return parse_update_release(raw, source)


def read_update_cache():
    cache = read_json(UPDATE_CACHE, {})
    return cache if isinstance(cache, dict) else {}


def write_update_cache(cache):
    ensure_dir(CACHE_DIR, 0o700)
    write_json(UPDATE_CACHE, cache)


def _epoch(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def update_status(cache=None):
    """Installed version, the cached result of the last check against the current source (no
    network) and the admin job."""
    if cache is None:
        cache = read_update_cache()
    custom = read_update_source()
    current = "source" in cache and cache.get("source") == custom
    version, release = installed_version()
    latest = cache.get("latest") if current and isinstance(cache.get("latest"), dict) else None
    available = False
    if latest:
        try:
            available = update_key(latest["version"], latest["release"]) > update_key(version, release)
        except (KeyError, TypeError, ValueError, AttributeError):
            latest = None
    return {
        "installed": "%s-%d" % (version, release),
        "installed_version": version,
        "installed_release": release,
        "latest": latest,
        "available": available,
        "checked_at": cache.get("checked_at") if current else None,
        "error": cache.get("error") if current else None,
        "update_source": custom,
        "last_failed_version": cache.get("last_failed_version"),
        "last_failed_at": cache.get("last_failed_at"),
        "job": job_get_status("admin"),
    }


def start_self_update(full):
    return start_admin_job("self-update", {"version": full}, "Update Runway to %s" % full,
                           title_key="self_update", title_params={"version": full})


def cmd_update_status(_payload):
    return update_status()


def cmd_update_check(payload):
    """Checks releases/latest unless the cache is fresh (12 hours; a forced check: 60 seconds).
    Failures are cached with checked_at as well. With auto_install, an available update starts
    the self-update job unless an admin job runs or the same version failed within 24 hours."""
    payload = payload or {}
    force = bool(payload.get("force"))
    source = update_source()
    custom = source["custom"]
    checked = False
    with FileLock("update"):
        cache = read_update_cache()
        same_source = "source" in cache and cache.get("source") == custom
        age = time.time() - _epoch(cache.get("checked_epoch"))
        if not same_source or not 0 <= age < (UPDATE_FORCE_MIN_AGE if force else UPDATE_CHECK_INTERVAL):
            cache.update({"source": custom, "checked_at": now_iso(), "checked_epoch": time.time()})
            try:
                cache["latest"] = fetch_update_release(source)
                cache["error"] = None
            except Exception as exc:  # noqa: BLE001 - cached, so a broken answer is not retried every run
                cache["error"] = str(exc) if isinstance(exc, HelperError) else "Unexpected release data: %s" % exc
                if not same_source:
                    cache["latest"] = None
            write_update_cache(cache)
            checked = True
    result = update_status(cache)
    result.update({"checked": checked, "started": False})
    latest = result["latest"]
    if payload.get("auto_install") and result["available"] and result["job"].get("state") not in ("queued", "running"):
        if (cache.get("last_failed_version") == latest["full"]
                and 0 <= time.time() - _epoch(cache.get("last_failed_epoch")) < UPDATE_RETRY_AFTER):
            result["auto_skipped"] = "Runway %s failed to install within the last 24 hours" % latest["full"]
        else:
            try:
                start_self_update(latest["full"])
                result["started"] = True
                result["job"] = job_get_status("admin")
            except HelperError as exc:
                result["auto_error"] = str(exc)
    return result


def cmd_update_install(payload):
    """Starts the self-update job for the version the administrator saw ("X.Y.Z-R")."""
    wanted = parse_update_full((payload or {}).get("version"))
    status = update_status()
    installed = (status["installed_version"], status["installed_release"])
    if update_key(*wanted) <= update_key(*installed):
        raise HelperError("Runway %s is installed; %s-%d is not newer" % (status["installed"], wanted[0], wanted[1]))
    latest = status["latest"]
    if not latest or not status["available"]:
        raise HelperError("No newer Runway release is available (installed: %s). Check for updates first."
                          % status["installed"])
    if update_key(*wanted) != update_key(latest["version"], latest["release"]):
        raise HelperError("Runway %s-%d is not the available update (%s): check for updates again."
                          % (wanted[0], wanted[1], latest["full"]))
    if status["job"].get("state") in ("queued", "running"):
        raise HelperError("Another background job (toolchain or update) is still running. "
                          "Please wait until it finishes.")
    result = start_self_update(latest["full"])
    result["version"] = latest["full"]
    return result


class _TailLog(object):
    """Job log wrapper that keeps the last bytes written (the output of a failed command)."""

    def __init__(self, log, keep=4000):
        self.log = log
        self.keep = keep
        self.tail = b""

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8", "replace")
        self.log.write(data)
        self.tail = (self.tail + data)[-self.keep:]

    def line(self, text):
        self.log.line(text)

    def text(self):
        return self.tail.decode("utf-8", "replace").strip()


def job_self_update(args, log):
    """Admin job "self-update": records a failure in the update cache (automatic installation
    then waits 24 hours before it tries the same version again) and removes the downloads."""
    wanted = args.get("version")
    try:
        _self_update(wanted, log)
    except BaseException:
        try:
            with FileLock("update"):
                cache = read_update_cache()
                cache.update({"last_failed_version": wanted if isinstance(wanted, str) else None,
                              "last_failed_at": now_iso(), "last_failed_epoch": time.time()})
                write_update_cache(cache)
        except Exception:  # noqa: BLE001 - best effort: the job reports the original error
            pass
        raise
    finally:
        shutil.rmtree(UPDATE_WORK_DIR, ignore_errors=True)


def _self_update(wanted, log):
    version, release = parse_update_full(wanted)
    target = update_key(version, release)
    source = update_source()
    cache = read_update_cache()
    latest = cache.get("latest") if cache.get("source") == source["custom"] else None
    if not isinstance(latest, dict) or latest.get("full") != wanted:
        raise HelperError("Runway %s is no longer the latest release: check for updates again." % wanted)
    # The cached release is checked again against the current source.
    package = latest.get("zip") if isinstance(latest.get("zip"), dict) else {}
    name = package.get("name")
    found = RE_UPDATE_ZIP.match(name) if isinstance(name, str) else None
    tag = latest.get("tag")
    tag_match = RE_UPDATE_TAG.match(tag) if isinstance(tag, str) else None
    if (not found or update_key(found.group(1), found.group(2)) != target or not tag_match
            or tag_match.group(1) != version
            or (tag_match.group(2) is not None and int(tag_match.group(2)) != release)):
        raise HelperError("The cached release does not describe Runway %s: check for updates again." % wanted)
    zip_url = _update_url(package.get("url"), source, "download", tag, name)
    sums_url = _update_url(latest.get("sums_url"), source, "checksum", tag, "SHA256SUMS")
    opener = update_opener(source)
    current = installed_version()
    if target <= update_key(*current):
        raise HelperError("Runway %s-%d is installed; %s is not newer." % (current[0], current[1], wanted))
    log.line("Updating Runway %s-%d to %s (release %s)" % (current[0], current[1], wanted, latest.get("tag")))

    shutil.rmtree(UPDATE_WORK_DIR, ignore_errors=True)
    ensure_dir(CACHE_DIR, 0o700)
    ensure_dir(UPDATE_WORK_DIR, 0o700)
    sums_path = os.path.join(UPDATE_WORK_DIR, "SHA256SUMS")
    download(sums_url, sums_path, None, log, limit=UPDATE_SUMS_MAX, opener=opener)
    with open(sums_path, "r", encoding="utf-8", errors="replace") as fh:
        expected = parse_shasums(fh.read()).get(name)
    if not expected:
        raise HelperError("SHA256SUMS of the release has no checksum for %s" % name)
    zip_path = os.path.join(UPDATE_WORK_DIR, name)
    download(zip_url, zip_path, expected, log, limit=UPDATE_ZIP_MAX, opener=opener)
    package_version, package_release, package_id = read_package_meta(zip_path)
    if package_id != EXTENSION_ID or update_key(package_version, package_release) != target:
        raise HelperError("The package is not Runway %s (meta.xml: %s %s-%d)"
                          % (wanted, package_id or "?", package_version, package_release))
    log.line("Package verified: meta.xml of %s %s-%d" % (package_id, package_version, package_release))
    current = installed_version()
    if target <= update_key(*current):
        raise HelperError("Runway %s-%d is installed; %s is not newer." % (current[0], current[1], wanted))

    # The upgrade replaces this helper's files, including /opt/runway/bin/runway-helper that
    # this job runs from (by rename: the running process keeps its copy). Nothing in the
    # upgrade stops runway-job-admin.service or removes the job files.
    plesk = shutil.which("plesk", path=ROOT_PATH) or "/usr/sbin/plesk"
    log.line("Running: plesk bin extension --upgrade %s" % zip_path)
    output = _TailLog(log)
    code = stream_process([plesk, "bin", "extension", "--upgrade", zip_path], output,
                          UPDATE_INSTALL_TIMEOUT, root_env(), cwd="/")
    if code != 0:
        raise HelperError("plesk bin extension --upgrade failed (exit %d): %s"
                          % (code, output.text()[-1500:] or "no output"))
    current = installed_version()
    if update_key(*current) != target:
        raise HelperError("plesk bin extension --upgrade finished, but Plesk reports Runway %s-%d instead of %s"
                          % (current[0], current[1], wanted))
    with FileLock("update"):
        cache = read_update_cache()
        if cache.get("last_failed_version") == wanted:
            cache.update({"last_failed_version": None, "last_failed_at": None, "last_failed_epoch": None})
            write_update_cache(cache)
    log.line("Runway %s is installed. Reload the Runway pages in the browser to use it." % wanted)
