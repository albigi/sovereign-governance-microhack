import json
import unittest

from applicability import ARCHETYPES, MAPPING, PROFILES, RESOURCES, evaluate, load_json

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


SCHEMAS = RESOURCES / "schemas"


@unittest.skipUnless(Draft202012Validator, "needs jsonschema: python -m pip install -r tools/oscal/requirements.txt")
class SchemaTests(unittest.TestCase):
    def assertValid(self, document, schema_name):
        schema = load_json(SCHEMAS / schema_name)
        Draft202012Validator.check_schema(schema)
        errors = [f"/{'/'.join(map(str, error.absolute_path))}: {error.message}"
                  for error in Draft202012Validator(schema).iter_errors(document)]
        self.assertEqual(errors, [])

    def test_kit_data_and_results_match_their_schemas(self):
        mapping = load_json(MAPPING)
        archetypes = load_json(ARCHETYPES)
        self.assertValid(mapping, "catalogue-mapping.schema.json")
        self.assertValid(archetypes, "archetype.schema.json")
        for path in sorted(PROFILES.glob("*.json")):
            with self.subTest(profile=path.stem):
                profile = load_json(path)
                self.assertValid(profile, "application-profile.schema.json")
                result = json.loads(json.dumps(evaluate(mapping, archetypes, profile)))
                self.assertValid(result, "applicability.schema.json")


class ReferenceTests(unittest.TestCase):
    def test_mapping_references_resolve(self):
        mapping = load_json(MAPPING)
        archetypes = {item["id"] for item in load_json(ARCHETYPES)["archetypes"]}
        themes = {theme["id"] for theme in mapping["themes"]}
        identifiers = [item["id"] for item in mapping["requirements"]]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        for item in mapping["requirements"]:
            self.assertIn(item["theme"], themes)
            for control in item["controls"]:
                self.assertLessEqual(set(control.get("archetypes", [])), archetypes)
        self.assertEqual({item["theme"] for item in mapping["requirements"]}, themes)


if __name__ == "__main__":
    unittest.main()
