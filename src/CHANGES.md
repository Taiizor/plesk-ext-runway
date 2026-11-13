# 1.2.0-1 (13 November 2026)

* [+] Runway in the navigation of the Power User view, of resellers and of the customer panel, and Runway's mark among the icons of a domain row for domains with an enabled application.
* [+] Document root on the Runway page (Advanced, above the static paths, every runtime): the domain's document root in Plesk, so static files can be served from a folder inside the application root (e.g. wwwroot) while the application's files stay out of reach; the form suggests the runtime's usual folder.
* [+] Health watch (opt-in): restarts an application in place when its health check path keeps failing; at most 3 restarts an hour.
* [+] Expected response content of the health check (opt-in): a JSON object such as {"status":"ok"} or a text the answer must contain; used by the status card, the health watch and zero-downtime deployments.
* [+] The application's memory without the file cache, with the file cache shown apart; a warning while the application root lies in a document root.
* [*] Behaviour change on systemd 254 and later: applications with a memory or CPU limit get MemoryPressureWatch=off, so .NET sees its limits (an application that ran above 75 % of its memory limit may need a higher limit).
* [-] "Restart in place" no longer looks transparent next to the other buttons of the status card.

# 1.1.0-1 (13 November 2026)

* [+] Zero-downtime deployments (opt-in per application, TCP and Unix socket mode): the new version starts next to the running one and gets the traffic only once it listens and its health check answers; a version that does not become ready never replaces the running one.
* [+] "Restart in place" for applications with zero-downtime deployments (domain page, `plesk ext runway --restart <domain> -plain`); the domain page shows the live slot and the progress of a switch.
* [+] Server settings: zero-downtime deployments for customers (off by default), maximum readiness timeout and drain period.
* [*] The root helper connects to an application's Unix socket through a descriptor of the checked file; saving an application keeps the port its service uses.
* [-] The installation checks that /usr/bin/python3 is 3.8 or newer and names the version it found.
* [-] "Use the default commands of this runtime" confirms that the commands were filled in, or says why it kept them.

# 1.0.0-1 (12 November 2026)

* [+] First public release.
* [+] Runtimes: Go, Rust, Bun, Java (Eclipse Temurin), .NET, Python (uv-managed CPython), Ruby (Plesk Ruby or system Ruby), PHP (Plesk PHP handlers and FrankenPHP) and prebuilt binaries.
* [+] Toolchain management for administrators: install, update and remove versions from official sources with checksum verification, build dependencies installer, live job log.
* [+] Per-domain applications built as the subscription's system user and run as hardened systemd services behind nginx (Apache through mod_proxy).
* [+] Listen modes: TCP port on 127.0.0.1, private Unix socket, or background worker without a proxy.
* [+] Proxy the whole domain or only a path prefix; static folders served by the web server; optional health check path.
* [+] Deployments from the panel, from the command line (`plesk ext runway`) and from Git through `tmp/deploy.txt` / `tmp/restart.txt` trigger files.
* [+] Sample application for every runtime and "fetch a prebuilt binary from a URL" deployments.
* [+] Server-wide port range, build timeout and resource limits; per-application memory, CPU and task limits set by the administrator.
* [+] Customer access through the "Runway applications management" permission of service plans and subscriptions.
* [+] User interface in every Plesk language (32 locales).
* [+] Built-in updater: checks the latest GitHub release twice a day, "Update now" on the overview (SHA-256 verified, never a downgrade), optional automatic installation, `plesk ext runway --check-update` / `--update`; every release also ships `runway.zip` for `plesk bin extension --upgrade-url`.
* [*] Security hardening from the pre-release review: no unit line runs as root (socket directories are created by the helper and systemd-tmpfiles), LD_PRELOAD-style loader variables are refused, a replaced Unix socket path is detected and contained, and the helper's customer-file inspection runs with resource limits.
* [*] Unix socket mode exports only RUNWAY_SOCKET; Stop persists until the application is started again.
* [*] Laravel Octane runs with Runway's Caddyfile (admin endpoint off, bound to 127.0.0.1 or the socket).
* [-] Toolchain channel removal, system Ruby Bundler, Java/Rust detection, Apache WebSockets, trigger files during deployments, start limit recovery and many smaller fixes.
