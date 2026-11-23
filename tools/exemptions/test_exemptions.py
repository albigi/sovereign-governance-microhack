import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import exemptions as ex

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
EXAMPLES = HERE.parent.parent / "resources" / "exemptions" / "examples"
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
HEAD = "1" * 40


def example(name="exc-legacy-client-transfer"):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


class Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initiative = ex.load_initiative(FIXTURES / "initiative.json")
        cls.verbs, conflicts = ex.merge_verbs(ex.load_catalogue(FIXTURES / "catalogue.csv"), initiative)
        assert not conflicts
        cls.references = initiative["references"]

    def check(self, doc, **overrides):
        options = dict(now=NOW, allowed_resource_groups=["rg-mh-example01"], references=self.references)
        options.update(overrides)
        return ex.validate_exemption(doc, doc.get("id"), self.verbs, **options)

    def assertRefused(self, doc, fragment, **overrides):
        errors = self.check(doc, **overrides)
        self.assertTrue(any(fragment in error for error in errors), errors)

    def test_sollte_exemption_passes(self):
        self.assertEqual(self.check(example()), [])

    def test_hidden_must_behind_a_policy_reference_is_refused(self):
        errors = self.check(example("exc-residency-outside-region"))
        self.assertTrue(any("also implements STM.2.1.7" in e for e in errors), errors)
        self.assertTrue(any("STM.2.1.7 is MUSS" in e for e in errors), errors)

    def test_missing_expiry_is_refused(self):
        self.assertRefused(example("exc-no-expiry"), "missing required fields: expiresOn")

    def test_every_group_of_the_reference_must_be_cited(self):
        doc = example()
        doc["requirements"] = ["KONF.14.1"]
        self.assertRefused(doc, "also implements KONF.14.1.1")

    def test_optional_requirement_needs_no_exemption(self):
        for ref, group in (("encryption-infrastructure", "KONF.11.8"), ("backup-geo-redundant-storage", "NOT.4.12")):
            for claims in ([group], ["KONF.14.1"]):
                with self.subTest(reference=ref, claims=claims):
                    self.assertRefused(dict(example(), policyDefinitionReferenceIds=[ref], requirements=claims),
                                       f"{group} is KANN")

    def test_reference_without_a_requirement_group_cannot_be_waived(self):
        self.assertRefused(example(), "must have identified requirement groups",
                           references={"transport-secure-transfer": []})

    def test_lab_assignment_is_a_name_and_resource_is_a_relative_id(self):
        self.assertRefused(dict(example(), policyAssignment="/subscriptions/other"), "must be an assignment name")
        self.assertRefused(dict(example(), resource="not-a-resource-id"), "resource must look like")

    @unittest.skipUnless((HERE.parents[1] / "resources/archetype-initiative/policyset.json").is_file(),
                         "requires challenge 2 in the same kit")
    def test_fixture_matches_the_generated_challenge_2_contract(self):
        directory = HERE.parents[1] / "resources/archetype-initiative"
        def properties(path):
            return json.loads(path.read_text(encoding="utf-8"))["properties"]

        fixture = properties(FIXTURES / "initiative.json")
        source = properties(directory / "policyset.json")
        actual = {policy["policyDefinitionReferenceId"]: policy for policy in source["policyDefinitions"]}
        for policy in fixture["policyDefinitions"]:
            self.assertEqual(policy, actual[policy["policyDefinitionReferenceId"]])
        for name, parameter in fixture["parameters"].items():
            self.assertEqual(parameter, {key: value for key, value in source["parameters"][name].items()
                                         if key != "metadata"})
        initiative = ex.load_initiative(directory / "policyset.json")
        for group in fixture["policyDefinitionGroups"]:
            self.assertEqual(group["category"], initiative["verbs"][group["name"]])
        for groups in initiative["references"].values():
            self.assertTrue({"DET.3.1.8", "DET.3.2"}.isdisjoint(groups))
        corp = json.loads((directory / "assignments.json").read_text(encoding="utf-8"))["archetypes"]["corp"]
        self.assertEqual(corp["assignmentName"], example()["policyAssignment"])
        for key in ("secureTransferEffect", "residencyEffect"):
            self.assertEqual(corp["parameters"][key]["value"], "Deny")

    def test_unknown_requirement_and_reference_are_refused(self):
        doc = example()
        doc["requirements"].append("XYZ.1.1")
        doc["policyDefinitionReferenceIds"].append("not-in-initiative")
        self.assertRefused(doc, "XYZ.1.1 is not a known requirement ID")
        self.assertRefused(doc, "'not-in-initiative' is not in the initiative")

    def test_expiry_in_the_past_or_too_far_is_refused(self):
        doc = example()
        doc["expiresOn"] = "2026-11-19T00:00:00Z"
        self.assertRefused(doc, "is not in the future")
        doc["expiresOn"] = "2027-03-01T00:00:00Z"
        self.assertRefused(doc, "more than 90 days ahead")
        self.assertEqual(self.check(doc, max_days=120), [])

    def test_mitigated_needs_compensating_controls(self):
        doc = example()
        doc["category"] = "Mitigated"
        doc["compensatingControls"] = []
        self.assertRefused(doc, "Mitigated needs at least one compensating control")

    def test_resource_group_outside_the_lab_is_refused(self):
        doc = example()
        doc["resourceGroup"] = "rg-production"
        self.assertRefused(doc, "outside the allowed lab scope")

    def test_id_must_match_file_name(self):
        errors = ex.validate_exemption(example(), "exc-other-name", self.verbs, now=NOW)
        self.assertTrue(any("must equal the file name" in e for e in errors), errors)

    def test_initiative_and_catalogue_must_agree(self):
        initiative = {"verbs": {"KONF.14.1": "KANN"}, "references": {}}
        _, conflicts = ex.merge_verbs({"KONF.14.1": "SOLLTE"}, initiative)
        self.assertEqual(len(conflicts), 1)


class Decision(unittest.TestCase):
    def review(self, user, state, commit=HEAD, at="2026-11-20T10:00:00Z", body=""):
        return {"user": user, "state": state, "commitId": commit, "submittedAt": at, "body": body}

    def test_approval_by_the_risk_owner_on_the_head_passes(self):
        reviews = [self.review("Risk-Owner", "APPROVED")]
        self.assertEqual(ex.decision_errors(example(), "lab-engineer", HEAD, reviews), [])

    def test_author_cannot_be_the_risk_owner(self):
        reviews = [self.review("risk-owner", "APPROVED")]
        errors = ex.decision_errors(example(), "risk-owner", HEAD, reviews)
        self.assertIn("opened the pull request", errors[0])

    def test_approval_of_an_older_commit_does_not_count(self):
        reviews = [self.review("risk-owner", "APPROVED", commit="0" * 40)]
        self.assertIn("not the current head", ex.decision_errors(example(), "lab-engineer", HEAD, reviews)[0])

    def test_later_change_request_withdraws_the_approval(self):
        reviews = [self.review("risk-owner", "APPROVED", at="2026-11-20T10:00:00Z"),
                   self.review("risk-owner", "CHANGES_REQUESTED", at="2026-11-20T10:05:00Z"),
                   self.review("risk-owner", "COMMENTED", at="2026-11-20T10:06:00Z")]
        self.assertIn("awaiting approval", ex.decision_errors(example(), "lab-engineer", HEAD, reviews)[0])

    def test_other_approvers_do_not_count(self):
        reviews = [self.review("someone-else", "APPROVED")]
        self.assertIn("awaiting approval", ex.decision_errors(example(), "lab-engineer", HEAD, reviews)[0])

    def test_lab_self_approval_needs_the_flag_and_an_approve_comment_on_the_head(self):
        approve = self.review("risk-owner", "COMMENTED", body="/approve\nI accept the risk until expiry.")
        self.assertIn("opened the pull request", ex.decision_errors(example(), "risk-owner", HEAD, [approve])[0])
        self.assertEqual(ex.decision_errors(example(), "risk-owner", HEAD, [approve], self_approval=True), [])
        for reviews, error in (([self.review("risk-owner", "COMMENTED", body="Looks fine, /approve later")],
                                "awaiting approval"),
                               ([dict(approve, commitId="0" * 40)], "not the current head")):
            with self.subTest(error=error):
                errors = ex.decision_errors(example(), "risk-owner", HEAD, reviews, self_approval=True)
                self.assertIn(error, errors[0])

    def test_self_approved_exemption_is_marked_in_azure(self):
        record = {"url": "https://github.com/owner/repo/pull/1", "author": "risk-owner"}
        body = ex.exemption_body(example(), "/assignment", record, {"user": "Risk-Owner", "submittedAt": "t"})
        self.assertEqual(body["properties"]["metadata"]["approvalMode"], "lab-self-approval")


class Apply(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp()) / "exemptions"
        self.folder.mkdir()
        self.addCleanup(shutil.rmtree, self.folder.parent)
        initiative = ex.load_initiative(FIXTURES / "initiative.json")
        self.verbs, _ = ex.merge_verbs(None, initiative)
        self.references = initiative["references"]

    def write(self, doc):
        path = self.folder / f"{doc['id']}.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def pr(self, number, path, state="MERGED", author="lab-engineer", approver="risk-owner", merged="2026-11-20"):
        reviews = [{"user": approver, "state": "APPROVED", "commitId": str(number) * 40,
                    "submittedAt": f"{merged}T08:00:00Z"}] if approver else []
        return {"number": number, "url": f"https://github.com/owner/repo/pull/{number}", "author": author,
                "state": state, "mergedAt": f"{merged}T08:30:00Z" if state == "MERGED" else "",
                "headSha": str(number) * 40, "files": [f"exemptions/{path.name}"], "reviews": reviews}

    def plan(self, files, prs, now=NOW):
        return ex.plan_apply(files, prs, self.verbs, self.references, now, 90, ["rg-mh-example01"])

    def test_validate_and_apply_require_lab_scope_and_initiative(self):
        for command in (["validate"], ["apply", "--dry-run"]):
            for options, missing in ((["--initiative", str(FIXTURES / "initiative.json")], "lab scope"),
                                     (["--catalogue", str(FIXTURES / "catalogue.csv"),
                                       "--resource-group", "rg-mh-example01"], "challenge 2 policy set")):
                with self.subTest(command=command, missing=missing), patch.object(ex, "run") as run:
                    with self.assertRaisesRegex(SystemExit, missing):
                        ex.main(command + options)
                    run.assert_not_called()

    def test_assignment_lookup_stops_at_the_lab_group(self):
        with patch.object(ex, "run", side_effect=ex.subprocess.CalledProcessError(1, "az")) as run:
            with self.assertRaises(ex.subprocess.CalledProcessError):
                ex.resolve_assignment("synthetic", example())
            run.assert_called_once()
            self.assertIn("/resourceGroups/rg-mh-example01/", run.call_args.args[0][-1])

    def test_failed_tool_call_reports_one_line_not_a_traceback(self):
        error = ex.subprocess.CalledProcessError(
            1, [r"C:\tools\gh.exe", "repo", "view"], stderr="GraphQL: Could not resolve to a Repository\n")
        args = ex.argparse.Namespace(handler=lambda _: (_ for _ in ()).throw(error))
        with self.assertRaisesRegex(SystemExit, r"'gh repo view' failed \(exit 1\): GraphQL: Could not resolve"):
            ex.run_handler(args)

    def test_only_approved_unexpired_files_are_applied(self):
        approved = self.write(example())
        unapproved = self.write(dict(example(), id="exc-unapproved"))
        expired = self.write(dict(example(), id="exc-expired", expiresOn="2026-11-01T00:00:00Z"))
        prs = [self.pr(1, approved), self.pr(2, unapproved, approver=None), self.pr(3, expired)]
        to_apply, expired_docs, refused = self.plan([approved, unapproved, expired], prs)
        self.assertEqual([doc["id"] for doc, _, _ in to_apply], ["exc-legacy-client-transfer"])
        self.assertEqual([doc["id"] for doc in expired_docs], ["exc-expired"])
        self.assertEqual([doc["id"] for doc, _ in refused], ["exc-unapproved"])

    def test_latest_merged_pull_request_is_the_decision_record(self):
        path = self.write(example())
        prs = [self.pr(1, path, merged="2026-11-18"), self.pr(4, path, approver="someone-else", merged="2026-11-19"),
               self.pr(5, path, state="CLOSED")]
        self.assertEqual(ex.decision_record_for(f"exemptions/{path.name}", prs)["number"], 4)
        _, _, refused = self.plan([path], prs)
        self.assertIn("awaiting approval", refused[0][1][0])

    def test_prune_never_touches_a_containing_scope(self):
        sub = "00000000-0000-0000-0000-000000000000"
        group = f"/subscriptions/{sub}/resourceGroups/rg-mh-example01"
        managed = {"metadata": {"managedBy": ex.MANAGED_BY}}
        items = [
            {"name": "exc-kept", "id": f"{group}/providers/Microsoft.Authorization/policyExemptions/exc-kept",
             "properties": managed},
            {"name": "exc-withdrawn", "id": f"{group.upper()}/providers/x/y/providers/"
             "Microsoft.Authorization/policyExemptions/exc-withdrawn", "properties": managed},
            {"name": "exc-inherited", "id": f"/subscriptions/{sub}/providers/Microsoft.Authorization/"
             "policyExemptions/exc-inherited", "properties": managed},
            {"name": "portal-made", "id": f"{group}/providers/Microsoft.Authorization/policyExemptions/portal-made",
             "properties": {"metadata": None}},
        ]
        pruned = ex.prunable(items, sub, "rg-mh-example01", {"exc-kept"})
        self.assertEqual([item["name"] for item in pruned], ["exc-withdrawn"])

    def test_body_carries_the_decision_record_and_expiry(self):
        doc = example()
        doc["justification"] = "x" * 600
        record = {"url": "https://github.com/owner/repo/pull/1", "author": "lab-engineer"}
        body = ex.exemption_body(doc, "/assignment", record, {"user": "risk-owner", "submittedAt": "t"})
        properties = body["properties"]
        self.assertEqual(properties["expiresOn"], "2026-12-04T00:00:00Z")
        self.assertEqual(properties["metadata"]["decisionRecord"], record["url"])
        self.assertEqual(properties["metadata"]["managedBy"], ex.MANAGED_BY)
        self.assertEqual(len(properties["description"]), 512)
        scope = ex.exemption_scope("00000000-0000-0000-0000-000000000000", doc)
        self.assertTrue(scope.endswith("/resourceGroups/rg-mh-example01/providers/"
                                       "Microsoft.Storage/storageAccounts/stmhexample01exc"))


class InitRepo(unittest.TestCase):
    def test_created_repository_validates_its_own_files(self):
        target = Path(tempfile.mkdtemp()) / "lab-exceptions"
        self.addCleanup(shutil.rmtree, target.parent)
        with redirect_stdout(io.StringIO()):
            ex.main(["init-repo", str(target), "--resource-group", "rg-mh-example01",
                     "--initiative", str(FIXTURES / "initiative.json")])
        for relative in ("tools/exemptions.py", "tools/evidence.py", "tools/gspp_extract.py", "lab.json",
                         ".github/workflows/exemption-check.yml", ".github/pull_request_template.md",
                         "policy/initiative.json", "schema/exemption.schema.json"):
            self.assertTrue((target / relative).is_file(), relative)
        shutil.copy(EXAMPLES / "exc-legacy-client-transfer.json", target / "exemptions")
        shutil.copy(EXAMPLES / "exc-residency-outside-region.json", target / "exemptions")
        output = io.StringIO()
        with redirect_stdout(output):
            code = ex.main(["validate", "--config", str(target / "lab.json"), "--as-of", "2026-11-20T09:00:00Z"])
        self.assertEqual(code, 1)
        self.assertIn("PASS", output.getvalue())
        self.assertIn("REFUSED", output.getvalue())
        self.assertFalse(json.loads((target / "lab.json").read_text(encoding="utf-8"))["selfApproval"])

    def test_copied_extractor_finds_its_catalogue_pin(self):
        mapping = HERE.parent.parent / "resources" / "catalogue-mapping.json"
        if not mapping.is_file():
            self.skipTest("this kit tree has no catalogue-mapping.json; the extractor pins the catalogue itself")
        target = Path(tempfile.mkdtemp()) / "lab-exceptions"
        self.addCleanup(shutil.rmtree, target.parent)
        with redirect_stdout(io.StringIO()):
            ex.main(["init-repo", str(target), "--resource-group", "rg-mh-example01",
                     "--initiative", str(FIXTURES / "initiative.json")])
        spec = importlib.util.spec_from_file_location("lab_gspp_extract", target / "tools" / "gspp_extract.py")
        extractor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(extractor)
        self.assertEqual(extractor.find_config(), (target / "tools" / "catalogue-mapping.json").resolve())
        expected = json.loads(mapping.read_text(encoding="utf-8"))["catalogue"]
        self.assertEqual(extractor.load_catalogue()["sha256"], expected["sha256"])


if __name__ == "__main__":
    unittest.main()
