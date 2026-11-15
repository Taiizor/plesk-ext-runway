# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Code scanning findings must point to the committed helper with their original line numbers."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.helper_sarif import ANALYSIS_PATH, COMMITTED_PATH, main, remap_locations


class HelperSarifTests(unittest.TestCase):
    def test_nested_relative_and_absolute_locations_preserve_line_numbers_and_fingerprints(self):
        region = {"startLine": 137, "startColumn": 9}
        report = {"runs": [{
            "artifacts": [{"location": {"uri": ANALYSIS_PATH}}],
            "results": [{
                "partialFingerprints": {"primaryLocationLineHash": "unchanged"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "./" + ANALYSIS_PATH}, "region": region}}],
                "codeFlows": [{"threadFlows": [{"locations": [{"location": {"physicalLocation": {
                    "artifactLocation": {"uri": "file:///repo/" + ANALYSIS_PATH}, "region": region},
                }}]}]}],
            }],
        }]}
        self.assertEqual(3, remap_locations(report))
        run = report["runs"][0]
        self.assertEqual(COMMITTED_PATH, run["artifacts"][0]["location"]["uri"])
        result = run["results"][0]
        location = result["locations"][0]["physicalLocation"]
        self.assertEqual("./" + COMMITTED_PATH, location["artifactLocation"]["uri"])
        self.assertEqual(region, location["region"])
        flow = result["codeFlows"][0]["threadFlows"][0]["locations"][0]["location"]["physicalLocation"]
        self.assertEqual("file:///repo/" + COMMITTED_PATH, flow["artifactLocation"]["uri"])
        self.assertEqual("unchanged", result["partialFingerprints"]["primaryLocationLineHash"])

    def test_unrelated_artifacts_and_non_uri_fields_stay_unchanged(self):
        report = {"uri": "other-" + ANALYSIS_PATH, "nested": [{"uri": "scripts/build_helper.py"}], "message": ANALYSIS_PATH}
        original = copy.deepcopy(report)
        self.assertEqual(0, remap_locations(report))
        self.assertEqual(original, report)

    def test_cli_rewrites_report_files_and_accepts_reports_without_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "python.sarif"
            report.write_text(json.dumps({"runs": [{"artifacts": [{"location": {"uri": ANALYSIS_PATH}}]}]}), encoding="utf-8")
            empty = root / "empty.sarif"
            empty.write_text('{"runs":[]}\n', encoding="utf-8")
            self.assertEqual(0, main([directory]))
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(COMMITTED_PATH, result["runs"][0]["artifacts"][0]["location"]["uri"])
            self.assertEqual('{"runs":[]}\n', empty.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
