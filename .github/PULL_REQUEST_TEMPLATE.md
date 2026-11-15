<!-- Thanks for the pull request. One topic per pull request, please; security fixes are
     coordinated through SECURITY.md first. Area labels are added automatically from the files
     you change; the maintainer sets the type label (bug, enhancement, ...), which decides the
     category of this change in the release notes. -->

## What changes

<!-- What and why. Reference the issue, e.g. "Fixes #12". -->

## How it was tested

<!-- Container or server, Plesk version and OS; which suites ran (helper-smoke, api-smoke,
     runtime-e2e, customer-smoke) and, for UI changes, which pages were checked in both themes. -->

## Checklist

- [ ] `python scripts/build_helper.py --check` and `python -m unittest discover -s tests -p 'test_*.py'` pass
- [ ] `python build.py --check`, `python tests/check_locales.py` and pyflakes on the assembled helper and build tools pass
- [ ] Tests cover the change (`tests/helper-smoke.sh`, `tests/api-smoke.sh`, `tests/runtime-e2e.sh`)
- [ ] `CHANGELOG.md` has an entry under `## [Unreleased]` (or the pull request gets the `skip-changelog` label)
- [ ] Documentation is updated (`README.md`; `docs/DESIGN.md` for contract changes; `docs/runtimes/` for adapters)
- [ ] No generated files are committed (`src/htdocs/index.php`, `src/htdocs/dist/`, `dist/`)
