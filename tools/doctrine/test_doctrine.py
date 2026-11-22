"""Tests for the enforcement decision rule. Run from the repository root."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctrine as d  # noqa: E402


def theme(doc, key):
    return next(t for t in doc["themes"] if t["key"] == key)


class Rule(unittest.TestCase):
    def test_branches(self):
        cases = [
            # verb, check, binding, remediation -> effect, deviation
            ("MUSS", "none", "bound", False, None, "none"),
            ("MUSS", "property", "bound", False, "Deny", "none"),
            ("SOLLTE", "property", "obligation", False, "Deny", "none"),
            ("SOLLTE", "property", "bound", False, "Deny", "exemption"),
            ("SOLLTE", "property", "bound", True, "Modify", "exemption"),
            ("SOLLTE", "existence", "bound", False, "AuditIfNotExists", "exemption"),
            ("SOLLTE", "existence", "bound", True, "DeployIfNotExists", "exemption"),
            ("SOLLTE", "property", "not-bound", True, "Audit", "archetype-change"),
            ("SOLLTE", "existence", "not-bound", False, "AuditIfNotExists", "archetype-change"),
            ("SOLLTE", "none", "obligation", False, None, "none"),
            ("SOLLTE", "none", "bound", False, None, "attestation-exception"),
            ("SOLLTE", "none", "not-bound", False, None, "archetype-change"),
            ("KANN", "property", "bound", False, "Deny", "archetype-change"),
            ("KANN", "property", "not-bound", False, "Audit", "not-required"),
            ("KANN", "none", "bound", False, None, "archetype-change"),
            ("KANN", "none", "not-bound", False, None, "not-required"),
        ]
        for verb, check, binding, remediation, effect, deviation in cases:
            with self.subTest(verb=verb, check=check, binding=binding, remediation=remediation):
                got = d.decide(verb, check, binding, remediation)
                self.assertEqual((got[0], got[1]), (effect, deviation))

    def test_existence_without_remediation_is_flagged(self):
        self.assertTrue(d.decide("SOLLTE", "existence", "bound", False)[2])

    def test_fallback(self):
        self.assertEqual(d.fit_effect("Modify", ["Audit", "Deny", "Disabled"])[0], "Deny")
        self.assertEqual(d.fit_effect("Deny", ["Audit", "Disabled"])[0], "Audit")
        self.assertEqual(d.fit_effect("DeployIfNotExists", ["AuditIfNotExists", "Disabled"])[0], "AuditIfNotExists")
        effect, note = d.fit_effect("Deny", ["Modify", "Disabled"])
        self.assertEqual(effect, "Disabled")
        self.assertIn("coverage gap", note)
        self.assertEqual(d.fit_effect("Deny", ["Deny"]), ("Deny", None))

    def test_classify_applies_fallback(self):
        doc = d.load()
        theme(doc, "transport-encryption")["policies"][0]["allowedEffects"] = ["Audit", "Disabled"]
        row = next(r for r in d.classify(doc) if r["theme"] == "transport-encryption" and r["archetype"] == "corp")
        self.assertEqual(row["policies"]["transport-secure-transfer"], "Audit")
        self.assertTrue(any("enforcement gap" in n for n in row["notes"]))


class ContractWithExemptionCheck(unittest.TestCase):
    """Shape that the exemption check and evidence generator of challenges 3 and 4 read."""

    @classmethod
    def setUpClass(cls):
        cls.doc = d.load()
        cls.policyset = d.build_policyset(cls.doc)
        cls.archetypes = d.build_assignments(cls.doc)
        cls.refs = {r["policyDefinitionReferenceId"]: r for r in cls.policyset["properties"]["policyDefinitions"]}

    def test_groups_are_requirement_ids_with_verb_category(self):
        groups = self.policyset["properties"]["policyDefinitionGroups"]
        for group in groups:
            self.assertEqual(group["category"], self.doc["requirements"][group["name"]]["verb"])
        used = {g for r in self.refs.values() for g in r["groupNames"]}
        self.assertEqual(used, {g["name"] for g in groups})

    def test_challenge_three_references(self):
        self.assertEqual(self.refs["transport-secure-transfer"]["groupNames"], ["KONF.14.1", "KONF.14.1.1"])
        self.assertTrue(self.refs["transport-secure-transfer"]["policyDefinitionId"].endswith("404c3081-a854-4457-ae30-26a93ef643f9"))
        self.assertEqual(self.refs["residency-allowed-locations"]["groupNames"], ["BES.2.2", "STM.2.1.7"])
        corp = self.archetypes["archetypes"]["corp"]
        self.assertEqual(corp["assignmentName"], "gspp-corp")
        self.assertEqual(corp["parameters"]["secureTransferEffect"]["value"], "Deny")
        self.assertEqual(corp["parameters"]["residencyEffect"]["value"], "Deny")

    def test_archetype_parameters_come_from_shared_archetypes(self):
        corp = self.archetypes["archetypes"]["corp"]["parameters"]
        shared = self.doc["archetypes"]["corp"]["parameters"]
        self.assertEqual(corp["allowedLocations"]["value"], shared["allowed_locations"])
        self.assertEqual(corp["minimumTlsVersion"]["value"], "TLS1_2")
        self.assertEqual(self.archetypes["siteParameters"], ["logAnalyticsWorkspaceId"])

    def test_platform_themes_stay_outside_the_set(self):
        defs = {r["policyDefinitionId"].rsplit("/", 1)[-1] for r in self.refs.values()}
        for key in ("activity-logging", "cloud-log-integration"):
            self.assertEqual(theme(self.doc, key)["scope"], "platform")
            self.assertNotIn(theme(self.doc, key)["platformDefinition"], defs)
        row = next(r for r in d.classify(self.doc) if r["theme"] == "activity-logging" and r["archetype"] == "corp")
        self.assertEqual(row["platformEffect"], "DeployIfNotExists")

    def test_exemption_only_where_every_group_is_sollte(self):
        verbs = {k: v["verb"] for k, v in self.doc["requirements"].items()}
        for row in d.classify(self.doc):
            for ref in row["policies"]:
                group_verbs = {verbs[g] for g in self.refs[ref]["groupNames"]}
                if group_verbs != {"SOLLTE"}:
                    self.assertNotEqual(row["deviation"], "exemption", f"{ref}/{row['archetype']}")

    def test_effect_defaults_never_block(self):
        for name, param in self.policyset["properties"]["parameters"].items():
            if name.endswith("Effect"):
                self.assertIn(param["defaultValue"], ("Audit", "AuditIfNotExists", "Disabled"), name)

    def test_remediating_archetypes_carry_roles(self):
        for arch in self.archetypes["archetypes"].values():
            effects = {p["value"] for p in arch["parameters"].values() if isinstance(p["value"], str)}
            if effects & {"Modify", "DeployIfNotExists"}:
                self.assertTrue(arch["roleDefinitionIds"])


class Invariants(unittest.TestCase):
    def test_committed_doctrine_is_clean(self):
        self.assertEqual(d.invariants(d.load()), [])

    def test_exemption_with_kann_group_is_refused(self):
        doc = d.load()
        theme(doc, "transport-encryption")["requirements"].append("KONF.11.8")
        self.assertTrue(any("exemption offered" in e for e in d.invariants(doc)))

    def test_obligation_must_bind_every_archetype(self):
        doc = d.load()
        theme(doc, "residency")["binding"]["online"] = "bound"
        self.assertTrue(any("shared" in e for e in d.invariants(doc)))

    def test_obligation_must_be_must(self):
        doc = d.load()
        theme(doc, "residency")["obligation"] = "BES.2.3"
        self.assertTrue(any("must be MUSS" in e for e in d.invariants(doc)))

    def test_unchecked_must_routes_to_named_decision(self):
        doc = d.load()
        theme(doc, "exception-authorisation")["route"] = "process-owner"
        self.assertTrue(any("named decision" in e for e in d.invariants(doc)))

    def test_duplicate_reference_id(self):
        doc = d.load()
        policies = theme(doc, "transport-encryption")["policies"]
        policies[1] = dict(policies[1], referenceId=policies[0]["referenceId"])
        self.assertTrue(any("duplicate reference ID" in e for e in d.invariants(doc)))

    def test_platform_theme_binds_every_archetype_alike(self):
        doc = d.load()
        theme(doc, "cloud-log-integration")["binding"]["online"] = "not-bound"
        self.assertTrue(any("one platform assignment" in e for e in d.invariants(doc)))

    def test_archetype_value_outside_definition_is_refused(self):
        doc = d.load()
        doc["archetypes"]["online"]["parameters"]["minimum_tls_version"] = "1.3"
        self.assertTrue(any("minimumTlsVersion/online" in e for e in d.invariants(doc)))

    def test_bindings_for_unknown_theme(self):
        doc = d.load()
        doc["archetypes"]["corp"]["bindings"]["no-such-theme"] = "bound"
        self.assertTrue(any("unknown themes" in e for e in d.invariants(doc)))


class Mapping(unittest.TestCase):
    """Cross-check with the shared catalogue mapping of challenge 1."""

    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads(d.MAPPING.read_text(encoding="utf-8"))

    def test_committed_files_agree(self):
        errors, notes = d.check_mapping(d.load(), self.mapping)
        self.assertEqual(errors, [])
        self.assertTrue(notes)

    def test_version_drift_is_detected(self):
        mapping = copy.deepcopy(self.mapping)
        control = next(c for r in mapping["requirements"] if r["id"] == "KONF.14.1" for c in r["controls"] if c.get("id", "").startswith("404c3081"))
        control["version"] = "9.9.9"
        errors, _ = d.check_mapping(d.load(), mapping)
        self.assertTrue(any("404c3081" in e and "version" in e for e in errors))

    def test_requirement_without_theme_is_detected(self):
        mapping = copy.deepcopy(self.mapping)
        mapping["requirements"].append(dict(mapping["requirements"][0], id="XYZ.1.1", controls=[]))
        errors, _ = d.check_mapping(d.load(), mapping)
        self.assertTrue(any(e.startswith("XYZ.1.1") for e in errors))

    def test_archetype_filter_is_respected(self):
        doc = d.load()
        theme(doc, "internal-exposure")["binding"]["online"] = "bound"
        errors, _ = d.check_mapping(doc, self.mapping)
        self.assertTrue(any("b2982f36" in e and "online" in e for e in errors))


class Applicable(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_one_per_line_and_csv(self):
        self.assertEqual(d.read_applicable(self.write("# list\nKONF.14.1\nBER.5.9\n"))[0], {"KONF.14.1", "BER.5.9"})
        self.assertEqual(d.read_applicable(self.write('route,id\nentra,"BER.5.9"\nazure-policy,KONF.14.1\n'))[0], {"KONF.14.1", "BER.5.9"})

    def test_applicability_json_of_challenge_one(self):
        report = {
            "archetype": {"id": "corp"},
            "requirements": [{"id": "KONF.14.1", "applicable": True}, {"id": "BER.5.8", "applicable": False}],
        }
        path = self.write(json.dumps(report))
        self.assertEqual(d.read_applicable(path), ({"KONF.14.1"}, "corp", {"KONF.14.1", "BER.5.8"}))
        ids, archetype, kept = d.applicable_from(d.load(), path)
        self.assertNotIn("BER.5.8", ids)
        self.assertIn("BER.4.6", kept)
        self.assertLessEqual(set(kept), ids)

    def test_filter_and_gap(self):
        doc = d.load()
        applicable = {"KONF.14.1", "BER.5.9", "XYZ.1.1"}
        self.assertEqual({r["theme"] for r in d.classify(doc, applicable)}, {"transport-encryption", "strong-authentication"})
        self.assertEqual(d.unmapped(doc, applicable), ["XYZ.1.1"])
        refs = [r["policyDefinitionReferenceId"] for r in d.build_policyset(doc, applicable)["properties"]["policyDefinitions"]]
        self.assertEqual(refs, ["transport-secure-transfer", "transport-minimum-tls"])


class Drift(unittest.TestCase):
    def run_check(self, *options):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = d.main([*options, "check"])
        return code, err.getvalue()

    def test_committed_files_are_current(self):
        code, err = self.run_check()
        self.assertEqual(code, 0, err)

    def test_changed_archetype_binding_is_detected(self):
        shared = json.loads(d.ARCHETYPES.read_text(encoding="utf-8"))
        online = next(a for a in shared["archetypes"] if a["id"] == "online")
        online["enforcement"]["bindings"]["encryption-at-rest"] = "bound"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archetypes.json"
            path.write_text(json.dumps(shared), encoding="utf-8")
            code, err = self.run_check("--archetypes", str(path))
        self.assertEqual(code, 1)
        self.assertIn("stale", err)


class CataloguePin(unittest.TestCase):
    """The catalogue pin is configured once, in the catalogue block of the shared mapping."""

    def write(self, tmp, name, data):
        path = Path(tmp) / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_pin_comes_from_the_mapping(self):
        block = json.loads(d.MAPPING.read_text(encoding="utf-8"))["catalogue"]
        doc = d.load()
        self.assertEqual(
            {k: doc["catalogue"][k] for k in ("repository", "path", "commit", "sha256")},
            {"repository": block["repository"], "path": block["path"], "commit": block["revision"], "sha256": block["sha256"]},
        )
        self.assertEqual(d.build_policyset(doc)["properties"]["metadata"]["catalogueCommit"], block["revision"])

    def test_changed_mapping_pin_flows_through(self):
        mapping = json.loads(d.MAPPING.read_text(encoding="utf-8"))
        mapping["catalogue"]["revision"] = "0" * 40
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(tmp, "catalogue-mapping.json", mapping)
            self.assertEqual(d.load(mapping=path)["catalogue"]["commit"], "0" * 40)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                code = d.main(["check", "--mapping", path])
        self.assertEqual(code, 1)
        self.assertIn("policyset.json is stale", err.getvalue())

    def test_copied_pin_is_refused(self):
        doc = json.loads(d.DOCTRINE.read_text(encoding="utf-8"))
        doc["catalogue"]["commit"] = "c3f37859fdf302394de39e89252eb3e72a45953c"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "belong only in the catalogue block"):
                d.load(self.write(tmp, "doctrine.json", doc))


if __name__ == "__main__":
    unittest.main()
