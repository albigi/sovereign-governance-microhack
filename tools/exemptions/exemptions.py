#!/usr/bin/env python3
"""Exemptions as code: validate, gate and apply time-boxed Azure Policy exemptions.

A pull request that adds or changes a file in exemptions/ is the decision record.

  validate   check exemption files against the rules (CI job `validate`)
  decision   check that the named risk owner approved the pull request head (CI job `decision`)
  apply      create the merged, approved, unexpired exemptions in Azure (run on main after merge)
  init-repo  create an exception repository with the workflow, template, tools and lab config

Standard library only. `validate --pr`, `decision` and `apply` call the GitHub CLI (`gh`); `apply`
calls the Azure CLI (`az`). Modal verbs come from the policy initiative's groups and, when present,
the pinned Grundschutz++ catalogue extract; the requester's own claim is never trusted.
"""

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANAGED_BY = "requirement-to-evidence-kit"
EXEMPTION_API = "2022-07-01-preview"
ASSIGNMENT_API = "2023-04-01"
DEFAULT_MAX_DAYS = 90
VERBS = ("MUSS", "SOLLTE", "KANN")

REQUIRED = (
    "id", "title", "requirements", "policyAssignment", "policyDefinitionReferenceIds",
    "resourceGroup", "category", "expiresOn", "riskOwner", "justification", "riskStatement",
)
OPTIONAL = ("$schema", "resource", "compensatingControls")
CATEGORIES = ("Waiver", "Mitigated")
ID_PATTERN = re.compile(r"^exc-[a-z0-9][a-z0-9-]{1,59}$")
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
REQUIREMENT_PATTERN = re.compile(r"^[A-Z]{2,5}\.[0-9]+(?:\.[0-9]+)*$")
RESOURCE_GROUP_PATTERN = re.compile(r"^[-\w.()]{1,90}$")
NAME_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]*"
RESOURCE_PATTERN = re.compile(rf"[A-Za-z][A-Za-z0-9.]+(?:/[A-Za-z0-9]+/{NAME_PATTERN})+")
MIN_TEXT = 20
# GitHub refuses an author's Approve review, so lab self-approval is a Comment review with this first line.
APPROVAL_MARKER = "/approve"


# ---------------------------------------------------------------- inputs

def parse_utc(value):
    """Parse an ISO 8601 UTC time ending in Z; Azure's seven fractional digits are accepted."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("must be an ISO 8601 UTC time ending in Z, e.g. 2026-12-01T00:00:00Z")
    text = value[:-1]
    if "." in text:
        head, fraction = text.split(".", 1)
        text = f"{head}.{fraction[:6]}"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        raise ValueError("must not carry an offset in addition to Z")
    return parsed.replace(tzinfo=timezone.utc)


def format_utc(moment):
    return moment.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_catalogue(path):
    """Requirement ID -> modal verb from the gspp extractor CSV (only `id` and `modal_verb` are read)."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {row["id"]: row["modal_verb"] for row in csv.DictReader(handle)}


def load_initiative(path):
    """Read a policy set definition (ARM shape or bare `properties`).

    Contract: each policyDefinitionGroups entry is named by a requirement ID and carries its modal verb
    in `category`; each policy's groupNames lists every requirement it implements, including an
    obligation that makes it binding.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    properties = data.get("properties", data)
    verbs = {group["name"]: group.get("category", "") for group in properties.get("policyDefinitionGroups", [])}
    references = {
        item["policyDefinitionReferenceId"]: list(item.get("groupNames", []))
        for item in properties.get("policyDefinitions", [])
    }
    return {"verbs": verbs, "references": references}


def merge_verbs(catalogue, initiative):
    """Combine the two verb sources; the pinned catalogue wins and every disagreement is reported."""
    verbs = dict(initiative["verbs"]) if initiative else {}
    conflicts = []
    if catalogue:
        for requirement, verb in sorted(verbs.items()):
            if requirement in catalogue and catalogue[requirement] != verb:
                conflicts.append(
                    f"initiative group {requirement} says {verb or 'no verb'}, "
                    f"the pinned catalogue says {catalogue[requirement]}"
                )
        verbs.update(catalogue)
    return verbs, conflicts


def find_catalogue(explicit=None, config=None):
    candidates = [Path(explicit)] if explicit else []
    if config and config.get("catalogue"):
        candidates.append(Path(config["catalogue"]))
    candidates += [HERE / "out" / "gspp-extract.csv", HERE.parent / "gspp" / "out" / "gspp-extract.csv"]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def load_verbs(args, config):
    """Return the initiative's references and verbs, cross-checked with the optional catalogue."""
    catalogue_path = find_catalogue(getattr(args, "catalogue", None), config)
    initiative_path = getattr(args, "initiative", None) or config.get("initiative")
    if not initiative_path:
        raise SystemExit("use --initiative or lab.json to identify the challenge 2 policy set; "
                         "the catalogue alone does not identify the groups behind a policy")
    catalogue = load_catalogue(catalogue_path) if catalogue_path else None
    initiative = load_initiative(initiative_path)
    if not initiative["references"]:
        raise SystemExit("the initiative contains no policy references")
    verbs, conflicts = merge_verbs(catalogue, initiative)
    if conflicts:
        raise SystemExit("Initiative and pinned catalogue disagree:\n  - " + "\n  - ".join(conflicts))
    if catalogue is None:
        print("note: no pinned catalogue extract found; modal verbs come from the initiative groups only")
    return verbs, initiative["references"]


def load_config(path):
    """Read lab.json (default ./lab.json if present); relative paths in it resolve against its folder."""
    if path is None:
        if not Path("lab.json").is_file():
            return {}
        path = "lab.json"
    path = Path(path)
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in ("exemptionsDir", "initiative", "catalogue"):
        if config.get(key):
            config[key] = str((path.parent / config[key]).resolve())
    return config


def load_exemption(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- rules

def _text(doc, key, minimum=1):
    value = doc.get(key)
    return isinstance(value, str) and len(value.strip()) >= minimum


def validate_exemption(doc, stem, verbs, now=None, max_days=DEFAULT_MAX_DAYS,
                       allowed_resource_groups=None, references=None):
    """Return the rule violations of one exemption file; an empty list means it may be proposed."""
    if not isinstance(doc, dict):
        return ["the file must hold one JSON object"]
    errors = []
    missing = [key for key in REQUIRED if doc.get(key) in (None, "", [])]
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")
    unknown = sorted(set(doc) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    if missing:
        return errors

    if doc["id"] != stem:
        errors.append(f"id {doc['id']!r} must equal the file name {stem!r}")
    if not ID_PATTERN.match(str(doc["id"])):
        errors.append("id must look like exc-<lowercase-words> (at most 64 characters)")
    if not _text(doc, "title") or len(doc["title"]) > 128:
        errors.append("title must be 1 to 128 characters (Azure display-name limit)")

    policy_references = doc["policyDefinitionReferenceIds"]
    if not isinstance(policy_references, list) or not all(isinstance(r, str) and r for r in policy_references):
        errors.append("policyDefinitionReferenceIds must list reference IDs from the initiative")
        policy_references = []
    requirements = doc["requirements"]
    if not isinstance(requirements, list) or not all(isinstance(r, str) for r in requirements):
        errors.append("requirements must be a list of requirement IDs")
        requirements = []
    claimed = set(requirements)
    checked = set(claimed)
    if references is not None:
        for reference in policy_references:
            if reference not in references:
                errors.append(f"policy reference {reference!r} is not in the initiative")
                continue
            derived = {group for group in references[reference] if REQUIREMENT_PATTERN.fullmatch(group)}
            if not derived or len(derived) != len(set(references[reference])):
                errors.append(f"policy reference {reference!r} must have identified requirement groups")
            hidden = sorted(derived - claimed)
            if hidden:
                errors.append(
                    f"policy reference {reference!r} also implements {', '.join(hidden)}: "
                    "name every requirement the exemption deviates from"
                )
            checked |= derived
    for requirement in sorted(checked):
        verb = verbs.get(requirement)
        if verb is None:
            errors.append(f"{requirement} is not a known requirement ID")
        elif verb == "MUSS":
            errors.append(
                f"{requirement} is MUSS: no exception or risk acceptance is possible; fix the resource instead"
            )
        elif verb == "KANN":
            errors.append(
                f"{requirement} is KANN (optional): no exemption is needed; change the archetype selection "
                "by a reviewed pull request instead"
            )
        elif verb != "SOLLTE":
            errors.append(f"{requirement} has unexpected modal verb {verb!r}")

    now = now or datetime.now(timezone.utc)
    try:
        expires = parse_utc(doc["expiresOn"])
    except (TypeError, ValueError) as error:
        errors.append(f"expiresOn {error}")
    else:
        if expires <= now:
            errors.append(f"expiresOn {doc['expiresOn']} is not in the future")
        elif expires > now + timedelta(days=max_days):
            errors.append(f"expiresOn is more than {max_days} days ahead; renew later with a new pull request")

    if doc["category"] not in CATEGORIES:
        errors.append(f"category must be one of {', '.join(CATEGORIES)}")
    controls = doc.get("compensatingControls", [])
    if not isinstance(controls, list) or not all(isinstance(c, str) and c.strip() for c in controls):
        errors.append("compensatingControls must be a list of non-empty strings")
    elif doc["category"] == "Mitigated" and not controls:
        errors.append("category Mitigated needs at least one compensating control")

    group = doc["resourceGroup"]
    if not isinstance(group, str) or not RESOURCE_GROUP_PATTERN.match(group):
        errors.append("resourceGroup must be a resource group name (no subscription path)")
    elif allowed_resource_groups and group.lower() not in {g.lower() for g in allowed_resource_groups}:
        errors.append(f"resourceGroup {group!r} is outside the allowed lab scope")
    if not isinstance(doc["policyAssignment"], str) or not re.fullmatch(NAME_PATTERN, doc["policyAssignment"]):
        errors.append("policyAssignment must be an assignment name inside the lab resource group")
    if "resource" in doc and not (isinstance(doc["resource"], str) and RESOURCE_PATTERN.fullmatch(doc["resource"])):
        errors.append("resource must look like Microsoft.Storage/storageAccounts/<name>")
    if not isinstance(doc["riskOwner"], str) or not LOGIN_PATTERN.match(doc["riskOwner"]):
        errors.append("riskOwner must be the GitHub login of the person who approves")
    for key in ("justification", "riskStatement"):
        if not _text(doc, key, MIN_TEXT):
            errors.append(f"{key} must be at least {MIN_TEXT} characters")
    return errors


def approval_marked(body):
    lines = str(body or "").strip().splitlines()
    return bool(lines) and lines[0].strip().lower() == APPROVAL_MARKER


def latest_reviews(reviews, self_approval=False):
    """Latest state-changing review per user (lower-cased login); plain comments change nothing.

    With lab self-approval, a Comment review whose first line is /approve counts as an approval.
    """
    latest = {}
    for review in sorted(reviews, key=lambda r: r.get("submittedAt") or ""):
        state = review.get("state")
        if self_approval and state == "COMMENTED" and approval_marked(review.get("body")):
            state = "APPROVED"
        if state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[str(review.get("user", "")).lower()] = dict(review, state=state)
    return latest


def approval_of(doc, reviews, self_approval=False):
    review = latest_reviews(reviews, self_approval).get(str(doc.get("riskOwner", "")).lower())
    return review if review and review["state"] == "APPROVED" else None


def decision_errors(doc, author, head_sha, reviews, self_approval=False):
    """Four-eyes rule: the named risk owner, who is not the author, approved the current head commit.

    Lab self-approval (selfApproval in lab.json) lets the author be the risk owner, so one account can run
    the lab; production keeps a different person.
    """
    owner = str(doc.get("riskOwner", ""))
    if not owner:
        return ["no riskOwner named"]
    if owner.lower() == str(author).lower() and not self_approval:
        return [f"risk owner @{owner} opened the pull request: a different person must approve"]
    review = approval_of(doc, reviews, self_approval)
    if review is None:
        how = f": submit a Comment review whose first line is {APPROVAL_MARKER}" if self_approval else ""
        return [f"awaiting approval by risk owner @{owner}{how}"]
    if review.get("commitId") != head_sha:
        return [
            f"@{owner} approved commit {str(review.get('commitId'))[:7]}, not the current head "
            f"{str(head_sha)[:7]}: approve again"
        ]
    return []


def decision_record_for(path, pull_requests):
    """Latest merged pull request that changed the file: the exemption's decision record."""
    merged = [pr for pr in pull_requests if pr.get("state") == "MERGED" and path in pr.get("files", [])]
    return max(merged, key=lambda pr: pr.get("mergedAt") or "", default=None)


# ---------------------------------------------------------------- external tools

def run(command):
    executable = shutil.which(command[0])
    if executable is None:
        raise SystemExit(f"{command[0]} not found on PATH")
    result = subprocess.run(
        [executable, *command[1:]], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout


def run_json(command):
    output = run(command)
    return json.loads(output) if output.strip() else None


def fetch_reviews(repo, number):
    output = run([
        "gh", "api", f"repos/{repo}/pulls/{number}/reviews", "--paginate", "--jq",
        ".[] | {user: .user.login, state: .state, commitId: .commit_id, submittedAt: .submitted_at, body: .body}",
    ])
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def fetch_pull_requests(repo, folder="exemptions", limit=500):
    """Pull requests that touched the exemptions folder, normalised, with their reviews."""
    prefix = folder.strip("/") + "/"
    items = run_json([
        "gh", "pr", "list", "--repo", repo, "--state", "all", "--limit", str(limit), "--json",
        "number,title,url,author,state,mergedAt,closedAt,headRefOid,files",
    ]) or []
    result = []
    for item in items:
        files = sorted(f["path"] for f in item.get("files") or [])
        if not any(path.startswith(prefix) for path in files):
            continue
        result.append({
            "number": item["number"],
            "title": item["title"],
            "url": item["url"],
            "author": (item.get("author") or {}).get("login", ""),
            "state": item["state"],
            "mergedAt": item.get("mergedAt") or "",
            "closedAt": item.get("closedAt") or "",
            "headSha": item["headRefOid"],
            "files": files,
            "reviews": fetch_reviews(repo, item["number"]),
        })
    return sorted(result, key=lambda pr: pr["number"])


def list_azure_exemptions(subscription, resource_group):
    """Exemptions on the group, on resources inside it and on containing scopes (subscription, management group)."""
    url = (f"/subscriptions/{subscription}/resourceGroups/{resource_group}/providers/"
           f"Microsoft.Authorization/policyExemptions?api-version={EXEMPTION_API}")
    return (run_json(["az", "rest", "--method", "get", "--url", url]) or {}).get("value", [])


# ---------------------------------------------------------------- commands

def exemption_files(directory):
    return sorted(Path(directory).glob("exc-*.json"))


def shown(path):
    """Print a path relative to the working directory when it lies inside it."""
    try:
        return Path(path).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def settings(args, config):
    directory = Path(getattr(args, "exemptions_dir", None) or config.get("exemptionsDir") or "exemptions")
    allowed = getattr(args, "resource_group", None) or config.get("allowedResourceGroups")
    max_days = getattr(args, "max_days", None) or config.get("maxDays") or DEFAULT_MAX_DAYS
    return directory, allowed, max_days


def validation_inputs(args):
    config = load_config(args.config)
    directory, allowed, max_days = settings(args, config)
    if not allowed:
        raise SystemExit("use --resource-group or allowedResourceGroups in lab.json to identify the lab scope")
    verbs, references = load_verbs(args, config)
    return directory, allowed, max_days, verbs, references


def command_validate(args):
    directory, allowed, max_days, verbs, references = validation_inputs(args)
    now = parse_utc(args.as_of) if args.as_of else None
    if args.pr:
        pr = run_json(["gh", "pr", "view", str(args.pr), "--repo", args.repo, "--json", "files"])
        changed = [Path(f["path"]) for f in pr["files"]]
        files = [p for p in changed if p.parent.name == directory.name and p.suffix == ".json" and p.is_file()]
    elif args.files:
        files = [Path(f) for f in args.files]
    else:
        files = exemption_files(directory)
    failed = 0
    for path in files:
        try:
            doc = load_exemption(path)
        except (OSError, json.JSONDecodeError) as error:
            errors = [f"cannot read JSON: {error}"]
        else:
            errors = validate_exemption(doc, path.stem, verbs, now=now, max_days=max_days,
                                        allowed_resource_groups=allowed, references=references)
        if errors:
            failed += 1
            print(f"REFUSED {shown(path)}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"PASS    {shown(path)}")
    if not files:
        print("no exemption files to check")
    return 1 if failed else 0


def command_decision(args):
    pr = run_json(["gh", "pr", "view", str(args.pr), "--repo", args.repo, "--json", "author,headRefOid,files"])
    reviews = fetch_reviews(args.repo, args.pr)
    config = load_config(args.config)
    directory, _, _ = settings(args, config)
    self_approval = bool(config.get("selfApproval"))
    author = pr["author"]["login"]
    failed = checked = 0
    for item in pr["files"]:
        path = Path(item["path"])
        if path.parent.name != directory.name or path.suffix != ".json":
            continue
        if not path.is_file():
            print(f"WITHDRAWN {path.as_posix()} (removing an exemption needs no risk-owner approval)")
            continue
        checked += 1
        errors = decision_errors(load_exemption(path), author, pr["headRefOid"], reviews, self_approval)
        if errors:
            failed += 1
            print(f"WAITING  {path.as_posix()}: {'; '.join(errors)}")
        else:
            lab = " (lab self-approval)" if self_approval else ""
            print(f"APPROVED {path.as_posix()} by its risk owner on {pr['headRefOid'][:7]}{lab}")
    if not checked:
        print("no added or changed exemption files")
    return 1 if failed else 0


def exemption_body(doc, assignment_id, record, approval):
    metadata = {
        "managedBy": MANAGED_BY,
        "requirements": ",".join(doc["requirements"]),
        "riskOwner": doc["riskOwner"],
        "decisionRecord": record["url"],
        "requestedBy": record["author"],
        "approvedBy": approval["user"],
        "approvedOn": approval.get("submittedAt") or "",
    }
    if str(approval["user"]).lower() == str(record["author"]).lower():
        metadata["approvalMode"] = "lab-self-approval"
    return {
        "properties": {
            "displayName": doc["title"],
            "description": doc["justification"][:512],
            "metadata": metadata,
            "policyAssignmentId": assignment_id,
            "policyDefinitionReferenceIds": doc["policyDefinitionReferenceIds"],
            "exemptionCategory": doc["category"],
            "expiresOn": doc["expiresOn"],
        }
    }


def exemption_scope(subscription, doc):
    scope = f"/subscriptions/{subscription}/resourceGroups/{doc['resourceGroup']}"
    if doc.get("resource"):
        scope += f"/providers/{doc['resource']}"
    return scope


def resolve_assignment(subscription, doc):
    scope = f"/subscriptions/{subscription}/resourceGroups/{doc['resourceGroup']}"
    url = f"{scope}/providers/Microsoft.Authorization/policyAssignments/{doc['policyAssignment']}"
    run(["az", "rest", "--method", "get", "--url", f"{url}?api-version={ASSIGNMENT_API}"])
    return url


def plan_apply(files, pull_requests, verbs, references, now, max_days, allowed, folder="exemptions",
               self_approval=False):
    """Decide offline which files may become Azure exemptions: (to_apply, expired, refused)."""
    to_apply, expired, refused = [], [], []
    for path in files:
        doc = load_exemption(path)
        try:
            if parse_utc(doc.get("expiresOn", "")) <= now:
                expired.append(doc)
                continue
        except ValueError:
            pass
        errors = validate_exemption(doc, path.stem, verbs, now=now, max_days=max_days,
                                    allowed_resource_groups=allowed, references=references)
        record = decision_record_for(f"{folder}/{path.name}", pull_requests)
        if record is None:
            errors.append("no merged pull request changed this file: no decision record")
        else:
            errors += decision_errors(doc, record["author"], record["headSha"], record["reviews"], self_approval)
        if errors:
            refused.append((doc, errors))
        else:
            to_apply.append((doc, record, approval_of(doc, record["reviews"], self_approval)))
    return to_apply, expired, refused


def prunable(items, subscription, resource_group, keep):
    """Kit-managed exemptions inside the group that main no longer approves; never one on a containing scope."""
    prefix = f"/subscriptions/{subscription}/resourcegroups/{resource_group}/".lower()
    return [
        item for item in items
        if str(item.get("id", "")).lower().startswith(prefix)
        and ((item.get("properties") or {}).get("metadata") or {}).get("managedBy") == MANAGED_BY
        and item.get("name") not in keep
    ]


def command_apply(args):
    directory, allowed, max_days, verbs, references = validation_inputs(args)
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if branch != "main" and not args.dry_run:
        raise SystemExit(f"apply runs from main only (current branch: {branch})")
    repo = args.repo or run_json(["gh", "repo", "view", "--json", "nameWithOwner"])["nameWithOwner"]
    pull_requests = fetch_pull_requests(repo, directory.name)
    subscription = "{subscription}" if args.dry_run else run(
        ["az", "account", "show", "--query", "id", "--output", "tsv"]
    ).strip()
    to_apply, expired, refused = plan_apply(
        exemption_files(directory), pull_requests, verbs, references,
        datetime.now(timezone.utc), max_days, allowed, directory.name,
        bool(load_config(args.config).get("selfApproval")),
    )
    for doc in expired:
        print(f"EXPIRED  {doc['id']}: not created (Azure keeps an expired exemption as a record only)")
    for doc, errors in refused:
        print(f"REFUSED  {doc.get('id')}")
        for error in errors:
            print(f"  - {error}")
    for doc, record, approval in to_apply:
        if args.dry_run:
            assignment_id = f"/subscriptions/{subscription}/.../policyAssignments/{doc['policyAssignment']}"
        else:
            assignment_id = resolve_assignment(subscription, doc)
        body = exemption_body(doc, assignment_id, record, approval)
        url = (f"{exemption_scope(subscription, doc)}/providers/Microsoft.Authorization/policyExemptions/"
               f"{doc['id']}?api-version={EXEMPTION_API}")
        if args.dry_run:
            print(f"DRY-RUN  PUT {url}\n{json.dumps(body, indent=2)}")
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(body, handle)
        try:
            run(["az", "rest", "--method", "put", "--url", url, "--body", f"@{handle.name}"])
        finally:
            Path(handle.name).unlink(missing_ok=True)
        print(f"APPLIED  {doc['id']} (decision {record['url']}, expires {doc['expiresOn']})")
    if args.prune and not args.dry_run:
        wanted = {doc["id"] for doc, _, _ in to_apply}
        for group in sorted(set(allowed or [])):
            for item in prunable(list_azure_exemptions(subscription, group), subscription, group, wanted):
                run(["az", "rest", "--method", "delete", "--url", f"{item['id']}?api-version={EXEMPTION_API}"])
                print(f"PRUNED   {item['name']} (no longer approved and unexpired in main)")
    return 1 if refused else 0


def command_init_repo(args):
    target = Path(args.target).resolve()
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty")
    kit = HERE.parent.parent
    resources = kit / "resources" / "exemptions"
    copies = {
        HERE / "exemptions.py": "tools/exemptions.py",
        HERE / "evidence.py": "tools/evidence.py",
        kit / "tools" / "gspp" / "extract.py": "tools/gspp_extract.py",
        resources / "exemption-check.yml": ".github/workflows/exemption-check.yml",
        resources / "pull_request_template.md": ".github/pull_request_template.md",
        resources / "exemption.schema.json": "schema/exemption.schema.json",
        Path(args.initiative): "policy/initiative.json",
    }
    # The extractor reads its catalogue pin from a catalogue-mapping.json next to itself.
    pin = kit / "resources" / "catalogue-mapping.json"
    if pin.is_file():
        copies[pin] = "tools/catalogue-mapping.json"
    for source, relative in copies.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (target / "exemptions").mkdir(exist_ok=True)
    (target / "exemptions" / ".gitkeep").write_text("", encoding="utf-8")
    config = {
        "exemptionsDir": "exemptions",
        "allowedResourceGroups": args.resource_group,
        "maxDays": args.max_days,
        "selfApproval": args.self_approval,
        "initiative": "policy/initiative.json",
        "catalogue": "tools/out/gspp-extract.csv",
    }
    (target / "lab.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (target / ".gitignore").write_text("tools/out/\nout/\n__pycache__/\n", encoding="utf-8")
    approver = (
        "risk owner. Lab self-approval is on (`selfApproval` in `lab.json`): the requester may be the risk\n"
        f"owner and approves with a Comment review whose first line is `{APPROVAL_MARKER}`. Production needs a\n"
        "different person.\n"
        if args.self_approval else "risk owner, who must not be the requester.\n"
    )
    (target / "README.md").write_text(
        "# Exception repository\n\n"
        "Each file in `exemptions/` is a time-boxed Azure Policy exemption. The pull request that adds it is\n"
        "the decision record: CI job `validate` applies the rules and CI job `decision` waits for the named\n"
        + approver +
        "After merge, run `python tools/exemptions.py apply` on `main`.\n"
        "This repository holds no subscription or tenant IDs.\n",
        encoding="utf-8",
    )
    print(f"Created {target}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--config", help="lab.json (default: ./lab.json if present)")
        p.add_argument("--catalogue", help="pinned catalogue extract CSV from the gspp extractor")
        p.add_argument("--initiative", help="policy set definition JSON from challenge 2")
        p.add_argument("--exemptions-dir")
        p.add_argument("--resource-group", action="append", help="allowed lab resource group (repeatable)")
        p.add_argument("--max-days", type=int)

    validate = sub.add_parser("validate", help="check exemption files against the rules")
    common(validate)
    validate.add_argument("files", nargs="*")
    validate.add_argument("--pr", type=int, help="check only the files this pull request adds or changes")
    validate.add_argument("--repo", help="owner/name, with --pr")
    validate.add_argument("--as-of", help="evaluate expiry as of this UTC time (default: now)")
    validate.set_defaults(handler=command_validate)

    decision = sub.add_parser("decision", help="check the risk owner's approval of a pull request")
    decision.add_argument("--pr", type=int, required=True)
    decision.add_argument("--repo", required=True)
    decision.add_argument("--config")
    decision.add_argument("--exemptions-dir")
    decision.set_defaults(handler=command_decision)

    apply = sub.add_parser("apply", help="create approved, unexpired exemptions in Azure (from main)")
    common(apply)
    apply.add_argument("--repo", help="owner/name (default: the current gh repository)")
    apply.add_argument("--dry-run", action="store_true", help="print the requests and change nothing")
    apply.add_argument("--prune", action="store_true", help="delete kit-managed exemptions no longer approved")
    apply.set_defaults(handler=command_apply)

    init = sub.add_parser("init-repo", help="create an exception repository folder")
    init.add_argument("target")
    init.add_argument("--resource-group", action="append", required=True, help="lab resource group (repeatable)")
    init.add_argument("--initiative", required=True, help="policy set definition JSON from challenge 2")
    init.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS)
    init.add_argument("--self-approval", action="store_true",
                      help="lab only: let the requester approve as risk owner, so one account can run the lab")
    init.set_defaults(handler=command_init_repo)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
