# Runtime notes: ruby (detected: Plesk Ruby extension + system ruby)

Status of facts: **[verified]** = checked on 2026-11-11 inside the `grt-plesk` container (Plesk
18.0.82, Ubuntu 24.04, Plesk Ruby extension 1.7.0-21176 installed during research, rubies 3.2.10 /
3.3.10 / 3.4.9, system ruby 3.2.3, puma 8.0.2, Rails 8.1.4.1) or against the official source.
**[unverified]** = from memory/docs excerpts, to be checked.

Design summary (DESIGN.md §5.2): no managed install in 1.0. Runway *detects* interpreters provided
by the Plesk Ruby extension (`/opt/plesk/ruby/<ver>`) and the distro (`/usr/bin/ruby`), the
"install" tab only shows instructions. Gems/bundles live under `~/.runway/`.

---

## 1. Version discovery (detected toolchain)

There is no download source. `list_installed()` **[verified]**:

1. Plesk Ruby extension registry: `/etc/psa/ruby_versions.d/plesk-ruby-<ver>.json`, one file per
   interpreter, content exactly `{"version": "3.4.9", "path": "/opt/plesk/ruby/3.4.9"}`.
   Equivalent CLIs: `plesk sbin rubymng versions` (lines `3.4.9 /opt/plesk/ruby/3.4.9`) and
   `plesk ext ruby --versions` (table `Enabled Version Full version Path`, e.g.
   `true 3.4.9 3.4.9-p82 /opt/plesk/ruby/3.4.9`). Reading the JSON files is enough and needs no
   subprocess; also glob `/opt/plesk/ruby/*/bin/ruby` for custom builds registered later
   (Plesk KB: custom rubies are built with ruby-build into `/opt/plesk/ruby/<ver>` and registered with
   `plesk sbin rubymng register <ver> /opt/plesk/ruby/<ver>`).
2. System ruby: `/usr/bin/ruby` (`ruby3.2` symlink on Ubuntu 24.04; packages `ruby`, `ruby-dev`,
   `ruby-full` → candidate `1:3.2~ubuntu1`). On Debian 12: `ruby` 3.1; AlmaLinux 9: `ruby` 3.0 (+
   `ruby-devel`) **[unverified versions]**.
3. Version string: run `<bin>/ruby --version` → `ruby 3.4.9 (2026-03-11 revision 76cca827ab) +PRISM [x86_64-linux]`;
   id = `3.4.9` (from the directory name for Plesk rubies, from `--version` for the system ruby).

Returned entries, e.g.:

```python
[{"id": "3.4.9", "label": "Ruby 3.4.9 (Plesk)", "path": "/opt/plesk/ruby/3.4.9"},
 {"id": "system", "label": "Ruby 3.2.3 (system /usr/bin/ruby)", "path": "/usr"}]
```

`version_re`: `^(system|\d+\.\d+\.\d+)$`. `list_available()` returns `[]` with a hint text; the
"install" action of the UI shows:

- Plesk Ruby extension: `plesk bin extension --install ruby` (installs packages `plesk-ruby3.2.10`,
  `plesk-ruby3.3.10`, `plesk-ruby3.4.9` = 45 MB each, plus Passenger and the distro `ruby` package
  as dependency) **[verified, took 34 s]**.
- Distro ruby: `apt-get install ruby-full ruby-dev` / `dnf install ruby ruby-devel`.
- Build dependencies (see §3).

---

## 2. Download

Not applicable (no official prebuilt tarballs for Linux). Managed installs via `ruby-build` or
`ruby-install` are a possible 2.x feature (compile from source, ~5 min, needs the full dev toolchain).

---

## 3. Install layout and system dependencies

### Plesk Ruby extension layout **[verified]**

```
/opt/plesk/ruby/3.4.9/
  bin/{ruby,gem,bundle,bundler,irb,erb,rake,rdoc,ri,racc,rbs,rdbg,syntax_suggest,typeprof}
  include/ruby-3.4.0/            # headers: native gems compile without extra packages
  lib/x86_64-linux-gnu/ruby/3.4.0/            # rubylibdir
  lib/x86_64-linux-gnu/ruby/gems/3.4.0/       # Gem.default_dir (root-owned, read-only for users)
  lib/x86_64-linux-gnu/ruby/site_ruby/3.4.0/
  lib/x86_64-linux-gnu/libruby-static.a  pkgconfig/
```

- Bundler is bundled with each interpreter: 2.4.19 (3.2), 2.5.22 (3.3), 2.6.9 (3.4); RubyGems
  3.4.19 / 3.5.22 / 3.6.9.
- `RbConfig::CONFIG`: `prefix=/opt/plesk/ruby/3.4.9`, `bindir=<prefix>/bin`,
  `CC=x86_64-linux-gnu-gcc`, `LIBS=-lm -lpthread`; the interpreter is linked **statically**
  (`libruby-static.a`), native extensions therefore link `-lruby-static -lz -lgmp -lcrypt …`.
- Binary deps (`dpkg -s plesk-ruby3.4.9`): `libc6 ≥ 2.38, libcrypt1, libffi8, libgmp10, libssl3t64,
  libyaml-0-2, zlib1g` — satisfied by the package manager.
- Passenger (`passenger`, `libapache2-mod-passenger-plesk` 6.2.0.1) is installed with the extension
  but Runway does not use it (apps run under systemd + puma).
- Per-domain Ruby settings of the Plesk extension (`plesk ext ruby --get-version -domain x`) are
  independent from Runway; do not enable both on the same document root.

### System ruby layout (Ubuntu 24.04) **[verified]**

`/usr/bin/ruby -> ruby3.2`, `/usr/bin/gem` (3.4.20), no `/usr/bin/bundle` unless `ruby-bundler` is
installed (bundler ships as a *bundled gem* of ruby3.2: run it as `ruby -S bundle` or `gem install
bundler` into `GEM_HOME`). Headers come from `ruby-dev` (not installed by default).

### Build dependencies **[verified by failure + fix]**

`bundle install` with puma failed on a stock Plesk server:
`/usr/bin/ld: cannot find -lz` / `cannot find -lgmp` (`mkmf.log`, nio4r 2.7.5) — the static
libruby pulls `-lz -lgmp -lcrypt` into every native extension link. After
`apt-get install zlib1g-dev libgmp-dev` (plus `libyaml-dev libffi-dev` for psych/ffi) puma 8.0.2,
nio4r, unicorn/raindrops and a full Rails 8.1 bundle compiled fine.

`build_deps()` for ruby (status + `build-deps-install` job):

| Distro | Packages |
|---|---|
| Ubuntu/Debian | `build-essential zlib1g-dev libgmp-dev libyaml-dev libffi-dev libssl-dev` (+ `ruby-dev` for the system ruby, `libsqlite3-dev`, `libpq-dev`, `default-libmysqlclient-dev` for the usual DB gems) |
| AlmaLinux/RHEL 9 | `gcc gcc-c++ make zlib-devel gmp-devel libyaml-devel libffi-devel openssl-devel` (+ `ruby-devel`, `sqlite-devel`, `libpq-devel`, `mariadb-connector-c-devel`) **[unverified names]** |

Detection: `shutil.which("gcc")`, `which("make")`, and header/lib probes
`os.path.exists("/usr/include/zlib.h")`, `/usr/include/gmp.h` (Debian: `/usr/include/x86_64-linux-gnu/gmp.h`),
`/usr/include/yaml.h`, `/usr/include/ffi.h` or `/usr/include/x86_64-linux-gnu/ffi.h`, `/usr/include/openssl/ssl.h`,
`<prefix>/include/ruby-<x.y>.0/ruby.h` for the selected interpreter.

---

## 4. Per-user environment (`env(home, version)`)

```python
def env(self, home, version):
    prefix = "/usr" if version == "system" else "/opt/plesk/ruby/%s" % version
    rw = os.path.join(home, ".runway")
    gems = rw + "/gems"                 # gem install target and bin dir (~/.runway/gems/bin)
    return {
        "PATH": [gems + "/bin", prefix + "/bin"],      # app-local binstubs come first if the app adds ./bin itself
        "GEM_HOME": gems,                              # where `gem install` writes
        "GEM_SPEC_CACHE": gems + "/specs",             # default would be ~/.cache/gem or ~/.local/share/gem
        "BUNDLE_PATH": rw + "/bundle",                 # `bundle install` target (ruby/<abi>/gems inside)
        "BUNDLE_APP_CONFIG": rw + "/bundle-config",    # instead of <app>/.bundle/config
        "BUNDLE_USER_HOME": rw + "/bundle-user",       # instead of ~/.bundle (user config, cache, plugins)
        "BUNDLE_USER_CACHE": rw + "/bundle-user/cache",
        "BUNDLE_JOBS": "4",
        "BUNDLE_WITHOUT": "development:test",
        "BUNDLE_DEPLOYMENT": "",                       # leave unset: deployment mode requires a committed Gemfile.lock
        "BUNDLE_RETRY": "3", "BUNDLE_SILENCE_ROOT_WARNING": "1",
        "RAILS_ENV": "production", "RACK_ENV": "production",
        "RAILS_LOG_TO_STDOUT": "1",                    # Rails: log to journald instead of log/production.log
        "RAILS_SERVE_STATIC_FILES": "",                # unset: nginx serves /assets via static_paths
        "MALLOC_ARENA_MAX": "2",                       # standard RSS reducer for MRI
        "XDG_CACHE_HOME": rw + "/cache", "XDG_DATA_HOME": rw + "/data", "XDG_CONFIG_HOME": rw + "/config",
    }
```

- `bundle config` confirms the env names (output `Set via BUNDLE_APP_CONFIG: "…/.runway/bundle-config"`,
  `Set via BUNDLE_PATH`, `Set via BUNDLE_USER_HOME`, `Set via BUNDLE_WITHOUT: [:development, :test]`,
  `Set via BUNDLE_JOBS: 4`) **[verified]**. With these set, nothing is written to `~/.bundle`,
  `~/.gem`, `~/.local` or `<app>/.bundle` **[verified]**; gems land in
  `~/.runway/bundle/ruby/3.4.0/gems/` and `~/.runway/gems/{gems,bin,specs,extensions}`.
- **No `GEM_PATH`** (security review C11, verified): RubyGems uses `GEM_PATH` verbatim and adds
  the interpreter's default directory only when `GEM_PATH` is unset, so `GEM_PATH=~/.runway/gems`
  hid the bundled gems of Ruby 3.x (`rexml`, `csv`, ...) from applications without Bundler. With
  only `GEM_HOME` set, `Gem.path` is `GEM_HOME` plus the default directory.
- `GEM_HOME`/`GEM_SPEC_CACHE` are RubyGems' documented variables (`gem env` shows
  "USER INSTALLATION DIRECTORY: ~/.local/share/gem/ruby/3.4.0" and "SPEC CACHE DIRECTORY:
  ~/.cache/gem/specs" as the defaults we override) **[verified]**.
- `SECRET_KEY_BASE` is **not** set by Runway; the customer adds it to the app env (see §5).
- Keep `HOME` = subscription home (Bundler reads `~/.gemrc`; harmless).

---

## 5. Detection and default commands

`inspect(app_dir)` looks for:

| File | Parse | Meaning |
|---|---|---|
| `Gemfile` | `gem "puma"`, `gem "unicorn"`, `gem "rails"`, `gem "sinatra"`, `gem "falcon"`; `ruby "3.4.9"` / `ruby file: ".ruby-version"` line | bundler app; preferred server |
| `Gemfile.lock` | present → `--frozen`-style install is possible | |
| `.ruby-version` / `.tool-versions` | `3.4.9` or `ruby-3.4.9` / `ruby 3.4.9` | toolchain hint (match Plesk ruby by major.minor) |
| `config.ru` | present | Rack app (puma/unicorn/rackup) |
| `config/puma.rb` | present → pass `-C config/puma.rb` | |
| `bin/rails`, `config/application.rb` | present | Rails: run `bundle exec rails assets:precompile` in build (not `bin/rails`: uploads often lose the exec bit); `/up` health path |
| `config/database.yml` | `adapter:` under `production:` | hint for DB build deps (sqlite3/pg/mysql2/trilogy) |
| `Procfile` | `web:` line | explicit start command |
| `app.rb` | regex `require ['"]sinatra` | Sinatra classic (`ruby app.rb` reads `PORT`?) → prefer `rackup`/puma with a generated config.ru |

`defaults(inspect)`:

| Case | build_cmd | start_cmd (tcp) | start_cmd (unix) |
|---|---|---|---|
| Gemfile (any) | `bundle install` (Runway env adds `--jobs`, `--without`) | | |
| Rails | `bundle install && bin/rails assets:precompile && bin/rails db:migrate` (`db:migrate` only when `config/database.yml` exists; sqlite default DB lives in `storage/`) | `bundle exec puma -C config/puma.rb -b tcp://$HOST:$PORT` | `bundle exec puma -C config/puma.rb -b 'unix://$RUNWAY_SOCKET?umask=0117'` |
| Rack (`config.ru`) with puma in Gemfile | `bundle install` | `bundle exec puma -e production -b tcp://$HOST:$PORT` | `bundle exec puma -e production -b 'unix://$RUNWAY_SOCKET?umask=0117'` |
| unicorn in Gemfile | `bundle install` | `bundle exec unicorn -E production -l $HOST:$PORT` | `bundle exec unicorn -E production -l $RUNWAY_SOCKET` |
| no Gemfile, `app.rb` | (empty) | `ruby app.rb` | idem (script reads `RUNWAY_SOCKET`) |

### Server flags **[verified from `--help` and runs]**

- **puma 8.0.2**: `-b/--bind URI` (`tcp://127.0.0.1:9292`, `unix:///abs/path.sock`,
  `unix:///abs/path.sock?umask=0117`, `ssl://…`), repeatable; `-p PORT`; `-e/--environment`
  (default development; also from `APP_ENV`/`RACK_ENV`/`RAILS_ENV`); `-C PATH` config file
  (default `config/puma.rb` if it exists; `--no-config`); `-w COUNT` cluster mode; `-t min:max`
  threads; `--pidfile`; `--control-url`/`--control-token`. **A `-b` on the command line replaces
  every `bind`/`port` of the config file** (`-C config/puma.rb -b unix://…` listened only on the
  socket, tcp 3000 stayed closed) **[verified]**. `?umask=0117` yields `srw-rw----` **[verified]**;
  without it the socket is 0777-umask.
- Rails' generated `config/puma.rb` (Rails 8.1) **[verified]**: `threads ENV.fetch("RAILS_MAX_THREADS", 3)`,
  `port ENV.fetch("PORT", 3000)` (binds **0.0.0.0**: `* Listening on http://0.0.0.0:18088`),
  `plugin :tmp_restart`, `pidfile ENV["PIDFILE"] if ENV["PIDFILE"]`, optional `plugin :solid_queue`
  when `SOLID_QUEUE_IN_PUMA` is set. Because `port` binds all interfaces, Runway must always pass
  `-b tcp://$HOST:$PORT` (the listener-uid check would pass, but the port would be public).
- **unicorn 7.x**: `-l/--listen ADDRESS` = `HOST:PORT` or `PATH` (unix socket), repeatable;
  `-o HOST` (default 0.0.0.0), `-p PORT` (default 8080), `-E RACK_ENV`, `-c FILE` config, `-D`.
  The unix socket is created `srwxrwxrwx` (0777) **[verified]**; the config file form
  `listen "/path.sock", umask: 0117` restricts it **[unverified]**. Default when no `-l`:
  `0.0.0.0:8080` — never start unicorn without `-l`.
- **Rails env**: `RAILS_ENV=production` (or `-e production`), `SECRET_KEY_BASE` **or**
  `RAILS_MASTER_KEY`/`config/master.key` for `credentials.yml.enc`; `assets:precompile` can run
  without secrets by setting `SECRET_KEY_BASE_DUMMY=1` (Rails ≥ 7.1, documented in
  `rails/application.rb`) **[verified source]**; `RAILS_LOG_TO_STDOUT`, `RAILS_SERVE_STATIC_FILES`,
  `RAILS_MAX_THREADS`, `WEB_CONCURRENCY` (puma workers), `PIDFILE`. Rails ≥ 7.1 exposes `/up`
  (health_path default for Rails apps; returned 200 in production **[verified]**). Rails 7.2+/8 sets
  `config.assume_ssl = true` and `force_ssl = true` in production → the nginx proxy must send
  `X-Forwarded-Proto` (the base WebConfig does) or the app redirects in a loop.
  `config.hosts` is empty by default (no host check); DB default is sqlite in `storage/`.

---

## 6. Minimal sample app (stdlib only) **[verified on Plesk ruby 3.4.9 and system ruby 3.2.3, tcp and unix]**

`app.rb`:

```ruby
#!/usr/bin/env ruby
# Runway sample app (stdlib only): listens on RUNWAY_SOCKET (unix) or HOST:PORT (tcp).
require "socket"

def serve(client)
  return unless client.gets                      # request line
  while (line = client.gets) && line.chomp != "" # drain headers
  end
  body = "Hello from Ruby #{RUBY_VERSION} (pid #{Process.pid})\n"
  client.write "HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n" \
               "Content-Length: #{body.bytesize}\r\nConnection: close\r\n\r\n#{body}"
rescue IOError, SystemCallError
ensure
  client.close
end

sock = ENV["RUNWAY_SOCKET"].to_s
if sock.empty?
  host = ENV.fetch("HOST", "127.0.0.1")
  port = Integer(ENV.fetch("PORT", "8080"))
  server = TCPServer.new(host, port)
  warn "listening on #{host}:#{port}"
else
  File.unlink(sock) if File.socket?(sock)
  server = UNIXServer.new(sock)
  File.chmod(0660, sock) # nginx connects through the psaserv group
  warn "listening on #{sock}"
end
trap("TERM") { exit }
trap("INT") { exit }
loop do
  client = server.accept
  Thread.new(client) { |c| serve(c) }
end
```

- Commands: build (empty), start `ruby app.rb`. Output: `Hello from Ruby 3.4.9 (pid 33064)`,
  socket `srw-rw---- user psaserv`.
- Optional Rack sample (needs network + build deps): `Gemfile` (`source "https://rubygems.org"`,
  `gem "puma"`, `gem "rack"`) and `config.ru`
  (`run ->(env) { [200, {"content-type" => "text/plain"}, ["Hello from Rack\n"]] }`), build
  `bundle install` (6.6 s), start `bundle exec puma -e production -b 'unix://$RUNWAY_SOCKET?umask=0117'`
  → `Hello from Rack on Ruby 3.4.9` **[verified]**.

---

## 7. Pitfalls and verification commands

- **Compilers and -dev libraries are the #1 failure**: `bundle install` dies with
  `An error occurred while installing nio4r … The compiler failed to generate an executable file`;
  the real cause is in `~/.runway/bundle/ruby/<abi>/extensions/x86_64-linux/<abi>-static/<gem>/mkmf.log`
  (`cannot find -lz`, `-lgmp`). The deploy log should print the last lines of that file.
- `webrick` is not part of Ruby ≥ 3.0 (gem only) — the sample uses raw sockets.
- `bundle exec` must be run with the same `BUNDLE_*` env at build and start time (the app unit
  gets the same `env()`), otherwise Bundler cannot find the gems ("Could not find puma in locally
  installed gems").
- `Gemfile.lock` generated on another platform may pin `PLATFORMS` without `x86_64-linux`; Bundler
  ≥ 2.2 then fails → `bundle lock --add-platform x86_64-linux` (document in the UI help).
- Passenger from the Plesk Ruby extension is a separate way to run Ruby on the same domain; Runway
  proxies to its own service and ignores it.
- puma `?umask=0117` applies to the socket only; `/run/runway/<id>` (2750, psaserv) already
  restricts other users.
- Memory: a Rails app is 150-300 MB RSS per process; `MALLOC_ARENA_MAX=2` and `-t 3:3` keep it
  predictable. `WEB_CONCURRENCY`/`-w` forks workers and multiplies memory.
- System ruby: `gem install` without `GEM_HOME` would try `/var/lib/gems` (fails as user); our
  env always sets `GEM_HOME`. Debian's `ruby` has no `bundle` binary by default (`ruby -S bundle`).
- Unlike Plesk PHP handlers, Plesk rubies can be removed by the admin via the extension; `inspect`
  must handle a vanished `path` (status "toolchain missing").

Verification commands and expected output **[verified]**:

```
ls /etc/psa/ruby_versions.d/                      → plesk-ruby-3.2.10.json plesk-ruby-3.3.10.json plesk-ruby-3.4.9.json
cat /etc/psa/ruby_versions.d/plesk-ruby-3.4.9.json → {"version": "3.4.9", "path": "/opt/plesk/ruby/3.4.9"}
plesk sbin rubymng versions                       → 3.4.9 /opt/plesk/ruby/3.4.9 (one per line)
/opt/plesk/ruby/3.4.9/bin/ruby --version          → ruby 3.4.9 (2026-03-11 revision 76cca827ab) +PRISM [x86_64-linux]
/opt/plesk/ruby/3.4.9/bin/bundle --version        → Bundler version 2.6.9
/usr/bin/ruby --version                           → ruby 3.2.3 (2024-01-18 revision 52bb2ac0a6) [x86_64-linux-gnu]
bundle exec puma --version                        → puma version 8.0.2
curl --unix-socket /run/runway/<id>/app.sock http://localhost/up → 200 (Rails) / 200 text (sample)
```
