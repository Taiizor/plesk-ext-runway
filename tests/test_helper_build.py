# Copyright 2026 Taiizor. Licensed under the MIT License.
"""Source assembly checks; these run on Windows as well as on Linux, without importing the helper."""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import build as package_build
from scripts.build_helper import SOURCE_DIR, TARGET, SourceError, assemble_helper, build_helper, check_helper, read_sources


class HelperBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "helper"
        self.source.mkdir()
        self.target = Path(self.temp.name) / "output" / "runway-helper"
        self.write("bootstrap.py", '#!/usr/bin/python3 -I\n# -*- coding: utf-8 -*-\nVERSION = "1.2.0"\n')
        self.write("section.py", 'def value():\n    return VERSION\n')
        self.manifest(["bootstrap.py", "section.py"])

    def write(self, name, text):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def manifest(self, value):
        self.write("manifest.json", json.dumps(value))

    def test_committed_artifact_matches_all_source_sections(self):
        self.assertEqual([], check_helper())
        sources = read_sources()
        tree = ast.parse(assemble_helper().decode("utf-8"), feature_version=(3, 8))
        self.assertTrue(sources)
        self.assertIsInstance(tree.body[-1], ast.If)
        self.assertEqual("bootstrap.py", sources[0][0])
        self.assertEqual("entrypoint.py", sources[-1][0])

    def test_deterministic_output_preserves_the_isolated_shebang_and_runtime_code(self):
        data = assemble_helper(self.source)
        self.assertEqual(data, assemble_helper(self.source))
        self.assertTrue(data.startswith(b"#!/usr/bin/python3 -I\n# -*- coding: utf-8 -*-\n"))
        self.assertIn(b"# Source: helper/section.py\n", data)
        self.assertNotIn(str(self.source).encode(), data)
        namespace = {}
        exec(compile(data, str(self.target), "exec"), namespace)
        self.assertEqual("1.2.0", namespace["value"]())

    def test_regeneration_does_not_rewrite_an_unchanged_artifact(self):
        self.assertTrue(build_helper(self.target, self.source))
        stamp = self.target.stat().st_mtime_ns
        self.assertFalse(build_helper(self.target, self.source))
        self.assertEqual(stamp, self.target.stat().st_mtime_ns)
        self.write("section.py", 'def value():\n    return "updated"\n')
        self.assertTrue(build_helper(self.target, self.source))
        self.assertIn(b'return "updated"', self.target.read_bytes())

    def test_check_fails_on_missing_or_stale_output_without_writing_it(self):
        self.assertTrue(check_helper(self.target, self.source))
        self.assertFalse(self.target.exists())
        build_helper(self.target, self.source)
        original = self.target.read_bytes()
        self.write("section.py", 'def value():\n    return "new"\n')
        self.assertTrue(check_helper(self.target, self.source))
        self.assertEqual(original, self.target.read_bytes())

    def test_crlf_sources_and_checkout_do_not_produce_spurious_changes(self):
        expected = assemble_helper(self.source)
        self.write("section.py", 'def value():\r\n    return VERSION\r\n')
        self.assertEqual(expected, assemble_helper(self.source))
        self.target.parent.mkdir()
        self.target.write_bytes(expected.replace(b"\n", b"\r\n"))
        self.assertEqual([], check_helper(self.target, self.source))
        self.assertTrue(build_helper(self.target, self.source))
        self.assertNotIn(b"\r\n", self.target.read_bytes())

    def test_manifest_rejects_invalid_shapes_and_paths(self):
        for value in ({}, [], None, [12], ["../outside.py"], ["/absolute.py"], ["runtimes\\go.py"]):
            with self.subTest(value=value):
                self.manifest(value)
                with self.assertRaises(SourceError):
                    assemble_helper(self.source)

    def test_manifest_rejects_invalid_json_duplicate_paths_and_missing_files(self):
        self.write("manifest.json", "[")
        with self.assertRaisesRegex(SourceError, "manifest.json"):
            assemble_helper(self.source)
        self.manifest(["bootstrap.py", "section.py", "section.py"])
        with self.assertRaisesRegex(SourceError, "duplicate helper source"):
            assemble_helper(self.source)
        self.manifest(["bootstrap.py", "missing.py"])
        with self.assertRaisesRegex(SourceError, "missing.py"):
            assemble_helper(self.source)

    def test_unlisted_python_sources_cannot_be_silently_omitted(self):
        self.write("runtimes/new.py", "NEW_RUNTIME = True\n")
        with self.assertRaisesRegex(SourceError, "missing from.*manifest"):
            assemble_helper(self.source)

    @unittest.skipIf(os.name == "nt", "symlink creation on Windows requires additional privileges")
    def test_source_symlinks_cannot_leave_the_source_directory(self):
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("OUTSIDE = True\n", encoding="utf-8")
        (self.source / "section.py").unlink()
        (self.source / "section.py").symlink_to(outside)
        with self.assertRaisesRegex(SourceError, "leaves its source directory"):
            assemble_helper(self.source)

    def test_invalid_encoding_and_syntax_report_the_source_filename(self):
        (self.source / "section.py").write_bytes(b"\xff")
        with self.assertRaisesRegex(SourceError, "section.py"):
            assemble_helper(self.source)
        self.write("section.py", "def broken(\n")
        with self.assertRaisesRegex(SourceError, "section.py:1"):
            assemble_helper(self.source)
        self.write("section.py", "match value:\n    case 1:\n        pass\n")
        with self.assertRaisesRegex(SourceError, "section.py"):
            assemble_helper(self.source)

    def test_duplicate_definitions_and_nonisolated_headers_are_rejected(self):
        self.write("section.py", "def same():\n    pass\ndef same():\n    pass\n")
        with self.assertRaisesRegex(SourceError, "duplicate top-level.*same"):
            assemble_helper(self.source)
        self.write("bootstrap.py", "#!/usr/bin/python3\nVERSION = 'changed'\n")
        with self.assertRaisesRegex(SourceError, "isolated Python shebang"):
            assemble_helper(self.source)

    def test_packaging_scans_original_helper_sources_for_leftover_markers(self):
        self.write("section.py", '# ' + 'TO' + 'DO' + ': finish this\n')
        with mock.patch.object(package_build, "HELPER_SOURCES", self.source):
            found = package_build.find_placeholders()
        self.assertTrue(any(item.startswith("helper/section.py:1:") for item in found))

    def test_manifest_source_order_matches_the_generated_statement_order(self):
        before = ast.parse("\n".join(text for _, text in read_sources(SOURCE_DIR)))
        after = ast.parse(TARGET.read_text(encoding="utf-8"))
        self.assertEqual(ast.dump(before, include_attributes=False), ast.dump(after, include_attributes=False))


class HelperPackagingTests(unittest.TestCase):
    """Exercise the real packaging CLI in an isolated tree with a tiny frontend fixture."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project with spaces"
        self.project.mkdir()
        root = SOURCE_DIR.parent
        for name in ("build.py", "package.json", "CHANGELOG.md"):
            shutil.copyfile(root / name, self.project / name)
        (self.project / "scripts").mkdir()
        shutil.copyfile(root / "scripts" / "build_helper.py", self.project / "scripts" / "build_helper.py")
        shutil.copytree(SOURCE_DIR, self.project / "helper", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(root / "src", self.project / "src",
                        ignore=shutil.ignore_patterns("frontend", "dist", "__pycache__", "*.pyc"))
        bundle = self.project / "src" / "htdocs" / "dist" / "main.js"
        bundle.parent.mkdir(parents=True, exist_ok=True)
        bundle.write_text("console.log('packaging fixture');\n", encoding="utf-8")
        (bundle.parent.parent / "index.php").write_text("<?php\n$bundle = '/dist/main.js';\n", encoding="utf-8")

    def run_build(self, *args):
        return subprocess.run([sys.executable, "-B", "build.py"] + list(args), cwd=str(self.project),
                              capture_output=True, text=True, timeout=60)

    def test_package_regenerates_stale_helper_and_contains_only_the_standalone_artifact(self):
        target = self.project / "src" / "sbin" / "runway-helper"
        target.write_bytes(target.read_bytes() + b"\n# Stale generated content\n")
        result = self.run_build("--no-frontend", "--strict")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        expected = assemble_helper(self.project / "helper")
        self.assertEqual(expected, target.read_bytes())
        packages = list((self.project / "dist").glob("*.zip"))
        self.assertEqual(1, len(packages))
        with zipfile.ZipFile(packages[0]) as package:
            self.assertEqual(expected, package.read("sbin/runway-helper"))
            self.assertEqual(0o100755, package.getinfo("sbin/runway-helper").external_attr >> 16)
            self.assertFalse(any(name.startswith("helper/") or name.endswith("manifest.json") for name in package.namelist()))
        verified = self.run_build("--verify", str(packages[0]))
        self.assertEqual(0, verified.returncode, verified.stdout + verified.stderr)

    def test_source_check_does_not_rewrite_stale_output_and_reports_markers_in_source_files(self):
        target = self.project / "src" / "sbin" / "runway-helper"
        content = target.read_bytes() + b"\n# Stale generated content\n"
        target.write_bytes(content)
        result = self.run_build("--check")
        self.assertEqual(1, result.returncode)
        self.assertIn("missing or stale", result.stderr)
        self.assertEqual(content, target.read_bytes())
        source = self.project / "helper" / "runtimes" / "go.py"
        source.write_bytes(source.read_bytes() + b"\n# " + b"TO" + b"DO" + b": incomplete\n")
        build_helper(target, self.project / "helper")
        result = self.run_build("--check")
        self.assertEqual(1, result.returncode)
        self.assertIn("helper/runtimes/go.py:", result.stderr)
        self.assertNotIn("src/sbin/runway-helper:", result.stderr)


if __name__ == "__main__":
    unittest.main()
