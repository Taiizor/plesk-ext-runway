# Releasing Runway

Releases are built and published by GitHub Actions (`.github/workflows/release.yml`) when a
tag `v<version>` is pushed. The workflow runs the whole CI first (lint, package, end-to-end
tests in the Plesk container) and only then creates the GitHub release with the zip that the
end-to-end job installed and tested.

## Versioning

- `src/meta.xml` holds `<version>` (semantic version `X.Y.Z`) and `<release>` (package release
  number, starts at `1`). The zip is `runway-<version>-<release>.zip`; Plesk upgrades when
  version or release is higher than the installed one.
- Tags: `vX.Y.Z` packages `X.Y.Z` with the release number of `src/meta.xml`; `vX.Y.Z-R` sets
  the release number too (repackaging the same version, e.g. a packaging fix).
- `build.py --version X.Y.Z[-R]` stamps the packaged `meta.xml` and the zip name without
  touching `src/meta.xml`; the release workflow passes the tag through it. The release workflow
  fails when the tag differs from `src/meta.xml`, and `build.py` fails when `package.json` or the
  helper's `VERSION` differ from the packaged version.

## Checklist

1. Make sure CI is green on `develop` (the default branch; releases are tagged on it).
2. Bump `<version>` / `<release>` in `src/meta.xml`, `version` in `package.json` and
   `VERSION = "X.Y.Z"` in `src/sbin/runway-helper` (shown as the helper version and sent as the
   User-Agent of downloads); `build.py --check` verifies that the three agree.
3. Changelogs, both are required by `build.py` (it fails when the version has no entry):
   - `CHANGELOG.md`: move the `## [Unreleased]` items to `## [X.Y.Z] - YYYY-MM-DD`, update
     the compare links at the bottom.
   - `src/CHANGES.md` (shown in the Plesk extension catalog): add `# X.Y.Z-R (D Month YYYY)`
     on top, one line per change, `[+]` new, `[*]` changed, `[-]` fixed.
4. Locally:

   ```sh
   bun install --frozen-lockfile
   python build.py --check            # structure, changelogs, no leftover placeholders
   python build.py --strict           # frontend build + zip + package verification
   python tests/check_locales.py
   ```

   Install the zip in the test container (`sh tests/deploy-test.sh`) and run
   `tests/helper-smoke.sh` and `tests/api-smoke.sh` (see CONTRIBUTING.md). For a release that
   changes runtime adapters, deploy the matching `examples/<runtime>-hello` once per runtime in
   both listen modes.
5. Commit (`Release X.Y.Z`), then tag and push:

   ```sh
   git tag -a vX.Y.Z -m "Runway X.Y.Z"
   git push origin develop vX.Y.Z
   ```

6. Watch the *Release* workflow. It publishes `runway-X.Y.Z-R.zip` and `SHA256SUMS` with the
   notes of the `CHANGELOG.md` section. If it fails after the tag was pushed, fix the problem,
   delete the tag (`git push --delete origin vX.Y.Z`, `git tag -d vX.Y.Z`) and tag again, or
   release `vX.Y.Z-<R+1>`.
7. Afterwards: add a fresh `## [Unreleased]` section to `CHANGELOG.md`.

## Package verification

`python build.py` verifies every zip it writes, and `python build.py --verify <zip>
[--version X.Y.Z-R]` checks an existing one:

- `meta.xml`, `DESCRIPTION.md`, `CHANGES.md`, `sbin/runway-helper`, `htdocs/index.php`,
  `htdocs/dist/main.js`, `plib/controllers/ApiController.php` are present;
- `_meta/icons/32x32.png`, `64x64.png` and `128x128.png` are PNGs of the right size (generated
  by `build.py` unless committed in `src/_meta/icons/`);
- Unix modes: `sbin/*` 0755, everything else 0644; LF line endings in text files; no BOM in
  PHP files; the helper has a shebang;
- no React sources (`frontend/`), source maps, hidden files or Python caches; no unsafe paths;
- with `--version`: the packaged id, version and release.

`python build.py --check` (and `--strict` for builds) fails on leftover placeholders in the
packaged files and in `src/frontend/`: `TODO`, `FIXME`, `TBD`, `XXX`, `CHANGEME`,
`REPLACE_ME`, `PLACEHOLDER`, *lorem ipsum*, `{{ variable }}` and `@@VARIABLE@@`. The generated
bundle `src/htdocs/dist/` is not scanned.

## Screenshots

The Plesk extension catalog shows `_meta/screenshots/*.png` from the package
(`src/_meta/screenshots/1.png` domain page, `2.png` toolchains, `3.png` overview, 1024x768); the
README shows `docs/screenshots/admin-overview.png`, `admin-toolchains.png` and
`admin-domain.png`, and `docs/screenshots/` holds more views (dark theme, customer, drawers).
`build.py` prints a note when `src/_meta/screenshots/` is empty. To refresh them:

1. Use the test container with a few applications in different states (running Go app, a
   stopped Bun app, a failed build) and at least two toolchains installed. Use neutral domain
   names (`example.com`, `shop.example.net`) and no real customer data.
2. Browser window 1440x900, Plesk default theme, English locale. Pages: overview, toolchains
   (with an install job log), domain page (status + logs), settings.
3. Save PNGs (at most 1 MB each) as `src/_meta/screenshots/1.png`, `2.png`, `3.png` (catalog
   order) and replace the files of the same name in `docs/screenshots/` (the README links
   `admin-overview.png`, `admin-toolchains.png`, `admin-domain.png`). The integration run used
   headless Chrome through puppeteer-core with the trial-license banner hidden.

## Plesk extension catalog

Catalog submission is not a 1.0 goal (DESIGN section 11). When it becomes one: the package
already follows the catalog layout (`meta.xml`, `DESCRIPTION.md`, `CHANGES.md`,
`_meta/icons`, `_meta/screenshots`); add screenshots, review `src/DESCRIPTION.md` and follow
Plesk's submission guidelines for vendors.
