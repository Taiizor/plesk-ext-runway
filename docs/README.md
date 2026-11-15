# Runway documentation

## Current guides

| Document | Purpose |
|---|---|
| [Project README](../README.md) | Features, installation, configuration, CLI and local development |
| [Design and contracts](DESIGN.md) | Current architecture, API, helper protocol, runtime adapters and deployments |
| [Optional operations](OPERATIONS.md) | History, diagnostics, releases/shared storage, notifications, recovery and plan policies |
| [Helper sources](../helper/README.md) | Source sections, manifest order, standalone generation and validation |
| [Contributing](../CONTRIBUTING.md) | Tooling, code rules, tests and adding a runtime |
| [Releasing](RELEASING.md) | Version changes, generated helper, validation, packaging and publishing |

From the repository root:

```sh
bun run build:helper      # regenerate src/sbin/runway-helper after editing helper/
bun run check:helper      # validate sources and their committed artifact without rewriting it
python build.py --check   # source structure, versions and leftover markers
python build.py --strict  # helper + frontend build, package and verification
```

Commit helper source changes and the regenerated standalone file together. Generated frontend
files and the `dist/` directory stay uncommitted. A full package build regenerates the helper
automatically; the check commands require it to be up to date already.

## Runtime notes

[Bun](runtimes/bun.md), [Java](runtimes/java.md), [.NET](runtimes/dotnet.md),
[Python](runtimes/python.md), [Ruby](runtimes/ruby.md) and [PHP](runtimes/php.md) record the
research and verification dates for each runtime. For the current implementation and defaults,
see [helper/runtimes/](../helper/runtimes/) and [DESIGN.md](DESIGN.md).

## Historical records

These describe the original 1.0 implementation and its test runs. Their file layouts, commands,
server state, version numbers and test counts are historical; use the current guides above for
development and release work.

| Document | Record |
|---|---|
| [Work plan](PLAN.md) | Original implementation phases and completion notes |
| [Foundation notes](FOUNDATION-NOTES.md) | Phase 2 SDK, Plesk and frontend investigation |
| [Integration report](INTEGRATION-REPORT.md) | Phase 4 package and Plesk integration checks |
| [Review report](REVIEW-REPORT.md) | Phase 5/6 findings, fixes and verification |
