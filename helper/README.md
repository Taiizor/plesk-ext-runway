# Privileged helper sources

Edit the Python source sections in this directory, then regenerate and commit the standalone
artifact with them:

```sh
python scripts/build_helper.py
python scripts/build_helper.py --check
python -m unittest discover -s tests -p 'test_*.py' -v
python -m pyflakes src/sbin/runway-helper scripts/build_helper.py
```

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
| `fetch.py`, `deploy.py` | Application downloads, builds and restarts |
| `switching/` | Zero-downtime pointers, web server reloads, connections, convergence and traffic switching |
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
