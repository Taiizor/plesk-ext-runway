# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Download retry contracts with real metadata parsing, file writes and checksum validation."""

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


@unittest.skipUnless(sys.platform.startswith("linux"), "the deployed helper requires Linux")
class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "src/sbin/runway-helper"
        loader = importlib.machinery.SourceFileLoader("runway_download_test", str(path))
        cls.h = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cls.h)

    def http_error(self, code):
        return self.h.urllib.error.HTTPError("https://example.test/", code, "test error", {}, io.BytesIO(b"error"))

    def response(self, body):
        stream = io.BytesIO(body)
        stream.headers = {"Content-Length": str(len(body))}
        return stream

    def test_go_metadata_recovers_from_transient_server_errors(self):
        raw = [{"version": "go1.27.4", "stable": True, "files": [
            {"os": "linux", "arch": "amd64", "kind": "archive", "filename": "go1.27.4.linux-amd64.tar.gz",
             "sha256": "a" * 64, "size": 123},
        ]}]
        errors = [self.http_error(500), self.http_error(503)]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(self.h, "CACHE_DIR", directory), \
                mock.patch.object(self.h, "host_arch", return_value=("amd64", "x86_64-unknown-linux-gnu")), \
                mock.patch.object(self.h.urllib.request, "urlopen", side_effect=errors + [self.response(json.dumps(raw).encode())]) as request, \
                mock.patch.object(self.h.time, "sleep") as sleep:
            releases = self.h.go_releases(force=True)
            self.assertEqual("1.27.4", releases[0]["version"])
            self.assertEqual("a" * 64, releases[0]["sha256"])
            self.assertEqual(3, request.call_count)
            self.assertEqual([mock.call(1), mock.call(2)], sleep.call_args_list)
            self.assertEqual("https://go.dev/dl/?mode=json&include=all", request.call_args.args[0].full_url)
        self.assertTrue(all(error.fp.closed for error in errors))

    def test_transient_http_retries_stop_after_three_attempts(self):
        for code in (500, 502, 503, 504):
            with self.subTest(code=code):
                errors = [self.http_error(code) for _ in range(3)]
                with mock.patch.object(self.h.urllib.request, "urlopen", side_effect=errors) as request, \
                        mock.patch.object(self.h.time, "sleep") as sleep:
                    with self.assertRaises(self.h.urllib.error.HTTPError) as caught:
                        self.h.http_get("https://example.test/")
                self.assertIs(errors[-1], caught.exception)
                self.assertEqual(3, request.call_count)
                self.assertEqual([mock.call(1), mock.call(2)], sleep.call_args_list)

    def test_permanent_errors_and_rate_limits_fail_without_retry(self):
        for code in (400, 401, 403, 404, 429, 501):
            with self.subTest(code=code), \
                    mock.patch.object(self.h.urllib.request, "urlopen", side_effect=self.http_error(code)) as request, \
                    mock.patch.object(self.h.time, "sleep") as sleep:
                with self.assertRaises(self.h.urllib.error.HTTPError):
                    self.h.http_get("https://example.test/")
                self.assertEqual(1, request.call_count)
                sleep.assert_not_called()

    def test_archive_retry_uses_the_redirect_opener_and_verifies_the_actual_payload(self):
        payload = b"verified archive payload"
        opener = SimpleNamespace(open=mock.Mock(side_effect=[self.http_error(502), self.response(payload)]))
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(self.h.urllib.request, "urlopen") as default_open, \
                mock.patch.object(self.h.time, "sleep") as sleep:
            dest = str(Path(directory) / "archive.bin")
            self.assertEqual(dest, self.h.download("https://example.test/archive", dest,
                                                  hashlib.sha256(payload).hexdigest(), mock.Mock(), opener=opener))
            self.assertEqual(payload, Path(dest).read_bytes())
            self.assertEqual(2, opener.open.call_count)
            default_open.assert_not_called()
            sleep.assert_called_once_with(1)

    def test_checksum_failure_does_not_trigger_another_download(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(self.h.urllib.request, "urlopen", return_value=self.response(b"wrong payload")) as request, \
                mock.patch.object(self.h.time, "sleep") as sleep:
            with self.assertRaisesRegex(self.h.HelperError, "Checksum mismatch"):
                self.h.download("https://example.test/archive", str(Path(directory) / "archive.bin"), "0" * 64, mock.Mock())
            self.assertEqual(1, request.call_count)
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
