import copy
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import evidence as ev

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
SNAPSHOT = json.loads((FIXTURES / "snapshot.json").read_text(encoding="utf-8"))


class Pack(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp)

    def run_pack(self, snapshot=None, as_of=None, scope=True, exemptions_dir=None, self_approval=False):
        path = self.temp / "snapshot.json"
        path.write_text(json.dumps(snapshot or SNAPSHOT), encoding="utf-8")
        scope_path = FIXTURES / "scope.json" if scope is True else None
        if isinstance(scope, dict):
            scope_path = self.temp / "scope.json"
            scope_path.write_text(json.dumps(scope), encoding="utf-8")
        return ev.generate(path, exemptions_dir or FIXTURES / "exemptions", FIXTURES / "initiative.json",
                           FIXTURES / "catalogue.csv", scope_path, as_of, self_approval=self_approval)

    def statuses(self, **options):
        pack, _, _ = self.run_pack(**options)
        return {key: value[0] for key, value in ev.statuses(pack).items()}

    def test_fixture_statuses(self):
        pack, _, _ = self.run_pack()
        found = ev.statuses(pack)
        self.assertEqual({key: value[0] for key, value in found.items()}, {
            "BES.2.2": "fulfilled", "DET.3.1.8": "unresolved", "KONF.11.8": "not-applicable",
            "KONF.14.1": "not-fulfilled", "KONF.14.1.1": "not-fulfilled", "STM.2.1.7": "fulfilled",
            "UMS.5.1": "fulfilled", "UMS.5.2": "fulfilled",
        })
        self.assertEqual(found["KONF.14.1"][1:], ("approved-temporary", "2026-12-04T00:00:00Z"))

    def test_same_inputs_give_the_same_bytes(self):
        first, _, _ = self.run_pack()
        second, _, _ = self.run_pack()
        self.assertEqual(ev.dump(first), ev.dump(second))

    def test_stale_evidence_is_never_fulfilled(self):
        found = self.statuses(as_of="2026-11-22T12:00:00Z")
        self.assertNotIn("fulfilled", found.values())
        self.assertEqual(found["KONF.14.1"], "unresolved")
        self.assertEqual(found["UMS.5.1"], "unresolved")

    def test_expired_exemption_awaits_re_evaluation(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot["collectedAt"] = "2026-12-04T06:00:00Z"
        for state in snapshot["policyStates"]:
            state["timestamp"] = "2026-12-04T05:00:00Z"
        found = self.statuses(snapshot=snapshot)
        self.assertEqual(found["KONF.14.1"], "unresolved")
        self.assertEqual(found["BES.2.2"], "fulfilled")

    def test_exempt_without_a_decision_record_fails(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot["pullRequests"] = [pr for pr in snapshot["pullRequests"] if pr["number"] != 1]
        found = self.statuses(snapshot=snapshot)
        self.assertEqual(found["KONF.14.1"], "not-fulfilled")
        self.assertEqual(found["UMS.5.1"], "not-fulfilled")
        pack, _, _ = self.run_pack(snapshot=snapshot)
        self.assertEqual(ev.statuses(pack)["KONF.14.1"][1], "")

    def test_expiry_changed_outside_the_pull_request_fails(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot["exemptions"][0]["expiresOn"] = "2027-06-01T00:00:00Z"
        self.assertEqual(self.statuses(snapshot=snapshot)["KONF.14.1"], "not-fulfilled")

    def test_non_waivable_group_never_gets_an_approved_deviation(self):
        for ref, group in (("residency-allowed-locations", "STM.2.1.7"), ("encryption-infrastructure", "KONF.11.8"),
                           ("backup-geo-redundant-storage", "NOT.4.12")):
            with self.subTest(reference=ref):
                snapshot = copy.deepcopy(SNAPSHOT)
                state = snapshot["policyStates"][-1]
                # Even the SOLLTE state must not claim an approved waiver when the same file also covers this ref.
                snapshot["policyStates"] = [state]
                refs = [state["policyDefinitionReferenceId"], ref]
                snapshot["exemptions"][0]["policyDefinitionReferenceIds"] = refs
                docs = self.temp / "exemptions"
                docs.mkdir(exist_ok=True)
                path = next((FIXTURES / "exemptions").glob("exc-*.json"))
                doc = json.loads(path.read_text(encoding="utf-8"))
                doc.update(policyDefinitionReferenceIds=refs, requirements=doc["requirements"] + [group, "BES.2.2"])
                (docs / path.name).write_text(json.dumps(doc), encoding="utf-8")
                pack, _, _ = self.run_pack(snapshot=snapshot, scope=False, exemptions_dir=docs)
                self.assertEqual(ev.statuses(pack)["KONF.14.1"], ("not-fulfilled", "", ""))

    def test_drifted_scope_reference_or_assignment_is_not_an_approved_deviation(self):
        for key, value in (("policyDefinitionReferenceIds", []),
                           ("policyAssignmentId", SNAPSHOT["exemptions"][0]["policyAssignmentId"]
                            .replace("/resourceGroups/rg-mh-example01", "")),
                           ("id", SNAPSHOT["exemptions"][0]["id"].replace(
                               "/providers/Microsoft.Storage/storageAccounts/stmhexample01exc", ""))):
            with self.subTest(field=key):
                snapshot = copy.deepcopy(SNAPSHOT)
                snapshot["exemptions"][0][key] = value
                pack, _, _ = self.run_pack(snapshot=snapshot)
                self.assertEqual(ev.statuses(pack)["KONF.14.1"], ("not-fulfilled", "", ""))

    def test_exemption_created_outside_the_process_fails_the_process_check(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        rogue = copy.deepcopy(snapshot["exemptions"][0])
        rogue.update(name="portal-exemption", metadata={}, expiresOn="")
        rogue["id"] = rogue["id"].replace("exc-legacy-client-transfer", "portal-exemption")
        snapshot["exemptions"].append(rogue)
        found = self.statuses(snapshot=snapshot)
        self.assertEqual(found["UMS.5.1"], "not-fulfilled")
        self.assertEqual(found["UMS.5.2"], "not-fulfilled")

    def test_lab_self_approval_counts_only_in_lab_mode_and_is_disclosed(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        pr = next(pr for pr in snapshot["pullRequests"] if pr["number"] == 1)
        pr["author"] = "risk-owner"
        for review in pr["reviews"]:
            review.update(state="COMMENTED", body="/approve")
        strict = self.statuses(snapshot=snapshot)
        self.assertEqual((strict["KONF.14.1"], strict["UMS.5.1"]), ("not-fulfilled", "not-fulfilled"))
        pack, _, results = self.run_pack(snapshot=snapshot, self_approval=True)
        self.assertEqual(ev.statuses(pack)["KONF.14.1"][1], "approved-temporary")
        reasons = {result["id"]: (result["status"], " ".join(result["reasons"])) for result in results}
        self.assertEqual(reasons["UMS.5.1"][0], "fulfilled")
        self.assertIn("lab self-approval", reasons["UMS.5.1"][1])
        self.assertIn("lab self-approval by the requester", reasons["KONF.14.1"][1])

    def test_non_compliant_and_unknown_states(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot["policyStates"][0]["complianceState"] = "NonCompliant"
        self.assertEqual(self.statuses(snapshot=snapshot)["STM.2.1.7"], "not-fulfilled")
        snapshot["policyStates"][0]["complianceState"] = "Unknown"
        self.assertEqual(self.statuses(snapshot=snapshot)["STM.2.1.7"], "unresolved")

    def test_without_scope_file_the_initiative_and_process_requirements_are_reviewed(self):
        found = self.statuses(scope=False)
        self.assertEqual(sorted(found), ["BES.2.2", "KONF.11.8", "KONF.14.1", "KONF.14.1.1", "NOT.4.12",
                                         "STM.2.1.7", "UMS.5.1", "UMS.5.2"])

    def test_candidate_coverage_is_not_an_observation(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot["policyStates"].append(dict(snapshot["policyStates"][0],
                                            policyDefinitionReferenceId="platform-only",
                                            policyDefinitionGroupNames=["DET.3.1.8"]))
        scope = {"requirements": [
            {"id": "DET.3.1.8", "applicable": True, "policy_coverage": "full", "reason": "Activity logs apply."},
            {"id": "UMS.5.1", "applicable": True, "policy_coverage": "none"},
            {"id": "UMS.5.2", "applicable": False, "reason": "Excluded for this test."},
        ]}
        pack, _, results = self.run_pack(snapshot=snapshot, scope=scope)
        self.assertEqual([(r["id"], r["status"], bool(r["observations"])) for r in results], [
            ("DET.3.1.8", "unresolved", False), ("UMS.5.1", "fulfilled", True), ("UMS.5.2", "not-applicable", False)])
        self.assertIn("Excluded for this test.", results[-1]["reasons"][0])
        first = pack["assessment-results"]["results"][0]["findings"][0]
        self.assertIn(ev.prop("applicability-reason", "Activity logs apply."), first["props"])

    def test_missing_compliance_state_is_not_a_pass_or_a_failure(self):
        state = dict(SNAPSHOT["policyStates"][0])
        del state["complianceState"]
        snapshot = dict(SNAPSHOT, policyStates=[ev.normalise_state(state)])
        self.assertEqual(self.statuses(snapshot=snapshot)["BES.2.2"], "unresolved")

    def test_partial_or_no_policy_coverage_is_never_fulfilled_by_policy_alone(self):
        scope = json.loads((FIXTURES / "scope.json").read_text(encoding="utf-8"))
        coverage = {"BES.2.2": "partial", "STM.2.1.7": "full"}
        for entry in scope["requirements"]:
            entry["policy_coverage"] = coverage.get(entry["id"], "none")
        found = self.statuses(scope=scope)
        self.assertEqual(found["BES.2.2"], "unresolved")
        self.assertEqual(found["STM.2.1.7"], "fulfilled")
        self.assertEqual(found["UMS.5.1"], "fulfilled")
        for entry in scope["requirements"]:
            if entry["id"] == "STM.2.1.7":
                entry["policy_coverage"] = "none"
        self.assertEqual(self.statuses(scope=scope)["STM.2.1.7"], "unresolved")

    def test_scope_file_fills_missing_verbs_and_must_agree(self):
        scope = json.loads((FIXTURES / "scope.json").read_text(encoding="utf-8"))
        scope["requirements"].append({"id": "ASST.2.1", "applicable": True, "modal_verb": "SOLLTE"})
        _, _, results = self.run_pack(scope=scope)
        self.assertEqual({result["id"]: result["verb"] for result in results}["ASST.2.1"], "SOLLTE")
        for entry in scope["requirements"]:
            if entry["id"] == "STM.2.1.7":
                entry["modal_verb"] = "SOLLTE"
        with self.assertRaises(SystemExit):
            self.run_pack(scope=scope)

    def test_compare_lists_status_changes(self):
        before, _, _ = self.run_pack()
        after, _, _ = self.run_pack(as_of="2026-11-22T12:00:00Z")
        changed = {requirement for requirement, _, _ in ev.compare(before, after)}
        self.assertIn("KONF.14.1", changed)
        self.assertEqual(ev.compare(before, before), [])

    def test_oscal_references_resolve(self):
        pack, _, _ = self.run_pack()
        document = pack["assessment-results"]
        result = document["results"][0]
        resources = {item["uuid"] for item in document["back-matter"]["resources"]}
        self.assertIn(document["import-ap"]["href"][1:], resources)
        observations = {item["uuid"] for item in result["observations"]}
        for item in result["findings"]:
            for related in item.get("related-observations", []):
                self.assertIn(related["observation-uuid"], observations)
        controls = [c["control-id"] for c in result["reviewed-controls"]["control-selections"][0]["include-controls"]]
        self.assertEqual(controls, [f["target"]["target-id"] for f in result["findings"]])

    @unittest.skipUnless(os.environ.get("OSCAL_SCHEMA"), "set OSCAL_SCHEMA to the OSCAL 1.1.3 assessment-results JSON schema")
    def test_official_oscal_schema(self):
        import jsonschema

        text = Path(os.environ["OSCAL_SCHEMA"]).read_text(encoding="utf-8")
        # Python's re has no Unicode property classes; this approximation covers the token pattern.
        text = text.replace(r"\\p{L}", r"[^\\W\\d_]").replace(r"\\p{N}", r"\\d")
        schema = json.loads(text)
        pack, _, _ = self.run_pack()
        validator = jsonschema.validators.validator_for(schema)(schema, format_checker=jsonschema.FormatChecker())
        errors = sorted(validator.iter_errors(pack), key=lambda e: list(e.path))
        self.assertEqual([f"{list(e.path)}: {e.message}" for e in errors], [])


if __name__ == "__main__":
    unittest.main()
