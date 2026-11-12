# Releasing Runway

Releases are built and published by GitHub Actions (`.github/workflows/release.yml`) when a
tag `v<version>` is pushed. The workflow runs the whole CI first (lint, package, end-to-end
tests in the Plesk container) and only then creates the GitHub release with the zip that the
end-to-end job installed and tested. Title and notes of the release page are generated (see
[Release page](#release-page)): nothing is typed by hand.

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

   Install the zip in the test container (`scripts/plesk-dev.sh install`) and run the CI suites
   against it (`scripts/plesk-dev.sh test`, see CONTRIBUTING.md). For a release that changes
   runtime adapters, deploy the matching `examples/<runtime>-hello` once per runtime in both
   listen modes (`bash tests/runtime-e2e.sh`).
5. Commit (`Release X.Y.Z`) and push. Optional: rehearse the release page without a tag (see
   [Rehearsal](#rehearsal)).
6. Tag and push:

   ```sh
   git tag -a vX.Y.Z -m "Runway X.Y.Z"
   git push origin develop vX.Y.Z
   ```

7. Watch the *Release* workflow. It publishes `runway-X.Y.Z-R.zip`, the same file as
   `runway.zip` and `SHA256SUMS` with the generated title and notes. If it fails after the tag
   was pushed (before the release page exists), fix the problem, delete the tag
   (`git push --delete origin vX.Y.Z`, `git tag -d vX.Y.Z`) and tag again, or release
   `vX.Y.Z-<R+1>`.
8. Afterwards: add a fresh `## [Unreleased]` section to `CHANGELOG.md`.

## Release page

The workflow writes the release page from a fixed template; the maintainer never types a title
or a description:

- **Title**: `Runway X.Y.Z` (or `Runway X.Y.Z-R` for a repackaged release).
- **Notes**, in this order:
  1. the `## [X.Y.Z] - YYYY-MM-DD` section of `CHANGELOG.md` (the workflow fails when the section
     is missing or empty, so write it before tagging);
  2. *Install*: the one-line `plesk bin extension --upgrade-url .../releases/latest/download/runway.zip`
     command, the `plesk bin extension --upgrade` command for the downloaded zip, the panel upload
     hint, the built-in updater and the requirements link;
  3. *Checksums (SHA-256)* of the versioned zip and `runway.zip` (the same as the attached
     `SHA256SUMS`);
  4. *What's Changed*: the list GitHub generates from the pull requests merged since the previous
     release, grouped by their labels as configured in `.github/release.yml` (breaking changes,
     security, new features, bug fixes, runtimes, documentation, dependencies, other), plus new
     contributors and the compare link. Pull requests labelled `skip-changelog` are left out, so
     label pull requests before tagging (CONTRIBUTING.md, "Labels").
- **Assets**: `runway-X.Y.Z-R.zip`, the same file under the fixed name `runway.zip` (so
  `https://github.com/Taiizor/plesk-ext-runway/releases/latest/download/runway.zip` always points
  at the newest release: `plesk bin extension --upgrade-url <that URL>` installs or updates in
  one command, and the *Install* part of the notes shows it) and `SHA256SUMS` listing both.

## Releases and the built-in updater

Installed servers find new versions through the GitHub API's `releases/latest` (the helper's
`update-check`, docs/DESIGN.md section 7) and install the versioned zip after checking it against
`SHA256SUMS` of the same release. Consequences for releasing:

- **A published release reaches servers on its own**: within 12 hours every server with update
  checks on shows it, and servers with automatic installation install it. Never publish a
  release that has not passed the whole workflow.
- **A broken release cannot be withdrawn**: deleting it makes the previous release "latest"
  again, but servers that installed it stay on it (the updater never downgrades). Fix it by
  publishing a newer version (`vX.Y.Z-<R+1>` for a packaging fix, or the next patch version).
- **Never mark a prerelease as latest**, and do not attach assets by hand: the updater ignores
  drafts and prereleases, expects exactly one `runway-X.Y.Z-R.zip` that matches the tag
  (`vX.Y.Z` or `vX.Y.Z-R`) plus `SHA256SUMS`, and refuses everything else (the check then shows an
  error on every server).
- The asset names, the tag format and the `meta.xml` inside the zip (`<id>runway</id>`, version,
  release) are part of the updater's contract: changing them breaks updates of installed
  versions.

## Rehearsal

*Actions > Release > Run workflow* on `develop` runs the release workflow without a tag: it
takes the version from `src/meta.xml`, builds and verifies the package, runs the lint and
packaging checks (tick *e2e* to run the end-to-end tests as well), renders the release notes
into the job summary and uploads them with the zip (and its `runway.zip` copy) as the
`release-rehearsal` artifact. Nothing is published. Use it to proof-read the notes before
pushing the tag.

## Package verification

`python build.py` verifies every zip it writes, and `python build.py --verify <zip>
[--version X.Y.Z-R]` checks an existing one:

- `meta.xml`, `DESCRIPTION.md`, `CHANGES.md`, `sbin/runway-helper`, `htdocs/index.php`,
  `htdocs/dist/main.js`, `plib/controllers/ApiController.php` are present;
- `_meta/icons/32x32.png`, `64x64.png` and `128x128.png` are PNGs of the right size (rendered
  by `bun run assets` from `assets/logo-tile.svg`, like `htdocs/images/logo.png`; the
  navigation icon `htdocs/images/nav.png` is the mark of `assets/logo.svg` in white, because
  Plesk draws it as it is on the dark sidebar; the build fails when they are missing);
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
