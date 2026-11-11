#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2026 Taiizor. Licensed under the MIT License.
"""
Packages the Runway Plesk extension into an installable zip.

Usage:
    python build.py                     # frontend build (bun) + dist/runway-<version>-<release>.zip
    python build.py --no-frontend       # package the already built frontend (src/htdocs/index.php + dist/)
    python build.py --check             # only validate the source tree (no build, no zip)
    python build.py --version 1.2.0     # package as version 1.2.0 (release from meta.xml)
    python build.py --version 1.2.0-3   # package as version 1.2.0, release 3
    python build.py --verify dist/runway-1.0.0-1.zip   # verify an existing package

The frontend is built with the Plesk Extension SDK through Bun ("bun run build" =
"plesk-ext-sdk build"). It generates src/htdocs/index.php and src/htdocs/dist/ (both
git-ignored), which are packaged together with the rest of src/. src/frontend/ (the React
sources) and source maps are not part of the package.

The generated htdocs/index.php loads dist/main.js through RequireJS without cache headers, so
browsers would keep an old bundle after an upgrade. The packaged copy is patched to request
dist/main.js?v=<version>-<release>.<sha256 prefix of main.js> (cache-buster); the generated
source file itself is left untouched.

The zip is created with Unix permissions (sbin scripts 0755, everything else 0644),
LF line endings for text files and generated PNG icons, so it can be built on
Windows and uploaded to a Linux Plesk server as-is. Every package is verified after it
was written (see verify_package()).

--version only changes the packaged meta.xml and the zip name; src/meta.xml is not modified.
The version must have an entry in src/CHANGES.md and CHANGELOG.md (release gate).

--check fails on structural problems and on leftover placeholders (TODO/FIXME markers,
template variables, filler text) in the packaged files and the frontend sources. A normal
build reports placeholders as warnings, --strict turns them into errors.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
DIST = os.path.join(ROOT, "dist")

TEXT_EXTENSIONS = {".php", ".phtml", ".xml", ".js", ".css", ".md", ".txt", ".json", ".ini", ".sh", ".svg", ".html"}
EXECUTABLE_PREFIXES = ("sbin/",)
# Source-only directories (relative to src/) that are never packaged.
EXCLUDED_DIRS = ("frontend",)
EXCLUDED_SUFFIXES = (".bak", ".swp", "~", ".map")
# Generated files: checked for presence, but not scanned for placeholders (third-party bundle).
GENERATED = ("htdocs/index.php", "htdocs/dist/")
FIXED_DATE = (2026, 1, 1, 0, 0, 0)
ICON_SIZES = (32, 64, 128)
REQUIRED_IN_PACKAGE = ("meta.xml", "DESCRIPTION.md", "CHANGES.md", "sbin/runway-helper",
                       "htdocs/index.php", "htdocs/dist/main.js", "plib/controllers/ApiController.php")
VERSION_RE = re.compile(r"^(\d+\.\d+\.\d+)(?:-(\d+))?$")
# require(['<baseUrl>/dist/main.js'], ...) in the generated htdocs/index.php (optionally already busted).
MAIN_JS_REF_RE = re.compile(rb"(/dist/main\.js)(\?v=[A-Za-z0-9._-]*)?(['\"])")

# Leftover placeholders that must never ship (--check / --strict fail on them).
PLACEHOLDER_PATTERNS = (
    (re.compile(r"\b(?:TODO|FIXME|TBD|XXX)\b"), "marker"),
    (re.compile(r"\b(?:CHANGEME|CHANGE_ME|REPLACEME|REPLACE_ME|PLACEHOLDER)\b"), "placeholder"),
    (re.compile(r"lorem ipsum", re.IGNORECASE), "filler text"),
    (re.compile(r"\{\{\s*[A-Za-z_][\w.-]*\s*\}\}"), "template variable"),
    (re.compile(r"@@[A-Z][A-Z0-9_]*@@"), "template variable"),
)


def read_meta():
    with open(os.path.join(SRC, "meta.xml"), "r", encoding="utf-8") as fh:
        meta = fh.read()
    fields = {}
    for key in ("id", "name", "version", "release"):
        match = re.search(r"<%s>([^<]+)</%s>" % (key, key), meta)
        if not match:
            raise SystemExit("meta.xml: missing <%s>" % key)
        fields[key] = match.group(1).strip()
    return fields


def apply_version_override(meta, override):
    """--version X.Y.Z[-R]: returns meta with the packaged version (and release) replaced."""
    match = VERSION_RE.match(override or "")
    if not match:
        raise SystemExit("--version must look like 1.2.3 or 1.2.3-4 (got %r)" % override)
    meta = dict(meta)
    meta["version"] = match.group(1)
    if match.group(2):
        meta["release"] = str(int(match.group(2)))
    return meta


def packaged_meta_xml(meta):
    """Contents of src/meta.xml with <version>/<release> set to the packaged values."""
    with open(os.path.join(SRC, "meta.xml"), "rb") as fh:
        data = fh.read().decode("utf-8")
    for key in ("version", "release"):
        data = re.sub(r"<%s>[^<]*</%s>" % (key, key), "<%s>%s</%s>" % (key, meta[key], key), data, count=1)
    return data.encode("utf-8")


def package_name(meta):
    return "%s-%s-%s.zip" % (meta["id"], meta["version"], meta["release"])


# ---------------------------------------------------------------------------
# Frontend build (Bun + @plesk/plesk-ext-sdk)
# ---------------------------------------------------------------------------

def build_frontend():
    bun = shutil.which("bun")
    if not bun:
        raise SystemExit("bun was not found in PATH (https://bun.sh); use --no-frontend to package an existing build")
    if not os.path.isdir(os.path.join(ROOT, "node_modules", "@plesk", "plesk-ext-sdk")):
        print("Installing frontend dependencies (bun install --frozen-lockfile)", flush=True)
        subprocess.run([bun, "install", "--frozen-lockfile"], cwd=ROOT, check=True)
    print("Building the frontend (bun run build)", flush=True)
    result = subprocess.run([bun, "run", "build"], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit("The frontend build failed (exit code %d)" % result.returncode)


# ---------------------------------------------------------------------------
# Icon generation (pure Python PNG encoder, no third-party packages)
# ---------------------------------------------------------------------------

def _png(width, height, pixels):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(pixels[y * width * 4:(y + 1) * width * 4]) for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _icon_color(px, py, size):
    """Color of one sample of the icon: a runway in perspective on a rounded navy tile."""
    background = (22, 34, 56)
    asphalt = (62, 76, 102)
    edge = (214, 222, 235)
    centre = (255, 190, 40)
    top, bottom = size * 0.16, size * 0.90
    if py < top or py > bottom:
        return background
    t = (py - top) / (bottom - top)  # 0 at the horizon, 1 in front
    half = size * (0.05 + 0.27 * t)
    dx = abs(px - size / 2.0)
    if dx > half:
        return background
    if dx > half - size * (0.012 + 0.03 * t):
        return edge
    # Dashes get longer towards the viewer (perspective): equal steps in sqrt(t).
    if dx < size * (0.006 + 0.022 * t) and (t ** 0.5 * 6.0) % 1.0 < 0.55:
        return centre
    return asphalt


def make_icon(size):
    """Rounded tile with a runway, anti-aliased by supersampling."""
    ss = 4
    pixels = bytearray(size * size * 4)
    radius = size * 0.22
    for y in range(size):
        for x in range(size):
            acc = [0.0, 0.0, 0.0, 0]  # summed r, g, b and number of covered samples
            for sy in range(ss):
                for sx in range(ss):
                    px = x + (sx + 0.5) / ss
                    py = y + (sy + 0.5) / ss
                    # rounded square mask
                    dx = max(radius - px, 0, px - (size - radius))
                    dy = max(radius - py, 0, py - (size - radius))
                    if dx * dx + dy * dy > radius * radius:
                        continue
                    color = _icon_color(px, py, size)
                    acc[0] += color[0]
                    acc[1] += color[1]
                    acc[2] += color[2]
                    acc[3] += 1
            covered = acc[3]
            offset = (y * size + x) * 4
            if covered:
                pixels[offset] = int(round(acc[0] / covered))
                pixels[offset + 1] = int(round(acc[1] / covered))
                pixels[offset + 2] = int(round(acc[2] / covered))
                pixels[offset + 3] = int(round(255.0 * covered / (ss * ss)))
    return _png(size, size, pixels)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def iter_source_files():
    for dirpath, dirnames, filenames in os.walk(SRC):
        rel_dir = os.path.relpath(dirpath, SRC).replace(os.sep, "/")
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                             and not (rel_dir == "." and d in EXCLUDED_DIRS))
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith(EXCLUDED_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, SRC).replace(os.sep, "/")
            yield full, rel


def iter_frontend_sources():
    """Text files of src/frontend (not packaged, but compiled into htdocs/dist/main.js)."""
    base = os.path.join(SRC, "frontend")
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, SRC).replace(os.sep, "/")
            if is_text(rel):
                yield full, rel


def is_text(rel):
    return os.path.splitext(rel)[1].lower() in TEXT_EXTENSIONS or rel.startswith(EXECUTABLE_PREFIXES)


def find_placeholders():
    """Leftover placeholders in packaged text files and frontend sources: ["rel:line: kind 'text'"]."""
    found = []
    candidates = [(full, rel) for full, rel in iter_source_files()
                  if is_text(rel) and not rel.startswith(GENERATED)]
    candidates += list(iter_frontend_sources())
    for full, rel in candidates:
        with open(full, "rb") as fh:
            text = fh.read().decode("utf-8", "replace")
        for number, line in enumerate(text.splitlines(), 1):
            for pattern, kind in PLACEHOLDER_PATTERNS:
                match = pattern.search(line)
                if match:
                    found.append("src/%s:%d: %s %r" % (rel, number, kind, match.group(0)))
                    break
    return found


def changelog_has(path, version, heading):
    """True when the Markdown file has a heading (regex, %s = escaped version) for the version."""
    if not os.path.isfile(path):
        return False
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return re.search(heading % re.escape(version), text, re.MULTILINE) is not None


def check_tree(meta, require_generated=True):
    """Structural checks of src/. Returns (errors, notes)."""
    errors = []
    notes = []
    for rel in ("meta.xml", "sbin/runway-helper", "DESCRIPTION.md", "CHANGES.md"):
        if not os.path.isfile(os.path.join(SRC, rel)):
            errors.append("missing src/%s" % rel)
    for rel in ("htdocs/index.php", "htdocs/dist/main.js"):
        if not os.path.isfile(os.path.join(SRC, rel)):
            message = ("missing src/%s (generated by the frontend build: run 'bun run build' "
                       "or 'python build.py' without --no-frontend)" % rel)
            (errors if require_generated else notes).append(message)
    if os.path.exists(os.path.join(SRC, "plib", "controllers", "IndexController.php")):
        errors.append("src/plib/controllers/IndexController.php must not exist "
                      "(the generated htdocs/index.php defines IndexController)")
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", meta["id"]):
        errors.append("invalid extension id %r" % meta["id"])
    if not VERSION_RE.match("%s-%s" % (meta["version"], meta["release"])):
        errors.append("invalid version/release %r-%r (expected 1.2.3 and a number)" % (meta["version"], meta["release"]))
    if not changelog_has(os.path.join(SRC, "CHANGES.md"), meta["version"], r"^#{1,3}\s*v?%s(?:-\d+)?(?:\s|$)"):
        errors.append("src/CHANGES.md has no '# %s' entry (shown in the Plesk extension catalog)" % meta["version"])
    if not changelog_has(os.path.join(ROOT, "CHANGELOG.md"), meta["version"], r"^##\s*\[v?%s\]"):
        errors.append("CHANGELOG.md has no '## [%s]' entry" % meta["version"])
    # One version everywhere: the helper reports VERSION to the panel and in its User-Agent.
    try:
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as fh:
            package_version = json.load(fh).get("version")
    except (OSError, ValueError):
        package_version = None
    if package_version != meta["version"]:
        errors.append("package.json has version %r, the package is %s (bump package.json)" % (package_version, meta["version"]))
    helper = os.path.join(SRC, "sbin", "runway-helper")
    if os.path.isfile(helper):
        with open(helper, encoding="utf-8") as fh:
            match = re.search(r'^VERSION = "([^"]*)"$', fh.read(), re.M)
        if not match or match.group(1) != meta["version"]:
            errors.append("src/sbin/runway-helper has VERSION %r, the package is %s (bump VERSION)"
                          % (match.group(1) if match else None, meta["version"]))
    for full, rel in iter_source_files():
        if rel.endswith(".php") or rel.endswith(".phtml"):
            with open(full, "rb") as fh:
                data = fh.read()
            if data.startswith(b"\xef\xbb\xbf"):
                errors.append("%s: UTF-8 BOM is not allowed (breaks PHP output)" % rel)
            if rel.endswith(".php") and not data.lstrip().startswith(b"<?php"):
                errors.append("%s: must start with <?php" % rel)
            if rel.endswith(".php") and data.rstrip().endswith(b"?>"):
                errors.append("%s: must not end with a closing ?> tag" % rel)
        if rel.startswith("sbin/"):
            with open(full, "rb") as fh:
                first = fh.readline()
            if not first.startswith(b"#!"):
                errors.append("%s: sbin scripts need a shebang line" % rel)
    shots = os.path.join(SRC, "_meta", "screenshots")
    if not (os.path.isdir(shots) and any(n.lower().endswith(".png") for n in os.listdir(shots))):
        notes.append("no screenshots in src/_meta/screenshots/ (needed for the Plesk catalog only; "
                     "see docs/RELEASING.md)")
    return errors, notes


# ---------------------------------------------------------------------------
# Packaging and verification
# ---------------------------------------------------------------------------

def cache_buster(meta, main_js):
    """Query string value for dist/main.js: package version plus a hash of the bundle, so every
    upgrade and every rebuilt bundle gets a new URL."""
    return "%s-%s.%s" % (meta["version"], meta["release"], hashlib.sha256(main_js).hexdigest()[:10])


def patch_index_php(data, tag):
    """Adds ?v=<tag> to the dist/main.js reference of the generated index.php."""
    patched, count = MAIN_JS_REF_RE.subn(lambda m: m.group(1) + b"?v=" + tag.encode("ascii") + m.group(3), data)
    if count != 1:
        raise SystemExit("htdocs/index.php: expected one reference to /dist/main.js, found %d" % count)
    return patched


def build(meta):
    os.makedirs(DIST, exist_ok=True)
    target = os.path.join(DIST, package_name(meta))
    if os.path.exists(target):
        os.unlink(target)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        def add(rel, data, mode):
            info = zipfile.ZipInfo(rel, FIXED_DATE)
            info.create_system = 3  # Unix, so external_attr permissions are honoured
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)

        with open(os.path.join(SRC, "htdocs", "dist", "main.js"), "rb") as fh:
            tag = cache_buster(meta, fh.read().replace(b"\r\n", b"\n"))
        for full, rel in iter_source_files():
            if rel == "meta.xml":
                data = packaged_meta_xml(meta)
            else:
                with open(full, "rb") as fh:
                    data = fh.read()
            is_exec = rel.startswith(EXECUTABLE_PREFIXES)
            if is_text(rel):
                data = data.replace(b"\r\n", b"\n")
            if rel == "htdocs/index.php":
                data = patch_index_php(data, tag)
            add(rel, data, 0o755 if is_exec else 0o644)

        for size in ICON_SIZES:
            rel = "_meta/icons/%dx%d.png" % (size, size)
            if not os.path.isfile(os.path.join(SRC, rel)):
                add(rel, make_icon(size), 0o644)
        if not os.path.isfile(os.path.join(SRC, "htdocs/images/logo.png")):
            add("htdocs/images/logo.png", make_icon(64), 0o644)
    return target


def png_size(data):
    """(width, height) of a PNG, or None when the data is not a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def verify_package(path, expected=None):
    """Checks a built zip: safe paths, Unix modes, LF endings, icons, required files, no React
    sources or source maps, and (when given) the expected id/version/release. Returns errors."""
    errors = []
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return ["%s: %s" % (path, exc)]
    with zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            errors.append("duplicate entries in the zip")
        for info in infos:
            name = info.filename
            parts = name.split("/")
            if name.startswith("/") or "\\" in name or ".." in parts:
                errors.append("%s: unsafe path" % name)
                continue
            if name.endswith("/"):
                continue
            if parts[0] in EXCLUDED_DIRS:
                errors.append("%s: the React sources must not be packaged" % name)
            if name.endswith(".map"):
                errors.append("%s: source maps must not be packaged" % name)
            if any(part.startswith(".") for part in parts) or "__pycache__" in parts or name.endswith(".pyc"):
                errors.append("%s: hidden or cache file in the package" % name)
            mode = info.external_attr >> 16
            wanted = 0o100755 if name.startswith(EXECUTABLE_PREFIXES) else 0o100644
            if info.create_system != 3 or mode != wanted:
                errors.append("%s: mode %o, expected %o with Unix attributes" % (name, mode, wanted))
            data = zf.read(name)
            if is_text(name) and b"\r\n" in data:
                errors.append("%s: CRLF line endings" % name)
            if name.endswith((".php", ".phtml")) and data.startswith(b"\xef\xbb\xbf"):
                errors.append("%s: UTF-8 BOM" % name)
            if name.startswith("sbin/") and not data.startswith(b"#!"):
                errors.append("%s: missing shebang line" % name)
        for rel in REQUIRED_IN_PACKAGE:
            if rel not in names:
                errors.append("missing %s" % rel)
        for size in ICON_SIZES:
            rel = "_meta/icons/%dx%d.png" % (size, size)
            if rel not in names:
                errors.append("missing %s" % rel)
            elif png_size(zf.read(rel)) != (size, size):
                errors.append("%s: not a %dx%d PNG" % (rel, size, size))
        found = {}
        if "meta.xml" in names:
            text = zf.read("meta.xml").decode("utf-8", "replace")
            for key in ("id", "version", "release"):
                match = re.search(r"<%s>([^<]+)</%s>" % (key, key), text)
                found[key] = match.group(1).strip() if match else None
            if expected:
                for key in ("id", "version", "release"):
                    if found[key] != expected[key]:
                        errors.append("meta.xml: <%s> is %r, expected %r" % (key, found[key], expected[key]))
        if "htdocs/index.php" in names and "htdocs/dist/main.js" in names and found.get("version"):
            refs = MAIN_JS_REF_RE.findall(zf.read("htdocs/index.php"))
            wanted = cache_buster(found, zf.read("htdocs/dist/main.js")).encode("ascii")
            if len(refs) != 1 or refs[0][1] != b"?v=" + wanted:
                errors.append("htdocs/index.php: dist/main.js must be loaded with the cache-buster ?v=%s"
                              % wanted.decode("ascii"))
    return errors


def report(errors, label="ERROR"):
    for error in errors:
        print("%s: %s" % (label, error), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="validate the source tree only (fails on leftover placeholders); no build, no zip")
    parser.add_argument("--no-frontend", action="store_true",
                        help="do not run the frontend build (package the existing src/htdocs/index.php and dist/)")
    parser.add_argument("--version", metavar="X.Y.Z[-R]",
                        help="package this version (and release) instead of the one in src/meta.xml")
    parser.add_argument("--strict", action="store_true",
                        help="fail the build on leftover placeholders (always on with --check)")
    parser.add_argument("--verify", metavar="ZIP",
                        help="verify an existing package and exit (with --version: also its version)")
    args = parser.parse_args()
    meta = read_meta()
    if args.version:
        meta = apply_version_override(meta, args.version)
    if args.verify:
        errors = verify_package(args.verify, meta if args.version else None)
        if errors:
            report(errors)
            return 1
        print("Package OK: %s" % args.verify)
        return 0

    if not args.check and not args.no_frontend:
        build_frontend()
    errors, notes = check_tree(meta, require_generated=not args.check)
    for note in notes:
        print("NOTE: " + note)
    placeholders = find_placeholders()
    if placeholders:
        strict = args.check or args.strict
        shown = placeholders[:50]
        if len(placeholders) > len(shown):
            shown.append("... and %d more" % (len(placeholders) - len(shown)))
        report(["leftover placeholder: " + item for item in shown], "ERROR" if strict else "WARNING")
        if strict:
            errors.append("%d leftover placeholder(s), see above" % len(placeholders))
    if errors:
        report(errors)
        return 1
    if args.check:
        print("Source tree OK (%s %s-%s)" % (meta["id"], meta["version"], meta["release"]))
        return 0
    target = build(meta)
    problems = verify_package(target, meta)
    if problems:
        report(problems)
        return 1
    print("Built and verified %s (%d bytes)" % (os.path.relpath(target, ROOT), os.path.getsize(target)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
