# Copyright 2026 Taiizor. Licensed under the MIT License.
"""All-runtime isolation policy, execution boundaries and offline namespace fixtures."""

import base64
import contextlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import socket
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock


@unittest.skipUnless(sys.platform.startswith("linux"), "isolation requires Linux namespaces")
class IsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "src/sbin/runway-helper"
        loader = importlib.machinery.SourceFileLoader("runway_isolation_test", str(path))
        cls.h = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cls.h)

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.home = self.root / "home"
        self.app = self.home / "apps/api"
        self.app.mkdir(parents=True)
        self.pw = SimpleNamespace(pw_name="fixture", pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(self.home))
        self.state = {"domain_id": 17, "sysuser": "fixture", "domain": "api.test", "app_root": "apps/api",
                      "app_dir": str(self.app), "runtime": "binary", "toolchain": "", "listen": "unix", "port": 25001,
                      "build_cmd": "echo build", "start_cmd": "./app", "env": {}, "enabled": True,
                      "suspended": False, "stopped": False, "switch": None, "slot": "", "zero_downtime": False,
                      "limits": {"memory_mb": 0, "cpu_percent": 0, "tasks": 0}, "build_limits": {},
                      "build_timeout": 60, "auto_deploy": False}
        for name, value in {"ISOLATION_CONFIG_DIR": self.root / "policy", "LOCK_DIR": self.root / "locks",
                            "OPS_CONFIG_DIR": self.root / "operations", "OPS_DATA_DIR": self.root / "ops-data",
                            "APPS_DIR": self.root / "states", "UNIT_DIR": self.root / "units",
                            "RUN_DIR": self.root / "run", "RERENDER_DIR": self.root / "rerender"}.items():
            value.mkdir()
            self.stack.enter_context(mock.patch.object(self.h, name, str(value)))
        self.stack.enter_context(mock.patch.object(self.h, "load_app_state", return_value=(self.state, self.pw)))
        self.stack.enter_context(mock.patch.object(self.h, "v_sysuser", return_value=self.pw))
        self.real_backend = self.h.isolation_backend
        self.backend = self.stack.enter_context(mock.patch.object(self.h, "isolation_backend", return_value="/usr/bin/bwrap"))
        self.probe = self.stack.enter_context(mock.patch.object(self.h, "isolation_probe"))
        self.stack.enter_context(mock.patch.object(self.h, "ensure_socket_dir"))
        self.systemctl = self.stack.enter_context(mock.patch.object(self.h, "systemctl"))
        self.stack.enter_context(mock.patch.object(self.h, "unit_is_active", return_value=False))
        self.stack.enter_context(mock.patch.object(self.h, "call_as_user", side_effect=lambda pw, fn, *a, **kw: fn(*a)))
        self.stack.enter_context(mock.patch.object(self.h, "cached_systemd_version", return_value=255))
        if os.environ.get("RUNWAY_ISOLATION_FIXTURES") != "1":
            # Pure policy/mount-plan tests do not need libseccomp or bubblewrap installed.
            # The offline runner and Plesk integration tests exercise the real syscall filter.
            self.stack.enter_context(mock.patch.object(self.h, "_isolation_seccomp_fd",
                                                       side_effect=lambda: os.memfd_create("fixture-filter", 0)))
        Path(self.h.socket_dir(17)).mkdir()

    def options(self, **changes):
        value = dict(self.h.isolation_defaults(), enabled=True, writable_paths=["uploads"])
        value.update(changes)
        self.h.write_json(self.h.isolation_config_path(17), value)
        return value

    def test_policy_rejects_traversal_absolute_paths_unknown_fields_and_fake_booleans(self):
        for values in ({"enabled": "true"}, {"network": "anything"}, {"read_only": False},
                       {"writable_paths": ["../other"]}, {"writable_paths": ["/etc"]},
                       {"writable_paths": ["."]}, {"writable_paths": [".runway/x"]},
                       {"writable_paths": [".git/hooks"]}, {"writable_paths": ["a"] * 21},
                       {"socket_paths": ["/etc/shadow"]}, {"socket_paths": ["/run/../etc/shadow"]},
                       {"socket_paths": ["/run/a"] * 9}):
            with self.subTest(values=values), self.assertRaises(self.h.HelperError):
                self.h.isolation_validate(values)
        self.assertFalse(self.h.isolation_options(17)["enabled"])
        Path(self.h.isolation_config_path(17)).write_text("invalid json")
        with self.assertRaises(self.h.HelperError):
            self.h.isolation_options(17)

    def test_every_runtime_uses_the_same_wrapper_and_gets_private_dependency_caches(self):
        self.options()
        for runtime in self.h.RUNTIME_KEYS:
            with self.subTest(runtime=runtime):
                state = dict(self.state, runtime=runtime)
                for build in (False, True):
                    command = self.h.isolation_command(state, self.pw, ["/bin/sh", "-c", "echo test"], build)
                    self.assertEqual("_isolate", command[1])
                    plan = json.loads(base64.b64decode(command[2]))
                    self.assertEqual(runtime, plan["runtime"])
                    self.assertEqual(build, plan["build"])
                    self.assertNotIn("env", plan)
                    self.assertIsNone(plan["command"])
                env = self.h.merged_env(state, self.pw)
                self.assertEqual(self.h.isolation_home(state, self.pw), env["HOME"])
                unit = self.h.render_app_unit(state, self.pw)
                self.assertIn(" _isolate ", unit)
                # ProtectKernelTunables would make the kernel refuse bubblewrap's own /proc.
                for line in ("MemoryMax=1024M", "CPUQuota=100%", "TasksMax=1024", "NoNewPrivileges=yes", "ProtectKernelTunables=no"):
                    self.assertIn(line, unit)
        self.assertEqual(set(self.h.RUNTIME_KEYS), set(self.h.ISOLATION_RUNTIME_PATHS))

    def test_disabled_policy_preserves_existing_execution_and_explicit_resource_limits_win(self):
        command = ["/bin/bash", "-c", "./app"]
        self.assertIs(command, self.h.isolation_command(self.state, self.pw, command))
        unit = self.h.render_app_unit(self.state, self.pw)
        self.assertNotIn(" _isolate ", unit)
        self.assertIn("ProtectKernelTunables=yes", unit)
        self.options()
        state = dict(self.state, limits={"memory_mb": 2048, "cpu_percent": 250, "tasks": 4096})
        self.assertEqual(state["limits"], self.h.isolation_limits(state))
        self.assertIn("MemoryMax=1024M", self.h.render_deploy_service(state))

    def test_preparation_rejects_symlinks_in_code_cache_and_writable_paths(self):
        self.options()
        outside = self.home / "other-app"
        outside.mkdir()
        (self.app / "uploads").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.h.isolation_prepare(self.state, self.pw)
        (self.app / "uploads").unlink()
        self.h.isolation_prepare(self.state, self.pw)
        cache = self.home / ".runway/isolation/17/home"
        cache.rmdir()
        cache.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.h.isolation_prepare(self.state, self.pw)

    def test_secret_start_commands_never_enter_unit_files_or_public_wrapper_arguments(self):
        self.options()
        self.state["start_cmd"] = "./app --password secret-command-value"
        unit = self.h.render_app_unit(self.state, self.pw)
        self.assertNotIn("secret-command-value", unit)
        encoded = unit.split(" _isolate ", 1)[1].splitlines()[0]
        self.assertNotIn("secret-command-value", base64.b64decode(encoded).decode())
        self.assertIn("RUNWAY_ISOLATION_PARTS=", self.h.render_env_file(self.state, self.pw))
        with self.assertRaises(self.h.HelperError):
            self.h.v_env({"RUNWAY_ISOLATION_COMMAND": "untrusted"})

    def test_loader_and_crypto_environment_is_only_restored_inside_the_sandbox(self):
        original = {"HOME": str(self.home), "PATH": "/app/custom/bin", "OPENSSL_CONF": "/app/engine.conf",
                    "LD_LIBRARY_PATH": "/app/lib", "BASH_ENV": "/app/startup", "TOKEN": "private-token"}
        outer = self.h.isolation_outer_environment(original, ["/bin/bash", "-c", "./app"])
        for key in ("OPENSSL_CONF", "LD_LIBRARY_PATH", "BASH_ENV", "TOKEN"):
            self.assertNotIn(key, outer)
        raw = "".join(outer["RUNWAY_ISOLATION_DATA_%d" % i] for i in range(int(outer["RUNWAY_ISOLATION_PARTS"])))
        self.assertEqual(original, json.loads(base64.b64decode(raw))["environment"])

    def test_backend_must_be_a_root_owned_non_setuid_non_writable_executable(self):
        for uid, mode in ((1000, 0o755), (0, 0o775), (0, 0o4755), (0, 0o644)):
            with self.subTest(uid=uid, mode=mode), \
                    mock.patch.object(self.h.os, "stat", return_value=SimpleNamespace(st_uid=uid, st_mode=stat.S_IFREG | mode)):
                with self.assertRaises(self.h.HelperError):
                    self.real_backend()

    def test_unix_socket_grants_cannot_be_used_to_mount_regular_files_or_symlinks(self):
        path = self.root / "service.sock"
        with socket.socket(socket.AF_UNIX) as service:
            service.bind(str(path))
            fd = self.h._isolation_socket_fd(str(path))
            self.assertTrue(stat.S_ISSOCK(os.fstat(fd).st_mode))
            os.close(fd)
        path.unlink()
        path.write_text("dummy private file")
        with self.assertRaises(self.h.HelperError):
            self.h._isolation_socket_fd(str(path))
        link = self.root / "linked.sock"
        link.symlink_to(path)
        with self.assertRaises(self.h.HelperError):
            self.h._isolation_socket_fd(str(link))

    def test_classic_configuration_saves_cannot_race_an_isolation_policy_change(self):
        with mock.patch.object(self.h, "DEPLOY_LOCK_WAIT", 0.3), self.h.FileLock("deploy-17"):
            with self.assertRaisesRegex(self.h.HelperError, "Another deployment or settings change is in progress"):
                self.h._app_apply(dict(self.state))
            with self.assertRaisesRegex(self.h.HelperError, "still in progress") as refused:
                self.h.cmd_app_action({"domain_id": 17, "action": "start"})
            self.assertEqual("operation_in_progress", refused.exception.code)
            with self.assertRaises(self.h.HelperError) as refused:
                self.h.cmd_app_deploy({"domain_id": 17})
            self.assertEqual("operation_in_progress", refused.exception.code)
        self.systemctl.assert_not_called()

    def test_tampering_found_by_a_status_query_waits_for_a_start_in_progress(self):
        holder = self.h.FileLock("deploy-17")
        self.assertTrue(holder.acquire(blocking=False))
        threading.Timer(0.4, holder.release).start()
        self.h.write_json(self.h.app_state_path(17), self.state)
        found = [("a symbolic link (still there)", "", {"path": "/run/runway/17/app.sock"})]
        with mock.patch.object(self.h, "contain_tampering", side_effect=lambda s, d: s.update(stopped=True, tampered=True, tampered_detail=d)) as contain, \
                mock.patch.object(self.h, "socket_check", side_effect=lambda s, pw: found[0] if found else None):
            caller = dict(self.state)
            started = time.monotonic()
            self.h.contain_tampering_waiting(caller, self.pw, "a symbolic link")
            self.assertGreaterEqual(time.monotonic() - started, 0.3)
            contain.assert_called_once()
            self.assertEqual("a symbolic link (still there)", contain.call_args.args[1])
            self.assertTrue(caller["tampered"])  # the caller's state carries the containment
            contain.reset_mock()
            found.clear()  # the operation it waited for (e.g. a Start) removed the entry
            self.h.contain_tampering_waiting(dict(self.state), self.pw, "a symbolic link")
            contain.assert_not_called()
            with mock.patch.object(self.h, "STOP_LOCK_WAIT", 0.2), self.h.FileLock("deploy-17"):
                self.h.contain_tampering_waiting(dict(self.state), self.pw, "a symbolic link")  # contained anyway
            contain.assert_called_once()

    def test_saves_and_starts_wait_for_a_short_holder_of_the_deploy_lock(self):
        holder = self.h.FileLock("deploy-17")
        self.assertTrue(holder.acquire(blocking=False))
        threading.Timer(0.4, holder.release).start()
        started = time.monotonic()
        lock, reason = self.h.try_deploy_lock(17, 5)
        try:
            self.assertIsNone(reason)
            self.assertGreaterEqual(time.monotonic() - started, 0.3)
        finally:
            lock.release()
        with self.h.FileLock("deploy-17"):
            self.assertEqual((None, "busy"), self.h.try_deploy_lock(17, 0.2))

    def test_a_running_deployment_refuses_saves_and_starts_at_once_but_never_stop(self):
        deploying = mock.patch.object(self.h, "unit_is_active", side_effect=lambda unit: unit == self.h.UNIT_DEPLOY % 17)
        with deploying, mock.patch.object(self.h, "DEPLOY_LOCK_WAIT", 30):
            started = time.monotonic()
            # The 1.0 wording: tests/helper-smoke.sh and docs/DESIGN.md section 12.5 rely on it.
            with self.assertRaisesRegex(self.h.HelperError, "^A deployment is running for this application") as refused:
                self.h._app_apply(dict(self.state))
            self.assertEqual("deployment_running", refused.exception.code)
            for refuse in (lambda: self.h.cmd_app_deploy({"domain_id": 17}),
                           lambda: self.h.cmd_isolation({"domain_id": 17, "action": "save", "options": {"enabled": True}}),
                           lambda: self.h.cmd_operations({"domain_id": 17, "action": "save", "options": {}})):
                with self.assertRaises(self.h.HelperError) as refused:
                    refuse()
                self.assertEqual("deployment_running", refused.exception.code)
            for action in ("start", "restart", "recover"):
                with self.subTest(action=action), \
                        self.assertRaisesRegex(self.h.HelperError, "^A deployment is already running for this application$"):
                    self.h.cmd_app_action({"domain_id": 17, "action": action})
            self.assertLess(time.monotonic() - started, 5)
            self.systemctl.assert_not_called()
            with self.h.FileLock("deploy-17"), mock.patch.object(self.h, "update_state_flags") as flags, \
                    mock.patch.object(self.h, "ops_event"):
                self.h.cmd_app_action({"domain_id": 17, "action": "stop"})
            flags.assert_called_once_with(17, stopped=True)
            self.systemctl.assert_any_call("disable", "--now", self.h.UNIT_APP % 17, check=True, timeout=120)

    def test_reapply_defers_a_busy_application_and_strips_its_root_exec_lines(self):
        unit = Path(self.h.UNIT_DIR) / (self.h.UNIT_APP % 17)
        unit.write_text("[Service]\nExecStartPre=+/bin/mkdir -p /run/runway/17\nExecStart=/bin/true\n")
        with mock.patch.object(self.h, "iter_app_states", return_value=[dict(self.state)]), \
                mock.patch.object(self.h, "unit_is_active", side_effect=lambda name: name == self.h.UNIT_DEPLOY % 17), \
                mock.patch.object(self.h, "run") as run, mock.patch.object(self.h, "write_units") as write_units, \
                mock.patch.object(self.h, "ensure_layout"), mock.patch.object(self.h, "sync_health_units"), \
                mock.patch.object(self.h, "sync_metrics_units"), mock.patch.object(self.h, "sync_public_files_units"):
            result = self.h.cmd_reapply_all(None)
            self.assertTrue(os.path.exists(self.h.rerender_marker_path(17)))
            with mock.patch.object(self.h, "iter_app_states", return_value=[dict(self.state, toolchain="1")]), \
                    mock.patch.object(self.h, "validate_app", return_value=(dict(self.state), self.pw)):
                self.assertEqual(0, self.h.rerender_runtime_apps("binary"))
        write_units.assert_not_called()
        self.assertEqual(0, result["count"])
        self.assertIn("#17: a deployment is running; its units are re-rendered once the deploy lock is free", result["errors"])
        self.assertNotIn("ExecStartPre=+", unit.read_text())
        self.assertIn("ExecStart=/bin/true", unit.read_text())
        for call in run.call_args_list:
            command = call.args[0]
            self.assertEqual(["systemd-run", "--on-active=60", "--unit=runway-rerender-17"], command[:3])
            self.assertEqual([self.h.HELPER_COPY, "_rerender", "17"], command[-3:])
        self.assertEqual(2, run.call_count)

    def test_a_waiting_save_keeps_the_variables_another_save_stored_meanwhile(self):
        self.h.write_json(self.h.app_state_path(17), dict(self.state, env={"API_KEY": "old"}))
        payload = {key: value for key, value in self.state.items() if key != "env"}
        holder = self.h.FileLock("deploy-17")
        self.assertTrue(holder.acquire(blocking=False))

        def other_save():
            self.h.write_json(self.h.app_state_path(17), dict(self.state, env={"API_KEY": "new"}))
            holder.release()

        threading.Timer(0.4, other_save).start()
        with mock.patch.object(self.h, "write_units"), mock.patch.object(self.h, "prepare_start"), \
                mock.patch.object(self.h, "ensure_layout"), mock.patch.object(self.h, "web_server_group"), \
                mock.patch.object(self.h, "allocate_port", return_value=25001):
            result = self.h._app_apply(payload)
        self.assertEqual({"API_KEY": "new"}, result["state"]["env"])
        self.assertEqual({"API_KEY": "new"}, self.h.read_json(self.h.app_state_path(17))["env"])

    def test_a_stop_that_arrives_while_start_waits_wins(self):
        holder = self.h.FileLock("deploy-17")
        self.assertTrue(holder.acquire(blocking=False))

        def stop():
            self.state["stopped"] = True  # what Stop wrote while Restart waited for the lock
            holder.release()

        threading.Timer(0.4, stop).start()
        with self.assertRaisesRegex(self.h.HelperError, "stopped while this action waited") as refused:
            self.h.cmd_app_action({"domain_id": 17, "action": "restart"})
        self.assertEqual("stopped_meanwhile", refused.exception.code)
        self.systemctl.assert_not_called()

    def test_stop_waits_briefly_for_a_short_holder_but_never_fails_on_the_lock(self):
        holder = self.h.FileLock("deploy-17")
        self.assertTrue(holder.acquire(blocking=False))
        threading.Timer(0.4, holder.release).start()
        with mock.patch.object(self.h, "update_state_flags"), mock.patch.object(self.h, "ops_event"):
            started = time.monotonic()
            self.h.cmd_app_action({"domain_id": 17, "action": "stop"})
            self.assertGreaterEqual(time.monotonic() - started, 0.3)
            self.systemctl.reset_mock()
            with mock.patch.object(self.h, "STOP_LOCK_WAIT", 0.2), self.h.FileLock("deploy-17"):
                self.h.cmd_app_action({"domain_id": 17, "action": "stop"})
        self.systemctl.assert_any_call("disable", "--now", self.h.UNIT_APP % 17, check=True, timeout=120)

    def test_reconcile_schedules_a_lost_rerender_again_and_drops_markers_of_removed_apps(self):
        self.h.write_json(self.h.app_state_path(17), self.state)
        for domain_id in (17, 18):
            Path(self.h.rerender_marker_path(domain_id)).write_text("")
        with mock.patch.object(self.h, "run") as run:
            self.h.reschedule_rerenders()
        self.assertEqual(1, run.call_count)
        self.assertEqual([self.h.HELPER_COPY, "_rerender", "17"], run.call_args.args[0][-3:])
        self.assertTrue(os.path.exists(self.h.rerender_marker_path(17)))
        self.assertFalse(os.path.exists(self.h.rerender_marker_path(18)))

    def test_deferred_rerender_waits_for_the_deploy_lock_and_renders_the_units(self):
        Path(self.h.rerender_marker_path(17)).write_text("")
        holder = self.h.FileLock("deploy-17")
        self.assertTrue(holder.acquire(blocking=False))
        threading.Timer(0.4, holder.release).start()
        with mock.patch.object(self.h, "write_units") as write_units, mock.patch.object(self.h, "sync_public_files_units"), \
                mock.patch.object(self.h, "deploy_timeout", return_value=10):
            self.h.internal_rerender(17)
            write_units.assert_called_once_with(self.state, self.pw)
            self.systemctl.assert_any_call("daemon-reload")
            self.assertFalse(os.path.exists(self.h.rerender_marker_path(17)))
            write_units.reset_mock()
            with mock.patch.object(self.h, "load_app_state", side_effect=self.h.HelperError("removed")):
                self.h.internal_rerender(17)
            write_units.assert_not_called()
            # A request that arrives while the re-render runs keeps its marker for Reconcile.
            Path(self.h.rerender_marker_path(17)).write_text("first")
            write_units.side_effect = lambda *a: Path(self.h.rerender_marker_path(17)).write_text("second")
            self.h.internal_rerender(17)
            self.assertEqual("second", Path(self.h.rerender_marker_path(17)).read_text())

    def test_removal_waits_for_the_deploy_lock_and_only_uninstall_goes_on_without_it(self):
        unit = os.path.join(self.h.UNIT_DIR, self.h.UNIT_APP % 17)
        with contextlib.ExitStack() as stack:
            for name in ("remove_socket_dir", "remove_link", "remove_include", "ops_remove_metadata", "sync_health_units"):
                stack.enter_context(mock.patch.object(self.h, name))
            remove = stack.enter_context(mock.patch.object(self.h, "remove_quietly"))
            stack.enter_context(mock.patch.object(self.h, "LOCK_TIMEOUT", 0.3))
            stack.enter_context(self.h.FileLock("deploy-17"))
            with self.assertRaisesRegex(self.h.HelperError, "still in progress"):
                self.h.remove_app(17)
            self.assertNotIn(mock.call(unit), remove.call_args_list)
            self.h.remove_app(17, force=True)
        remove.assert_any_call(unit)
        remove.assert_any_call(self.h.rerender_marker_path(17))
        self.systemctl.assert_any_call("stop", "runway-rerender-17.timer", "runway-rerender-17.service",
                                       "runway-redeploy-17.timer", "runway-redeploy-17.service", timeout=60)

    def test_uninstall_removes_every_application_and_its_leftover_units(self):
        units = Path(self.h.UNIT_DIR)
        (units / (self.h.UNIT_APP % 17)).write_text("[Service]\n")
        (units / "runway-app-99.service").write_text("[Service]\n")  # an application without a state
        (self.root / "tmpfiles").mkdir()
        inside = str(self.root)

        def remove_quietly(path):
            # Only files of this fixture: the other paths of an application are real ones.
            if str(path).startswith(inside) and os.path.lexists(path):
                os.remove(path)

        with contextlib.ExitStack() as stack:
            for name in ("remove_socket_dir", "remove_link", "remove_include", "ops_remove_metadata",
                         "sync_health_units", "sync_metrics_units"):
                stack.enter_context(mock.patch.object(self.h, name))
            stack.enter_context(mock.patch.object(self.h, "remove_quietly", side_effect=remove_quietly))
            stack.enter_context(mock.patch.object(self.h, "iter_app_states", return_value=[dict(self.state)]))
            stack.enter_context(mock.patch.object(self.h, "LOCK_TIMEOUT", 0.3))
            stack.enter_context(mock.patch.object(self.h, "TMPFILES_DIR", str(self.root / "tmpfiles")))
            rmtree = stack.enter_context(mock.patch.object(self.h.shutil, "rmtree"))
            stack.enter_context(self.h.FileLock("deploy-17"))
            result = self.h.cmd_uninstall({})
        self.assertEqual([17], result["removed_apps"])
        self.assertEqual(["removed leftover units: runway-app-99.service"], result["errors"])
        self.assertEqual([], sorted(path.name for path in units.iterdir()))
        self.assertTrue(rmtree.called)

    def test_uninstall_sweeps_leftover_application_units_only(self):
        units = Path(self.h.UNIT_DIR)
        leftovers = ["runway-app-99-b.service", "runway-app-99.service", "runway-deploy-99.path",
                     "runway-deploy-99.service", "runway-public-files-99.timer"]
        kept = ["runway-health.timer", "runway-converge.service", "runway-job-admin.service", "other.service"]
        for name in leftovers + kept:
            (units / name).write_text("[Unit]\n")
        self.assertEqual(leftovers, self.h.remove_leftover_app_units())
        self.assertEqual(sorted(kept), sorted(path.name for path in units.iterdir()))
        self.systemctl.assert_any_call("disable", "--now", *leftovers, timeout=120)
        self.systemctl.assert_any_call("stop", "runway-rerender-*.timer", "runway-rerender-*.service",
                                       "runway-redeploy-*.timer", "runway-redeploy-*.service", timeout=60)

    def test_customer_application_removal_keeps_the_administrator_policy(self):
        self.options()
        with contextlib.ExitStack() as stack:
            for name in ("remove_socket_dir", "remove_link", "remove_include", "ops_remove_metadata", "sync_health_units"):
                stack.enter_context(mock.patch.object(self.h, name))
            remove = stack.enter_context(mock.patch.object(self.h, "remove_quietly"))
            self.h.remove_app(17)
        self.assertTrue(self.h.isolation_options(17)["enabled"])
        self.assertNotIn(mock.call(self.h.isolation_config_path(17)), remove.call_args_list)

    def test_failed_namespace_probe_preserves_the_previous_policy_and_running_processes(self):
        self.probe.side_effect = self.h.HelperError("kernel refuses user namespaces")
        with self.assertRaises(self.h.HelperError):
            self.h.cmd_isolation({"domain_id": 17, "action": "save", "options": {"enabled": True}})
        self.systemctl.assert_not_called()
        self.assertFalse(self.h.isolation_options(17)["enabled"])

    def test_policy_changes_stop_old_slots_then_queue_an_isolated_build_and_preserve_stopped_state(self):
        written = []
        with mock.patch.object(self.h, "write_units", side_effect=lambda *a: written.append(self.h.isolation_options(17))), \
                mock.patch.object(self.h, "existing_app_units", return_value=["a.service", "b.service"]), \
                mock.patch.object(self.h, "start_deploy_job") as deploy:
            result = self.h.cmd_isolation({"domain_id": 17, "action": "save", "options": {"enabled": True}})
            self.assertTrue(result["options"]["enabled"])
            self.systemctl.assert_any_call("stop", "a.service", "b.service", check=True, timeout=120)
            self.assertTrue(written[0]["enabled"])
            deploy.assert_called_once_with(17, "build", False, actor="panel")
            self.state["stopped"] = True
            self.h.cmd_isolation({"domain_id": 17, "action": "save", "options": {"enabled": True, "network": "offline"}})
            self.assertTrue(deploy.call_args.args[2])

    def test_offline_tcp_is_rejected_and_a_setup_failure_never_runs_unconfined(self):
        self.state["listen"] = "tcp"
        with self.assertRaises(self.h.HelperError):
            self.h.cmd_isolation({"domain_id": 17, "action": "save", "options": {"enabled": True, "network": "offline"}})
        self.systemctl.assert_not_called()
        self.state["listen"] = "unix"
        self.backend.side_effect = self.h.HelperError("backend unavailable")
        with self.assertRaises(self.h.HelperError):
            self.h.cmd_isolation({"domain_id": 17, "action": "save", "options": {"enabled": True}})
        self.assertFalse(self.h.isolation_options(17)["enabled"])

    def test_a_render_failure_leaves_the_new_policy_enforced_and_the_application_stopped(self):
        with mock.patch.object(self.h, "write_units", side_effect=self.h.HelperError("cannot render")), \
                mock.patch.object(self.h, "existing_app_units", return_value=["a.service"]), \
                mock.patch.object(self.h, "update_state_flags") as flags:
            with self.assertRaises(self.h.HelperError):
                self.h.cmd_isolation({"domain_id": 17, "action": "save", "options": {"enabled": True}})
            self.assertTrue(self.h.isolation_options(17)["enabled"])
            flags.assert_called_once_with(17, stopped=True)

    def test_source_and_release_slots_have_separate_code_mounts_and_explicit_shared_data(self):
        self.options(writable_paths=["storage"])
        (self.app / "storage").mkdir()
        self.h.write_json(self.h.ops_config_path(17), {"shared_paths": ["storage"]})
        release = self.home / ".runway/releases/17/release"
        release.mkdir(parents=True)
        (release / "storage").symlink_to(self.app / "storage", target_is_directory=True)
        state = dict(self.state, app_dir=str(release))
        self.h.isolation_prepare(state, self.pw)
        args, fds = self.h.isolation_bwrap_args(self.h.isolation_plan(state, self.pw, ["/bin/true"]), os.getuid(), os.getgid())
        try:
            self.assertIn(str(release), args)
            self.assertIn(str(self.app / "storage"), args)
            self.assertIn("--ro-bind-fd", args)
            self.assertIn("--bind-fd", args)
        finally:
            for fd in fds:
                os.close(fd)

    @unittest.skipUnless(os.environ.get("RUNWAY_ISOLATION_FIXTURES") == "1", "use scripts/test_isolation.py for bounded offline execution")
    def test_real_namespaces_block_sibling_secrets_source_writes_host_processes_and_network(self):
        self.options(network="offline")
        self.h.isolation_prepare(self.state, self.pw)
        sibling = self.home / "apps/other"
        sibling.mkdir()
        (sibling / "secret").write_text("dummy sibling secret")
        source = self.app / "source.txt"
        source.write_text("immutable code")
        (self.app / "escape").symlink_to(sibling, target_is_directory=True)
        script = """import json,os,pathlib,socket
app=pathlib.Path(%r)
assert not pathlib.Path(%r).exists()
assert not (app/'escape/secret').exists()
assert os.stat('/proc/self/ns/pid').st_ino != %d
try:
    (app/'source.txt').write_text('changed')
except OSError:
    pass
else:
    raise AssertionError('source code was writable')
(app/'uploads/output.txt').write_text('allowed')
assert 'NoNewPrivs:\\t1' in pathlib.Path('/proc/self/status').read_text()
assert not [fd for fd in os.listdir('/proc/self/fd') if int(fd)>3]
import ctypes,errno,platform,subprocess,threading
libc=ctypes.CDLL(None,use_errno=True)
assert libc.unshare(0x10000000)==-1 and ctypes.get_errno()==errno.EPERM
assert libc.setns(-1,0)==-1 and ctypes.get_errno()==errno.EPERM
assert libc.syscall(435,0,0)==-1 and ctypes.get_errno()==errno.ENOSYS
number=56 if platform.machine()=='x86_64' else 220
child=libc.syscall(number,0x10000011,0,0,0,0)
if child==0:
    os._exit(99)
if child>0:
    os.waitpid(child,0)
    raise AssertionError('clone created a nested user namespace')
assert ctypes.get_errno()==errno.EPERM
event=threading.Event(); thread=threading.Thread(target=event.set); thread.start(); thread.join(2)
assert event.is_set()
subprocess.run(['/bin/true'],check=True,timeout=2)
s=socket.socket()
try:
    s.connect(('192.0.2.1',80))
except OSError:
    pass
else:
    raise AssertionError('offline network connected')
print(json.dumps({'isolated':True}))
""" % (str(self.app), str(sibling), os.stat('/proc/self/ns/pid').st_ino)
        plan = self.h.isolation_plan(self.state, self.pw, ["/usr/bin/python3", "-c", script])
        args, fds = self.h.isolation_bwrap_args(plan, os.getuid(), os.getgid())
        try:
            result = subprocess.run(args, pass_fds=fds, capture_output=True, text=True, timeout=15,
                                    env={"PATH": "/usr/bin:/bin", "HOME": str(self.home), "LANG": "C.UTF-8"})
        finally:
            for fd in fds:
                os.close(fd)
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        self.assertTrue(json.loads(result.stdout)["isolated"])
        self.assertEqual("immutable code", source.read_text())
        self.assertEqual("allowed", (self.app / "uploads/output.txt").read_text())

    @unittest.skipUnless(os.environ.get("RUNWAY_ISOLATION_FIXTURES") == "1", "use scripts/test_isolation.py")
    def test_real_unprivileged_launcher_restores_private_environment_after_confinement(self):
        self.options(network="offline")
        self.h.isolation_prepare(self.state, self.pw)
        outside = self.home / "outside"
        outside.mkdir()
        command = ["/usr/bin/python3", "-c",
                   "import os,pathlib; assert os.environ['TOKEN']=='dummy-token'; "
                   "assert os.environ['OPENSSL_CONF']=='/unavailable/custom.conf'; "
                   "assert not any(k.startswith('RUNWAY_ISOLATION_') for k in os.environ); "
                   "assert not pathlib.Path(%r).exists(); print('launcher-confined')" % str(outside)]
        env = self.h.isolation_outer_environment({"HOME": str(self.home), "TOKEN": "dummy-token",
                                                  "OPENSSL_CONF": "/unavailable/custom.conf"}, command)
        encoded = self.h.isolation_command(self.state, self.pw, command)[2]
        helper = str(Path(__file__).resolve().parents[1] / "src/sbin/runway-helper")
        # The outer test namespace maps the trusted host root to an unmapped uid. Only the
        # package ownership probe, fixture passwd identity and scratch run directory are
        # substituted in this child; the launcher and namespace construction are unchanged.
        bootstrap = """import importlib.machinery,importlib.util,os,types
assert 'OPENSSL_CONF' not in os.environ and 'TOKEN' not in os.environ
loader=importlib.machinery.SourceFileLoader('launcher',%r)
h=importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name,loader)); loader.exec_module(h)
h.isolation_backend=lambda:'/usr/bin/bwrap'
h.pwd.getpwuid=lambda uid:types.SimpleNamespace(pw_dir=%r,pw_name='fixture')
h.RUN_DIR=%r
h.internal_isolate(%r)
""" % (helper, str(self.home), self.h.RUN_DIR, encoded)
        result = subprocess.run(["/usr/bin/python3", "-I", "-c", bootstrap], env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("launcher-confined", result.stdout.strip())

    @unittest.skipUnless(os.environ.get("RUNWAY_ISOLATION_FIXTURES") == "1", "use scripts/test_isolation.py")
    def test_real_offline_service_can_connect_only_to_its_granted_filesystem_socket(self):
        with tempfile.TemporaryDirectory(dir="/run") as service_dir, socket.socket(socket.AF_UNIX) as server:
            path = service_dir + "/database.sock"
            hidden = service_dir + "/private-key"
            Path(hidden).write_text("fixture-secret")
            server.bind(path)
            server.listen(1)
            server.settimeout(5)
            self.options(network="offline", socket_paths=[path])
            self.h.isolation_prepare(self.state, self.pw)
            command = ["/usr/bin/python3", "-c",
                       "import pathlib,socket; assert not pathlib.Path(%r).exists(); "
                       "s=socket.socket(socket.AF_UNIX); s.connect(%r); s.sendall(b'fixture'); s.close()" % (hidden, path)]
            args, fds = self.h.isolation_bwrap_args(self.h.isolation_plan(self.state, self.pw, command), os.getuid(), os.getgid())
            try:
                result = subprocess.run(args, pass_fds=fds, env={"PATH": "/usr/bin:/bin"},
                                        capture_output=True, text=True, timeout=15)
            finally:
                for fd in fds:
                    os.close(fd)
            self.assertEqual(0, result.returncode, result.stderr)
            connection, _ = server.accept()
            with connection:
                self.assertEqual(b"fixture", connection.recv(32))

    @unittest.skipUnless(os.environ.get("RUNWAY_ISOLATION_FIXTURES") == "1", "use scripts/test_isolation.py")
    def test_real_build_can_write_its_own_source_while_sibling_data_stays_hidden(self):
        self.options(network="offline")
        self.h.isolation_prepare(self.state, self.pw)
        sibling = self.home / "sibling"
        sibling.mkdir()
        command = ["/usr/bin/python3", "-c", "import pathlib; assert not pathlib.Path(%r).exists(); pathlib.Path(%r).write_text('built')"
                   % (str(sibling), str(self.app / "output"))]
        args, fds = self.h.isolation_bwrap_args(self.h.isolation_plan(self.state, self.pw, command, build=True), os.getuid(), os.getgid())
        try:
            result = subprocess.run(args, pass_fds=fds, env={"PATH": "/usr/bin:/bin"},
                                    capture_output=True, text=True, timeout=15)
        finally:
            for fd in fds:
                os.close(fd)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("built", (self.app / "output").read_text())


if __name__ == "__main__":
    unittest.main()
