# Copyright 2026 Taiizor. Licensed under the MIT License.

# --- PHP (detected Plesk handlers + managed FrankenPHP) ------------------------

class PhpRuntime(Runtime):
    key = "php"
    label = "PHP"
    toolchain = "detected"
    version_re = r"^(system|plesk-\d+\.\d+|frankenphp-\d+\.\d+\.\d+)$"
    hint = ("Plesk PHP versions (php -S, Composer) are detected; FrankenPHP (static binary from GitHub, "
            "verified with SHA-256) can be installed for production servers and unix sockets.")
    install_help = ("PHP versions come from Plesk (Tools & Settings > Updates > PHP interpreter versions). "
                    "FrankenPHP versions can be installed here.")
    docs_url = "https://frankenphp.dev/docs/"
    unix_toolchain_re = r"^frankenphp-"
    public_dirs = ("public", "web")
    defaults_per_toolchain = True
    fp_root = BASE_DIR + "/frankenphp"
    _plesk = None

    def plesk_versions(self):
        """{minor: full version} of the Plesk PHP CLI binaries."""
        if self._plesk is not None:
            return self._plesk
        found = {}
        data = read_json("/etc/psa/php_versions.json")
        for item in (data.get("php") if isinstance(data, dict) else None) or []:
            clipath = str(item.get("clipath") or "") if isinstance(item, dict) else ""
            match = re.match(r"^/opt/plesk/php/(\d+\.\d+)/bin/php$", clipath)
            if match and os.path.isfile(clipath):
                full = str(item.get("version") or "")
                found[match.group(1)] = full if re.match(r"^\d+\.\d+\.\d+$", full) else match.group(1)
        for name in _listdir("/opt/plesk/php"):
            if re.match(r"^\d+\.\d+$", name) and os.path.isfile("/opt/plesk/php/%s/bin/php" % name):
                found.setdefault(name, name)
        self._plesk = found
        return found

    def list_installed(self):
        result = []
        plesk = self.plesk_versions()
        for minor in sorted(plesk, key=num_key, reverse=True):
            result.append({"id": "plesk-" + minor, "label": "PHP %s (Plesk)" % plesk[minor],
                           "path": "/opt/plesk/php/%s/bin/php" % minor, "kind": "detected"})
        if os.path.isfile("/usr/bin/php"):
            result.append({"id": "system", "label": "PHP (system /usr/bin/php)", "path": "/usr/bin/php",
                           "kind": "detected"})
        for name in sorted(_listdir(self.fp_root), key=num_key, reverse=True):
            path = os.path.join(self.fp_root, name, "frankenphp")
            if re.match(r"^\d+\.\d+\.\d+$", name) and os.path.isfile(path):
                result.append({"id": "frankenphp-" + name, "label": "FrankenPHP " + name, "path": path,
                               "kind": "managed"})
        return result

    def releases(self, force=False):
        asset = "frankenphp-linux-" + machine_arch()
        result = []
        for rel in github_releases("php/frankenphp", force, per_page=20):
            match = re.match(r"^v(\d+\.\d+\.\d+)$", rel["tag"])
            if match and not rel["prerelease"] and asset in rel["assets"]:
                result.append({"version": match.group(1), "asset": rel["assets"][asset]})
        result.sort(key=lambda r: num_key(r["version"]), reverse=True)
        return result

    def list_available(self, force=False):
        return [{"id": "frankenphp-" + r["version"], "label": "FrankenPHP " + r["version"]}
                for r in self.releases(force)[:10]]

    def check_installable(self, version):
        if not version.startswith("frankenphp-"):
            raise HelperError(self.install_help)

    def install(self, version, log):
        version = self.check_version(version)
        self.check_installable(version)
        number = version[len("frankenphp-"):]
        target = os.path.join(self.fp_root, number)
        if os.path.isfile(target + "/frankenphp"):
            log.line("FrankenPHP %s is already installed." % number)
            return
        rel = next((r for r in self.releases(force=True) if r["version"] == number), None)
        if not rel:
            raise HelperError("FrankenPHP %s was not found in the release list" % number)
        sha = rel["asset"].get("sha256")
        if not sha:
            log.line("WARNING: the release publishes no checksum for this file; the download is NOT verified.")
        ensure_dir(self.fp_root)
        work = tempfile.mkdtemp(prefix=".tmp-", dir=self.fp_root)
        try:
            stage = os.path.join(work, number)
            os.mkdir(stage, 0o755)
            download(https_url(rel["asset"]["url"]), stage + "/frankenphp", sha, log)
            os.chmod(stage + "/frankenphp", 0o755)
            proc = run([stage + "/frankenphp", "version"], timeout=60,
                       env=root_env({"XDG_DATA_HOME": work + "/data", "XDG_CONFIG_HOME": work + "/config"}))
            if proc.returncode != 0:
                raise HelperError("frankenphp version failed: %s" % (proc.stderr or proc.stdout).strip()[-300:])
            log.line(proc.stdout.strip())
            swap_dir(stage, target, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        log.line("FrankenPHP %s installed to %s" % (number, target))

    def remove(self, version):
        version = self.check_version(version)
        if not version.startswith("frankenphp-"):
            Runtime.remove(self, version)
        self._remove_dir(self.fp_root, version[len("frankenphp-"):])

    def is_installed(self, version):
        if version.startswith("frankenphp-"):
            return os.path.isfile(os.path.join(self.fp_root, version[len("frankenphp-"):], "frankenphp"))
        return Runtime.is_installed(self, version)

    def env(self, home, version, app_dir=None):
        rw = os.path.join(home, ".runway")
        paths = []
        if version.startswith("frankenphp-"):
            paths.append(os.path.join(self.fp_root, version[len("frankenphp-"):]))
            plesk = self.plesk_versions()
            if plesk:  # php CLI for Composer and artisan
                paths.append("/opt/plesk/php/%s/bin" % max(plesk, key=num_key))
        elif version.startswith("plesk-"):
            paths.append("/opt/plesk/php/%s/bin" % version[len("plesk-"):])
        paths.append(COMPOSER_BIN_DIR)
        return {
            "PATH": paths,
            "COMPOSER_HOME": rw + "/composer",
            "COMPOSER_CACHE_DIR": rw + "/composer/cache",
            "COMPOSER_NO_INTERACTION": "1",
            "COMPOSER_FUND": "0",
            "COMPOSER_PROCESS_TIMEOUT": "600",
            "COMPOSER_MEMORY_LIMIT": "-1",
            "XDG_DATA_HOME": rw + "/data",
            "XDG_CONFIG_HOME": rw + "/config",
            "XDG_CACHE_HOME": rw + "/cache",
            "APP_ENV": "production",
        }

    def inspect(self, app_dir):
        found = _files(app_dir, "composer.json", "composer.lock", "artisan", "public/index.php", "index.php",
                       "config/octane.php", "public/worker.php", "Caddyfile")
        if not found:
            return None
        info = {"composer": "composer.json" in found, "lockfile": "composer.lock" in found,
                "artisan": "artisan" in found, "public": "public/index.php" in found,
                "root_index": "index.php" in found, "worker": "public/worker.php" in found,
                "octane": False, "laravel": False}
        if info["composer"]:
            data = _json_file(os.path.join(app_dir, "composer.json"))
            require = data.get("require") if isinstance(data.get("require"), dict) else {}
            info["octane"] = "laravel/octane" in require
            info["laravel"] = "laravel/framework" in require
        return info

    def defaults(self, inspect, listen="tcp", toolchain=""):
        info = (inspect or {}).get("php") or {}
        build = "composer install --no-dev --optimize-autoloader --no-interaction --no-progress" \
            if info.get("composer") else ""
        docroot = "." if info.get("root_index") and not info.get("public") else "public/"
        unix = listen == "unix"
        if (toolchain or "").startswith("frankenphp-"):
            if info.get("octane") and info.get("artisan"):
                # Octane with Runway's Caddyfile (written before every start, see prepare_start):
                # admin endpoint off (the unit may bind only its own port) and the site bound to
                # 127.0.0.1:$PORT or the socket. Octane probes the HTTP and the admin port on
                # 127.0.0.1 before it starts: both are $PORT in TCP mode; in socket mode another
                # host than 127.0.0.1 skips that probe (the Caddyfile binds the socket).
                start = "php artisan octane:frankenphp --caddyfile=%s %s" % (
                    OCTANE_CADDYFILE, "--host=localhost" if unix else "--port=$PORT --admin-port=$PORT")
            else:
                address = '"unix/$RUNWAY_SOCKET|0660"' if unix else "$HOST:$PORT"
                start = "frankenphp php-server --listen %s -r %s" % (address, docroot)
                if info.get("worker") and docroot == "public/":
                    start += " -w public/worker.php"
            return {"build_cmd": build, "start_cmd": start}
        # php -S cannot listen on a unix socket: unix mode needs a FrankenPHP toolchain.
        return {"build_cmd": build, "start_cmd": "php -S $HOST:$PORT -t " + docroot.rstrip("/"),
                "unix_supported": False}

    def sample(self, listen, toolchain=""):
        return {"public/index.php": (SAMPLE_PHP, 0o640)}

    def prepare_start(self, state, pw):
        if OCTANE_CADDYFILE in (state.get("start_cmd") or ""):
            call_as_user(pw, _user_write_octane_caddyfile, state["app_dir"], state.get("listen"))

    def build_deps(self):
        return ["git", "unzip"]


OCTANE_CADDYFILE = ".runway/Caddyfile"
OCTANE_STUB = "vendor/laravel/octane/src/Commands/stubs/Caddyfile"
# Laravel Octane 2.24's stubs/Caddyfile: used when the project has no vendor/ copy yet.
OCTANE_CADDYFILE_STUB = """{
	{$CADDY_GLOBAL_OPTIONS}

	admin {$CADDY_SERVER_ADMIN_HOST}:{$CADDY_SERVER_ADMIN_PORT}

	frankenphp {
		worker {
			file "{$APP_PUBLIC_PATH}/frankenphp-worker.php"
			{$CADDY_SERVER_WORKER_DIRECTIVE}
			{$CADDY_SERVER_WATCH_DIRECTIVES}
		}
	}
}

{$CADDY_EXTRA_CONFIG}

{$CADDY_SERVER_SERVER_NAME} {
	log {
		level {$CADDY_SERVER_LOG_LEVEL}
		format filter {
			wrap {$CADDY_SERVER_LOGGER}
			fields {
				request>uri query {
					replace authorization REDACTED
				}
			}
		}
	}

	@compressible not path /.well-known/mercure

	route {
		root * "{$APP_PUBLIC_PATH}"
		encode @compressible zstd br gzip

		{$CADDY_SERVER_EXTRA_DIRECTIVES}

		php_server {
			index frankenphp-worker.php
			try_files {path} frankenphp-worker.php
			resolve_root_symlink
		}
	}
}
"""


def octane_caddyfile(stub, listen):
    """Runway's Caddyfile for Laravel Octane from Octane's own stub: the admin endpoint is turned
    off (the unit may bind only the application's port; Octane would bind 2019+) and the site
    address (Octane's "http://:$PORT", i.e. every interface) is replaced by 127.0.0.1:$PORT or the
    unix socket. Returns None when the stub does not look like Octane's."""
    if listen == "unix":
        site = ["http:// {", "\tbind unix/{$RUNWAY_SOCKET}|0660"]
    else:
        site = ["http://:{$PORT} {", "\tbind 127.0.0.1"]
    out = []
    site_done = admin_done = False
    for line in stub.splitlines():
        if re.match(r"^\s*admin(\s|$)", line):
            if not admin_done:
                out.append("\tadmin off")
                admin_done = True
            continue
        if not site_done and re.match(r"^\{\$CADDY_SERVER_SERVER_NAME\}\s*\{$", line.strip()):
            out += site
            site_done = True
            continue
        out.append(line)
    if not site_done:
        return None
    if not admin_done:
        first = next((i for i, line in enumerate(out) if line.strip() and not line.strip().startswith("#")), None)
        if first is None or out[first].strip() != "{":
            return None
        out.insert(first + 1, "\tadmin off")
    header = ["# Managed by the Plesk Runway extension: Laravel Octane's Caddyfile with the admin endpoint off",
              "# and the site bound to %s. Rewritten before every start; do not edit."
              % ("the unix socket RUNWAY_SOCKET" if listen == "unix" else "127.0.0.1:PORT")]
    return "\n".join(header + out) + "\n"


def _user_write_octane_caddyfile(app_dir, listen):
    """Runs as the customer: writes .runway/Caddyfile from the project's Octane stub (or the built-in
    copy) for the listen mode."""
    text = None
    stub = os.path.join(app_dir, OCTANE_STUB)
    if os.path.isfile(stub):
        try:
            text = octane_caddyfile(_read_small(stub, 65536), listen)
        except (HelperError, OSError):
            text = None
    if text is None:
        text = octane_caddyfile(OCTANE_CADDYFILE_STUB, listen)
    folder = os.path.join(app_dir, os.path.dirname(OCTANE_CADDYFILE))
    os.makedirs(folder, 0o750, exist_ok=True)
    if os.path.islink(folder):
        raise HelperError("%s is a symbolic link" % folder)
    fd = os.open(os.path.join(app_dir, OCTANE_CADDYFILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    return True
