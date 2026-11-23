# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Later uploads become readable without building or restarting the application."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HELPER = Path(__file__).resolve().parent.parent / "src" / "sbin" / "runway-helper"


@unittest.skipUnless(sys.platform.startswith("linux"), "public file permissions require Linux")
class PublicFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("runway_public_files", str(HELPER))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.h = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.h)

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.app = self.root / "apps/example"
        self.public = self.app / "wwwroot"
        self.public.mkdir(parents=True)
        self.units = self.root / "units"
        self.units.mkdir()
        (self.root / "states").mkdir()
        self.state = {"domain_id": 17, "app_dir": str(self.app), "app_root": "apps/example",
                      "document_root": "apps/example/wwwroot", "runtime": "dotnet", "listen": "unix",
                      "enabled": True, "suspended": False, "tampered": False, "stopped": False}
        self.pw = SimpleNamespace(pw_dir=str(self.root))
        self.stack.enter_context(mock.patch.object(self.h, "UNIT_DIR", str(self.units)))
        self.stack.enter_context(mock.patch.object(self.h, "LOCK_DIR", str(self.root / "locks")))
        self.stack.enter_context(mock.patch.object(self.h, "APPS_DIR", str(self.root / "states")))
        self.load = self.stack.enter_context(mock.patch.object(self.h, "load_app_state", return_value=(self.state, self.pw)))
        self.systemctl = self.stack.enter_context(mock.patch.object(self.h, "systemctl"))
        self.active = self.stack.enter_context(mock.patch.object(self.h, "unit_is_active", return_value=False))
        self.stack.enter_context(mock.patch.object(self.h, "unit_enabled", return_value=True))
        # Exercise the actual descriptor-based walk with the test process's own uid.
        self.call_as_user = self.h.call_as_user
        self.as_user = self.stack.enter_context(mock.patch.object(
            self.h, "call_as_user", side_effect=lambda pw, func, *args, **kwargs: func(*args)))

    def mode(self, path):
        return stat.S_IMODE(path.stat().st_mode)

    def tick(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.h.internal_public_files(17)
        return output.getvalue()

    def test_files_uploaded_after_initial_scan_are_repaired_without_deploy_or_restart(self):
        self.tick()
        folder = self.public / "uploads/reports"
        folder.mkdir(parents=True)
        uploaded = folder / "report.pdf"
        uploaded.write_bytes(b"download")
        for path, mode in ((folder.parent, 0o770), (folder, 0o750), (uploaded, 0o640)):
            path.chmod(mode)
        secret = self.app / "appsettings.json"
        secret.write_text("private")
        secret.chmod(0o600)
        hidden = folder / ".env"
        hidden.write_text("private")
        hidden.chmod(0o600)
        hidden_dir = folder / ".private"
        hidden_dir.mkdir(mode=0o700)
        (hidden_dir / "secret").write_text("private")
        (hidden_dir / "secret").chmod(0o600)
        (folder / "link").symlink_to(secret)
        (folder / "linked-dir").symlink_to(self.app, target_is_directory=True)
        os.mkfifo(str(folder / "pipe"), 0o600)

        self.assertIn("readable for the web server", self.tick())
        self.assertEqual(0o775, self.mode(folder.parent))
        self.assertEqual(0o755, self.mode(folder))
        self.assertEqual(0o644, self.mode(uploaded))
        for path in (secret, hidden, hidden_dir / "secret", folder / "pipe"):
            self.assertEqual(0o600, self.mode(path))
        self.assertEqual(0o700, self.mode(hidden_dir))
        self.systemctl.assert_not_called()
        self.assertEqual("", self.tick())  # Rechecking an unchanged tree is silent.
        self.as_user.assert_called()
        self.assertIs(self.h._user_open_public_files, self.as_user.call_args.args[1])

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "privilege drop requires root")
    def test_periodic_scan_really_drops_privileges_and_preserves_another_owners_files(self):
        account = self.h.pwd.getpwnam("nobody")
        pw = SimpleNamespace(pw_name=account.pw_name, pw_uid=account.pw_uid,
                             pw_gid=account.pw_gid, pw_dir=str(self.root))
        uploaded = self.public / "upload.txt"
        uploaded.write_text("download")
        uploaded.chmod(0o640)
        foreign = self.public / "root-owned.txt"
        foreign.write_text("private")
        foreign.chmod(0o640)
        for path in (self.root, self.root / "apps", self.app, self.public, uploaded):
            os.chown(str(path), pw.pw_uid, pw.pw_gid)
        self.public.chmod(0o750)
        self.load.return_value = (self.state, pw)
        with mock.patch.object(self.h, "call_as_user", self.call_as_user):
            self.tick()
        self.assertEqual(0o644, self.mode(uploaded))
        self.assertEqual(0o640, self.mode(foreign))
        self.assertEqual(0, foreign.stat().st_uid)

    def test_each_check_uses_current_root_and_leaves_sources_and_outside_roots_alone(self):
        old = self.public / "old.txt"
        old.write_text("old")
        old.chmod(0o640)
        other = self.app / "public"
        other.mkdir(mode=0o750)
        new = other / "new.txt"
        new.write_text("new")
        new.chmod(0o640)
        self.state["document_root"] = "apps/example/public"
        self.tick()
        self.assertEqual(0o644, self.mode(new))
        self.assertEqual(0o640, self.mode(old))
        for root in ("apps/example", "apps", "outside"):
            with self.subTest(root=root):
                self.state["document_root"] = root
                self.assertEqual("", self.tick())
                self.assertEqual(0o640, self.mode(old))

    def test_disabled_suspended_workers_and_deployments_are_skipped_but_stopped_apps_are_checked(self):
        for changes in ({"enabled": False}, {"suspended": True}, {"tampered": True},
                        {"listen": "none"}, {"document_root": ""}):
            with self.subTest(changes=changes), mock.patch.dict(self.state, changes):
                self.tick()
        self.as_user.assert_not_called()
        self.active.return_value = True
        self.tick()
        self.as_user.assert_not_called()
        self.active.return_value = False
        self.state["stopped"] = True
        self.tick()
        self.as_user.assert_called_once()

    def test_scan_never_takes_the_deploy_lock(self):
        with self.h.FileLock("deploy-17"):
            self.tick()
        self.as_user.assert_called_once()

    def test_timer_install_recovery_and_removal(self):
        self.h.sync_public_files_units(self.state)
        service = self.units / "runway-public-files-17.service"
        timer = self.units / "runway-public-files-17.timer"
        self.assertIn("_public-files 17", service.read_text())
        self.assertIn("TimeoutStartSec=120", service.read_text())
        self.assertIn("OnUnitInactiveSec=60", timer.read_text())
        self.systemctl.assert_any_call("enable", "--now", timer.name, check=True)
        self.systemctl.reset_mock()
        self.active.return_value = True
        self.h.sync_public_files_units(self.state)
        self.systemctl.assert_not_called()
        self.active.return_value = False
        self.h.sync_public_files_units(self.state)
        self.systemctl.assert_called_once_with("enable", "--now", timer.name, check=True)
        self.state["enabled"] = False
        self.h.sync_public_files_units(self.state)
        self.assertFalse(timer.exists())
        self.assertFalse(service.exists())
        self.systemctl.assert_any_call("disable", "--now", timer.name)
        self.systemctl.assert_any_call("stop", service.name)

    def test_document_root_sync_installs_the_timer_without_changing_customer_files(self):
        self.h.write_json(self.h.app_state_path(17), self.state)
        uploaded = self.public / "upload.txt"
        uploaded.write_text("download")
        uploaded.chmod(0o640)
        result = self.h.cmd_app_docroot({"domain_id": 17, "document_root": "apps/example/wwwroot"})
        self.assertIsNone(result["public"])
        self.assertEqual(0o640, self.mode(uploaded))
        self.assertTrue((self.units / "runway-public-files-17.timer").exists())
        self.tick()
        self.assertEqual(0o644, self.mode(uploaded))
        self.h.cmd_app_docroot({"domain_id": 17, "document_root": ""})
        self.assertFalse((self.units / "runway-public-files-17.timer").exists())
        self.assertEqual("", self.h.read_json(self.h.app_state_path(17))["document_root"])

    def test_removing_an_application_stops_and_removes_its_permission_units(self):
        self.h.sync_public_files_units(self.state)
        self.systemctl.reset_mock()
        with contextlib.ExitStack() as stack:
            # Other application resources belong to the host, outside this temporary unit tree.
            for name in ("remove_socket_dir", "remove_link", "remove_include", "ops_remove_metadata", "sync_health_units"):
                stack.enter_context(mock.patch.object(self.h, name))
            remove = stack.enter_context(mock.patch.object(self.h, "remove_quietly"))
            self.h.remove_app(17)
        stopped = self.systemctl.call_args_list[0].args
        for name in ("runway-public-files-17.timer", "runway-public-files-17.service"):
            self.assertIn(name, stopped)
            remove.assert_any_call(str(self.units / name))


if __name__ == "__main__":
    unittest.main()
