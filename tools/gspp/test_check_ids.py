import csv
import tempfile
import unittest
from pathlib import Path

from check_ids import check_document, load_extract, scan_text
from extract import FIELDS

PIN = {"repository": "https://github.com/example-org/example-catalogue", "path": "catalog.json",
       "revision": "a" * 40, "sha256": "b" * 64}


def row(identifier, modal="SOLLTE", level="normal-SdT", title="Short", statement=""):
    values = {field: "" for field in FIELDS}
    values.update(id=identifier, modal_verb=modal, security_level=level, title=title,
                  statement_300=statement, source_commit=PIN["revision"], source_sha256=PIN["sha256"])
    return values


ROWS = {
    "AB.1.1": row("AB.1.1"),
    "AB.1.2": row("AB.1.2", modal="MUSS", level="erhöht", title="A long enough catalogue title"),
}


class CheckDocumentTests(unittest.TestCase):
    def test_unknown_id_and_wrong_verb_or_level_fail(self):
        document = {"requirements": [
            {"id": "AB.1.1", "modal_verb": "SOLLTE", "security_level": "normal"},
            {"id": "AB.1.2", "modal_verb": "SOLLTE", "security_level": "normal"},
            {"id": "AB.9.9"},
        ]}
        count, errors = check_document(document, ROWS)
        self.assertEqual(count, 3)
        self.assertEqual(len(errors), 3)
        self.assertIn("modal verb is MUSS", errors[0])
        self.assertIn("security level is elevated", errors[1])
        self.assertIn("AB.9.9 is not in the pinned catalogue", errors[2])

    def test_oscal_control_ids_are_checked_and_other_ids_ignored(self):
        document = {"components": [{"uuid": "x", "implemented-requirements": [{"control-id": "AB.1.2"}]}], "id": "corp"}
        self.assertEqual(check_document(document, ROWS), (1, []))


class ExtractAndScanTests(unittest.TestCase):
    def write_extract(self, directory, **changes):
        path = Path(directory) / "extract.csv"
        with path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow({**row("AB.1.1"), **changes})
        return path

    def test_extract_built_from_the_configured_pin_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(list(load_extract(self.write_extract(directory), PIN)), ["AB.1.1"])

    def test_extract_from_another_catalogue_or_revision_is_refused(self):
        for name, changes in (("digest", {"source_sha256": "0" * 64}), ("commit", {"source_commit": "c" * 40})):
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, "not built from the pinned catalogue.*extract.py again"):
                    load_extract(self.write_extract(directory, **changes), PIN)

    def test_copied_title_is_found_outside_output_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "out").mkdir()
            (root / "challenge.md").write_text("Step 2: A long  enough\nCatalogue title.", encoding="utf-8")
            (root / "out" / "extract.md").write_text("A long enough catalogue title", encoding="utf-8")
            count, findings = scan_text(root, ROWS)
        self.assertEqual(count, 1)
        self.assertEqual(findings, ["challenge.md: contains the catalogue title of AB.1.2"])


if __name__ == "__main__":
    unittest.main()
