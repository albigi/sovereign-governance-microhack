import unittest

from applicability import ARCHETYPES, MAPPING, PROFILES, archetype_for, evaluate, load_json


ARCHETYPE_DATA = {
    "archetypes": [
        {"id": "corp", "title": "Corp", "constraints": {"internet_facing": [False]}, "parameters": {}},
        {"id": "online", "title": "Online", "constraints": {"internet_facing": [True]}, "parameters": {}},
    ]
}


def profile(**facts):
    result = {
        "id": "app", "name": "App", "archetype": "corp", "protection_need": "normal",
        "data_classification": "internal", "internet_facing": False, "stores_data": True,
        "personal_data": False, "resource_types": ["Microsoft.Storage/storageAccounts"],
    }
    result.update(facts)
    return result


def requirement(identifier, level="normal", applies_when=(), controls=(), checkable="yes"):
    return {
        "id": identifier, "modal_verb": "SOLLTE", "security_level": level, "theme": "t",
        "route": "azure-policy", "checkable": checkable, "applies_when": list(applies_when),
        "controls": list(controls), "deviation_path": "policy-exemption", "owner": "platform",
        "evidence": "e", "gap": "",
    }


def policy(name, resource_types=("*",), **extra):
    return {"kind": "policy-definition", "id": name, "name": name, "resource_types": list(resource_types), **extra}


def mapping(*requirements):
    return {
        "schema_version": "1.0.0", "checked": "2026-01-01",
        "catalogue": {"revision": "r", "sha256": "s"}, "requirements": list(requirements),
    }


def rows(result):
    return {row["id"]: row for row in result["requirements"]}


class RuleTests(unittest.TestCase):
    def test_elevated_requirement_applies_only_at_high_protection_need(self):
        data = mapping(requirement("A.1", level="elevated"))
        normal = rows(evaluate(data, ARCHETYPE_DATA, profile()))["A.1"]
        high = rows(evaluate(data, ARCHETYPE_DATA, profile(protection_need="high")))["A.1"]
        self.assertEqual((normal["applicable"], normal["policy_coverage"], normal["controls"]), (False, None, []))
        self.assertIn("protection need is normal", normal["reason"])
        self.assertTrue(high["applicable"])
        self.assertEqual(high["reason"], "Elevated-level requirement and the protection need is high.")

    def test_failed_condition_gives_its_otherwise_reason(self):
        condition = {"fact": "personal_data", "equals": True, "otherwise": "No personal data."}
        row = rows(evaluate(mapping(requirement("A.1", applies_when=[condition])), ARCHETYPE_DATA, profile()))["A.1"]
        self.assertEqual((row["applicable"], row["reason"]), (False, "No personal data."))

    def test_includes_any_is_case_insensitive_and_named_in_reason(self):
        condition = {"fact": "resource_types", "includes_any": ["microsoft.storage/storageaccounts"], "otherwise": "x"}
        row = rows(evaluate(mapping(requirement("A.1", applies_when=[condition])), ARCHETYPE_DATA, profile()))["A.1"]
        self.assertTrue(row["applicable"])
        self.assertEqual(row["reason"], "Resource_types include Microsoft.Storage/storageAccounts.")

    def test_controls_are_filtered_and_coverage_follows_remaining_policies(self):
        data = mapping(
            requirement("A.1", controls=[policy("vm", ["Microsoft.Compute/virtualMachines"]), {"kind": "attestation", "id": "x", "name": "x"}]),
            requirement("A.2", controls=[policy("online-only", archetypes=["online"]), policy("any")]),
            requirement("A.3", controls=[policy("storage", ["microsoft.storage/STORAGEACCOUNTS"])], checkable="partial"),
        )
        result = rows(evaluate(data, ARCHETYPE_DATA, profile()))
        self.assertEqual([control["id"] for control in result["A.1"]["controls"]], ["x"])
        self.assertEqual(result["A.1"]["policy_coverage"], "none")
        self.assertEqual([control["id"] for control in result["A.2"]["controls"]], ["any"])
        self.assertEqual(result["A.2"]["policy_coverage"], "full")
        self.assertEqual(result["A.3"]["policy_coverage"], "partial")

    def test_profile_that_breaks_its_archetype_is_refused(self):
        with self.assertRaisesRegex(ValueError, "breaks archetype corp"):
            archetype_for(profile(internet_facing=True), ARCHETYPE_DATA)
        with self.assertRaisesRegex(ValueError, "unknown archetype"):
            archetype_for(profile(archetype="sandbox"), ARCHETYPE_DATA)


class KitDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = load_json(MAPPING)
        cls.archetypes = load_json(ARCHETYPES)

    def test_every_profile_fits_its_archetype_and_keeps_the_scope_contract(self):
        paths = sorted(PROFILES.glob("*.json"))
        self.assertEqual(len(paths), 10)
        for path in paths:
            with self.subTest(profile=path.stem):
                result = evaluate(self.mapping, self.archetypes, load_json(path))
                self.assertEqual(result["profile"]["id"], path.stem)
                for row in result["requirements"]:
                    self.assertIsInstance(row["applicable"], bool)
                    self.assertTrue(row["reason"])
                    self.assertEqual(row["policy_coverage"] is None, not row["applicable"])

    def test_leave_planner_result(self):
        result = evaluate(self.mapping, self.archetypes, load_json(PROFILES / "leave-planner.json"))
        self.assertEqual(result["summary"]["applicable"], 17)
        self.assertEqual(result["summary"]["policy_coverage"], {"full": 2, "partial": 7, "none": 8})
        not_applicable = sorted(row["id"] for row in result["requirements"] if not row["applicable"])
        self.assertEqual(not_applicable, ["BER.5.8", "BES.2.3", "DET.3.2", "DET.5.10.2", "KONF.11.8", "NOT.4.12"])


if __name__ == "__main__":
    unittest.main()
