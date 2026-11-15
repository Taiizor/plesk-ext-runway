# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Linux helper contracts without Plesk, systemd, downloads or changes to server state."""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HELPER = Path(__file__).resolve().parent.parent / "src" / "sbin" / "runway-helper"
RUNTIMES = ("go", "rust", "bun", "java", "dotnet", "python", "ruby", "php", "binary")


@unittest.skipUnless(sys.platform.startswith("linux"), "the deployed helper requires Linux stdlib modules")
class HelperContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("runway_contract", str(HELPER))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.helper = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.helper)

    def state(self, listen="tcp", **changes):
        pw = SimpleNamespace(pw_name="runwaytest", pw_uid=10001, pw_gid=10001, pw_dir="/srv/runwaytest")
        payload = {"domain_id": 17, "domain": "sample.test", "sysuser": pw.pw_name, "runtime": "binary",
                   "app_root": "apps/sample", "start_cmd": "./app", "build_cmd": "echo build", "enabled": True,
                   "listen": listen, "port": 25001, "env": {"APP_TOKEN": "secret with spaces"}}
        payload.update(changes)
        with mock.patch.object(self.helper, "v_sysuser", return_value=pw):
            return self.helper.validate_app(payload)

    def test_runtime_registry_and_public_metadata_are_complete(self):
        self.assertEqual(RUNTIMES, self.helper.RUNTIME_KEYS)
        metadata = self.helper.cmd_runtimes({})["runtimes"]
        self.assertEqual(list(RUNTIMES), [item["key"] for item in metadata])
        for item in metadata:
            self.assertTrue({"key", "version_re", "toolchain", "default_listen", "unix_toolchain_re"} <= item.keys())

    def test_project_aware_defaults_resolve_across_source_sections(self):
        fixtures = [
            ("go", {}, "./bin/app"),
            ("rust", {"rust": {"package": "demo"}}, "./target/release/demo"),
            ("bun", {"bun": {"package": True, "lockfile": "bun.lock", "start_script": True}}, "bun run start"),
            ("java", {"java": {"main_java": "App.java", "main_class": "App"}}, "java -XX:MaxRAMPercentage=75 -cp build App"),
            ("dotnet", {"dotnet": {"project": "App.csproj", "assembly_name": "App"}}, "dotnet publish/App.dll"),
            ("python", {"python": {"script": "app.py"}}, ".venv/bin/python app.py"),
            ("binary", {"binary": {"executables": ["server"]}}, "./server"),
        ]
        for runtime, project, expected in fixtures:
            with self.subTest(runtime=runtime):
                self.assertEqual(expected, self.helper.runtime_defaults(runtime, project)["start_cmd"])
        bun = self.helper.runtime_defaults("bun", fixtures[2][1])
        self.assertEqual("bun install --frozen-lockfile", bun["build_cmd"])
        php = self.helper.runtime_defaults("php", {}, "unix", "plesk-8.4")
        self.assertFalse(php["unix_supported"])
        frankenphp = self.helper.runtime_defaults("php", {}, "unix", "frankenphp-1.13.5")
        self.assertIn("$RUNWAY_SOCKET", frankenphp["start_cmd"])

    def test_sample_templates_are_available_to_every_runtime(self):
        for key, runtime in self.helper.RUNTIMES.items():
            for listen in ("tcp", "unix"):
                with self.subTest(runtime=key, listen=listen):
                    samples = runtime.sample(listen, "10.0.100" if key == "dotnet" else "")
                    self.assertTrue(samples)
                    for name, (content, mode) in samples.items():
                        self.assertFalse(name.startswith("/"))
                        self.assertNotIn("..", name.split("/"))
                        self.assertTrue(content)
                        self.assertEqual(0, mode & 0o022)
        compile(self.helper.SAMPLE_PYTHON, "sample.py", "exec")

    def test_services_and_environment_keep_privilege_and_secret_boundaries(self):
        for listen in ("tcp", "unix", "none"):
            with self.subTest(listen=listen):
                state, pw = self.state(listen, limits={"memory_mb": 512, "cpu_percent": 50, "tasks": 256})
                with mock.patch.object(self.helper.grp, "getgrgid", return_value=SimpleNamespace(gr_name="psacln")), \
                        mock.patch.object(self.helper, "cached_systemd_version", return_value=255):
                    unit = self.helper.render_app_unit(state, pw)
                self.assertIn("User=runwaytest\n", unit)
                self.assertIn("NoNewPrivileges=yes\n", unit)
                self.assertIn("MemoryMax=512M\n", unit)
                self.assertIn("MemoryPressureWatch=off\n", unit)
                self.assertIn("ExecStart=/bin/bash -c ${RUNWAY_START_CMD}\n", unit)
                self.assertNotIn("secret with spaces", unit)
                self.assertNotIn("ExecStartPre=+", unit)
                env = self.helper.render_env_file(state, pw)
                self.assertIn("APP_TOKEN=", env)
                self.assertIn("secret with spaces", env)

    def test_workers_have_no_health_or_zero_downtime_and_slots_keep_distinct_endpoints(self):
        state, _ = self.state("none", health_path="/health", health_match="ok", health_watch=True, zero_downtime=True)
        self.assertEqual("worker", state["mode"])
        self.assertEqual("", state["health_path"])
        self.assertEqual("", state["health_match"])
        self.assertFalse(state["health_watch"])
        self.assertFalse(state["zero_downtime"])
        state, _ = self.state("tcp", zero_downtime=True)
        state.update(slot="a", port_a=25001, port_b=25002)
        self.assertEqual("b", self.helper.zd_target(state))
        self.assertEqual(25002, self.helper.slot_view(state, "b")["port"])
        self.assertNotEqual(self.helper.slot_view(state, "a")["_socket"], self.helper.slot_view(state, "b")["_socket"])

    def test_input_validation_still_rejects_traversal_injection_and_reserved_variables(self):
        for value in ("../outside", "apps/../../outside", "apps/./example"):
            with self.subTest(path=value), self.assertRaises(self.helper.HelperError):
                self.helper.v_app_root(value, "/srv/customer")
        for name in ("PORT", "HOST", "LD_PRELOAD", "GCONV_PATH"):
            with self.subTest(name=name), self.assertRaises(self.helper.HelperError):
                self.helper.v_env({name: "untrusted"})
        with self.assertRaises(self.helper.HelperError):
            self.helper.v_command("./app\nExecStartPre=+/bin/true", "start command", False, False)
        with self.assertRaises(self.helper.HelperError):
            self.helper.v_health_match("{bad json", "/health")

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "CLI protocol requires root")
    def test_copied_artifact_runs_in_isolation_without_the_source_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "runway-helper"
            copied.write_bytes(HELPER.read_bytes())
            for command, payload, exit_code in (("runtimes", "{}", 0), ("unknown-command", "{}", 1), ("runtimes", "[", 1)):
                with self.subTest(command=command, payload=payload):
                    result = subprocess.run([sys.executable, "-I", str(copied), command], input=payload,
                                            capture_output=True, text=True, cwd=directory, timeout=10)
                    self.assertEqual(exit_code, result.returncode, result.stderr)
                    self.assertEqual("", result.stderr)
                    response = json.loads(result.stdout)
                    self.assertEqual(exit_code == 0, response["ok"])
                    if command == "runtimes" and exit_code == 0:
                        self.assertEqual(list(RUNTIMES), [item["key"] for item in response["runtimes"]])


if __name__ == "__main__":
    unittest.main()
