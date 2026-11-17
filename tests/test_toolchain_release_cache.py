# Copyright 2026 Taiizor. Licensed under the MIT License.
"""CI release-cache preparation without network calls, Docker or access to real credentials."""

import contextlib
import io
import json
import subprocess
import unittest
from unittest import mock

from scripts import cache_toolchain_releases as cache


class ToolchainReleaseCacheTests(unittest.TestCase):
    def test_public_release_metadata_is_fetched_through_authenticated_gh(self):
        release = [{"tag_name": "v1.2.3", "assets": []}]
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps(release), stderr="")
        with mock.patch.object(cache.subprocess, "run", return_value=response) as run:
            metadata = cache.fetch_release_metadata()
        self.assertEqual({repo: release for repo in cache.REPOSITORIES}, metadata)
        self.assertEqual(len(cache.REPOSITORIES), run.call_count)
        for call, (repo, per_page) in zip(run.call_args_list, cache.REPOSITORIES.items()):
            self.assertEqual(["gh", "api", "--method", "GET"], call.args[0][:4])
            self.assertEqual("repos/%s/releases?per_page=%d" % (repo, per_page), call.args[0][4])
            self.assertTrue(call.kwargs["check"])

    def test_invalid_release_lists_fail_before_cache_seeding(self):
        for payload in ({"message": "API error"}, [], ["invalid release"]):
            with self.subTest(payload=payload), \
                    mock.patch.object(cache.subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, stdout=json.dumps(payload), stderr="")):
                with self.assertRaisesRegex(ValueError, "Invalid GitHub release list for oven-sh/bun"):
                    cache.fetch_release_metadata()

    def test_only_release_metadata_reaches_docker(self):
        metadata = {"oven-sh/bun": [{"tag_name": "bun-v1.2.3", "assets": []}]}
        with mock.patch.dict(cache.os.environ, {
            "GH_TOKEN": "workflow-token", "GITHUB_TOKEN": "other-token", "DOCKER_HOST": "test-docker",
        }, clear=True), mock.patch.object(cache.subprocess, "run") as run:
            cache.seed_cache("test-plesk", metadata)
        args, kwargs = run.call_args
        self.assertEqual(["docker", "exec", "-i", "test-plesk", "python3", "-c"], args[0][:6])
        self.assertEqual(metadata, json.loads(kwargs["input"]))
        self.assertEqual({"DOCKER_HOST": "test-docker"}, kwargs["env"])
        self.assertNotIn("workflow-token", " ".join(args[0]) + kwargs["input"])
        self.assertNotIn("other-token", " ".join(args[0]) + kwargs["input"])

    def test_failed_metadata_request_aborts_without_exposing_captured_gh_output(self):
        error = subprocess.CalledProcessError(1, ["gh", "api"], stderr="private-debug-header")
        stderr = io.StringIO()
        with mock.patch.object(cache, "fetch_release_metadata", side_effect=error), \
                mock.patch.object(cache, "seed_cache") as seed, contextlib.redirect_stderr(stderr):
            self.assertEqual(1, cache.main(["--container", "test-plesk"]))
        seed.assert_not_called()
        self.assertIn("Release cache preparation failed", stderr.getvalue())
        self.assertNotIn("private-debug-header", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
