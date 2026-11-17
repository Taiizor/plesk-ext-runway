#!/usr/bin/env python3
# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Warm a disposable CI container's release cache through the runner's authenticated gh CLI."""

import argparse
import json
import os
import subprocess
import sys


REPOSITORIES = {"oven-sh/bun": 60, "astral-sh/uv": 10, "php/frankenphp": 20}
CONTAINER_CODE = """
import importlib.machinery
import importlib.util
import json
import sys
from unittest import mock

loader = importlib.machinery.SourceFileLoader("runway_ci_cache", "/opt/runway/bin/runway-helper")
helper = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(helper)
for repo, releases in json.load(sys.stdin).items():
    # Use the installed helper's parser and cache format without another network request.
    with mock.patch.object(helper, "http_json", return_value=releases):
        parsed = helper.github_releases(repo, force=True)
    if not parsed:
        raise RuntimeError("No published releases cached for " + repo)
    print("Cached %d releases for %s" % (len(parsed), repo))
"""


def fetch_release_metadata():
    """Only public release JSON leaves the runner; gh retains the workflow credential."""
    metadata = {}
    for repo, per_page in REPOSITORIES.items():
        result = subprocess.run(
            ["gh", "api", "--method", "GET", "repos/%s/releases?per_page=%d" % (repo, per_page),
             "--hostname", "github.com",
             "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2022-11-28"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        releases = json.loads(result.stdout)
        if not isinstance(releases, list) or not releases or not all(isinstance(item, dict) for item in releases):
            raise ValueError("Invalid GitHub release list for " + repo)
        metadata[repo] = releases
    return metadata


def seed_cache(container, metadata):
    # No credential is passed in Docker arguments, stdin or environment.
    env = {key: value for key, value in os.environ.items() if key.upper() not in ("GH_TOKEN", "GITHUB_TOKEN")}
    subprocess.run(
        ["docker", "exec", "-i", container, "python3", "-c", CONTAINER_CODE],
        input=json.dumps(metadata), text=True, encoding="utf-8", check=True, env=env,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="runway-plesk")
    args = parser.parse_args(argv)
    try:
        metadata = fetch_release_metadata()
        seed_cache(args.container, metadata)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        # Captured gh output may contain debug headers; keep it out of CI diagnostics.
        print("Release cache preparation failed: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
