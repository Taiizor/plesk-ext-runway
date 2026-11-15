#!/usr/bin/env python3
# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Map CodeQL's complete-helper analysis copy back to the committed standalone script.

Usage: python scripts/helper_sarif.py <SARIF file or directory>
The analysis copy is byte-identical, so line numbers and code snippets need no adjustment.
"""

import argparse
import json
import sys
from pathlib import Path

ANALYSIS_PATH = "codeql-helper/runway_helper.py"
COMMITTED_PATH = "src/sbin/runway-helper"


def remap_locations(value):
    """Rewrite matching artifact URIs at any depth, including code flows and artifact tables."""
    count = 0
    if isinstance(value, dict):
        uri = value.get("uri")
        if isinstance(uri, str) and (uri == ANALYSIS_PATH or uri.endswith("/" + ANALYSIS_PATH)):
            value["uri"] = uri[:-len(ANALYSIS_PATH)] + COMMITTED_PATH
            count += 1
        count += sum(remap_locations(child) for child in value.values())
    elif isinstance(value, list):
        count += sum(remap_locations(child) for child in value)
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="CodeQL SARIF output file or directory")
    args = parser.parse_args(argv)
    files = sorted(args.path.rglob("*.sarif")) if args.path.is_dir() else [args.path]
    if not files:
        parser.error("no SARIF files found in %s" % args.path)
    try:
        reports = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in files]
        total = 0
        for path, report in reports:
            count = remap_locations(report)
            if count:
                path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                total += count
    except (OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    print("Mapped %d helper artifact URI(s) to %s" % (total, COMMITTED_PATH))
    return 0


if __name__ == "__main__":
    sys.exit(main())
