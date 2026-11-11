Runway runs compiled and long-running web applications per domain **without Docker**. Install a
toolchain once, point a domain at its application directory, and Runway builds the app as the
subscription's system user, runs it as a hardened systemd service and lets nginx proxy the domain
to it.

**Runtimes:** Go, Rust, Bun, Java (Eclipse Temurin), .NET, Python (uv-managed CPython), Ruby,
PHP (Plesk PHP handlers and FrankenPHP) and any prebuilt Linux binary.

**For administrators**

- Install, update and remove toolchain versions from official sources; checksums are verified.
- Install common build dependencies (C compiler, pkg-config, OpenSSL headers) with one click.
- Server-wide port range, build timeout and resource limits for applications and builds.
- Grant the feature to customers with the **Runway applications management** permission.

**For every domain**

- Pick a runtime and version, the application directory, build and start commands and
  environment variables (stored root-only, never shown in process lists).
- Listen on a TCP port on `127.0.0.1` or on a private Unix socket that only the web server can
  reach; run background workers without a proxy.
- Proxy the whole domain or only a path such as `/api`, and let nginx serve static folders.
- Start, stop, restart, build and redeploy from the panel (a stopped application stays stopped
  until you start it); watch the status, the application journal and the build log live.
- Deploy from Git: touching `tmp/deploy.txt` in the application directory rebuilds and restarts
  the app, `tmp/restart.txt` restarts it.
- Create a minimal sample application for the chosen runtime to try everything in a minute.

**Security model:** a root helper re-validates every request, everything that touches customer
files runs as the customer with resource limits, unit files never contain customer text and no
unit line runs as root, and services run with systemd sandboxing, memory/CPU/task limits, a port
ownership check and a socket tampering check.

Requires Plesk Obsidian 18.0.55 or later on Linux with systemd and python3. Source code, issues
and documentation: https://github.com/Taiizor/plesk-ext-runway
