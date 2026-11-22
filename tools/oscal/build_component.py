#!/usr/bin/env python3
"""Generate the Azure OSCAL component definition from the catalogue mapping.

resources/catalogue-mapping.json is the single source; the component is derived
from it and never edited by hand. The output is deterministic: UUIDs are
name-based (version 5) and last-modified is the mapping's checked date. Run with
--check to fail when the committed file is out of date.
"""

import argparse
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import quote


TOOLS = Path(__file__).resolve().parent
KIT = TOOLS.parents[1]
MAPPING = KIT / "resources" / "catalogue-mapping.json"
OUTPUT = KIT / "resources" / "azure-component-definition.json"
NS = "urn:microhack:sovereign-governance"
ROOT = uuid.uuid5(uuid.NAMESPACE_URL, NS)
OSCAL_VERSION = "1.1.3"
VERSION = "0.1.0"

COMPONENTS = (
    ("policy-definition", "azure-policy", "service", "Azure Policy",
     "Evaluates Azure resource configuration against built-in policy definitions and audits, denies or remediates it.",
     "Checks the requirements that resource configuration can show."),
    ("entra", "microsoft-entra-id", "service", "Microsoft Entra ID",
     "Identity provider: Conditional Access, Privileged Identity Management and audit logs.",
     "Enforces sign-in and privileged-access requirements that resource configuration cannot show."),
    ("platform", "azure-platform", "service", "Azure platform defaults",
     "Behaviour Azure services provide without extra configuration, such as encryption at rest with platform-managed keys, automated database backups and the Azure Resource Graph inventory.",
     "Covers requirements that the services meet by default."),
    ("defender", "microsoft-defender-for-cloud", "service", "Microsoft Defender for Cloud",
     "Security posture management and vulnerability findings. Optional: the findings used here need a paid plan.",
     "Adds technical evidence for vulnerability requirements where a plan is enabled."),
    ("purview", "microsoft-purview", "service", "Microsoft Purview",
     "Data map and sensitivity labels. Optional: needs a licence.",
     "Adds technical evidence for data inventory and classification where it is licensed."),
    ("attestation", "attestation-and-exception-process", "process-procedure", "Attestation and exception process",
     "Records kept in the repository and approved by pull request: attestations for requirements no technical control can check, and time-boxed exceptions with a named approver.",
     "Evidences what technical controls cannot show, and governs every deviation."),
)
ROLES = {
    "platform": "Platform team",
    "network": "Network team",
    "identity": "Identity team",
    "security-operations": "Security operations",
    "data": "Data owner",
    "application": "Application owner",
    "service-assurance": "Service assurance",
    "information-security-officer": "Information security officer",
}
PROPS = ("modal_verb", "security_level", "theme", "match", "route", "checkable", "deviation_path")


def uid(name):
    return str(uuid.uuid5(ROOT, name))


def prop(name, value):
    return {"name": name, "ns": NS, "value": value}


def catalogue_href(catalogue):
    base = catalogue["repository"].replace("https://github.com/", "https://raw.githubusercontent.com/")
    return f"{base}/{catalogue['revision']}/{quote(catalogue['path'])}"


def control_text(control):
    text = control["name"]
    if control["kind"] == "policy-definition":
        text += f" (built-in policy {control['version']})"
    if control.get("requires_paid_plan"):
        text += " (needs a paid plan)"
    return text


def implemented(requirement, slug, controls):
    props = [prop(name.replace("_", "-"), requirement[name]) for name in PROPS]
    props += [
        prop("policy-definition-id", f"/providers/Microsoft.Authorization/policyDefinitions/{control['id']}")
        for control in controls if control["kind"] == "policy-definition"
    ]
    item = {
        "uuid": uid(f"implemented-requirement/{slug}/{requirement['id']}"),
        "control-id": requirement["id"],
        "description": "; ".join(control_text(control) for control in controls) + ".",
        "props": props,
        "responsible-roles": [{"role-id": requirement["owner"]}],
    }
    if requirement["gap"]:
        item["remarks"] = f"Gap: {requirement['gap']}"
    return item


def build(mapping):
    catalogue = mapping["catalogue"]
    source = uid("resource/catalogue")
    components = []
    for kind, slug, kind_type, title, description, purpose in COMPONENTS:
        requirements = [
            implemented(requirement, slug, controls)
            for requirement in mapping["requirements"]
            for controls in [[control for control in requirement["controls"] if control["kind"] == kind]]
            if controls
        ]
        if not requirements:
            continue
        components.append({
            "uuid": uid(f"component/{slug}"),
            "type": kind_type,
            "title": title,
            "description": description,
            "purpose": purpose,
            "control-implementations": [{
                "uuid": uid(f"control-implementation/{slug}"),
                "source": f"#{source}",
                "description": f"Candidate implementation of Grundschutz++ requirements by {title}. Not a compliance statement.",
                "implemented-requirements": requirements,
            }],
        })
    owners = sorted({requirement["owner"] for requirement in mapping["requirements"]})
    unknown = [owner for owner in owners if owner not in ROLES]
    if unknown:
        raise ValueError(f"No role title for owner {', '.join(unknown)}")
    return {
        "component-definition": {
            "uuid": uid("component-definition"),
            "metadata": {
                "title": "Azure controls for Grundschutz++ requirements (candidate)",
                "last-modified": f"{mapping['checked']}T00:00:00Z",
                "version": VERSION,
                "oscal-version": OSCAL_VERSION,
                "props": [prop("status", mapping["status"])],
                "roles": [{"id": owner, "title": ROLES[owner]} for owner in owners],
                "remarks": f"Generated from catalogue-mapping.json by tools/oscal/build_component.py. {mapping['notice']}",
            },
            "components": components,
            "back-matter": {
                "resources": [
                    {
                        "uuid": source,
                        "title": f"{catalogue['name']}, revision {catalogue['revision'][:12]}",
                        "rlinks": [{
                            "href": catalogue_href(catalogue),
                            "media-type": "application/oscal.catalog+json",
                            "hashes": [{"algorithm": "SHA-256", "value": catalogue["sha256"]}],
                        }],
                    },
                    {
                        "uuid": uid("resource/catalogue-mapping"),
                        "title": "Catalogue mapping (source of this component definition)",
                        "rlinks": [{"href": "catalogue-mapping.json", "media-type": "application/json"}],
                    },
                ]
            },
        }
    }


def render(mapping):
    return json.dumps(build(mapping), indent=2, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true", help="Fail if the output file differs from a fresh build")
    args = parser.parse_args()
    text = render(json.loads(args.mapping.read_text(encoding="utf-8")))
    if args.check:
        current = args.output.read_text(encoding="utf-8").replace("\r\n", "\n") if args.output.exists() else ""
        if current != text:
            sys.exit(f"{args.output.name} is out of date: run python tools/oscal/build_component.py")
        print(f"{args.output.name} is up to date with {args.mapping.name}.")
        return
    args.output.write_text(text, encoding="utf-8", newline="\n")
    document = json.loads(text)["component-definition"]
    count = sum(len(item["implemented-requirements"]) for component in document["components"] for item in component["control-implementations"])
    print(f"Wrote {args.output.name}: {len(document['components'])} components, {count} implemented requirements.")


if __name__ == "__main__":
    main()
