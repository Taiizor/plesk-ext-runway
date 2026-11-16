# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Metrics regression tests with real SQLite and disposable Linux helper state."""

import contextlib
import importlib.machinery
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


@unittest.skipUnless(sys.platform.startswith("linux"), "the deployed helper requires Linux")
class MetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "src/sbin/runway-helper"
        loader = importlib.machinery.SourceFileLoader("runway_metrics_test", str(path))
        cls.h = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cls.h)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in {
            "STATE_DIR": str(self.root), "CACHE_DIR": str(self.root / "cache"),
            "LOCK_DIR": str(self.root / "locks"), "APPS_DIR": str(self.root / "apps"),
            "METRICS_DB_PATH": str(self.root / "metrics.sqlite"),
            "_CPU_PREV_FILE": str(self.root / "cache/cpu_prev.json"),
            "UNIT_DIR": str(self.root / "units"),
        }.items():
            self.stack.enter_context(mock.patch.object(self.h, key, value))
        self.now = 1800000000
        self.stack.enter_context(mock.patch.object(self.h.time, "time", side_effect=lambda: self.now))
        self.states = [{"domain_id": 17, "app_dir": "/srv/one"}, {"domain_id": 18, "app_dir": "/srv/two"}]
        self.stack.enter_context(mock.patch.object(self.h, "iter_app_states", side_effect=lambda: iter(self.states)))
        self.infos = {self.h.app_unit(17): self.info(), self.h.app_unit(18): self.info(memory=200)}
        self.show = self.stack.enter_context(mock.patch.object(self.h, "unit_show", side_effect=lambda *_: self.infos))
        self.read_server_counters = self.h.server_disk_counters
        self.disk_counters = {"sda": [1000, 2000]}
        self.stack.enter_context(mock.patch.object(self.h, "server_disk_counters", side_effect=lambda: self.disk_counters))
        self.fast_size = self.h._fast_dir_size
        self.stack.enter_context(mock.patch.object(self.h, "_fast_dir_size", side_effect=lambda path: 1000 if path == "/srv/one" else 2000))
        self.h.ensure_dir(self.h.APPS_DIR, 0o700)
        self.h.ensure_dir(self.h.UNIT_DIR)
        for state in self.states:
            self.h.write_json(self.h.app_state_path(state["domain_id"]), state)

    def info(self, memory=100, cpu=1000000000, net=500, instance="1", read=0, write=0):
        return {"ActiveState": "active", "MemoryCurrent": str(memory), "CPUUsageNSec": str(cpu),
                "IPIngressBytes": str(net), "IPEgressBytes": "0", "NRestarts": "0",
                "MainPID": instance, "ActiveEnterTimestampMonotonic": instance, "ControlGroup": "",
                "IOReadBytes": str(read), "IOWriteBytes": str(write)}

    def rows(self, table):
        db = self.h._open_metrics_db()
        try:
            return db.execute("SELECT * FROM " + table + " ORDER BY timestamp").fetchall()
        finally:
            db.close()

    def test_background_tick_records_all_apps_and_server_without_panel_requests(self):
        self.h.internal_metrics()
        self.now += 60
        self.h.internal_metrics()
        self.assertEqual(4, len(self.rows("app_metrics")))
        self.assertEqual(2, len(self.rows("server_metrics")))
        self.assertEqual(2, self.show.call_count)  # One batched systemctl read per tick.

    def test_first_sample_is_not_copied_into_fake_history(self):
        app = self.h.cmd_app_metrics({"domain_id": 17, "range": "7d"})
        server = self.h.cmd_server_metrics({"range": "7d"})
        for response in (app, server):
            self.assertEqual(1, len(response["metrics"]))
            self.assertEqual(self.now, response["metrics"][0]["time"])
            self.assertEqual(self.now - 7 * 86400, response["start_time"])
            self.assertEqual(self.now, response["end_time"])

    def test_project_summary_refreshes_unvisited_apps_and_excludes_removed_apps(self):
        db = self.h._open_metrics_db()
        with db:
            db.execute("""INSERT INTO app_metrics
                          (domain_id, timestamp, cpu_percent, memory_bytes, memory_used_bytes, disk_bytes, net_bytes, net_rate, restarts)
                          VALUES (99, ?, 99, 9999, 9999, 9999, 0, 999, 0)""", (self.now,))
        db.close()
        summary = self.h.cmd_server_metrics({})["project_summary"]
        self.assertEqual(300, summary["memory_used_bytes"])
        self.assertEqual(3000, summary["disk_bytes"])
        self.assertEqual(0, summary["net_rate"])
        self.assertEqual({17, 18, 99}, {row[0] for row in self.rows("app_metrics")})

    def test_cpu_and_network_deltas_survive_duplicate_requests_and_reset_on_restart(self):
        first = self.h.record_app_metric_sample(17)
        self.now += 1
        self.assertEqual(first, self.h.record_app_metric_sample(17))
        self.assertEqual(1, self.show.call_count)
        self.now += 59
        self.infos[self.h.app_unit(17)] = self.info(cpu=4000000000, net=1700)
        sample = self.h.record_app_metric_sample(17)
        self.assertEqual(5.0, sample["cpu_percent"])
        self.assertEqual(20.0, sample["net_rate"])
        self.now += 60
        self.infos[self.h.app_unit(17)] = self.info(cpu=9000000000, net=5000, instance="2")
        restarted = self.h.record_app_metric_sample(17)
        self.assertEqual(0, restarted["cpu_percent"])
        self.assertEqual(0, restarted["net_rate"])

    def test_server_rates_use_counter_deltas_and_repeated_reads_keep_the_measurement(self):
        proc = {
            "/proc/stat": "cpu 100 0 100 800 0 0 0\n",
            "/proc/meminfo": "MemTotal: 2048 kB\nMemAvailable: 1024 kB\n",
            "/proc/net/dev": "eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n",
        }
        original_open = open

        def read_proc(path, *args, **kwargs):
            return io.StringIO(proc[path]) if path in proc else original_open(path, *args, **kwargs)

        with mock.patch.object(self.h, "open", side_effect=read_proc, create=True):
            self.h.record_server_metric_sample()
            self.now += 60
            proc["/proc/stat"] = "cpu 200 0 200 1600 0 0 0\n"
            proc["/proc/net/dev"] = "eth0: 7000 0 0 0 0 0 0 0 14000 0 0 0 0 0 0 0\n"
            sample = self.h.record_server_metric_sample()
            self.assertEqual(20.0, sample["cpu_percent"])
            self.assertEqual(1024 * 1024, sample["memory_used_bytes"])
            self.assertEqual(100.0, sample["net_rx_rate"])
            self.assertEqual(200.0, sample["net_tx_rate"])
            self.assertEqual(sample, self.h.record_server_metric_sample())
            self.assertEqual(2, len(self.rows("server_metrics")))

    def test_application_disk_rates_are_bytes_per_second_and_history_preserves_unknown_warmup(self):
        first = self.h.record_app_metric_sample(17)
        self.assertIsNone(first["disk_read_rate"])
        self.now += 60
        self.infos[self.h.app_unit(17)] = self.info(read=6000, write=12000)
        sample = self.h.record_app_metric_sample(17)
        self.assertEqual(100, sample["disk_read_rate"])
        self.assertEqual(200, sample["disk_write_rate"])
        self.assertEqual(sample, self.h.record_app_metric_sample(17))
        self.now += 60
        self.infos[self.h.app_unit(17)] = self.info(read=18000, write=36000)
        response = self.h.cmd_app_metrics({"domain_id": 17, "range": "7d"})
        self.assertEqual(200, response["latest"]["disk_read_rate"])
        self.assertEqual(150, response["metrics"][0]["disk_read_rate"])
        self.assertEqual(300, response["metrics"][0]["disk_write_rate"])
        self.assertEqual(1000, response["metrics"][0]["disk"])

    def test_project_totals_include_io_from_all_apps_and_report_incomplete_measurements(self):
        self.assertIsNone(self.h.cmd_server_metrics({})["project_summary"]["disk_read_rate"])
        self.now += 60
        self.infos[self.h.app_unit(17)] = self.info(read=6000, write=12000)
        self.infos[self.h.app_unit(18)] = self.info(read=12000, write=18000)
        summary = self.h.cmd_server_metrics({})["project_summary"]
        self.assertEqual(300, summary["disk_read_rate"])
        self.assertEqual(500, summary["disk_write_rate"])
        self.assertEqual(3000, summary["disk_bytes"])
        self.now += 60
        self.infos[self.h.app_unit(18)]["IOReadBytes"] = str(2 ** 64 - 1)
        self.assertIsNone(self.h.cmd_server_metrics({})["project_summary"]["disk_read_rate"])

    def test_downsampling_preserves_raw_peaks_separately_from_averages(self):
        self.now += 45
        db = self.h._open_metrics_db()
        with db:
            db.executemany("""INSERT INTO app_metrics
                (domain_id, timestamp, cpu_percent, memory_bytes, memory_used_bytes, disk_bytes,
                 restarts, net_rate, disk_read_rate, disk_write_rate)
                VALUES (17, ?, ?, ?, ?, 1000, 0, ?, ?, ?)""", [
                    (self.now - 20, 0.1, 100, 80, 100, 1000, 0),
                    (self.now - 10, 0.6, 300, 240, 600, 6000, 2000),
                    (self.now, 0.2, 200, 160, 200, 2000, 1000),
                ])
        db.close()
        response = self.h.cmd_app_metrics({"domain_id": 17, "range": "1h"})
        self.assertEqual(1, len(response["metrics"]))
        sample = response["metrics"][0]
        self.assertEqual(0.3, sample["cpu"])
        self.assertEqual(0.6, sample["cpu_peak"])
        self.assertEqual(240, sample["memory_used_peak"])
        self.assertEqual(300, sample["memory_peak"])
        self.assertEqual(600, sample["net_rate_peak"])
        self.assertEqual(3000, sample["disk_read_rate"])
        self.assertEqual(6000, sample["disk_read_rate_peak"])
        self.assertEqual(2000, sample["disk_write_rate_peak"])

    def test_disk_rates_reset_after_service_restart_and_counter_reset(self):
        self.h.record_app_metric_sample(17)
        self.now += 60
        self.infos[self.h.app_unit(17)] = self.info(read=9000, write=12000, instance="2")
        restarted = self.h.record_app_metric_sample(17)
        self.assertIsNone(restarted["disk_read_rate"])
        self.now += 60
        self.infos[self.h.app_unit(17)] = self.info(read=10, write=20, instance="2")
        reset = self.h.record_app_metric_sample(17)
        self.assertIsNone(reset["disk_read_rate"])
        self.assertIsNone(reset["disk_write_rate"])

    def test_server_disk_rates_handle_device_changes_and_counter_resets(self):
        self.assertIsNone(self.h.record_server_metric_sample()["disk_read_rate"])
        self.now += 60
        self.disk_counters = {"sda": [7000, 14000]}
        sample = self.h.record_server_metric_sample()
        self.assertEqual(100, sample["disk_read_rate"])
        self.assertEqual(200, sample["disk_write_rate"])
        self.assertEqual(sample, self.h.record_server_metric_sample())
        self.now += 60
        self.disk_counters["sdb"] = [999999, 999999]
        self.assertIsNone(self.h.record_server_metric_sample()["disk_read_rate"])
        self.now += 60
        self.disk_counters = {"sda": [1, 1], "sdb": [999999, 999999]}
        self.assertIsNone(self.h.record_server_metric_sample()["disk_write_rate"])

    def test_server_counts_leaf_devices_once_and_uses_512_byte_sectors(self):
        def list_devices(path):
            if path == "/sys/block":
                return ["sda", "sdb", "dm-0", "loop0", "ram0"]
            return ["sda", "sdb"] if path == "/sys/block/dm-0/slaves" else []

        with mock.patch.object(self.h.os, "listdir", side_effect=list_devices), \
                mock.patch.object(self.h, "_read_text", return_value="1 0 20 0 1 0 40 0 0 0 0"):
            self.assertEqual({"sda": [10240, 20480], "sdb": [10240, 20480]}, self.read_server_counters())

    def test_legacy_cgroup_io_and_empty_counter_files(self):
        info = {"ControlGroup": "/system.slice/runway-app-17.service"}
        def cgroup_file(path, *_args):
            if path.endswith("/blkio.throttle.io_service_bytes_recursive"):
                return io.StringIO("8:0 Read 1024\n8:0 Write 2048\n8:0 Sync 3072\nTotal 3072\n")
            raise FileNotFoundError(path)

        with mock.patch.object(self.h, "open", side_effect=cgroup_file, create=True):
            self.assertEqual([1024, 2048], self.h.unit_disk_counters(info))
        with mock.patch.object(self.h, "open", return_value=io.StringIO(""), create=True):
            self.assertEqual([0, 0], self.h.unit_disk_counters(info))
        with mock.patch.object(self.h, "open", side_effect=AssertionError("unsafe path"), create=True):
            self.assertEqual([None, None], self.h.unit_disk_counters({"ControlGroup": "/../etc"}))

    def test_upgrade_preserves_history_without_inventing_io_measurements(self):
        db = sqlite3.connect(self.h.METRICS_DB_PATH)
        db.executescript("""
            CREATE TABLE app_metrics (domain_id INTEGER, timestamp INTEGER, cpu_percent REAL,
                memory_bytes INTEGER, memory_used_bytes INTEGER, disk_bytes INTEGER, restarts INTEGER,
                PRIMARY KEY (domain_id, timestamp));
            INSERT INTO app_metrics VALUES (17, 1800000000, 5, 100, 100, 1000, 0);
            CREATE TABLE server_metrics (timestamp INTEGER PRIMARY KEY, cpu_percent REAL,
                memory_used_bytes INTEGER, memory_total_bytes INTEGER, disk_used_bytes INTEGER,
                disk_total_bytes INTEGER);
            INSERT INTO server_metrics VALUES (1800000000, 10, 100, 200, 1000, 2000);
        """)
        db.close()
        db = self.h._open_metrics_db()
        for table in ("app_metrics", "server_metrics"):
            self.assertEqual([(None, None)], db.execute("SELECT disk_read_rate, disk_write_rate FROM " + table).fetchall())
        db.close()
        self.assertEqual(1, len(self.rows("app_metrics")))
        self.assertEqual(1, len(self.rows("server_metrics")))

    def test_stopped_app_keeps_disk_usage_and_unsupported_ip_accounting_is_not_a_huge_counter(self):
        self.infos[self.h.app_unit(17)] = {"ActiveState": "inactive"}
        stopped = self.h.record_app_metric_sample(17)
        self.assertEqual(1000, stopped["disk_bytes"])
        self.assertEqual(0, stopped["memory_used_bytes"])
        self.infos[self.h.app_unit(18)]["IPIngressBytes"] = str(2 ** 64 - 1)
        self.assertEqual(0, self.h.record_app_metric_sample(18)["net_bytes"])

    def test_deployment_slots_are_summed(self):
        state = dict(self.states[0], slot="a", zero_downtime=True)
        self.infos[self.h.app_unit(17, "a")] = self.info(memory=200)
        self.infos[self.h.app_unit(17, "b")] = self.info(memory=300)
        sample = self.h.record_app_metric_sample(17, state)
        self.assertEqual(600, sample["memory_used_bytes"])

    def test_failed_app_does_not_stop_other_samples_or_produce_partial_summary(self):
        del self.infos[self.h.app_unit(17)]
        response = self.h.cmd_server_metrics({})
        self.assertIsNone(response["project_summary"])
        self.assertIn("#17", response["collection_errors"][0])
        self.assertEqual([18], [row[0] for row in self.rows("app_metrics")])
        with self.assertRaisesRegex(self.h.HelperError, "#17"):
            self.h.internal_metrics()

    def test_retention_does_not_depend_on_timestamp_modulo(self):
        self.now -= 15 * 86400
        self.h.collect_metric_samples()
        self.now += 15 * 86400 + 61
        self.h.collect_metric_samples()
        self.assertEqual(2, len(self.rows("app_metrics")))
        self.assertEqual(1, len(self.rows("server_metrics")))

    def test_disk_cache_persists_between_short_lived_helper_invocations(self):
        with mock.patch.object(self.h.subprocess, "run", return_value=SimpleNamespace(stdout=b"4 /tmp/app\n")) as du:
            self.assertEqual(4096, self.fast_size(str(self.root)))
            self.now += 60
            self.assertEqual(4096, self.fast_size(str(self.root)))
            self.assertEqual(1, du.call_count)
            self.now += 61
            self.assertEqual(4096, self.fast_size(str(self.root)))
            self.assertEqual(2, du.call_count)

    def test_timer_is_installed_idempotently_and_removed_with_its_service(self):
        with mock.patch.object(self.h, "systemctl") as systemctl, \
                mock.patch.object(self.h, "unit_enabled", return_value=True), \
                mock.patch.object(self.h, "unit_is_active", return_value=True):
            self.h.sync_metrics_units()
            service = self.root / "units/runway-metrics.service"
            timer = self.root / "units/runway-metrics.timer"
            self.assertIn("ExecStart=%s _metrics\n" % self.h.HELPER_COPY, service.read_text())
            self.assertIn("OnUnitActiveSec=60\n", timer.read_text())
            systemctl.assert_any_call("enable", "--now", self.h.UNIT_METRICS_TIMER, check=True)
            systemctl.reset_mock()
            self.h.sync_metrics_units()
            systemctl.assert_not_called()
            self.h.sync_metrics_units(enabled=False)
            self.assertFalse(service.exists())
            self.assertFalse(timer.exists())
            systemctl.assert_any_call("stop", self.h.UNIT_METRICS)


if __name__ == "__main__":
    unittest.main()
