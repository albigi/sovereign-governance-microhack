import contextlib
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import extract as gspp
from extract import extract


def requirement(identifier, modal="SOLLTE", children=None):
    result = {
        "id": identifier,
        "title": "Title",
        "props": [{"name": "sec_level", "value": "normal-SdT"}],
        "params": [{"id": "p1", "values": ["example"]}],
        "parts": [{
            "name": "statement",
            "prose": "x" * 301,
            "props": [{"name": "modal_verb", "value": modal}],
        }],
    }
    if children is not None:
        result["controls"] = children
    return result


def catalogue(controls):
    return {"groups": [{"id": "A", "groups": [{"id": "A.1", "controls": controls}]}]}


def document(controls=None, **metadata):
    metadata = {"oscal-version": "1.1.3", "last-modified": "2026-10-29T08:03:17Z", **metadata}
    return json.dumps({"catalog": {"metadata": metadata, **catalogue(controls or [requirement("A.1")])}}).encode()


DATA = document()
REVISION = "a" * 40
PIN = {
    "repository": "https://github.com/example-org/example-catalogue",
    "path": "layer/Example++/catalog.json",
    "revision": REVISION,
    "sha256": hashlib.sha256(DATA).hexdigest(),
    "oscal_version": "1.1.3",
    "last_modified": "2026-10-29",
}
URL = f"https://raw.githubusercontent.com/example-org/example-catalogue/{REVISION}/layer/Example%2B%2B/catalog.json"


class Opener:
    def __init__(self, data):
        self.data = data
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        return io.BytesIO(self.data)


class ExtractTests(unittest.TestCase):
    def test_nested_controls_keep_relationships_and_parameters(self):
        rows = list(extract(catalogue([requirement("A.1", children=[requirement("A.1.1", "KANN")])]), PIN))
        self.assertEqual([row["id"] for row in rows], ["A.1", "A.1.1"])
        self.assertEqual(rows[0]["source_commit"], REVISION)
        self.assertEqual(rows[0]["source_sha256"], PIN["sha256"])
        self.assertEqual(rows[1]["parent_control"], "A.1")
        self.assertEqual(rows[1]["group"], "A / A.1")
        self.assertEqual(rows[1]["modal_verb"], "KANN")
        self.assertEqual(len(rows[0]["statement_300"]), 300)
        self.assertIn('"values":["example"]', rows[0]["parameters"])
        self.assertEqual(rows[0]["target_object_categories"], "")

    def test_duplicate_ids_and_missing_modal_fail(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            list(extract(catalogue([requirement("A.1"), requirement("A.1")]), PIN))
        with self.assertRaisesRegex(ValueError, "modal"):
            list(extract(catalogue([requirement("A.1", "")]), PIN))


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.output = self.directory / "out" / "extract.csv"

    def write_config(self, name="catalogue-mapping.json", **changes):
        pin = {key: value for key, value in {**PIN, **changes}.items() if value is not None}
        path = self.directory / name
        path.write_text(json.dumps({"catalogue": pin, "requirements": []}), encoding="utf-8")
        return path

    def run_tool(self, *args, opener=None):
        opener = opener or Opener(DATA)
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            gspp.main([str(arg) for arg in args], opener)
        return stdout.getvalue(), opener

    def test_url_is_built_from_the_configured_repository_revision_and_path(self):
        self.assertEqual(gspp.catalogue_url(PIN), URL)

    def test_download_and_extract_follow_the_configuration(self):
        config = self.write_config()
        stdout, opener = self.run_tool("--config", config, "--output", self.output)
        self.assertEqual(opener.urls, [URL])
        with self.output.open(encoding="utf-8", newline="") as source:
            rows = list(csv.DictReader(source))
        self.assertEqual([(row["source_commit"], row["source_sha256"]) for row in rows], [(REVISION, PIN["sha256"])])
        self.assertIn(str(config), stdout)

    def test_different_revision_in_the_configuration_changes_the_download(self):
        other = "b" * 40
        _, opener = self.run_tool("--config", self.write_config(revision=other), "--output", self.output)
        self.assertEqual(opener.urls, [URL.replace(REVISION, other)])

    def test_digest_mismatch_is_rejected_and_writes_nothing(self):
        config = self.write_config()
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.run_tool("--config", config, "--output", self.output, opener=Opener(document([requirement("B.1")])))
        self.assertFalse(self.output.exists())

    def test_local_input_is_still_digest_checked(self):
        mirror = self.directory / "mirror.json"
        mirror.write_bytes(document([requirement("B.1")]))
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.run_tool("--config", self.write_config(), "--input", mirror, "--output", self.output)
        mirror.write_bytes(DATA)
        self.run_tool("--config", self.write_config(), "--input", mirror, "--output", self.output)
        self.assertTrue(self.output.exists())

    def test_description_that_contradicts_the_catalogue_is_rejected(self):
        for field, value in (("oscal_version", "1.0.4"), ("last_modified", "2026-01-01")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    self.run_tool("--config", self.write_config(**{field: value}), "--output", self.output)
        self.assertFalse(self.output.exists())

    def test_bad_configuration_is_rejected(self):
        cases = {
            "missing revision": ({"revision": None}, "revision is missing"),
            "branch instead of commit": ({"revision": "main"}, "40-character"),
            "short commit": ({"revision": "c3f3785"}, "40-character"),
            "uppercase commit": ({"revision": "A" * 40}, "40-character"),
            "short digest": ({"sha256": "ab" * 16}, "sha256 must be 64"),
            "missing digest": ({"sha256": None}, "sha256 is missing"),
            "plain http": ({"repository": "http://github.com/example-org/example-catalogue"}, "https://github.com/<owner>"),
            "other host": ({"repository": "https://example.com/example-org/example-catalogue"}, "https://github.com/<owner>"),
            "no repository name": ({"repository": "https://github.com/example-org"}, "https://github.com/<owner>"),
            "empty path": ({"path": ""}, "path is missing"),
            "path outside the repository": ({"path": "../catalog.json"}, "relative path"),
            "absolute path": ({"path": "/catalog.json"}, "relative path"),
            "query in path": ({"path": "catalog.json?raw=1"}, "relative path"),
        }
        for name, (changes, message) in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, message):
                    gspp.load_catalogue(self.write_config(**changes))

    def test_missing_or_malformed_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "--config"):
            gspp.load_catalogue(self.directory / "absent.json")
        for text in ("[]", '{"requirements": []}'):
            with self.subTest(text=text):
                path = self.directory / "bad.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Invalid catalogue configuration"):
                    gspp.load_catalogue(path)

    def test_a_file_holding_only_the_pin_is_accepted(self):
        path = self.directory / "pin.json"
        path.write_text(json.dumps(PIN), encoding="utf-8")
        self.assertEqual(gspp.load_catalogue(path), PIN)

    def test_pin_option_reports_the_values_to_configure_and_writes_nothing(self):
        other = "b" * 40
        newer = document([requirement("A.1"), requirement("A.2")], **{"last-modified": "2026-12-01T00:00:00Z"})
        stdout, opener = self.run_tool("--config", self.write_config(), "--pin", other, "--output", self.output, opener=Opener(newer))
        self.assertEqual(opener.urls, [URL.replace(REVISION, other)])
        reported = json.loads(stdout[stdout.index("{"):])
        self.assertEqual(reported, {"revision": other, "sha256": hashlib.sha256(newer).hexdigest(),
                                    "oscal_version": "1.1.3", "last_modified": "2026-12-01"})
        self.assertIn("2 controls", stdout)
        self.assertIn("different from", stdout)
        self.assertFalse(self.output.exists())

    def test_pin_option_rejects_branches_and_local_input(self):
        config = self.write_config()
        with self.assertRaisesRegex(ValueError, "40-character"):
            self.run_tool("--config", config, "--pin", "main")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_tool("--config", config, "--pin", "b" * 40, "--input", self.directory / "x.json")

    def test_old_constants_still_import_and_come_from_the_committed_configuration(self):
        pin = gspp.load_catalogue()
        self.assertEqual((gspp.REVISION, gspp.SHA256, gspp.SOURCE), (pin["revision"], pin["sha256"], gspp.catalogue_url(pin)))
        with self.assertRaises(AttributeError):
            gspp.UNKNOWN

    def test_committed_pin_is_valid(self):
        self.assertEqual(gspp.pin_problems(gspp.load_catalogue()), [])

    def test_standalone_copy_finds_a_catalogue_mapping_next_to_it(self):
        tools = self.directory / "lab" / "tools"
        tools.mkdir(parents=True)
        script = tools / "gspp_extract.py"
        shutil.copy(Path(gspp.__file__), script)
        mirror = self.directory / "catalogue.json"
        mirror.write_bytes(DATA)
        command = [sys.executable, str(script), "--input", str(mirror), "--output", str(self.directory / "copy.csv")]
        lonely = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(lonely.returncode, 0)
        self.assertIn("--config", lonely.stderr)
        shutil.copy(self.write_config(), tools / "catalogue-mapping.json")
        together = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(together.returncode, 0, together.stderr)
        with (self.directory / "copy.csv").open(encoding="utf-8", newline="") as source:
            self.assertEqual({row["source_commit"] for row in csv.DictReader(source)}, {REVISION})


if __name__ == "__main__":
    unittest.main()
