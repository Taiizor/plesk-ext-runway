# Security policy

Runway runs a root helper on Plesk servers and executes customer code as system services, so
security reports are taken seriously and handled before anything else.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x (latest release) | yes |
| older releases, unreleased branches | no: upgrade to the latest release |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

- Use GitHub's private vulnerability reporting:
  [Report a vulnerability](https://github.com/Taiizor/plesk-ext-runway/security/advisories/new)
  (repository *Security* tab).
- Include the Runway version, Plesk version and OS, the steps to reproduce, the impact you
  expect (for example "a customer can read files of another subscription") and, if possible, a
  proof of concept. Do not access data that is not yours and do not degrade servers you do not
  own.

You can expect an acknowledgement within 3 working days and an assessment within 10. Fixes are
released as a new version with a GitHub security advisory; reporters are credited unless they
prefer otherwise. Please give us up to 90 days before public disclosure.

## Threat model

Runway assumes that **the Plesk administrator is trusted** and that **customers (subscription
owners) are not**: a customer controls the application files, the build and start commands,
the environment variables and everything the application does at runtime. Other local users
(other subscriptions, PHP scripts, cron jobs, SSH users) are untrusted as well.

What Runway protects:

| Asset | Threat | Protection |
|---|---|---|
| root on the server | command injection through domain settings (newlines in commands, `ExecStartPre=` smuggling, env values) | PHP validates, the root helper re-validates every field; unit files contain no customer text (`ExecStart=/bin/bash -c ${RUNWAY_START_CMD}` from a root-only environment file with strict quoting) |
| root on the server | the customer's environment (e.g. `LD_PRELOAD`) reaching a process that runs as root | no Exec line of an application unit runs as root (no `+`/`!` prefix): the socket directory is created by the helper and, at boot, by `systemd-tmpfiles` (`/etc/tmpfiles.d/runway-<id>.conf`); the loader variables `LD_PRELOAD`, `LD_AUDIT`, `GCONV_PATH` and `GLIBC_TUNABLES` are refused in the environment variables as defence in depth (an application that needs one sets it in its start command); an upgrade re-renders every unit and strips such lines from units it cannot re-render |
| root on the server | symlink/hard link tricks in the application directory, FIFOs, huge files, `SIGSTOP` to hang the helper | every access to customer files happens in a child process that dropped to the customer's uid with a deadline and no inherited descriptors; reads never follow symlinks and are size-capped |
| server resources | millions of files or huge project files in the application directory making the helper's child allocate gigabytes | the child that inspects customer files runs with resource limits (512 MiB address space, 64 MiB file size, CPU time = deadline + 5 s); directory listings stop at fixed caps (80 names shown, at most 10 000 entries counted) |
| other subscriptions | reading or writing another customer's files; acting as another system user | builds and services run as the subscription's system user with `NoNewPrivileges`, `ProtectSystem=full`, `PrivateTmp`, `PrivateDevices`, `RestrictSUIDSGID` and related sandboxing; the system user is resolved by the helper, never taken from the request |
| other applications | taking over another application's port or socket | per-app `SocketBindAllow=tcp:<port>` + `SocketBindDeny=any` (systemd 249+; with zero-downtime deployments each slot may bind only its own port), listener-owner check before traffic is sent to a port, Unix sockets in a `2750 user:psaserv` directory created by root |
| other applications | a customer replacing its own `app.sock` with a symbolic link to another application's socket (nginx, a `psaserv` member, would follow it and route the customer's domain to that backend) | the helper checks the socket path with `lstat` on every status request, in the scheduled reconcile (every 10 minutes) and after every deployment; anything but a socket owned by the application's user is removed as root (never followed), the service is stopped and disabled, the application is marked "tampered" (state *Stopped: socket replaced*, note in its journal) and only an explicit Start runs it again. With zero-downtime deployments the web server uses `/run/runway/<id>.sock`, a symbolic link that only root can create or replace (in the root-owned `/run/runway`) and that points to one of the slot sockets `a.sock`/`b.sock`; these and `app.sock` are checked the same way, and a switch moves the traffic only to a socket the application's user owns. See the residual risk below. |
| root on the server | a customer swapping a socket for a symbolic link between Runway's check and its connection, so that the root helper talks to a root-only socket (for example the Docker socket) during a listener or health check | the helper opens the socket with `O_PATH`/`O_NOFOLLOW`, checks the descriptor (a socket owned by the application's user) and connects through `/proc/self/fd/<n>`, i.e. to exactly the checked file |
| server resources | fork bombs, memory exhaustion, endless builds | `TasksMax` always applies to builds, optional `MemoryMax`/`CPUQuota` for builds and applications (set by the administrator only), build deadline |
| secrets | environment variables leaking through `ps`, D-Bus or the panel to other users | variables are sent to the helper on stdin, stored in `/etc/runway/env/<id>.env` (root, 0600) and only readable by users who may manage the domain |
| toolchains | tampered downloads | HTTPS from the official sources only, checksum verification (SHA-256/512 as published), safe extraction (no absolute paths, `..` or device files), root-owned read-only install trees |
| Plesk state | suspended or deleted domains keep running | event listener plus a scheduled reconcile every 10 minutes stop, rename or remove services; builds re-check the state before restarting |
| panel users | CSRF, privilege escalation in the API | every mutation is a POST with Plesk's forgery protection token; every domain action checks admin rights or the customer's permission and access to that domain; admin-only actions check the admin role |
| internal services | "Fetch from URL" used to reach the server's loopback/private network (SSRF), including DNS rebinding | https only (PHP and helper), the download runs as the customer; every address of the host must be public, and the connection goes to exactly the address that was checked (the lookup is pinned, TLS still verifies the host name), with the same check for every redirect; no proxies; 500 MB cap |
| the extension itself | a tampered or corrupted package installed by the built-in updater | see [Updates](#updates) below: HTTPS from the repository's GitHub releases only, SHA-256 from the same release, `meta.xml` and version checks, no downgrades, administrators only, automatic installation is opt-in |

Out of scope (by design):

- Anything the administrator configures or installs: administrators are root-equivalent in
  Plesk.
- The security of the customer's own application (its dependencies, authentication, data). It
  runs with the customer's privileges, exactly like PHP code of the same subscription.
- In **TCP mode**, any local user can connect to `127.0.0.1:<port>`, bypassing nginx (and
  anything nginx enforces, such as client IP restrictions). Use the **Unix socket** mode on
  shared servers; see the README section "Listen modes". With zero-downtime deployments the
  port of the standby slot is free between two switches, so any local process may bind it; the
  next switch then uses another free port, and the traffic is switched to a port only after
  Runway checked that the application's own user alone listens on it. The web server
  configuration never falls back to a port: when the root-owned include file that names the live
  port is missing, the requests fail (502) instead of reaching whoever holds some port.
- Zero-downtime deployments run the old and the new version side by side for up to the
  readiness timeout plus the drain period, each within the application's limits, so the
  application can use twice its memory and CPU limits for that time. Customers can only turn
  the setting on when the administrator allows it, and the administrator caps both timeouts
  (*Runway > Settings*).
- Denial of service by a customer within the limits the administrator granted.
- **Residual window of the socket check**: the socket directory belongs to the subscription's
  system user (the application must create its socket there), so a customer with shell access
  can re-create a symbolic link at any time (with zero-downtime deployments: replace the slot
  socket that the root-owned link points to). Runway removes it at the next check, i.e. within the
  status polling interval while someone has the domain page open and at most within 10 minutes
  (scheduled reconcile) otherwise. During that window nginx may route requests for the customer's
  own domain to another application's backend on the same server (the requests still carry the
  customer's domain in `Host`; the other application's own vhost restrictions do not apply to
  them). Applications that must not be reachable this way should check the `Host` header, or the
  server should not host mutually hostile customers on one machine.
- Vulnerabilities of Plesk itself, systemd, nginx or the toolchains: report them to their
  vendors (for Plesk: https://www.plesk.com/security-advisories/).

Test-only switches (root-owned files, never present on production servers): the helper accepts
plain `http://` and private addresses for "Fetch from URL" while `/etc/runway/allow-insecure-fetch`
exists, the panel's reconcile leaves applications alone while
`/var/lib/runway/pause-reconcile` exists (at most one hour after its last modification), a
zero-downtime switch kills itself at a named step while `/var/lib/runway/test-switch-fault`
exists (at most one hour; tests of the recovery after a crash), and
`/etc/runway/update-source` replaces the GitHub API URL of the built-in updater with the URL on
its first line (https only, `http://` only while `allow-insecure-fetch` exists; package and
release page URLs must then lie below that URL's own `scheme://host:port/`, with the same path
rules as for GitHub). Its content decides where root downloads packages from, so the helper
ignores it unless the file and `/etc/runway` are owned by root and writable by nobody else, and
the overview shows a warning while it is active. The test scripts
create and remove them; `runway-helper info` reports the first as `fetch_insecure` and the last
as `update_source`.

## Updates

Runway is distributed through the GitHub releases of this repository, not the Plesk extension
catalog, so Plesk itself never offers updates for it. The built-in updater:

- asks `https://api.github.com/repos/Taiizor/plesk-ext-runway/releases/latest` (one HTTPS request
  twice a day while *Settings > Updates > Check for updates* is on, the default, or when an
  administrator clicks *Check now*; nothing about the server is sent besides the request itself
  and the `plesk-runway/<version>` User-Agent);
- takes package URLs only as exactly
  `https://github.com/Taiizor/plesk-ext-runway/releases/download/<tag>/<file name>` of the
  validated tag (parsed, not compared as a string prefix: no query, fragment, percent-escapes or
  `.`/`..` segments) and the release page only as `.../releases/tag/<tag>`, ignores drafts and
  prereleases, never installs the same or an older version, and keeps no release notes;
- downloads the versioned zip and `SHA256SUMS` of the same release over HTTPS (redirects, such as
  GitHub's to its asset host, are followed only to `https://` URLs, at most five), refuses the zip
  unless its SHA-256 matches the line of exactly that file name and its `meta.xml` names the
  extension `runway` with the expected version and release, then runs
  `plesk bin extension --upgrade` as root in the administrator's background job;
- is available to administrators only (panel, API and CLI; customers get "access denied"), and
  installs automatically only when an administrator turns on *Install updates automatically*.

The SHA-256 checksum comes from the same release as the package. It protects against corrupted
or truncated downloads, **not** against a compromised GitHub account, a compromised release
workflow or a malicious release: whoever can publish a release of this repository can run code
as root on servers that install it (automatically, when automatic installation is on). Keep
automatic installation off when that risk is not acceptable, and review the release notes before
clicking *Update now*.

## Hardening checklist for administrators

- Prefer the Unix socket listen mode for customer applications.
- On AlmaLinux/RHEL with SELinux in enforcing mode, nginx/Apache may need policy changes to
  reach the applications (README, Requirements); the overview shows the SELinux mode.
- Set default memory, CPU and task limits and build limits under *Runway > Settings*.
- Grant the **Runway applications management** permission only to plans that need it.
- Keep Plesk, the OS (systemd 249+) and the installed toolchains up to date; remove toolchain
  versions that are no longer used.
