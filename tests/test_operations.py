# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Optional operations using disposable Linux fixtures, without Plesk/systemd/network access."""

import contextlib
import hashlib
import hmac
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux helper contracts")
class OperationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "src/sbin/runway-helper"
        loader = importlib.machinery.SourceFileLoader("runway_operations_test", str(path))
        cls.h = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cls.h)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.source = self.home / "apps/api"
        self.source.mkdir(parents=True)
        self.pw = SimpleNamespace(pw_name="fixture", pw_dir=str(self.home), pw_uid=os.getuid(), pw_gid=os.getgid())
        self.state = {"domain_id": 17, "domain": "api.test", "sysuser": "fixture", "app_dir": str(self.source),
                      "runtime": "binary", "toolchain": "", "start_cmd": "./app", "build_cmd": "", "env": {},
                      "slot": "", "zero_downtime": False, "stopped": False, "enabled": True, "suspended": False,
                      "listen": "tcp", "port": 25001, "build_timeout": 60}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {"OPS_CONFIG_DIR": str(self.root / "config"), "OPS_DATA_DIR": str(self.root / "ops"),
                            "CONF_DIR": str(self.root / "conf"), "STATE_DIR": str(self.root / "state"),
                            "APPS_DIR": str(self.root / "state/apps"),
                            "JOBS_DIR": str(self.root / "jobs"), "LOCK_DIR": str(self.root / "locks")}.items():
            self.stack.enter_context(mock.patch.object(self.h, name, value))
        self.stack.enter_context(mock.patch.object(self.h, "v_sysuser", return_value=self.pw))
        self.stack.enter_context(mock.patch.dict(os.environ, {"HOME": str(self.home)}))
        self.release = "20261115T120000-012345abcdef"

    def options(self, **changes):
        return dict(self.h.ops_defaults(), **changes)

    def as_user(self, _pw, function, *args, **_kwargs):
        return function(*args)

    def test_defaults_do_not_create_metadata_or_change_execution(self):
        options = self.h.ops_options(17)
        for key in ("history", "diagnostics", "preflight", "releases", "notifications", "backup", "backup_secrets", "restore_start"):
            self.assertIs(options[key], False)
        self.assertIsNone(self.h.ops_begin(self.state, "build", "panel", "customer"))
        self.assertEqual(self.state, self.h.ops_execution_state(self.state))
        self.h.ops_preflight(self.state, self.pw, options)
        self.assertFalse((self.root / "ops").exists())

    def test_settings_validate_bounds_paths_secret_and_default_off(self):
        previous = self.options(notification_secret="abcdefghijklmnop")
        self.assertEqual("abcdefghijklmnop", self.h.ops_validate({"notification_secret": ""}, previous)["notification_secret"])
        self.assertEqual("", self.h.ops_validate({"clear_notification_secret": True}, previous)["notification_secret"])
        invalid = [{"history": "true"}, {"history_limit": 0}, {"release_limit": 1}, {"shared_paths": ["../wwwroot"]},
                   {"shared_paths": ["/etc"]}, {"shared_paths": ["a", "a/b"]}, {"shared_paths": ["tmp/files"]},
                   {"shared_paths": ["uploads"], "exclude_paths": ["uploads/private"]},
                   {"notifications": True}, {"notification_url": "http://example.com/hook"},
                   {"notification_url": "https://127.0.0.1/hook"}, {"notification_secret": "short"}, {"unknown": True}]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(self.h.HelperError):
                self.h.ops_validate(values)

    def test_shared_tree_is_skipped_before_size_scan_copy_and_publish(self):
        (self.source / "app").write_bytes(b"code")
        shared = self.source / "wwwroot"
        shared.mkdir()
        (shared / "media.bin").write_bytes(b"m" * 512 * 1024)
        # An unreadable/symlinked descendant is never visited either.
        (shared / "outside").symlink_to(self.root)
        options = self.options(shared_paths=["wwwroot"], release_max_mb=1, min_free_mb=0)
        candidate = self.h._user_prepare_release(str(self.home), 17, str(self.source), self.release, options)
        self.assertEqual(4, candidate["bytes"])
        target = Path(candidate["path"])
        self.assertFalse((target / "wwwroot").exists())
        (target / "publish").mkdir()
        self.h._user_shared_links(str(self.source), str(target), ["wwwroot"], "dotnet")
        self.assertEqual(shared.resolve(), (target / "wwwroot").resolve())
        self.assertEqual(shared.resolve(), (target / "publish/wwwroot").resolve())
        self.h._user_remove_release(str(self.home), 17, self.release)
        self.assertTrue((shared / "media.bin").is_file())
        self.assertFalse(target.exists())

    def test_size_symlink_deadline_and_free_disk_fail_before_copy(self):
        (self.source / "app").write_bytes(b"12345")
        with self.assertRaises(self.h.HelperError):
            self.h._user_release_walk(str(self.source), [], 4, time.monotonic() + 10)
        with self.assertRaises(self.h.HelperError):
            self.h._user_release_walk(str(self.source), [], 100, time.monotonic() - 1)
        with mock.patch.object(self.h.shutil, "disk_usage", return_value=SimpleNamespace(free=0)), self.assertRaises(self.h.HelperError):
            self.h._user_prepare_release(str(self.home), 17, str(self.source), self.release, self.options())
        (self.source / "link").symlink_to(self.root)
        with self.assertRaises(self.h.HelperError):
            self.h._user_release_walk(str(self.source), [], 100, time.monotonic() + 10)
        self.assertFalse(Path(self.h.ops_release_path(self.pw, 17, self.release)).exists())

    def test_release_walk_bounds_directory_descriptors_and_closes_on_failure(self):
        for i in range(140):
            (self.source / str(i)).mkdir()
        before = len(os.listdir("/proc/self/fd"))
        self.assertEqual(140, self.h._user_release_walk(str(self.source), [], 100, time.monotonic() + 10)["entries"])
        self.assertEqual(before, len(os.listdir("/proc/self/fd")))
        current = self.source
        for _depth in range(65):
            current = current / "nested"
            current.mkdir()
        with self.assertRaises(self.h.HelperError):
            self.h._user_release_walk(str(self.source), [], 100, time.monotonic() + 10)
        self.assertEqual(before, len(os.listdir("/proc/self/fd")))

    def test_build_generated_virtualenv_and_dependency_links_are_not_followed(self):
        (self.source / ".venv/bin").mkdir(parents=True)
        (self.source / ".venv/bin/python").symlink_to("/usr/local/bin/python")
        with self.assertRaises(self.h.HelperError):
            self.h._user_release_walk(str(self.source), [], 100, time.monotonic() + 10)
        result = self.h._user_release_walk(str(self.source), [], 100, time.monotonic() + 10, None, True)
        self.assertLess(result["bytes"], 100)

    def test_release_storage_and_cleanup_refuse_symlink_escapes(self):
        (self.home / ".runway").symlink_to(self.root)
        with self.assertRaises(OSError):
            self.h._user_prepare_release(str(self.home), 17, str(self.source), self.release, self.options())
        self.assertFalse((self.root / "releases").exists())

    def test_customer_child_cannot_choose_root_rendered_execution_path(self):
        forged = {"path": "/tmp/forged\nUser=root", "bytes": 1, "entries": 1}
        with mock.patch.object(self.h, "call_as_user", return_value=forged):
            state, copied = self.h.ops_prepare_release(self.state, self.pw, self.options(), self.release)
        expected = self.h.ops_release_path(self.pw, 17, self.release)
        self.assertEqual(expected, state["_release_dir"])
        self.assertEqual(expected, copied["path"])

    def test_shared_link_attachment_refuses_build_output_and_parent_escape(self):
        release_dir = self.home / "candidate"
        (release_dir / "wwwroot").mkdir(parents=True)
        (release_dir / "wwwroot/app.css").write_text("versioned")
        with self.assertRaises(self.h.HelperError):
            self.h._user_shared_links(str(self.source), str(release_dir), ["wwwroot"], "dotnet")
        (release_dir / "outside").symlink_to(self.root)
        with self.assertRaises(self.h.HelperError):
            self.h._user_shared_links(str(self.source), str(release_dir), ["outside/files"], "binary")
        self.assertFalse((self.root / "files").exists())

    def test_execution_selects_each_slot_without_rewriting_logical_source(self):
        data = {"source": self.state["app_dir"], "sysuser": "fixture", "slots": {"": self.release, "a": self.release}}
        with mock.patch.object(self.h, "ops_release_state", return_value=data):
            result = self.h.ops_execution_state(self.state)
            self.assertEqual(self.h.ops_release_path(self.pw, 17, self.release), result["app_dir"])
            self.assertEqual(str(self.source), self.state["app_dir"])
            self.assertEqual(result["app_dir"], self.h.ops_execution_state(dict(self.state, _slot="a"))["app_dir"])
            self.assertEqual(str(self.source), self.h.ops_execution_state(dict(self.state, _slot="b"))["app_dir"])
            self.assertEqual("/changed", self.h.ops_execution_state(dict(self.state, app_dir="/changed"))["app_dir"])

    def test_staging_does_not_replace_live_slot_and_failed_switch_restores_mapping(self):
        first = "20261115T110000-012345abcdef"
        old = {"source": str(self.source), "sysuser": "fixture", "slots": {"a": first}, "records": []}
        self.h.ensure_dir(self.h.ops_dir(17), 0o700)
        self.h.write_json(self.h.ops_dir(17) + "/releases.json", old)
        state = dict(self.state, slot="a", zero_downtime=True)
        previous = self.h.ops_stage_release(state, self.release)
        self.assertEqual({"a": first, "b": self.release}, self.h.ops_release_state(17)["slots"])
        with mock.patch.object(self.h, "unit_is_active", return_value=False), mock.patch.object(self.h, "call_as_user"):
            self.assertTrue(self.h.ops_release_result(state, self.pw, self.options(), self.release, previous, False, True, switched=True))
        self.assertEqual(old, self.h.ops_release_state(17))

    def test_ambiguous_switch_never_removes_a_running_candidate(self):
        state = dict(self.state, slot="a", zero_downtime=True)
        previous = self.h.ops_stage_release(state, self.release)
        with mock.patch.object(self.h, "unit_is_active", return_value=True), mock.patch.object(self.h, "call_as_user") as remove:
            self.assertFalse(self.h.ops_release_result(state, self.pw, self.options(), self.release, previous, False, True, switched=True))
            remove.assert_not_called()
        self.assertEqual(self.release, self.h.ops_release_state(17)["slots"]["b"])

    def test_ambiguous_switch_to_original_sources_preserves_unmapped_target(self):
        data = {"source": self.state["app_dir"], "sysuser": "fixture", "slots": {"": self.release, "a": self.release}}
        self.h.ensure_dir(self.h.ops_dir(17), 0o700)
        self.h.write_json(self.h.ops_dir(17) + "/releases.json", data)
        state = dict(self.state, slot="a", zero_downtime=False)
        previous = self.h.ops_stage_release(state, None, target="")
        with mock.patch.object(self.h, "unit_is_active", return_value=True):
            self.assertFalse(self.h.ops_release_result(state, self.pw, self.options(), None, previous, False, False, switched=True))
        self.assertNotIn("", self.h.ops_release_state(17)["slots"])

    def test_history_redacts_env_values_and_prunes_only_logs(self):
        self.h.ops_save(17, {"history": True, "history_limit": 1})
        self.h.ensure_dir(str(self.root / "jobs"), 0o700)
        self.state["env"] = {"TOKEN": "fixture-secret"}
        self.h.write_file_atomic(self.h.job_paths("deploy-17")[1], "build fixture-secret", 0o600)
        record = self.h.ops_begin(self.state, "build", "panel", "customer\nadmin")
        with mock.patch.object(self.h, "ops_event"):
            self.h.ops_finish(self.state, record, False, "failed", "deploy-17")
            self.assertEqual("customeradmin", self.h.ops_history(17)[0]["actor"])
            self.assertNotIn("fixture-secret", Path(self.h.ops_dir(17), record["id"] + ".log").read_text())
            next_record = self.h.ops_begin(self.state, "restart", "cli", "cli")
            self.h.ops_finish(self.state, next_record, True, "", "deploy-17")
        self.assertEqual(1, len(self.h.ops_history(17)))
        self.assertFalse(Path(self.h.ops_dir(17), record["id"] + ".log").exists())

    def test_recovery_secrets_require_both_export_and_import_opt_in(self):
        options = self.options(backup=True, notifications=True, notification_url="https://example.com/hook", notification_secret="abcdefghijklmnop")
        self.state["env"] = {"TOKEN": "fixture-only"}
        plain = self.h.ops_export(self.state, options)["bundle"]
        self.assertNotIn("environment", plain)
        self.assertFalse(plain["operations"]["notifications"])
        secret_bundle = self.h.ops_export(self.state, dict(options, backup_secrets=True))["bundle"]
        clean, environment = self.h.ops_check_import(secret_bundle, False)
        self.assertEqual("", clean["notification_secret"])
        self.assertIsNone(environment)
        restored, environment = self.h.ops_check_import(secret_bundle, True)
        self.assertEqual("abcdefghijklmnop", restored["notification_secret"])
        self.assertEqual(self.state["env"], environment)
        with self.assertRaises(self.h.HelperError):
            self.h.ops_export(self.state, self.options())

    def test_preflight_is_independent_and_never_blocks_when_disabled(self):
        with mock.patch.object(self.h, "ops_diagnostics", return_value={"checks": [{"key": "disk", "ok": False}]}) as check:
            self.h.ops_preflight(self.state, self.pw, self.options(preflight=True))
            check.assert_not_called()
            with self.assertRaises(self.h.HelperError):
                self.h.ops_preflight(self.state, self.pw, self.options(diagnostics=True, preflight=True))

    def test_notification_signs_exact_body_and_disables_redirects_and_proxies(self):
        options = self.options(notification_url="https://example.com/hook", notification_secret="abcdefghijklmnop")
        event = {"event": "deploy_failed", "detail": {"deployment": self.release}}
        response = mock.MagicMock()
        response.__enter__.return_value.getcode.return_value = 204
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(self.h.urllib.request, "build_opener", return_value=opener) as create:
            self.h._user_send_notification(options, event)
        request = opener.open.call_args[0][0]
        expected = "sha256=" + hmac.new(b"abcdefghijklmnop", request.data, hashlib.sha256).hexdigest()
        self.assertEqual(expected, request.get_header("X-runway-signature"))
        self.assertEqual(event, json.loads(request.data))
        self.assertEqual({}, create.call_args[0][0].proxies)
        self.assertIsInstance(create.call_args[0][1], self.h._PinnedHTTPSHandler)
        self.assertIsNone(create.call_args[0][2].redirect_request(None, None, 302, "", {}, "http://127.0.0.1"))

    def test_notification_error_never_stores_credential_url(self):
        with mock.patch.object(self.h, "call_as_user", side_effect=OSError("https://example.com/secret-token")):
            self.h.ops_notify(self.state, self.options(), {"event": "deploy_failed"})
        result = Path(self.h.ops_dir(17), "notification.json").read_text()
        self.assertNotIn("secret-token", result)
        self.assertEqual("OSError", json.loads(result)["error"])

    def test_running_app_refuses_recovery_or_release_clear(self):
        self.h.ops_save(17, {"backup": True})
        bundle = self.h.ops_export(self.state, self.options(backup=True))["bundle"]
        with mock.patch.object(self.h, "unit_is_active", return_value=True), self.assertRaises(self.h.HelperError):
            self.h.ops_import(self.state, self.pw, bundle)
        with mock.patch.object(self.h, "load_app_state", return_value=(self.state, self.pw)), self.assertRaises(self.h.HelperError):
            self.h.cmd_operations({"domain_id": 17, "action": "clear-releases"})

    def deployment_fixture(self, mode="build", stopped=False, slots=False):
        self.state, self.pw = self.h.validate_app({"domain_id": 17, "domain": "api.test", "sysuser": "fixture",
            "app_root": "apps/api", "runtime": "binary", "start_cmd": "./app", "build_cmd": "echo build",
            "enabled": True, "port": 25001, "build_timeout": 60, "zero_downtime": slots})
        self.state.update(stopped=stopped, slot="a" if slots else "")
        self.h.ops_save(17, {"releases": True, "history": True, "min_free_mb": 0, "shared_paths": ["wwwroot"]})
        (self.source / "app").write_text("versioned")
        (self.source / "wwwroot").mkdir()
        (self.source / "wwwroot/media.bin").write_bytes(b"x" * 1024)
        for path in (self.h.app_state_path(17), self.h.job_paths("deploy-17")[2], self.h.app_triggers_path(17)):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.h.write_json(self.h.app_state_path(17), self.state)
        self.h.write_json(self.h.job_paths("deploy-17")[2], {"mode": mode, "actor": "customer"})
        patches = {"load_app_state": mock.Mock(return_value=(self.state, self.pw)),
                   "trigger_mtimes": mock.Mock(return_value={}), "call_as_user": mock.Mock(side_effect=self.as_user),
                   "job_set_status": mock.Mock(), "JobLog": mock.Mock(), "merged_env": mock.Mock(return_value={}),
                   "_build_preexec": mock.Mock(return_value=None), "stream_process": mock.Mock(return_value=0),
                   "deploy_open_public_files": mock.Mock(), "write_units": mock.Mock(),
                   "systemctl": mock.Mock(), "prepare_start": mock.Mock(), "unit_is_active": mock.Mock(return_value=False),
                   "restart_and_check": mock.Mock(return_value=(True, None)), "zd_restart": mock.Mock(return_value=(True, None))}
        for name, value in patches.items():
            self.stack.enter_context(mock.patch.object(self.h, name, value))
        return patches

    def test_full_deploy_builds_candidate_and_stopped_deploy_never_starts(self):
        patches = self.deployment_fixture(stopped=True)
        self.h._deploy_once(17, "deploy-17")
        patches["restart_and_check"].assert_not_called()
        patches["zd_restart"].assert_not_called()
        selected = self.h.ops_release_state(17)["slots"][""]
        release_path = self.h.ops_release_path(self.pw, 17, selected)
        self.assertEqual(release_path, patches["_build_preexec"].call_args[0][1])
        self.assertTrue(Path(release_path, "wwwroot").is_symlink())
        self.assertEqual("succeeded", self.h.ops_history(17)[0]["state"])
        self.assertEqual("customer", self.h.ops_history(17)[0]["actor"])

    def test_full_failed_classic_deploy_restores_old_mapping_and_records_failure(self):
        patches = self.deployment_fixture()
        old = {"source": self.state["app_dir"], "sysuser": "fixture", "slots": {"": self.release},
               "records": [self.h.ops_release_record(self.state, self.release)]}
        self.h.ensure_dir(self.h.ops_dir(17), 0o700)
        self.h.write_json(self.h.ops_dir(17) + "/releases.json", old)
        patches["restart_and_check"].side_effect = self.h.HelperError("candidate failed")
        self.h._deploy_once(17, "deploy-17")
        self.assertEqual(old, self.h.ops_release_state(17))
        patches["systemctl"].assert_any_call("restart", self.h.UNIT_APP % 17, timeout=120)
        self.assertEqual("failed", self.h.ops_history(17)[0]["state"])
        self.assertFalse(Path(self.h.ops_release_path(self.pw, 17, self.h.ops_history(17)[0]["release"])).exists())

    def test_full_failed_slot_deploy_keeps_live_mapping(self):
        restart = self.h.zd_restart
        patches = self.deployment_fixture(slots=True)
        old = {"source": self.state["app_dir"], "sysuser": "fixture", "slots": {"a": self.release},
               "records": [self.h.ops_release_record(self.state, self.release)]}
        self.h.ensure_dir(self.h.ops_dir(17), 0o700)
        self.h.write_json(self.h.ops_dir(17) + "/releases.json", old)
        patches["unit_is_active"].side_effect = lambda unit: unit == self.h.app_unit(17, "a")
        patches["zd_restart"].side_effect = restart
        with mock.patch.object(self.h, "zd_switch", side_effect=self.h.HelperError("readiness failed")), \
                mock.patch.object(self.h, "read_pointer_slot", return_value="a"):
            self.h._deploy_once(17, "deploy-17")
        self.assertEqual(old, self.h.ops_release_state(17))
        patches["restart_and_check"].assert_not_called()
        self.assertFalse(any(call.args[:1] == ("restart",) for call in patches["systemctl"].call_args_list))
        self.assertEqual("failed", self.h.ops_history(17)[0]["state"])

    def test_rollback_rejects_incompatible_start_command_without_switching(self):
        patches = self.deployment_fixture(mode="rollback")
        old = {"source": self.state["app_dir"], "sysuser": "fixture", "slots": {"": self.release},
               "records": [dict(self.h.ops_release_record(self.state, self.release), start_hash="incompatible")]}
        self.h.ensure_dir(self.h.ops_dir(17), 0o700)
        self.h.write_json(self.h.ops_dir(17) + "/releases.json", old)
        self.h.write_json(self.h.job_paths("deploy-17")[2], {"mode": "rollback", "release": self.release})
        self.h._deploy_once(17, "deploy-17")
        patches["restart_and_check"].assert_not_called()
        self.assertEqual(old, self.h.ops_release_state(17))
        self.assertEqual("failed", self.h.ops_history(17)[0]["state"])

    def test_first_zero_downtime_start_selects_code_for_actual_classic_unit(self):
        restart = self.h.zd_restart
        self.deployment_fixture(slots=True)
        self.state["slot"] = ""
        context = {"selected": self.release}
        with mock.patch.object(self.h, "zd_plain_restart", return_value=(self.state, self.h.UNIT_APP % 17)):
            restart(self.state, self.pw, "deploy-17", mock.Mock(), release_context=context)
        self.assertEqual({"": self.release}, self.h.ops_release_state(17)["slots"])
        self.assertFalse(context["switch"])

    def test_running_switch_selects_code_for_other_slot(self):
        restart = self.h.zd_restart
        patches = self.deployment_fixture(slots=True)
        patches["unit_is_active"].return_value = True
        context = {"selected": self.release}
        with mock.patch.object(self.h, "zd_switch", return_value=(True, None)):
            restart(self.state, self.pw, "deploy-17", mock.Mock(), release_context=context)
        self.assertEqual({"b": self.release}, self.h.ops_release_state(17)["slots"])
        self.assertTrue(context["switch"])

    def test_forced_plain_restart_selects_code_for_current_slot(self):
        restart = self.h.zd_restart
        self.deployment_fixture(slots=True)
        self.state["restart_plain"] = True
        context = {"selected": self.release}
        with mock.patch.object(self.h, "zd_plain_restart", return_value=(self.state, self.h.app_unit(17, "a"))):
            restart(self.state, self.pw, "deploy-17", mock.Mock(), release_context=context)
        self.assertEqual({"a": self.release}, self.h.ops_release_state(17)["slots"])
        self.assertFalse(context["switch"])

    def test_retiring_slots_preserves_live_code_or_explicitly_staged_classic_code(self):
        old = "20261115T110000-012345abcdef"
        self.h.ensure_dir(self.h.ops_dir(17), 0o700)
        data = {"source": self.state["app_dir"], "sysuser": "fixture", "slots": {"": old, "a": self.release}}
        self.h.write_json(self.h.ops_dir(17) + "/releases.json", data)
        self.h.ops_retire_slots(dict(self.state, slot="a"))
        self.assertEqual({"": self.release}, self.h.ops_release_state(17)["slots"])
        self.h.write_json(self.h.ops_dir(17) + "/releases.json", data)
        self.h.ops_retire_slots(dict(self.state, slot="a"), True)
        self.assertEqual({"": old}, self.h.ops_release_state(17)["slots"])


if __name__ == "__main__":
    unittest.main()
