# Runtime notes: php (detected Plesk handlers + managed FrankenPHP)

Status of facts: **[verified]** = checked on 2026-11-11 inside the `grt-plesk` container (Plesk
18.0.82, Ubuntu 24.04, handlers PHP 8.3.36 / 8.4.27, Composer 2.11.1, FrankenPHP v1.13.5 static
binary, Laravel 12 + Octane 2.24) or against the official source. **[unverified]** = from docs
excerpts/memory, to be checked by the implementer.

Design summary (DESIGN.md §5.2): PHP interpreters are *detected* from the Plesk PHP handlers
(`/opt/plesk/php/<x.y>/bin/php`); the only *managed* download is the **FrankenPHP** static binary
(`/opt/runway/frankenphp/<ver>/frankenphp`). Composer is Plesk's `composer.phar`. Apps run as
systemd services (Octane/FrankenPHP, `frankenphp php-server`, or `php -S` fallback).

---

## 1. Version discovery

### 1a. Plesk PHP handlers (detected) **[verified]**

Three equivalent sources, pick the first that exists:

1. `/etc/psa/php_versions.json` (root-readable file, no subprocess):

```json
{"php":[
 {"id":"plesk-php84-fpm","path":"/opt/plesk/php/8.4/sbin/php-fpm","clipath":"/opt/plesk/php/8.4/bin/php",
  "phpini":"/opt/plesk/php/8.4/etc/php.ini","version":"8.4.27","displayname":"%24version","type":"fpm",
  "system":true,"service":"plesk-php84-fpm","poold":"/opt/plesk/php/8.4/etc/php-fpm.d"},
 {"id":"plesk-php84-cgi","path":"/opt/plesk/php/8.4/bin/php-cgi","clipath":"/opt/plesk/php/8.4/bin/php",
  "phpini":"/opt/plesk/php/8.4/etc/php.ini","version":"8.4.27","displayname":"%24version","type":"cgi","system":true}]}
```

2. `plesk bin php_handler --list -json true` → JSON array:
   `[{"id":"plesk-php84-fpm","displayname":"8.4.27","fullVersion":"8.4.27","version":"8.4","type":"fpm",
   "path":"/opt/plesk/php/8.4/sbin/php-fpm","clipath":"/opt/plesk/php/8.4/bin/php",
   "phpini":"/opt/plesk/php/8.4/etc/php.ini","custom":true,"status":"enabled"}, …]`
   (`-json` needs the literal `true`; without it the command prints the table shown in 3).
3. `plesk bin php_handler --list` → table with columns `id, display name, full version, version,
   type, cgi-bin, php-cli, php.ini, custom, status` (one row per handler: cgi, fastcgi, fpm,
   fpm-dedicated per PHP version).
4. Fallback: glob `/opt/plesk/php/*/bin/php` and run `<php> -r 'echo PHP_VERSION;'`.

De-duplicate by `clipath` (four handlers share one CLI binary). Entries:
`{"id": "8.4", "label": "PHP 8.4.27 (Plesk)", "path": "/opt/plesk/php/8.4/bin/php"}`; also offer
the OS PHP (`/usr/bin/php`) when present (not on a stock Plesk). `version_re`: `^\d+\.\d+$`.

### 1b. FrankenPHP (managed) **[verified]**

- Repository moved to **`php/frankenphp`** (the old `dunglas/frankenphp` URL redirects, but download
  URLs are `https://github.com/php/frankenphp/releases/download/<tag>/<asset>`).
- `https://api.github.com/repos/php/frankenphp/releases/latest` (tag `v1.13.5`, 2026-11-05) or
  `…/releases?per_page=10` for the newest 10 tags (channel `latest` = newest tag). Tags **have** a `v`.
- Assets of v1.13.5 (name, bytes, `digest`):

```
frankenphp-linux-x86_64            177736160  sha256:cdb85dd2fd6c0468f53079e845c81621563024772ac400e5d1c17d0751324b71
frankenphp-linux-x86_64-gnu        182386600  sha256:1da3de11f32a3a3dca0dc52ce41f9dfc4037a4a18b58a4704a3d493e6cb4414c
frankenphp-linux-x86_64-mimalloc   177746632  (musl + mimalloc allocator, experimental)
frankenphp-linux-x86_64-debug      303595664  (unstripped)
frankenphp-linux-aarch64           173764552  sha256:72272e9b…
frankenphp-linux-aarch64-gnu       176898256  sha256:44ff0950…
frankenphp-mac-arm64, frankenphp-windows-x86_64.zip
```

- **There are no checksum files in the release**; the only published checksum is the GitHub API
  asset field `"digest": "sha256:<hex>"` (verified equal to `sha256sum` of the download). Use it;
  when the field is absent (old releases) mark the install as "unverified" in the log.
- Which asset: `frankenphp-linux-<x86_64|aarch64>` (musl, fully static, runs on every distro, no
  dynamic extension loading) is the Runway default; the `-gnu` variant (glibc ≥ 2.28, can load
  `.so` extensions) is what Laravel Octane downloads itself.
- Show: newest 10 tags (`v1.13.5` …) + channel `latest`. Octane 2.24 requires ≥ 1.13.2.

---

## 2. Download **[verified]**

- URL: `https://github.com/php/frankenphp/releases/download/v1.13.5/frankenphp-linux-x86_64`
  — a single ELF file (`static-pie linked`, Go build), ~178 MB, no archive, no inner layout.
- Store as `/opt/runway/frankenphp/<ver>/frankenphp` (strip the `v`: `1.13.5`), mode 0755 root.
  Download to a temp file, verify the `digest`, rename.
- Nothing else is needed: the binary embeds PHP 8.5.12 and Caddy 2.11.9 with 80 extensions
  (`frankenphp version` → `FrankenPHP v1.13.5 PHP 8.5.12 Caddy v2.11.9 h1:…`).
- Composer fallback when Plesk's phar is missing: `https://getcomposer.org/download/latest-stable/composer.phar`
  + `https://getcomposer.org/download/latest-stable/composer.phar.sha256` **[unverified URLs]**,
  stored as `/opt/runway/composer/composer.phar`.

---

## 3. Install layout, PATH and system dependencies

### Plesk PHP **[verified]**

```
/opt/plesk/php/8.4/bin/{php,php-cgi,phpdbg,pear,pecl,phar,lsphp}   # no php-config/headers unless plesk-php84-dev is installed
/opt/plesk/php/8.4/sbin/php-fpm
/opt/plesk/php/8.4/etc/php.ini  + etc/php.d/*.ini (opcache, mysqlnd, xdebug (off), imagick, intl, redis, …)
/opt/plesk/php/8.4/lib/php/modules/                                 # extension .so files
```

- CLI defaults of the Plesk php.ini: `memory_limit=128M`, `max_execution_time=0`,
  `disable_functions=` (empty), `open_basedir=` (empty), `opcache.enable_cli=0`. The per-domain
  `/var/www/vhosts/system/<domain>/etc/php.ini` (open_basedir, `disable_functions=opcache_get_status`)
  is **not** applied to the CLI binary unless passed with `-c` — Runway uses the plain CLI ini.
- Loaded modules of the 8.4 CLI include `pcntl posix sockets redis imagick intl pdo_mysql pgsql
  sqlite3 sodium zip` (full list: `php -m`); `swoole`/`openswoole` are **not** shipped.
- ini overrides without touching Plesk files: `PHPRC=<dir or file>` and `PHP_INI_SCAN_DIR=:<dir>`
  (leading `:` keeps the default scan dir) **[verified with 8.4]**.
- PATH entry for the user: `/opt/plesk/php/<x.y>/bin` (gives `php`, `pecl`, `phar`).

### Composer **[verified]**

- `/usr/lib/plesk-9.0/composer.phar` on Debian/Ubuntu, `/usr/lib64/plesk-9.0/composer.phar` on
  RHEL-family (Plesk KB 12376967222551); 3.8 MB, `Composer version 2.11.1 2026-10-30`, not owned by
  a package (Plesk's own updater refreshes it). Optional third location when the "Composer" extension
  is installed: `/usr/local/psa/var/modules/composer/composer.phar` **[KB, unverified]**.
- Invocation: `/opt/plesk/php/8.4/bin/php /usr/lib/plesk-9.0/composer.phar …`. Runway should ship a
  tiny wrapper `/opt/runway/bin/composer` (`#!/bin/sh` → `exec php "$COMPOSER_PHAR" "$@"`, with
  `COMPOSER_PHAR` resolved at install time) so `composer` works on PATH for customers.

### FrankenPHP **[verified]**

```
/opt/runway/frankenphp/1.13.5/frankenphp   (0755 root)
```

- No system dependencies (musl static). `-gnu` variant: glibc ≥ 2.28 **[docs]**.
- php.ini lookup of the static binary: `./php.ini` in the working directory, then
  `/etc/frankenphp/php.ini`, `/etc/frankenphp/php.d/*.ini`; `PHPRC` (dir or file) and
  `PHP_INI_SCAN_DIR` work **[verified]**. Nothing loaded by default → `memory_limit=128M`,
  `opcache.enable=1`. Default threads: 2 × CPUs (`total_threads 32` on the test host).
- Caddy state: `$XDG_DATA_HOME/caddy/{locks,instance.uuid,last_clean.json}` (falls back to
  `~/.local/share/caddy`), `$XDG_CONFIG_HOME/caddy/autosave.json` — set both XDG vars under
  `~/.runway` **[verified]**.
- `frankenphp php-cli script.php` works; `php-cli -v/-m/--ini` print *"this functionality is not
  available in frankenphp php-cli with a php version lower than 8.6"* — use a script to inspect.

### Swoole / RoadRunner (alternatives, not managed in 1.0)

- Swoole/OpenSwoole need a PECL build against the Plesk PHP (`apt-get install plesk-php84-dev
  gcc make` then `/opt/plesk/php/8.4/bin/pecl install swoole`) **[unverified]**; document only.
- RoadRunner: GitHub `roadrunner-server/roadrunner` v3.0.1 (2026-10-21), assets
  `roadrunner-3.0.1-linux-amd64.tar.gz` (23 MB), `-linux-arm64.tar.gz`, `.deb`, API `digest` present
  **[verified]**; under Octane it is obtained with `composer require spiral/roadrunner-cli
  spiral/roadrunner-http` + `./vendor/bin/rr get-binary` (writes `<app>/rr`). Octane always passes
  `-o http.address=<host>:<port>` → **tcp only with Octane**; standalone RoadRunner supports
  `http.address: "unix://${RUNWAY_SOCKET}"` (environment substitution of `.rr.yaml`) +
  `unix_socket: {mode: "0660"}` **[docs]**. Use the variable, not the literal
  `/run/runway/<id>/app.sock`: with zero-downtime deployments each slot has its own socket
  (README, "Zero-downtime deployments").

---

## 4. Per-user environment (`env(home, version)`)

```python
def env(self, home, version, frankenphp_version=None):
    rw = os.path.join(home, ".runway")
    paths = ["/opt/plesk/php/%s/bin" % version, "/opt/runway/bin"]   # composer wrapper
    if frankenphp_version:
        paths.insert(0, "/opt/runway/frankenphp/%s" % frankenphp_version)  # Octane finds `frankenphp` on PATH
    return {
        "PATH": paths,
        "COMPOSER_HOME": rw + "/composer",            # auth.json, global config  (default $XDG_CONFIG_HOME/composer)
        "COMPOSER_CACHE_DIR": rw + "/composer/cache", # default $XDG_CACHE_HOME/composer
        "COMPOSER_NO_INTERACTION": "1",
        "COMPOSER_FUND": "0", "COMPOSER_PROCESS_TIMEOUT": "600",
        "COMPOSER_MEMORY_LIMIT": "-1",                # composer needs > 128M on big projects
        "XDG_DATA_HOME": rw + "/data",                # FrankenPHP/Caddy -> ~/.runway/data/caddy
        "XDG_CONFIG_HOME": rw + "/config",            # Caddy autosave; Octane's own stub uses these too
        "XDG_CACHE_HOME": rw + "/cache",
        "PHP_INI_SCAN_DIR": "",                       # leave unset; customers may set PHPRC in the app env
        "APP_ENV": "production",                      # Laravel convention; overridable by the app env text
    }
```

All `COMPOSER_*` names are from the Composer CLI docs **[verified]**; `composer install` as the
user with them wrote only to `~/.runway/composer/{cache,…}` and `<app>/vendor` **[verified]**.
Environment variables are visible to PHP in `$_SERVER` and `getenv()` under FrankenPHP
**[verified]** and `php -S`.

---

## 5. Detection and default commands

`inspect(app_dir)`:

| File | Parse | Meaning |
|---|---|---|
| `composer.json` | `name`, `require.php` (e.g. `"^8.3"` → pick a matching handler), `require["laravel/octane"]`, `require["laravel/framework"]`, `scripts` keys, `config.platform.php` | composer project; Laravel; Octane |
| `composer.lock`, `vendor/autoload.php` | present | lock → reproducible install; vendor → already built |
| `artisan` (file, executable bit irrelevant) | present | Laravel; run `php artisan …` |
| `config/octane.php` + `public/frankenphp-worker.php` | present | Octane installed for FrankenPHP (`octane:install` done) |
| `public/index.php` | present | document root = `public/` |
| `index.php` (root) | present, no `public/` | document root = app root |
| `frankenphp` (file in root), `Caddyfile`, `.rr.yaml`, `rr` | present | user-provided server config/binaries |
| `.env` / `.env.example` | `APP_KEY=` empty? | Laravel needs `php artisan key:generate` once |
| `worker.php` / `public/worker.php` | present | FrankenPHP worker mode script |

`defaults(inspect)`:

| Case | build_cmd | start_cmd (tcp) | start_cmd (unix) |
|---|---|---|---|
| composer.json | `composer install --no-dev --optimize-autoloader --no-interaction --no-progress` | | |
| Laravel + Octane (frankenphp installed) | above + `php artisan octane:install --server=frankenphp --no-interaction` (idempotent; copies `public/frankenphp-worker.php`) + `php artisan optimize` | Runway default (1.0, verified with Laravel 13 + Octane 2.24 + FrankenPHP 1.13.5 through nginx): `php artisan octane:frankenphp --caddyfile=.runway/Caddyfile --port=$PORT --admin-port=$PORT`; Octane's own `octane:start ... --host=$HOST --port=$PORT` listens on **all interfaces** and binds an admin port that the unit's `SocketBindDeny=any` refuses (crash loop) | `php artisan octane:frankenphp --caddyfile=.runway/Caddyfile --host=localhost` with the Runway Caddyfile below |
| Laravel without Octane, frankenphp installed | composer install + `php artisan optimize` | `frankenphp php-server --listen 127.0.0.1:$PORT -r public/` | `frankenphp php-server --listen "unix/$RUNWAY_SOCKET\|0660" -r public/` |
| any `public/index.php`, frankenphp installed | composer install (if composer.json) | `frankenphp php-server --listen $HOST:$PORT -r public/` (+ `-w public/worker.php` when present) | `frankenphp php-server --listen "unix/$RUNWAY_SOCKET\|0660" -r public/` |
| no frankenphp | composer install (if composer.json) | `php -S $HOST:$PORT -t public` (or `-t .`) | **tcp only** (`php -S unix:…` → `Invalid address`) → UI must force `listen=tcp` |

`$LISTEN_ADDR` (base env) equals `$HOST:$PORT` in tcp mode; for `frankenphp` unix mode the
`unix/…|0660` form must be used, not `$LISTEN_ADDR`.

### Server flags **[verified]**

- **`frankenphp php-server`**: `-l/--listen <addr>` (default **`:80`**, i.e. all interfaces →
  always pass it), `-r/--root <dir>`, `-w/--worker <file>` (repeatable), `--watch[=glob]`,
  `-a/--access-log`, `-v/--debug`, `--no-compress`, `-d/--domain <name>` (switches to HTTPS +
  ACME: never use behind nginx), `-m/--mercure`. Listen address grammar (Caddy):
  `host:port`, `127.0.0.1:8080`, `unix//abs/path.sock`, `unix//abs/path.sock|0660` — note **one**
  slash after `unix` when the path starts with `/` is what `--listen` accepted in tests
  (`unix/$RUNWAY_SOCKET|0660`); Caddy docs write `unix//path`. Default socket mode without the
  `|mode` suffix is **0200** (`s-w-------`): nginx (group psaserv) could not connect → always append
  `|0660`. Missing paths fall back to `index.php` (`try_files {path} index.php` behaviour built in:
  `/nope/xyz` → 200) so Laravel/Symfony front controllers work without a router. Logs are JSON on
  stderr; `HTTP/2 skipped because it requires TLS` warnings are normal.
- **Laravel Octane** (`octane:start`, Octane 2.24): `--server=frankenphp|roadrunner|swoole`,
  `--host=127.0.0.1`, `--port=8000`, `--admin-host=localhost`, `--admin-port=2019`,
  `--workers=auto`, `--max-requests=500`, `--caddyfile=<path>`, `--https`, `--http-redirect`,
  `--watch`, `--poll`, `--log-level`, `--rr-config` (RoadRunner), `--task-workers` (Swoole).
  Binary lookup: `ExecutableFinder()->find('frankenphp', null, [base_path()])` → **PATH first, then
  `<app>/frankenphp`**; when not found it downloads `frankenphp-linux-x86_64-gnu` (182 MB) into
  `<app>/frankenphp` (with `--no-interaction` the confirm defaults to yes) **[verified]**.
  It then runs `frankenphp run -c <Caddyfile>` with env `CADDY_SERVER_SERVER_NAME="http://:$PORT"`
  (**the `--host` value is ignored for the listener; the server binds `*:$PORT`** —
  `ss` showed `*:18092`) plus `APP_BASE_PATH`, `APP_PUBLIC_PATH`, `LARAVEL_OCTANE=1`, `MAX_REQUESTS`,
  `REQUEST_MAX_EXECUTION_TIME`, `CADDY_GLOBAL_OPTIONS=auto_https disable_redirects`,
  `CADDY_SERVER_ADMIN_HOST/PORT`, `CADDY_SERVER_LOG_LEVEL`, `CADDY_SERVER_LOGGER=json`,
  `CADDY_SERVER_WORKER_COUNT`, `CADDY_SERVER_WORKER_DIRECTIVE`, `CADDY_SERVER_EXTRA_DIRECTIVES`,
  `CADDY_SERVER_WATCH_DIRECTIVES` + `config('octane.caddy.env')`. State file:
  `storage/logs/octane-server-state.json` (`masterProcessId`, host, port, adminPort — Octane chose
  `12111` for port 18092, i.e. it derives a free admin port when the default would clash
  **[observed]**). `php artisan octane:status|stop|reload` use that file. The request is served by
  FrankenPHP's **embedded PHP 8.5.12 (ZTS)**, not by the Plesk handler (`/rwinfo` printed
  `8.5.12 frankenphp zts`); the Plesk PHP only runs `artisan`/`composer`.
- **Runway Caddyfile for Octane** (`.runway/Caddyfile`, written as the system user by the helper's
  `prepare_start()` before every start, from Octane's stub
  `vendor/laravel/octane/src/Commands/stubs/Caddyfile` or a built-in copy of the 2.24 stub: the
  `admin` line becomes `admin off` and the site line `{$CADDY_SERVER_SERVER_NAME} {` becomes
  `http://:{$PORT} {` + `bind 127.0.0.1` (tcp) or `http:// {` + `bind unix/{$RUNWAY_SOCKET}|0660`
  (unix)). The admin endpoint must be off: the unit allows only `bind()` of the application's port,
  and Caddy treats a refused admin listener as fatal. `--admin-port=$PORT` and, in unix mode,
  `--host=localhost` only satisfy Octane's port probe (`fsockopen` on 127.0.0.1 for the HTTP and
  the admin port); the Caddyfile ignores them. Verified in grt-plesk: tcp `ss` shows
  `127.0.0.1:20000` only, unix `srw-rw----` socket, `/` and `/up` 200 through nginx, no admin
  listener. The unix-mode file as originally researched (with the admin line that Runway now turns
  off) **[verified: socket `srw-rw----`, `/up` 200, no tcp listener]**:

```
{
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
http:// {
	bind unix/{$RUNWAY_SOCKET}|0660
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
```

  (`{$RUNWAY_SOCKET}` is expanded by Caddy from the unit environment. Writing the socket into the
  site address itself — `unix/…|0660 {` — is parsed as a *path* and fails; use `bind`.) In tcp
  mode Runway uses `http://:{$PORT} {` plus `bind 127.0.0.1`: a site address with a host adds a
  Host matcher, and nginx forwards the domain's `Host`.
- **`php -S`** (PHP CLI server): `php -S <addr>:<port> [-t docroot] [router.php]`, tcp only,
  one request at a time (`PHP_CLI_SERVER_WORKERS=<n>` forks workers in PHP ≥ 7.4 **[unverified]**),
  `php_sapi_name()` = `cli-server`; serves Laravel's `public/` with `/up` → 200 **[verified]**.
  Development-grade; the UI should label it "fallback".

---

## 6. Minimal sample app **[verified with php -S (8.4.27) and frankenphp php-server (8.5.12), tcp + unix]**

`sample()` writes `public/index.php`:

```php
<?php
// Runway sample app: served by `frankenphp php-server -r public/` (tcp or unix) or `php -S` (tcp).
header("Content-Type: text/plain; charset=utf-8");
echo "Hello from PHP " . PHP_VERSION . " (" . php_sapi_name() . ")\n";
```

and `.runway/worker.php` is **not** needed for the sample (request mode). Commands:

| listen | with managed FrankenPHP | without |
|---|---|---|
| tcp | `frankenphp php-server --listen $HOST:$PORT -r public/` | `php -S $HOST:$PORT -t public` |
| unix | `frankenphp php-server --listen "unix/$RUNWAY_SOCKET\|0660" -r public/` | n/a (tcp only) |

Expected: `curl --unix-socket /run/runway/<id>/app.sock http://localhost/` →
`Hello from PHP 8.5.12 (frankenphp)`; `curl http://127.0.0.1:$PORT/` → `Hello from PHP 8.4.27 (cli-server)`.

Optional worker-mode sample (`-w public/worker.php`) **[verified]**:

```php
<?php
ignore_user_abort(true);
$handler = static function () { header("Content-Type: text/plain"); echo "worker hi " . PHP_VERSION . "\n"; };
$max = (int) ($_SERVER["MAX_REQUESTS"] ?? 0); $n = 0;
while (frankenphp_handle_request($handler)) { gc_collect_cycles(); if ($max && ++$n >= $max) { break; } }
```

---

## 7. Pitfalls and verification commands

- **Two PHPs**: under Octane/FrankenPHP the web requests run on the embedded PHP (8.5.x, ZTS,
  fixed extension set of 80: no `imap`, `xdebug`, `swoole`, `newrelic`; `imagick` is bundled but
  unsupported with OpenMP). `composer install` runs on the Plesk handler and will complain about
  `require.php`/`platform` mismatches only in that direction. Explain this in the UI help.
- **Octane binds all interfaces** (`http://:$PORT`) and an admin port: Runway's Caddyfile (above)
  fixes both; `octane:reload`/`octane:status` need the admin endpoint and do not work under Runway
  (restart the service instead). Admin endpoint listens on
  `localhost:<adminPort>`; with several Octane apps make sure ports differ (Octane picks a free one
  when 2019 is taken **[observed]**; passing `--admin-port=$((PORT+10000))` is deterministic).
- **Octane downloads a 182 MB binary into the app root** when `frankenphp` is neither on PATH nor
  in the app root; Runway must put `/opt/runway/frankenphp/<ver>` on PATH *before* `octane:install`
  / `octane:start`, and `inspect` should flag a user-supplied `<app>/frankenphp` (it wins over PATH
  only when PATH has none; `ExecutableFinder` checks PATH first).
- `octane:start` keeps running in the foreground and spawns `frankenphp run`; systemd's default
  `KillMode=control-group` stops both. `php artisan octane:stop` is not needed by Runway.
- First boot failure mode: `worker script has failed on restart … has not reached
  frankenphp_handle_request()` means the Laravel app itself throws while booting (missing `.env`/
  `APP_KEY`, DB session table missing, …) **[verified by provoking it]**; show the deploy/app log and
  suggest `php artisan key:generate`, `migrate --force`, `SESSION_DRIVER=file`.
- Unix socket default mode is 0200 — always `|0660` in `--listen`/`bind`.
- `frankenphp php-server --domain` enables HTTPS/ACME and the Mercure hub; never pass it behind nginx.
- `php -S` cannot listen on unix sockets; `listen=unix` must be rejected for that start command.
- Composer: `COMPOSER_MEMORY_LIMIT=-1` avoids `Allowed memory size of 134217728 bytes exhausted`
  with the Plesk CLI ini (128M); `--no-dev` drops `require-dev`; `post-install-cmd` scripts of the
  project run (Laravel's `package:discover`) — keep `--no-scripts` only for untrusted projects.
- Plesk updates replace `composer.phar` automatically; never patch it. Keep the optional Runway
  download fallback behind the Plesk phar.
- FrankenPHP/Caddy writes under `XDG_DATA_HOME`/`XDG_CONFIG_HOME` only (verified); without the
  vars it creates `~/.local/share/caddy` in the subscription home — set them.
- Static-binary TLS trust: outgoing HTTPS from PHP (curl/openssl) in the musl binary needs
  `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt` (Debian/Ubuntu) or
  `SSL_CERT_DIR=/etc/pki/tls/certs` (RHEL) per FrankenPHP known issues **[docs]** — add to `env()`
  when the file exists.
- Memory: Octane keeps the app in memory per worker (~50-100 MB each, default workers = CPU
  count); set `--workers=2` as default. A PHP fatal hitting `memory_limit` can stop the whole
  FrankenPHP server (docs) → systemd `Restart=on-failure` from the base covers it.

Verification commands and expected output **[verified]**:

```
/opt/plesk/php/8.4/bin/php --version | head -1   → PHP 8.4.27 (cli) (built: …) (NTS)
/opt/plesk/php/8.4/bin/php /usr/lib/plesk-9.0/composer.phar --version → Composer version 2.11.1 2026-10-30 14:52:10
plesk bin php_handler --list -json true | python3 -c 'import json,sys; print([h["clipath"] for h in json.load(sys.stdin)])'
/opt/runway/frankenphp/1.13.5/frankenphp version  → FrankenPHP v1.13.5 PHP 8.5.12 Caddy v2.11.9 h1:…
/opt/runway/frankenphp/1.13.5/frankenphp build-info | grep 'dep.*dunglas/frankenphp' → dep github.com/dunglas/frankenphp v1.13.5
echo '<?php echo PHP_VERSION, " ", count(get_loaded_extensions()), "\n";' > /tmp/i.php && frankenphp php-cli /tmp/i.php → 8.5.12 80
frankenphp php-server --listen 'unix//run/runway/1/app.sock|0660' -r public/ ; curl --unix-socket /run/runway/1/app.sock http://localhost/ → app output, socket srw-rw----
php artisan octane:start --server=frankenphp --host=127.0.0.1 --port=$PORT ; curl http://127.0.0.1:$PORT/up → 200
```
