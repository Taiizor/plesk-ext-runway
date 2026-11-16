# Privileged helper sources

Edit the Python source sections in this directory, then regenerate and commit the standalone
artifact with them. Run these commands from the repository root:

```sh
bun run build:helper
bun run check:helper
python -m unittest discover -s tests -p 'test_*.py' -v
python -m pyflakes src/sbin/runway-helper scripts/build_helper.py
```

The package scripts invoke `python scripts/build_helper.py` and
`python scripts/build_helper.py --check`, respectively. The Python entry points also work on their
own, including in CI jobs and Linux test containers that do not install Bun. `build:helper`
regenerates the artifact; `check:helper` only validates it and never rewrites it.

`src/sbin/runway-helper` is generated and committed so existing helper tooling, installation
and systemd's atomic helper replacement keep working. Do not edit it directly. `python build.py`
and `--no-frontend` regenerate it; `python build.py --check` and CI reject a missing or stale
artifact without changing any file. Change the version in `bootstrap.py`, then regenerate.

## Source layout

| Path | Responsibility |
|---|---|
| `bootstrap.py` | Isolated interpreter header, standard-library imports, version, constants and base error |
| `utilities.py`, `validation.py`, `paths.py` | Shared utilities, untrusted input validation and server paths |
| `customer.py` | Privilege dropping and bounded access to subscription files |
| `systemd.py`, `ports.py`, `jobs.py` | Unit/environment rendering, listeners, ports and background job state |
| `downloads.py`, `toolchains.py` | Verified toolchain downloads and Go/Rust installation support |
| `runtimes/` | Common adapter interface, one source file per runtime, shared detection utilities and registry |
| `samples.py` | Application templates returned by the adapters |
| `commands.py`, `updater.py` | Toolchain/job API commands and extension updates |
| `applications.py`, `app_control.py`, `app_queries.py`, `lifecycle.py` | Application state, controls, inspection, document roots, install/uninstall and reconciliation |
| `health.py`, `health_watch.py` | Response matching and periodic health checks |
| `metrics.py` | SQLite resource history, periodic collection and project totals |
| `fetch.py`, `deploy.py` | Application downloads, builds and restarts |
| `switching/` | Zero-downtime pointers, web server reloads, connections, convergence and traffic switching |
| `operations/` | Opt-in history, diagnostics, isolated releases, HTTPS notifications and recovery metadata |
| `entrypoint.py` | Public command dispatch, internal systemd entry points and JSON protocol |

## Assembly contract

These are source sections of one program, not independently imported Python modules. They
share the helper's global namespace; a function can refer to an adapter or utility defined in a
different section. The explicit order in `manifest.json` preserves initialization and dispatch
order. Add every new `.py` file to that manifest; omitted files, duplicates, paths outside this
directory and invalid Python 3.8 syntax fail assembly.

The builder reads and parses the sources without executing them, joins them in manifest order,
adds source-location comments, and checks the complete program for syntax and duplicate top-level
function/class definitions. It adds no runtime imports, loader, dependencies or installed files.
The installed script still starts with `#!/usr/bin/python3 -I`, validates untrusted input,
drops privileges for customer files and copies itself to `/opt/runway/bin/runway-helper` by
atomic rename. The JSON API, state, service paths and systemd entry points remain the same.

Run pyflakes on the assembled artifact so it sees all definitions in their shared namespace.
CI checks the committed artifact, the assembler's failure paths and the Linux helper contracts;
the latter also run on Python 3.8 in a small Docker container without Plesk or systemd. On Windows,
the source assembly tests run locally and the Linux contracts skip. The existing Plesk smoke and
end-to-end suites exercise the packaged artifact as before. CodeQL analyzes a complete `.py`
copy of the assembled program, instead of treating the sections as independent modules.
`scripts/helper_sarif.py` maps report locations back to the committed helper, with the same line
numbers, so findings link to the repository file.

## Resource monitoring

Installation and upgrades enable `runway-metrics.timer`, which calls the installed helper's
`_metrics` entry point every minute to collect server and configured application metrics even
when the panel is closed. Uninstallation stops and removes both the timer and its service.
Samples are stored in `/var/lib/runway/metrics.sqlite` for 14 days; disk scans share a persistent
two-minute cache. Concurrent panel and timer samples share a lock, and requests less than ten
seconds apart reuse their last measurement instead of replacing counter deltas with zeros.

Project Load includes the current configured applications and all active deployment slots.
Application CPU percentages use one logical CPU as 100%, so their sum can exceed 100% on a
multi-core host. Application memory excludes reclaimable file cache when cgroup data is
available. Stopped applications retain their disk usage. Charts use real timestamps and leave
unmeasured intervals blank; existing missing history cannot be reconstructed.

Both load cards show disk capacity and separate read/write rates. The application's Disk I/O
chart plots both rates on the same scale. These are bytes per second averaged over the interval
between counter samples, not cumulative bytes or logical application read/write calls. Cached
reads may generate no block-device I/O. Applications use `IOReadBytes`/`IOWriteBytes`, with
cgroup v2 `io.stat` and cgroup v1 blkio fallbacks; unit files enable I/O accounting. Host rates
sum whole leaf devices from `/sys/block/*/stat`, excluding partitions, loop/RAM devices and
stacked mapper/RAID views to avoid counting the same I/O twice. Initial, unavailable or reset
counters remain NULL until another valid sample; the UI shows a dash for an unknown rate.

Application network metrics are systemd IP accounting (IPv4/IPv6 ingress plus egress), not
domain HTTP bandwidth. Unix socket traffic between nginx and an application is outside those
counters, and IP accounting also depends on kernel BPF support. Check collection on the server
with `systemctl status runway-metrics.timer` and `journalctl -u runway-metrics.service`.
