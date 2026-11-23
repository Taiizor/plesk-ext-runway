# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Offline dependency selection, verified installation and atomic publication contracts."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


@unittest.skipUnless(sys.platform.startswith("linux"), "the deployed helper requires Linux")
class IsolationDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "src/sbin/runway-helper"
        loader = importlib.machinery.SourceFileLoader("runway_dependency_test", str(path))
        cls.h = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cls.h)

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, value in (("BASE_DIR", self.root), ("BIN_DIR", self.bin),
                            ("ISOLATION_BWRAP", self.root / "system-bwrap"),
                            ("ISOLATION_MANAGED_BWRAP", self.bin / "bwrap")):
            self.stack.enter_context(mock.patch.object(self.h, name, str(value)))
        self.log = mock.Mock()

    def status(self, ready=False, managed=False, version=None):
        return {"available": ready, "bubblewrap": ready, "libseccomp": True,
                "version": version or (self.h.ISOLATION_SOURCE_VERSION if ready else ""),
                "path": (self.h.ISOLATION_MANAGED_BWRAP if managed else self.h.ISOLATION_BWRAP) if ready else "",
                "reason": "" if ready else "Missing compatible bubblewrap"}

    def test_existing_executable_must_meet_version_and_feature_requirements(self):
        metadata = SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o755)
        for version, help_text in (("bubblewrap 0.9.0", "--bind-fd --ro-bind-fd --seccomp"),
                                   ("bubblewrap 0.13.1", "--seccomp"),
                                   ("unexpected output", "--bind-fd --ro-bind-fd --seccomp")):
            with self.subTest(version=version), mock.patch.object(self.h.os, "stat", return_value=metadata), \
                    mock.patch.object(self.h, "run", side_effect=[SimpleNamespace(returncode=0, stdout=version),
                                                                SimpleNamespace(returncode=0, stdout=help_text)]):
                with self.assertRaises(self.h.HelperError):
                    self.h._isolation_check_bwrap(self.h.ISOLATION_BWRAP)

    def test_backend_prefers_the_distribution_and_can_use_the_managed_copy(self):
        with mock.patch.object(self.h, "_isolation_check_bwrap", return_value="0.13.1") as verify, \
                mock.patch.object(self.h, "_isolation_seccomp_library"):
            self.assertEqual(self.h.ISOLATION_BWRAP, self.h.isolation_backend())
            self.assertEqual(1, verify.call_count)
        with mock.patch.object(self.h, "_isolation_check_bwrap", side_effect=[self.h.HelperError("too old"), "0.13.1"]), \
                mock.patch.object(self.h, "_isolation_seccomp_library"):
            self.assertEqual(self.h.ISOLATION_MANAGED_BWRAP, self.h.isolation_backend())

    def test_missing_library_never_reports_dependencies_ready(self):
        with mock.patch.object(self.h, "_isolation_bwrap_details", return_value={"path": "/usr/bin/bwrap", "version": "0.13.1"}), \
                mock.patch.object(self.h, "_isolation_seccomp_library", side_effect=self.h.HelperError("missing library")):
            result = self.h.isolation_dependencies_status()
        self.assertTrue(result["bubblewrap"])
        self.assertFalse(result["libseccomp"])
        self.assertFalse(result["available"])
        self.assertIn("missing library", result["reason"])

    def test_repository_candidates_handle_old_packages_epochs_and_both_managers(self):
        for manager, output, supported in (("apt-get", "  Candidate: 0.9.0-1ubuntu0.3\n", False),
                                           ("apt-get", "  Candidate: 1:0.13.1-1\n", True),
                                           ("apt-get", "  Candidate: (none)\n", False),
                                           ("dnf", "bubblewrap.x86_64 0.8.0-2.el9 epel\n", False),
                                           ("dnf", "bubblewrap.x86_64 0.8.0-2.el9 epel\nbubblewrap.x86_64 0.13.1-1.el9 updates\n", True)):
            with self.subTest(manager=manager, output=output), \
                    mock.patch.object(self.h, "run", return_value=SimpleNamespace(returncode=0, stdout=output)):
                self.assertEqual(supported, self.h._isolation_repository_supported(manager))

    def test_compatible_system_installation_is_idempotent_and_offline(self):
        with mock.patch.object(self.h, "isolation_dependencies_status", return_value=self.status(True)), \
                mock.patch.object(self.h, "dependency_manager") as manager, \
                mock.patch.object(self.h, "_isolation_build_bwrap") as build:
            self.h.job_isolation_deps(self.log)
        manager.assert_not_called()
        build.assert_not_called()

    def test_old_distribution_uses_a_verified_build_without_installing_an_obsolete_package(self):
        with mock.patch.object(self.h, "isolation_dependencies_status", side_effect=[self.status(), self.status(), self.status(True, True)]), \
                mock.patch.object(self.h, "dependency_manager", return_value="apt-get"), \
                mock.patch.object(self.h, "dependency_refresh"), \
                mock.patch.object(self.h, "_isolation_repository_supported", return_value=False), \
                mock.patch.object(self.h, "dependency_install") as packages, \
                mock.patch.object(self.h, "_isolation_build_bwrap") as build:
            self.h.job_isolation_deps(self.log)
        packages.assert_not_called()  # The existing compatible libseccomp is kept.
        build.assert_called_once_with("apt-get", self.log)

    def test_supported_distribution_updates_only_the_incompatible_bubblewrap(self):
        with mock.patch.object(self.h, "isolation_dependencies_status", side_effect=[self.status(), self.status(), self.status(True), self.status(True)]), \
                mock.patch.object(self.h, "dependency_manager", return_value="dnf"), \
                mock.patch.object(self.h, "dependency_refresh"), \
                mock.patch.object(self.h, "_isolation_repository_supported", return_value=True), \
                mock.patch.object(self.h, "dependency_install") as packages, \
                mock.patch.object(self.h, "_isolation_build_bwrap") as build:
            self.h.job_isolation_deps(self.log)
        packages.assert_called_once_with("dnf", ["bubblewrap"], self.log, upgrade=("bubblewrap",))
        build.assert_not_called()

    def test_compatible_managed_versions_are_kept_even_when_the_pinned_release_is_newer(self):
        for version in ("0.10.0", "0.13.1", "99.0.0"):
            with self.subTest(version=version), \
                    mock.patch.object(self.h, "isolation_dependencies_status", return_value=self.status(True, True, version)), \
                    mock.patch.object(self.h, "dependency_manager") as manager, \
                    mock.patch.object(self.h, "dependency_install") as packages, \
                    mock.patch.object(self.h, "_isolation_build_bwrap") as build:
                self.h.job_isolation_deps(self.log)
            manager.assert_not_called()
            packages.assert_not_called()
            build.assert_not_called()

    def test_missing_library_does_not_replace_a_compatible_managed_binary(self):
        current = self.status(True, True, "0.10.0")
        current.update(available=False, libseccomp=False)
        with mock.patch.object(self.h, "isolation_dependencies_status", side_effect=[current, self.status(True, True, "0.10.0"), self.status(True, True, "0.10.0")]), \
                mock.patch.object(self.h, "dependency_manager", return_value="dnf"), \
                mock.patch.object(self.h, "dependency_refresh"), \
                mock.patch.object(self.h, "dependency_install") as packages, \
                mock.patch.object(self.h, "_isolation_build_bwrap") as build:
            self.h.job_isolation_deps(self.log)
        packages.assert_called_once_with("dnf", ["libseccomp"], self.log)
        build.assert_not_called()

    def test_build_uses_a_pinned_bounded_download_and_private_workspace(self):
        observed = {}

        def archive(url, destination, digest, log, limit):
            observed.update(url=url, digest=digest, limit=limit, work=Path(destination).parent)
            content = b"project('fixture', 'c')\n"
            with tarfile.open(destination, "w:xz") as output:
                member = tarfile.TarInfo("bubblewrap-" + self.h.ISOLATION_SOURCE_VERSION + "/meson.build")
                member.size = len(content)
                output.addfile(member, io.BytesIO(content))
            return destination

        def process(command, log, timeout, env):
            self.assertEqual(str(observed["work"]), os.path.commonpath([env["HOME"], str(observed["work"])]))
            self.assertEqual(str(observed["work"]), os.path.commonpath([env["TMPDIR"], str(observed["work"])]))
            self.assertEqual(0o700, stat.S_IMODE(observed["work"].stat().st_mode))
            if command[0] == "ninja":
                target = Path(command[2])
                target.mkdir()
                (target / "bwrap").write_bytes(b"\x7fELFfixture")
            return 0

        with mock.patch.object(self.h, "download", side_effect=archive), \
                mock.patch.object(self.h, "dependency_install"), \
                mock.patch.object(self.h, "stream_process", side_effect=process), \
                mock.patch.object(self.h, "_isolation_publish_binary") as publish:
            self.h._isolation_build_bwrap("apt-get", self.log)
        self.assertEqual(self.h.ISOLATION_SOURCE_URL, observed["url"])
        self.assertEqual(self.h.ISOLATION_SOURCE_SHA256, observed["digest"])
        self.assertEqual(4 * 1024 * 1024, observed["limit"])
        self.assertFalse(observed["work"].exists())
        publish.assert_called_once()

    def test_failed_binary_validation_keeps_the_previous_copy_and_removes_temporary_files(self):
        source = self.root / "built"
        previous = Path(self.h.ISOLATION_MANAGED_BWRAP)
        previous.write_bytes(b"previous")
        for content in (b"#!/bin/sh\n", b"\x7fELFfixture"):
            source.write_bytes(content)
            with mock.patch.object(self.h, "_isolation_check_bwrap", side_effect=self.h.HelperError("invalid build")):
                with self.assertRaises(self.h.HelperError):
                    self.h._isolation_publish_binary(str(source))
            self.assertEqual(b"previous", previous.read_bytes())
            self.assertEqual([], list(self.bin.glob(".bwrap-*")))

    def test_atomic_publication_keeps_the_system_binary_untouched_and_never_sets_setuid(self):
        source = self.root / "built"
        source.write_bytes(b"\x7fELFfixture")
        system = Path(self.h.ISOLATION_BWRAP)
        system.write_text("distribution package")
        with mock.patch.object(self.h, "_isolation_check_bwrap", return_value=self.h.ISOLATION_SOURCE_VERSION):
            self.h._isolation_publish_binary(str(source))
        self.assertEqual("distribution package", system.read_text())
        published = Path(self.h.ISOLATION_MANAGED_BWRAP)
        self.assertEqual(b"\x7fELFfixture", published.read_bytes())
        self.assertEqual(0o755, stat.S_IMODE(published.stat().st_mode))
        self.assertEqual([], list(self.bin.glob(".bwrap-*")))

    def test_xz_source_archive_rejects_traversal(self):
        archive = self.root / "source.tar.xz"
        with tarfile.open(archive, "w:xz") as output:
            member = tarfile.TarInfo("../outside")
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
        destination = self.root / "extract"
        destination.mkdir()
        with self.assertRaises(self.h.HelperError):
            self.h.safe_extract(str(archive), str(destination))
        self.assertFalse((self.root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
