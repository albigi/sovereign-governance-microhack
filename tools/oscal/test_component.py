import copy
import json
import sys
import unittest
from pathlib import Path

from build_component import MAPPING, OUTPUT, render
from validate import CACHE, SCHEMAS, load_schema, reference_errors, schema_errors

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gspp"))
from extract import catalogue_url, load_catalogue  # noqa: E402

try:
    import jsonschema  # noqa: F401
    import regex  # noqa: F401
    DEPENDENCIES = True
except ImportError:
    DEPENDENCIES = False


def component():
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


class ComponentTests(unittest.TestCase):
    def test_committed_component_is_built_from_the_mapping(self):
        current = OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(current, render(json.loads(MAPPING.read_text(encoding="utf-8"))))

    def test_every_mapped_requirement_is_implemented(self):
        mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
        implemented = {
            item["control-id"]
            for part in component()["component-definition"]["components"]
            for implementation in part["control-implementations"]
            for item in implementation["implemented-requirements"]
        }
        self.assertEqual(implemented, {item["id"] for item in mapping["requirements"]})

    def test_catalogue_source_is_the_configured_pin(self):
        pin = load_catalogue()
        resource = component()["component-definition"]["back-matter"]["resources"][0]
        self.assertEqual(resource["rlinks"][0]["href"], catalogue_url(pin))
        self.assertEqual(resource["rlinks"][0]["hashes"][0]["value"], pin["sha256"])

    def test_changing_the_catalogue_pin_changes_the_component_source(self):
        mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
        mapping["catalogue"].update(revision="b" * 40, sha256="c" * 64)
        link = json.loads(render(mapping))["component-definition"]["back-matter"]["resources"][0]["rlinks"][0]
        self.assertEqual(link["href"], catalogue_url(mapping["catalogue"]))
        self.assertIn("b" * 40, link["href"])
        self.assertEqual(link["hashes"][0]["value"], "c" * 64)

    def test_reference_check_finds_duplicates_and_dangling_links(self):
        document = component()
        self.assertEqual(reference_errors(document)[0], [])
        broken = copy.deepcopy(document)
        definition = broken["component-definition"]
        definition["components"][1]["uuid"] = definition["components"][0]["uuid"]
        definition["components"][0]["control-implementations"][0]["source"] = "#missing"
        definition["metadata"]["roles"].pop()
        messages = " ".join(reference_errors(broken)[0])
        self.assertIn("also used at", messages)
        self.assertIn("source #missing", messages)
        self.assertIn("is not defined in metadata.roles", messages)


@unittest.skipUnless(DEPENDENCIES, "needs python -m pip install -r tools/oscal/requirements.txt")
class NistSchemaTests(unittest.TestCase):
    def test_component_is_valid_against_cached_nist_schemas(self):
        versions = [version for version in sorted(SCHEMAS) if (CACHE / f"oscal_component_schema-{version}.json").exists()]
        if not versions:
            self.skipTest("run python tools/oscal/validate.py once to cache the NIST schemas")
        for version in versions:
            with self.subTest(oscal=version):
                self.assertEqual(schema_errors(component(), load_schema(version)), [])

    def test_nist_schema_rejects_a_broken_component(self):
        version = next((v for v in sorted(SCHEMAS) if (CACHE / f"oscal_component_schema-{v}.json").exists()), None)
        if version is None:
            self.skipTest("run python tools/oscal/validate.py once to cache the NIST schemas")
        broken = component()
        broken["component-definition"]["components"][0]["uuid"] = "not-a-uuid"
        self.assertTrue(schema_errors(broken, load_schema(version)))


if __name__ == "__main__":
    unittest.main()
