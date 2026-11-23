#!/usr/bin/env python3
"""Evidence as a by-product of change: an OSCAL assessment-results pack from policy state and pull requests.

  collect   read policy compliance state, Azure exemptions and exception pull requests into one snapshot
  generate  turn a snapshot and the repository files into OSCAL assessment results (offline, deterministic)
  compare   list the requirement statuses that differ between two packs

Status rules: missing, stale, unknown or expired evidence is `unresolved`, never `fulfilled`. An exempt
resource is `not-fulfilled`; it carries an approved temporary deviation only if a merged pull request shows
the named risk owner's approval and the Azure exemption still matches the approved file.

Standard library only. `collect` calls the Azure CLI (`az`), the GitHub CLI (`gh`) and `git`.
"""

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import exemptions as ex

NS = "urn:requirement-to-evidence:v1"
UUID_NS = uuid.uuid5(uuid.NAMESPACE_URL, NS)
OSCAL_VERSION = "1.1.3"
PACK_VERSION = "1.0.0"
SNAPSHOT_VERSION = 1
DEFAULT_MAX_AGE_HOURS = 36
EXEMPTION_MARKER = "/providers/microsoft.authorization/policyexemptions/"
# Requirements evidenced by the exception process itself, not by a policy result. The check text is the
# kit's own; the requirement text stays in the catalogue.
PROCESS = {
    "UMS.5.1": "every exemption in force was approved on its final commit by its named risk owner, "
               "who did not open the request",
    "UMS.5.2": "every exemption in force has a file with requirements, justification, risk statement, "
               "risk owner and expiry, and a merged pull request",
}
LAB_UMS_5_1 = ("every exemption in force was approved on its final commit by its named risk owner; lab "
               "self-approval allowed the requester to approve, production needs a different person")
RANK = {"fulfilled": 1, "deviation": 2, "unresolved": 3, "not-fulfilled": 4}


# ---------------------------------------------------------------- helpers

def parse_time(value):
    """Parse ISO 8601 with Z or an offset; return None when empty or unreadable."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "." in text:
        head, rest = text.split(".", 1)
        digits = len(rest) - len(rest.lstrip("0123456789"))
        text = f"{head}.{rest[:min(digits, 6)]}{rest[digits:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def stamp(moment):
    return ex.format_utc(moment)


def requirement_key(requirement):
    head, *rest = requirement.split(".")
    return (head, tuple(int(part) if part.isdigit() else -1 for part in rest), requirement)


def uid(*parts):
    return str(uuid.uuid5(UUID_NS, "|".join(parts)))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def resource_name(resource_id):
    return resource_id.rstrip("/").rsplit("/", 1)[-1]


def exemption_scope(exemption_id):
    lowered = exemption_id.lower()
    index = lowered.find(EXEMPTION_MARKER)
    return lowered[:index] if index >= 0 else lowered


# ---------------------------------------------------------------- collect

def normalise_state(item):
    moment = parse_time(item.get("timestamp"))
    state = item.get("complianceState")
    if not state:
        legacy = item.get("isCompliant")
        state = ("Compliant" if legacy else "NonCompliant") if isinstance(legacy, bool) else "Unknown"
    return {
        "resourceId": item.get("resourceId") or "",
        "policyAssignmentName": item.get("policyAssignmentName") or "",
        "policyDefinitionReferenceId": item.get("policyDefinitionReferenceId") or "",
        "policyDefinitionGroupNames": sorted(item.get("policyDefinitionGroupNames") or []),
        "complianceState": state,
        "timestamp": stamp(moment) if moment else "",
    }


def normalise_exemption(item):
    properties = item.get("properties") or {}
    return {
        "name": item.get("name") or "",
        "id": item.get("id") or "",
        "policyAssignmentId": properties.get("policyAssignmentId") or "",
        "policyDefinitionReferenceIds": sorted(properties.get("policyDefinitionReferenceIds") or []),
        "exemptionCategory": properties.get("exemptionCategory") or "",
        "expiresOn": properties.get("expiresOn") or "",
        "metadata": properties.get("metadata") or {},
    }


def collect(resource_groups, repo, folder="exemptions", now=None):
    subscription = ex.run(["az", "account", "show", "--query", "id", "--output", "tsv"]).strip()
    states, exemptions = [], {}
    for group in sorted(set(resource_groups)):
        for item in ex.run_json(["az", "policy", "state", "list", "--resource-group", group, "--output", "json"]) or []:
            states.append(normalise_state(item))
        for item in ex.list_azure_exemptions(subscription, group):
            exemptions[item["id"].lower()] = normalise_exemption(item)
    return {
        "snapshotVersion": SNAPSHOT_VERSION,
        "collectedAt": stamp(now or datetime.now(timezone.utc)),
        "scope": {"resourceGroups": sorted(set(resource_groups))},
        "repository": {"name": repo, "commit": ex.run(["git", "rev-parse", "HEAD"]).strip()},
        "policyStates": sorted(states, key=lambda s: (s["resourceId"].lower(), s["policyAssignmentName"].lower(),
                                                      s["policyDefinitionReferenceId"].lower())),
        "exemptions": [exemptions[key] for key in sorted(exemptions)],
        "pullRequests": ex.fetch_pull_requests(repo, folder),
    }


# ---------------------------------------------------------------- evaluate

class Context:
    """Everything `generate` reads; built once so the evaluation is a pure function of its inputs."""

    def __init__(self, snapshot, documents, references, verbs, scope, as_of, max_age_hours, folder,
                 self_approval=False):
        self.snapshot = snapshot
        self.documents = documents
        self.references = None if references is None else {key.lower(): groups for key, groups in references.items()}
        self.verbs = verbs
        self.scope = scope
        self.as_of = as_of
        self.max_age = timedelta(hours=max_age_hours)
        self.max_age_hours = max_age_hours
        self.folder = folder
        self.self_approval = self_approval
        self.pull_requests = snapshot.get("pullRequests", [])
        self.observations = {}

    def groups_of(self, state):
        reference = state["policyDefinitionReferenceId"].lower()
        if self.references is not None:
            return self.references.get(reference, [])
        return state.get("policyDefinitionGroupNames", [])

    def record_of(self, name):
        return ex.decision_record_for(f"{self.folder}/{name}.json", self.pull_requests)

    def observe(self, key, description, methods, collected, evidence, props=()):
        self.observations[key] = {
            "uuid": uid("observation", key),
            "description": description,
            "props": [prop(name, value) for name, value in props if value],
            "methods": list(methods),
            "collected": collected,
            "relevant-evidence": evidence,
        }
        return self.observations[key]["uuid"]


def prop(name, value):
    return {"name": name, "ns": NS, "value": str(value)}


def match_exemptions(state, exemptions):
    resource = state["resourceId"].lower()
    assignment = "/policyassignments/" + state["policyAssignmentName"].lower()
    reference = state["policyDefinitionReferenceId"].lower()
    for item in sorted(exemptions, key=lambda e: e["name"]):
        scope = exemption_scope(item["id"])
        if not (resource == scope or resource.startswith(scope + "/")):
            continue
        if not item["policyAssignmentId"].lower().endswith(assignment):
            continue
        listed = [r.lower() for r in item["policyDefinitionReferenceIds"]]
        if listed and reference not in listed:
            continue
        yield item


def judge_exempt(context, state):
    """Status of an Exempt policy state: an approved deviation only with a matching, approved file."""
    matched = next(match_exemptions(state, context.snapshot.get("exemptions", [])), None)
    if matched is None:
        return "unresolved", "reported exempt, but no matching exemption is in the snapshot", None
    name = matched["name"]
    expires = parse_time(matched["expiresOn"])
    if expires and expires <= context.as_of:
        return "unresolved", f"exemption {name} expired at {stamp(expires)}; awaiting policy re-evaluation", None
    document = context.documents.get(name)
    if document is None:
        return "not-fulfilled", f"exemption {name} has no file in the exception repository: no decision record", None
    record = context.record_of(name)
    if record is None:
        return "not-fulfilled", f"exemption {name} has no merged pull request: no decision record", None
    errors = ex.decision_errors(document, record["author"], record["headSha"], record["reviews"],
                                context.self_approval)
    if errors:
        return "not-fulfilled", f"exemption {name} lacks an approved decision: {'; '.join(errors)}", None
    expected_refs = {ref.lower() for ref in document.get("policyDefinitionReferenceIds", [])}
    azure_refs = {ref.lower() for ref in matched["policyDefinitionReferenceIds"]}
    if not expected_refs or azure_refs != expected_refs:
        return "not-fulfilled", f"exemption {name}: Azure policy references differ from the approved file", None
    sub = state["resourceId"].strip("/").split("/")
    if len(sub) < 2 or sub[0].lower() != "subscriptions" or not document.get("resourceGroup"):
        return "unresolved", f"exemption {name}: cannot verify its approved resource scope", None
    group = f"/subscriptions/{sub[1]}/resourceGroups/{document['resourceGroup']}"
    assignment = f"{group}/providers/Microsoft.Authorization/policyAssignments/{document.get('policyAssignment', '')}"
    if (exemption_scope(matched["id"]) != ex.exemption_scope(sub[1], document).lower()
            or matched["policyAssignmentId"].lower() != assignment.lower()
            or matched["exemptionCategory"] != document.get("category")):
        return "not-fulfilled", f"exemption {name}: Azure scope, assignment or category differs from the approved file", None
    if context.references is not None:
        if any(not context.references.get(ref) for ref in expected_refs):
            return "unresolved", f"exemption {name}: not every approved reference has known policy groups", None
        groups = {g for ref in expected_refs for g in context.references[ref]}
    elif expected_refs == {state["policyDefinitionReferenceId"].lower()}:
        groups = context.groups_of(state)
    else:
        return "unresolved", f"exemption {name}: the initiative is needed to verify all policy references", None
    if not groups or any(not context.verbs.get(group) for group in groups):
        return "unresolved", f"exemption {name}: no verified modal verb for every policy group", None
    if any(context.verbs[group] != "SOLLTE" or group not in document.get("requirements", []) for group in groups):
        return "not-fulfilled", f"exemption {name}: only explicitly cited SOLLTE groups can be waived", None
    approved = parse_time(document.get("expiresOn"))
    if approved is None or expires is None or expires != approved:
        return "not-fulfilled", f"exemption {name} in Azure does not match the approved expiry in its file", None
    approval = ex.approval_of(document, record["reviews"], context.self_approval)
    deviation = {
        "exemption": name,
        "expiresOn": stamp(expires),
        "decisionRecord": record["url"],
        "approvedBy": approval["user"],
        "category": matched["exemptionCategory"],
    }
    own = " (lab self-approval by the requester)" if approval["user"].lower() == record["author"].lower() else ""
    reason = (f"approved temporary deviation {name} until {stamp(expires)}, "
              f"approved by @{approval['user']}{own} in {record['url']}")
    return "deviation", reason, deviation


def judge_state(context, state):
    moment = parse_time(state.get("timestamp"))
    label = (f"{resource_name(state['resourceId'])} against {state['policyAssignmentName']}/"
             f"{state['policyDefinitionReferenceId']}")
    if moment is None or moment < context.as_of - context.max_age:
        when = stamp(moment) if moment else "an unknown time"
        return "unresolved", f"{label}: evaluated at {when}, older than {context.max_age_hours} hours", None
    compliance = state["complianceState"]
    if compliance == "Compliant":
        return "fulfilled", f"{label}: Compliant", None
    if compliance == "NonCompliant":
        return "not-fulfilled", f"{label}: NonCompliant", None
    if compliance == "Exempt":
        status, reason, deviation = judge_exempt(context, state)
        return status, f"{label}: Exempt; {reason}", deviation
    return "unresolved", f"{label}: state {compliance} is not evidence of fulfilment", None


def state_observation(context, state):
    key = "state|" + "|".join(state[k].lower() for k in
                              ("resourceId", "policyAssignmentName", "policyDefinitionReferenceId"))
    description = (f"Azure Policy evaluated {resource_name(state['resourceId'])} against assignment "
                   f"{state['policyAssignmentName']}, policy {state['policyDefinitionReferenceId']}: "
                   f"{state['complianceState']}.")
    return context.observe(
        key, description, ["TEST"], state.get("timestamp") or context.snapshot["collectedAt"],
        [{"href": "#" + uid("resource", "snapshot"), "description": "Policy state in the snapshot."}],
        [("resource-id", state["resourceId"]), ("policy-assignment", state["policyAssignmentName"]),
         ("policy-reference", state["policyDefinitionReferenceId"]),
         ("compliance-state", state["complianceState"])],
    )


def pr_observation(context, pr):
    outcome = {"MERGED": "merged", "CLOSED": "closed without merge (refused)", "OPEN": "open (pending)"}
    approvals = sorted(review["user"] for review in
                       ex.latest_reviews(pr.get("reviews", []), context.self_approval).values()
                       if review["state"] == "APPROVED")
    files = ", ".join(path.rsplit("/", 1)[-1] for path in pr.get("files", []))
    description = (f"Pull request #{pr['number']} by @{pr['author']}, {outcome.get(pr['state'], pr['state'])}: "
                   f"{files}; approved by {', '.join('@' + a for a in approvals) or 'nobody'}.")
    collected = pr.get("mergedAt") or pr.get("closedAt") or context.snapshot["collectedAt"]
    return context.observe(
        f"pr|{pr['number']}", description, ["EXAMINE"], collected,
        [{"href": pr["url"], "description": f"Decision record: pull request #{pr['number']}."}],
        [("decision-record", pr["url"]), ("pr-state", pr["state"].lower())],
    )


def in_force(context):
    """Names of exemptions in force at as-of: unexpired in Azure or as an approved file."""
    names = set()
    for item in context.snapshot.get("exemptions", []):
        expires = parse_time(item["expiresOn"])
        if expires is None or expires > context.as_of:
            names.add(item["name"])
    for name, document in context.documents.items():
        expires = parse_time(document.get("expiresOn"))
        if expires is not None and expires > context.as_of:
            names.add(name)
    return sorted(names)


def judge_process(context, requirement):
    collected = parse_time(context.snapshot.get("collectedAt"))
    if collected is None or collected < context.as_of - context.max_age:
        return "unresolved", f"pull-request history collected more than {context.max_age_hours} hours ago", [], None
    observations = [pr_observation(context, pr) for pr in context.pull_requests]
    names = in_force(context)
    azure = {item["name"]: item for item in context.snapshot.get("exemptions", [])}
    problems = []
    for name in names:
        document = context.documents.get(name)
        record = context.record_of(name)
        if document is None:
            problems.append(f"{name} is in Azure without a file in the exception repository")
            continue
        if record is None:
            problems.append(f"{name} has no merged pull request")
            continue
        if requirement == "UMS.5.1":
            problems += [f"{name}: {error}" for error in
                         ex.decision_errors(document, record["author"], record["headSha"], record["reviews"],
                                            context.self_approval)]
        else:
            missing = [key for key in ("requirements", "justification", "riskStatement", "riskOwner", "expiresOn")
                       if not document.get(key)]
            if missing:
                problems.append(f"{name} lacks {', '.join(missing)}")
            if name in azure and not azure[name]["expiresOn"]:
                problems.append(f"{name} has no expiry in Azure")
    if not names and not context.pull_requests:
        return "unresolved", "no exemption and no exception pull request to examine", observations, None
    if problems:
        return "not-fulfilled", "; ".join(problems), observations, None
    refused = sum(1 for pr in context.pull_requests if pr["state"] == "CLOSED")
    pending = sum(1 for pr in context.pull_requests if pr["state"] == "OPEN")
    check = LAB_UMS_5_1 if requirement == "UMS.5.1" and context.self_approval else PROCESS[requirement]
    reason = (f"{len(names)} exemption(s) in force and each meets the check ({check}); "
              f"{refused} request(s) refused, {pending} pending")
    return "fulfilled", reason, observations, None


def evaluate(context):
    """Return one result per requirement, sorted by requirement ID."""
    if context.scope is not None:
        entries = {item["id"]: item for item in context.scope.get("requirements", [])}
    else:
        groups = set()
        if context.references is None:
            for state in context.snapshot.get("policyStates", []):
                groups |= set(state.get("policyDefinitionGroupNames", []))
        else:
            for groups_of in context.references.values():
                groups |= set(groups_of)
        entries = {requirement: {"id": requirement, "applicable": True} for requirement in groups | set(PROCESS)}
    states = context.snapshot.get("policyStates", [])
    results = []
    for requirement in sorted(entries, key=requirement_key):
        entry = entries[requirement]
        result = {"id": requirement, "verb": context.verbs.get(requirement, ""), "observations": [],
                  "deviations": [], "applicability_reason": entry.get("reason")}
        if entry.get("applicable") is False:
            result.update(status="not-applicable",
                          reasons=[f"not applicable: {entry.get('reason') or 'no reason given in the scope file'}"])
            results.append(result)
            continue
        if requirement in PROCESS:
            status, reason, observations, _ = judge_process(context, requirement)
            result.update(status=status, reasons=[reason], observations=observations)
            results.append(result)
            continue
        relevant = [s for s in states if requirement in context.groups_of(s)]
        if not relevant:
            result.update(status="unresolved",
                          reasons=["no automated evidence in this snapshot: assess and record it manually"])
            results.append(result)
            continue
        verdicts = []
        for state in relevant:
            status, reason, deviation = judge_state(context, state)
            verdicts.append(status)
            result["reasons"] = result.get("reasons", []) + [reason]
            result["observations"].append(state_observation(context, state))
            if deviation:
                result["deviations"].append(deviation)
        result["status"] = max(verdicts, key=RANK.get)
        if result["status"] != "deviation":
            result["deviations"] = []
        coverage = entry.get("policy_coverage")
        if result["status"] == "fulfilled" and coverage in ("partial", "none"):
            result["status"] = "unresolved"
            gap = "covers only part of this requirement" if coverage == "partial" else "cannot show this requirement"
            result["reasons"].append(f"policy evidence {gap} (policy_coverage {coverage} in the scope file): "
                                     "attest it and record it manually")
        results.append(result)
    return results


# ---------------------------------------------------------------- OSCAL

def gspp_status(status):
    return "not-fulfilled" if status == "deviation" else status


def finding(result):
    status = result["status"]
    state, reason = {
        "fulfilled": ("satisfied", "pass"),
        "not-applicable": ("satisfied", "other"),
        "deviation": ("not-satisfied", "other"),
        "not-fulfilled": ("not-satisfied", "fail"),
        "unresolved": ("not-satisfied", "other"),
    }[status]
    props = [prop("gspp-status", gspp_status(status))]
    if result["verb"]:
        props.append(prop("modal-verb", result["verb"]))
    if result["applicability_reason"]:
        props.append(prop("applicability-reason", result["applicability_reason"]))
    for deviation in sorted(result["deviations"], key=lambda d: d["exemption"]):
        props += [prop("deviation", "approved-temporary"), prop("exemption", deviation["exemption"]),
                  prop("expires-on", deviation["expiresOn"]), prop("decision-record", deviation["decisionRecord"])]
    item = {
        "uuid": uid("finding", result["id"]),
        "title": f"{result['id']} ({result['verb'] or 'verb unknown'}): {gspp_status(status)}",
        "description": " ".join(sorted(set(result["reasons"]))) or "No evidence.",
        "props": props,
        "target": {"type": "objective-id", "target-id": result["id"], "status": {"state": state, "reason": reason}},
    }
    if result["observations"]:
        item["related-observations"] = [{"observation-uuid": u} for u in sorted(set(result["observations"]))]
    return item


def build_pack(context, results, inputs):
    """Assemble the OSCAL document; `inputs` lists (role, href, bytes or None) for the back-matter."""
    digest = sha256("\n".join(f"{role}|{href}|{sha256(data) if data is not None else ''}"
                              for role, href, data in inputs).encode() + stamp(context.as_of).encode())
    method = uid("resource", "method")
    resources = [{
        "uuid": method,
        "title": "Assessment method: requirement-to-evidence kit, evidence generator",
        "description": ("Automated assessment: Azure Policy compliance state per requirement group, and "
                        "exception pull requests for requirements evidenced by a human decision. "
                        f"Evidence older than {context.max_age_hours} hours is unresolved."),
    }]
    for role, href, data in inputs:
        link = {"href": href}
        if data is not None:
            link["hashes"] = [{"algorithm": "SHA-256", "value": sha256(data)}]
        resources.append({"uuid": uid("resource", role), "title": f"Input: {role}", "rlinks": [link]})
    repository = context.snapshot.get("repository", {})
    groups = ", ".join(context.snapshot.get("scope", {}).get("resourceGroups", [])) or "the lab scope"
    observations = sorted(context.observations.values(), key=lambda o: o["uuid"])
    for item in observations:
        if not item["props"]:
            del item["props"]
    as_of = stamp(context.as_of)
    return {
        "assessment-results": {
            "uuid": uid("pack", digest),
            "metadata": {
                "title": f"Requirement evidence for {groups}",
                "last-modified": as_of,
                "version": PACK_VERSION,
                "oscal-version": OSCAL_VERSION,
                "props": [prop("inputs-sha256", digest),
                          prop("repository", repository.get("name") or "unknown"),
                          prop("repository-commit", repository.get("commit") or "unknown")],
            },
            "import-ap": {"href": "#" + method},
            "results": [{
                "uuid": uid("result", digest),
                "title": f"Requirement statuses as of {as_of}",
                "description": (f"Statuses for resource groups {groups}, from a snapshot collected at "
                                f"{context.snapshot.get('collectedAt')}."),
                "start": context.snapshot.get("collectedAt") or as_of,
                "end": as_of,
                "reviewed-controls": {"control-selections": [{
                    "include-controls": [{"control-id": r["id"]} for r in results]}]},
                "observations": observations,
                "findings": [finding(r) for r in results],
            }],
            "back-matter": {"resources": resources},
        }
    }


def summary(context, results):
    repository = context.snapshot.get("repository", {})
    lines = [
        "# Evidence summary",
        "",
        f"As of {stamp(context.as_of)}; snapshot collected {context.snapshot.get('collectedAt')}; repository "
        f"{repository.get('name')} at {str(repository.get('commit'))[:7]}.",
        "",
        "| Requirement | Verb | Status | Deviation | Basis |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        deviation = "; ".join(f"{d['exemption']} until {d['expiresOn']} ([decision]({d['decisionRecord']}))"
                              for d in result["deviations"])
        basis = " ".join(sorted(set(result["reasons"]))).replace("|", "/")
        lines.append(f"| {result['id']} | {result['verb'] or '?'} | {gspp_status(result['status'])} | "
                     f"{deviation or '-'} | {basis} |")
    return "\n".join(lines) + "\n"


def load_documents(directory):
    documents, raw = {}, {}
    for path in ex.exemption_files(directory):
        data = path.read_bytes()
        raw[path] = data
        documents[path.stem] = json.loads(data.decode("utf-8"))
    return documents, raw


def input_ref(path):
    """Name an input relative to the working directory, else by file name: packs carry no local paths."""
    try:
        return Path(path).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return Path(path).name


def generate(snapshot_path, exemptions_dir, initiative_path=None, catalogue_path=None, scope_path=None,
             as_of=None, max_age_hours=DEFAULT_MAX_AGE_HOURS, self_approval=False):
    """Return (pack, summary text, results). Same inputs give the same bytes."""
    snapshot_bytes = Path(snapshot_path).read_bytes()
    snapshot = json.loads(snapshot_bytes.decode("utf-8"))
    if snapshot.get("snapshotVersion") != SNAPSHOT_VERSION:
        raise SystemExit(f"snapshot version {snapshot.get('snapshotVersion')} is not {SNAPSHOT_VERSION}")
    inputs = [("snapshot", input_ref(snapshot_path), snapshot_bytes)]
    initiative = None
    if initiative_path:
        initiative = ex.load_initiative(initiative_path)
        inputs.append(("initiative", input_ref(initiative_path), Path(initiative_path).read_bytes()))
    catalogue = None
    if catalogue_path:
        catalogue = ex.load_catalogue(catalogue_path)
        inputs.append(("catalogue", input_ref(catalogue_path), Path(catalogue_path).read_bytes()))
    verbs, conflicts = ex.merge_verbs(catalogue, initiative)
    if conflicts:
        raise SystemExit("Initiative and pinned catalogue disagree:\n  - " + "\n  - ".join(conflicts))
    scope = None
    if scope_path:
        scope_bytes = Path(scope_path).read_bytes()
        scope = json.loads(scope_bytes.decode("utf-8"))
        inputs.append(("scope", input_ref(scope_path), scope_bytes))
        # The applicability file fills verbs the catalogue and initiative lack; it must not contradict them.
        for item in scope.get("requirements", []):
            verb = item.get("modal_verb")
            if not verb:
                continue
            if verbs.get(item["id"], verb) != verb:
                conflicts.append(f"{item['id']}: the scope file says {verb}, the catalogue or initiative "
                                 f"says {verbs[item['id']]}")
            verbs.setdefault(item["id"], verb)
        if conflicts:
            raise SystemExit("Scope file and verb sources disagree:\n  - " + "\n  - ".join(conflicts))
    documents, raw = load_documents(exemptions_dir)
    for path, data in sorted(raw.items()):
        inputs.append((f"exemption {path.stem}", input_ref(path), data))
    for pr in snapshot.get("pullRequests", []):
        inputs.append((f"pull request {pr['number']}", pr["url"], None))
    moment = parse_time(as_of) if as_of else parse_time(snapshot.get("collectedAt"))
    if moment is None:
        raise SystemExit("no valid --as-of and no collectedAt in the snapshot")
    context = Context(snapshot, documents, initiative["references"] if initiative else None, verbs, scope,
                      moment, max_age_hours, Path(exemptions_dir).name, self_approval)
    results = evaluate(context)
    return build_pack(context, results, inputs), summary(context, results), results


def dump(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def statuses(pack):
    found = {}
    for item in pack["assessment-results"]["results"][0]["findings"]:
        props = {}
        for entry in item.get("props", []):
            props.setdefault(entry["name"], entry["value"])
        found[item["target"]["target-id"]] = (props.get("gspp-status", ""), props.get("deviation", ""),
                                              props.get("expires-on", ""))
    return found


def compare(first, second):
    before, after = statuses(first), statuses(second)
    changes = []
    for requirement in sorted(set(before) | set(after), key=requirement_key):
        old, new = before.get(requirement), after.get(requirement)
        if old != new:
            changes.append((requirement, old, new))
    return changes


# ---------------------------------------------------------------- commands

def command_collect(args):
    config = ex.load_config(args.config)
    groups = args.resource_group or config.get("allowedResourceGroups")
    if not groups:
        raise SystemExit("name the lab resource group with --resource-group or allowedResourceGroups in lab.json")
    repo = args.repo or ex.run_json(["gh", "repo", "view", "--json", "nameWithOwner"])["nameWithOwner"]
    folder = Path(args.exemptions_dir or config.get("exemptionsDir") or "exemptions").name
    snapshot = collect(groups, repo, folder)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(dump(snapshot), encoding="utf-8", newline="\n")
    print(f"Wrote {args.out}: {len(snapshot['policyStates'])} policy states, {len(snapshot['exemptions'])} "
          f"exemptions, {len(snapshot['pullRequests'])} exception pull requests")
    return 0


def command_generate(args):
    config = ex.load_config(args.config)
    catalogue = args.catalogue or ex.find_catalogue(None, config)
    pack, text, results = generate(
        args.snapshot, args.exemptions_dir or config.get("exemptionsDir") or "exemptions",
        args.initiative or config.get("initiative"), catalogue, args.scope, args.as_of, args.max_age_hours,
        bool(config.get("selfApproval")),
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(dump(pack), encoding="utf-8", newline="\n")
    if args.summary:
        Path(args.summary).write_text(text, encoding="utf-8", newline="\n")
    counts = {}
    for result in results:
        counts[gspp_status(result["status"])] = counts.get(gspp_status(result["status"]), 0) + 1
    print(f"Wrote {args.out}: " + ", ".join(f"{counts[key]} {key}" for key in sorted(counts)))
    return 0


def describe(entry):
    if entry is None:
        return "absent"
    status, deviation, expires = entry
    return f"{status} ({deviation} until {expires})" if deviation else status


def command_compare(args):
    first_bytes, second_bytes = Path(args.first).read_bytes(), Path(args.second).read_bytes()
    changes = compare(json.loads(first_bytes), json.loads(second_bytes))
    print("byte-identical" if first_bytes == second_bytes else "files differ in bytes")
    for requirement, old, new in changes:
        print(f"{requirement}: {describe(old)} -> {describe(new)}")
    print(f"{len(changes)} status difference(s)")
    return 1 if changes else 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    collect_parser = sub.add_parser("collect", help="snapshot policy state, exemptions and exception pull requests")
    collect_parser.add_argument("--config")
    collect_parser.add_argument("--resource-group", action="append")
    collect_parser.add_argument("--repo", help="owner/name (default: the current gh repository)")
    collect_parser.add_argument("--exemptions-dir")
    collect_parser.add_argument("--out", default="out/snapshot.json")
    collect_parser.set_defaults(handler=command_collect)

    generate_parser = sub.add_parser("generate", help="write the OSCAL evidence pack from a snapshot")
    generate_parser.add_argument("--snapshot", required=True)
    generate_parser.add_argument("--config")
    generate_parser.add_argument("--exemptions-dir")
    generate_parser.add_argument("--initiative")
    generate_parser.add_argument("--catalogue")
    generate_parser.add_argument("--scope", help="applicability file from challenge 1")
    generate_parser.add_argument("--as-of", help="evaluation time (default: the snapshot's collectedAt)")
    generate_parser.add_argument("--max-age-hours", type=int, default=DEFAULT_MAX_AGE_HOURS)
    generate_parser.add_argument("--out", default="out/evidence.oscal.json")
    generate_parser.add_argument("--summary", help="also write a Markdown table")
    generate_parser.set_defaults(handler=command_generate)

    compare_parser = sub.add_parser("compare", help="list status differences between two packs")
    compare_parser.add_argument("first")
    compare_parser.add_argument("second")
    compare_parser.set_defaults(handler=command_compare)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
