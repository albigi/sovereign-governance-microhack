#!/usr/bin/env python3
"""Decide which mapped Grundschutz++ requirements apply to one application.

Reads resources/catalogue-mapping.json, resources/archetypes.json and an
application profile from resources/profiles/. Writes the result as JSON to
tools/gspp/out/ and prints it as a Markdown table. The rule is deterministic:

1. The profile must satisfy the constraints of its archetype.
2. An elevated-level requirement applies only when the protection need is high.
3. Every applies_when condition of the requirement must hold for the profile.
4. Candidate controls are kept when they fit the application's resource types
   ('*' fits all) and, if they name archetypes, the profile's archetype.
"""

import argparse
import json
import os
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
KIT = TOOLS.parents[1]
RESOURCES = KIT / "resources"
MAPPING = RESOURCES / "catalogue-mapping.json"
ARCHETYPES = RESOURCES / "archetypes.json"
PROFILES = RESOURCES / "profiles"
OUT = TOOLS / "out"
SCHEMA_VERSION = "1.0.0"
NOTICE = "Candidate result from a candidate mapping. It is not a compliance statement."
PROFILE_FACTS = (
    "id", "name", "archetype", "protection_need", "data_classification",
    "internet_facing", "stores_data", "personal_data", "resource_types",
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def profile_path(value):
    """Accept a profile file path or the id of a profile in resources/profiles/."""
    path = Path(value)
    if path.suffix != ".json" and len(path.parts) == 1:
        return PROFILES / f"{value}.json"
    return path


def archetype_for(profile, archetypes):
    """Return the profile's archetype; raise ValueError if the profile breaks its constraints."""
    missing = [fact for fact in PROFILE_FACTS if fact not in profile]
    if missing:
        raise ValueError(f"Profile is missing {', '.join(missing)}")
    by_id = {archetype["id"]: archetype for archetype in archetypes["archetypes"]}
    archetype = by_id.get(profile["archetype"])
    if archetype is None:
        raise ValueError(f"Profile {profile['id']}: unknown archetype {profile['archetype']!r}; expected one of {', '.join(by_id)}")
    for fact, allowed in archetype["constraints"].items():
        if profile[fact] not in allowed:
            raise ValueError(
                f"Profile {profile['id']} breaks archetype {archetype['id']}: "
                f"{fact} is {json.dumps(profile[fact])}, allowed {json.dumps(allowed)}"
            )
    return archetype


def holds(condition, profile):
    value = profile[condition["fact"]]
    if "equals" in condition:
        return value == condition["equals"]
    if "any_of" in condition:
        return value in condition["any_of"]
    wanted = {item.lower() for item in condition["includes_any"]}
    return any(item.lower() in wanted for item in value)


def describe(condition, profile):
    fact = condition["fact"]
    if "includes_any" in condition:
        wanted = {item.lower() for item in condition["includes_any"]}
        found = [item for item in profile[fact] if item.lower() in wanted]
        return f"{fact} include {', '.join(found)}"
    return f"{fact} is {json.dumps(profile[fact])}"


def decide(requirement, profile):
    """Return (applicable, reason) for one requirement."""
    reasons = []
    if requirement["security_level"] == "elevated":
        if profile["protection_need"] != "high":
            return False, "Elevated-level requirement; the protection need is normal."
        reasons.append("elevated-level requirement and the protection need is high")
    for condition in requirement["applies_when"]:
        if not holds(condition, profile):
            return False, condition["otherwise"]
        reasons.append(describe(condition, profile))
    if not reasons:
        return True, "Applies to every application."
    reason = "; ".join(reasons)
    return True, reason[0].upper() + reason[1:] + "."


def fits(control, profile):
    archetypes = control.get("archetypes")
    if archetypes and profile["archetype"] not in archetypes:
        return False
    types = control.get("resource_types")
    if not types or "*" in types:
        return True
    own = {item.lower() for item in profile["resource_types"]}
    return any(item.lower() in own for item in types)


def policy_coverage(requirement, controls):
    if not any(control["kind"] == "policy-definition" for control in controls):
        return "none"
    return "full" if requirement["checkable"] == "yes" else "partial"


def evaluate(mapping, archetypes, profile):
    archetype = archetype_for(profile, archetypes)
    rows = []
    for requirement in mapping["requirements"]:
        applicable, reason = decide(requirement, profile)
        controls = [control for control in requirement["controls"] if fits(control, profile)] if applicable else []
        rows.append({
            "id": requirement["id"],
            "applicable": applicable,
            "reason": reason,
            "modal_verb": requirement["modal_verb"],
            "security_level": requirement["security_level"],
            "theme": requirement["theme"],
            "route": requirement["route"],
            "checkable": requirement["checkable"],
            "policy_coverage": policy_coverage(requirement, controls) if applicable else None,
            "deviation_path": requirement["deviation_path"],
            "owner": requirement["owner"],
            "controls": controls,
            "evidence": requirement["evidence"],
            "gap": requirement["gap"],
        })
    applicable_rows = [row for row in rows if row["applicable"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "candidate",
        "notice": NOTICE,
        "catalogue": {"revision": mapping["catalogue"]["revision"], "sha256": mapping["catalogue"]["sha256"]},
        "mapping": {"schema_version": mapping["schema_version"], "checked": mapping["checked"]},
        "profile": {key: value for key, value in profile.items() if key != "$schema"},
        "archetype": {"id": archetype["id"], "title": archetype["title"], "parameters": archetype["parameters"]},
        "summary": {
            "requirements": len(rows),
            "applicable": len(applicable_rows),
            "not_applicable": len(rows) - len(applicable_rows),
            "policy_coverage": {
                level: sum(row["policy_coverage"] == level for row in applicable_rows)
                for level in ("full", "partial", "none")
            },
        },
        "requirements": rows,
    }


def control_label(control):
    label = control["name"]
    if control["kind"] == "policy-definition":
        label = f"Policy: {label}"
    if control.get("requires_paid_plan"):
        label += " (paid)"
    return label


def markdown(result):
    profile = result["profile"]
    summary = result["summary"]
    lines = [
        f"## {profile['name']} ({result['archetype']['title']}, protection need {profile['protection_need']})",
        "",
        f"{summary['applicable']} of {summary['requirements']} mapped requirements apply. "
        f"Azure Policy coverage: full {summary['policy_coverage']['full']}, "
        f"partial {summary['policy_coverage']['partial']}, none {summary['policy_coverage']['none']}.",
        "",
        "| Requirement | Verb | Level | Route | Policy coverage | Candidate controls |",
        "|---|---|---|---|---|---|",
    ]
    for row in result["requirements"]:
        if row["applicable"]:
            controls = "; ".join(control_label(control) for control in row["controls"])
            lines.append(
                f"| {row['id']} | {row['modal_verb']} | {row['security_level']} | {row['route']} "
                f"| {row['policy_coverage']} | {controls} |"
            )
    lines += ["", "| Not applicable | Verb | Level | Reason |", "|---|---|---|---|"]
    for row in result["requirements"]:
        if not row["applicable"]:
            lines.append(f"| {row['id']} | {row['modal_verb']} | {row['security_level']} | {row['reason']} |")
    return "\n".join(lines) + "\n"


def write(result, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def shown(path):
    try:
        return os.path.relpath(path)
    except ValueError:
        return str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--profile", help="Profile id from resources/profiles/ (for example leave-planner) or a path to a profile file")
    target.add_argument("--all", action="store_true", help="Evaluate every profile in resources/profiles/")
    parser.add_argument("--output", type=Path, help="Output file (default tools/gspp/out/applicability-<profile id>.json)")
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--archetypes", type=Path, default=ARCHETYPES)
    args = parser.parse_args()
    if args.all and args.output:
        parser.error("--output works with --profile only")
    mapping = load_json(args.mapping)
    archetypes = load_json(args.archetypes)
    paths = sorted(PROFILES.glob("*.json")) if args.all else [profile_path(args.profile)]
    for path in paths:
        result = evaluate(mapping, archetypes, load_json(path))
        output = args.output or OUT / f"applicability-{result['profile']['id']}.json"
        write(result, output)
        if args.all:
            summary = result["summary"]
            print(
                f"{result['profile']['id']}: {summary['applicable']} of {summary['requirements']} apply "
                f"(policy coverage full {summary['policy_coverage']['full']}, partial {summary['policy_coverage']['partial']}, "
                f"none {summary['policy_coverage']['none']}) -> {shown(output)}"
            )
        else:
            print(markdown(result))
            print(f"Wrote {shown(output)}")


if __name__ == "__main__":
    main()
