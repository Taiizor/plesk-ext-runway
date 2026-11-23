# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Offline contracts for complete dependency checks and conservative package installation."""

import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


@unittest.skipUnless(sys.platform.startswith("linux"), "the deployed helper requires Linux")
class DependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "src/sbin/runway-helper"
        loader = importlib.machinery.SourceFileLoader("runway_dependencies_test", str(path))
        cls.h = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cls.h)

    def setUp(self):
        self.log = mock.Mock()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patch = mock.patch.object(self.h, "BIN_DIR", directory.name + "/bin")
        patch.start()
        self.addCleanup(patch.stop)

    def test_local_database_checks_require_configured_packages_and_native_architecture(self):
        output = ("git\tinstall ok installed\t1:2.43\ncmake\thold ok installed\t3.28\n"
                  "libssl-dev:amd64\tinstall ok installed\t3.0\n"
                  "libffi-dev\tdeinstall ok config-files\t3.4\n"
                  "libyaml-dev\tinstall ok unpacked\t0.2\n")
        with mock.patch.object(self.h, "run", return_value=SimpleNamespace(stdout=output)) as run, \
                mock.patch.object(self.h, "host_arch", return_value=("amd64", "native")):
            versions = self.h.dependency_versions("apt-get")
            self.assertEqual("3.0", self.h.dependency_version(versions, "libssl-dev"))
            self.assertIsNone(self.h.dependency_version({"libssl-dev:arm64": "3.0"}, "libssl-dev"))
        self.assertEqual({"git": "1:2.43", "cmake": "3.28", "libssl-dev:amd64": "3.0"}, versions)
        self.assertEqual("dpkg-query", run.call_args.args[0][0])

    def test_rpm_versions_include_the_epoch_and_do_not_query_repositories(self):
        with mock.patch.object(self.h, "run", return_value=SimpleNamespace(stdout="gcc\t0:12.1-1\nopenssl-devel\t1:3.0-2\n")) as run:
            self.assertEqual({"gcc": "0:12.1-1", "openssl-devel": "1:3.0-2"}, self.h.dependency_versions("dnf"))
        self.assertEqual("rpm", run.call_args.args[0][0])

    def test_status_includes_missing_headers_even_when_every_executable_exists(self):
        with mock.patch.object(self.h, "dependency_manager", return_value="apt-get"), \
                mock.patch.object(self.h, "dependency_versions", return_value={name: "1" for name in self.h.BUILD_PACKAGES["apt-get"] if name != "libssl-dev"}), \
                mock.patch.object(self.h.shutil, "which", return_value="/usr/bin/tool"):
            status = self.h.build_deps_status()
        self.assertTrue(status["cc"])
        self.assertFalse(status["libssl-dev"])
        self.assertTrue(status["libffi-dev"])

    def test_complete_install_is_offline_even_if_repositories_have_newer_packages(self):
        installed = {name: "old-but-compatible" for name in self.h.BUILD_PACKAGES["apt-get"]}
        with mock.patch.object(self.h, "dependency_manager", return_value="apt-get"), \
                mock.patch.object(self.h, "dependency_versions", return_value=installed), \
                mock.patch.object(self.h.shutil, "which", return_value="/usr/bin/tool"), \
                mock.patch.object(self.h, "dependency_refresh") as refresh, \
                mock.patch.object(self.h, "stream_process") as process, \
                mock.patch.object(self.h, "run") as run:
            self.h.job_build_deps(self.log)
        refresh.assert_not_called()
        process.assert_not_called()
        run.assert_not_called()
        self.assertTrue(any("keeping the installed version" in call.args[0] for call in self.log.line.call_args_list))

    def test_missing_build_headers_refresh_once_and_are_checked_after_installation(self):
        installed = {name: "1" for name in self.h.BUILD_PACKAGES["apt-get"] if name != "libyaml-dev"}
        complete = dict(installed, **{"libyaml-dev": "1"})
        with mock.patch.object(self.h, "dependency_manager", return_value="apt-get"), \
                mock.patch.object(self.h, "dependency_versions", side_effect=[installed, complete]), \
                mock.patch.object(self.h.shutil, "which", return_value="/usr/bin/tool"), \
                mock.patch.object(self.h, "dependency_refresh") as refresh, \
                mock.patch.object(self.h, "dependency_install") as install:
            self.h.job_build_deps(self.log)
        refresh.assert_called_once_with("apt-get", self.log)
        install.assert_called_once_with("apt-get", self.h.BUILD_PACKAGES["apt-get"], self.log)

    def test_apt_requests_only_missing_packages_and_uses_a_private_transaction_guard(self):
        observed = {}

        def process(command, log, timeout, env):
            observed["command"] = command
            guard = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("DPkg::Pre-Install-Pkgs::=")))
            observed["guard"] = guard
            self.assertEqual(0o700, guard.stat().st_mode & 0o777)
            self.assertEqual(0o700, guard.parent.stat().st_mode & 0o777)
            self.assertIn("VERSION 2", guard.read_text())
            return 0

        with mock.patch.object(self.h, "dependency_versions", side_effect=[{"git": "1"}, {"git": "1", "libffi-dev": "2"}]), \
                mock.patch.object(self.h, "run", return_value=SimpleNamespace(stdout="Inst libffi-dev (2 repository [amd64])\n")), \
                mock.patch.object(self.h, "stream_process", side_effect=process):
            self.h.dependency_install("apt-get", ["git", "libffi-dev"], self.log)
        self.assertEqual("libffi-dev", observed["command"][-1])
        self.assertNotIn("git", observed["command"])
        self.assertIn("--no-upgrade", observed["command"])
        self.assertIn("--no-remove", observed["command"])
        self.assertFalse(observed["guard"].parent.exists())

    def test_apt_rejects_transitive_upgrades_downgrades_reinstalls_and_removals(self):
        plans = ("Inst libc6 [1] (2 repo [amd64])\n", "Inst libc6 [2] (1 repo [amd64])\n",
                 "Inst libc6 [1] (1 repo [amd64])\n", "Remv unrelated [1]\n")
        for plan in plans:
            with self.subTest(plan=plan), \
                    mock.patch.object(self.h, "dependency_versions", return_value={"libc6:amd64": "1"}), \
                    mock.patch.object(self.h, "run", return_value=SimpleNamespace(stdout=plan)), \
                    mock.patch.object(self.h, "stream_process") as process:
                with self.assertRaisesRegex(self.h.HelperError, "Update system packages separately"):
                    self.h.dependency_install("apt-get", ["libffi-dev"], self.log)
                process.assert_not_called()

    def test_apt_hook_rechecks_the_real_transaction_and_allows_only_explicit_incompatibilities(self):
        actions = (("new - < 1 /cache/new.deb", None),
                   ("libc6 1 < 2 /cache/libc6.deb", SystemExit),
                   ("libc6 1 = 1 /cache/libc6.deb", SystemExit),
                   ("libc6 1 > - **REMOVE**", SystemExit),
                   ("libc6 1 = 1 **CONFIGURE**", None),
                   ("bubblewrap 0.9 < 0.13 /cache/bwrap.deb", None))
        script = compile(self.h.dependency_apt_guard(("bubblewrap",)), "apt-guard", "exec")
        for action, error in actions:
            with self.subTest(action=action), mock.patch.object(sys, "stdin", io.StringIO("VERSION 2\nconfig=value\n\n" + action + "\n")):
                if error:
                    with self.assertRaises(error):
                        exec(script, {})
                else:
                    exec(script, {})
        with mock.patch.object(sys, "stdin", io.StringIO("VERSION 3\n")), self.assertRaises(SystemExit):
            exec(script, {})

    def test_dnf_excludes_all_installed_packages_except_an_explicit_incompatible_dependency(self):
        before = {"bubblewrap": "0:0.9-1", "libc": "1", "git": "1"}
        after = dict(before, bubblewrap="0:0.13-1")
        with mock.patch.object(self.h, "dependency_versions", side_effect=[before, after]), \
                mock.patch.object(self.h, "stream_process", return_value=0) as process:
            self.h.dependency_install("dnf", ["git", "bubblewrap"], self.log, upgrade=("bubblewrap",))
        command = process.call_args.args[0]
        self.assertIn("--exclude=libc", command)
        self.assertIn("--exclude=git", command)
        self.assertNotIn("--exclude=bubblewrap", command)
        self.assertNotIn("--setopt=strict=0", command)
        self.assertEqual("bubblewrap", command[-1])

    def test_missing_packages_after_successful_transaction_are_reported_as_failure(self):
        with mock.patch.object(self.h, "dependency_versions", return_value={}), \
                mock.patch.object(self.h, "stream_process", return_value=0):
            with self.assertRaisesRegex(self.h.HelperError, "still missing"):
                self.h.dependency_install("dnf", ["libyaml-devel"], self.log)

    def test_unavailable_compiler_is_not_reported_ready_just_because_packages_are_installed(self):
        with mock.patch.object(self.h, "dependency_manager", return_value="dnf"), \
                mock.patch.object(self.h, "dependency_versions", return_value={name: "1" for name in self.h.BUILD_PACKAGES["dnf"]}), \
                mock.patch.object(self.h.shutil, "which", side_effect=lambda name, path: None if name == "cc" else "/usr/bin/" + name), \
                mock.patch.object(self.h, "stream_process") as process:
            with self.assertRaisesRegex(self.h.HelperError, "Repair the installed packages separately"):
                self.h.job_build_deps(self.log)
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
