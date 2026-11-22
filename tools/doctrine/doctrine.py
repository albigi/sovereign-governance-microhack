#!/usr/bin/env python3
"""Enforcement decision rule: GS++ requirement -> Azure Policy effect and deviation path.

  classify  print the effect and deviation path of each theme per archetype
  generate  write the archetype initiative and the generated tables in resources/doctrine.md
  check     fail on drift between the sources and the generated files, on a broken invariant,
            or on a disagreement with the shared catalogue mapping

Sources: resources/doctrine.json (themes, policies, routes), the 'enforcement' field of each
archetype in resources/archetypes.json (bindings, approved remediation, assignment name) and the
catalogue pin in the 'catalogue' block of resources/catalogue-mapping.json (never copied here).
Standard library only. The rule is explained in resources/doctrine.md.
"""
import argparse
import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DOCTRINE = KIT / "resources" / "doctrine.json"
ARCHETYPES = KIT / "resources" / "archetypes.json"
MAPPING = KIT / "resources" / "catalogue-mapping.json"
OUT_DIR = KIT / "resources" / "archetype-initiative"
DOC = KIT / "resources" / "doctrine.md"
POLICYSET_FILE = "policyset.json"
ASSIGNMENTS_FILE = "assignments.json"
SOURCES = "resources/doctrine.json, resources/archetypes.json"

VERB_RANK = {"KANN": 1, "SOLLTE": 2, "MUSS": 3}
CHECKS = ("property", "existence", "none")
BINDINGS = ("obligation", "bound", "not-bound")
SCOPES = ("initiative", "platform")
REMEDIATING = ("Modify", "DeployIfNotExists")
REPORTING_DEFAULTS = ("Audit", "AuditIfNotExists", "Disabled")
FALLBACK = {
    "Deny": ["Audit"],
    "Modify": ["Deny", "Audit"],
    "DeployIfNotExists": ["AuditIfNotExists"],
    "Audit": [],
    "AuditIfNotExists": [],
}
DEVIATIONS = {
    "none": "none: cannot be waived",
    "exemption": "time-boxed Azure Policy exemption via a reviewed pull request",
    "attestation-exception": "time-boxed exception outside Azure Policy via a reviewed pull request",
    "archetype-change": "reviewed change to the archetype",
    "not-required": "none needed",
}


def decide(verb, check, binding, remediation):
    """Return (effect, deviation, notes) for a requirement in one archetype.

    effect is None when Azure Policy cannot check the requirement.
    """
    notes = []
    enforce = verb == "MUSS" or binding in ("obligation", "bound")
    if check == "none":
        effect = None
    elif enforce and check == "property":
        effect = "Modify" if remediation else "Deny"
    elif enforce:
        effect = "DeployIfNotExists" if remediation else "AuditIfNotExists"
        if not remediation:
            notes.append("existence check: Azure Policy reports but cannot prevent")
    else:
        effect = "Audit" if check == "property" else "AuditIfNotExists"

    if verb == "MUSS" or binding == "obligation":
        deviation = "none"
    elif verb == "KANN":
        deviation = "archetype-change" if binding == "bound" else "not-required"
    elif binding == "bound":
        deviation = "exemption" if effect else "attestation-exception"
    else:
        deviation = "archetype-change"
    return effect, deviation, notes


def fit_effect(desired, allowed):
    """Return (effect, note): the desired effect, or the strongest weaker one the definition allows."""
    if desired in allowed:
        return desired, None
    for alternative in FALLBACK.get(desired, []):
        if alternative in allowed:
            return alternative, f"definition offers no {desired}, uses {alternative} (enforcement gap)"
    return "Disabled", f"definition offers neither {desired} nor a reporting effect (coverage gap)"


PIN_FIELDS = {"repository": "repository", "path": "path", "commit": "revision", "sha256": "sha256"}


def catalogue_pin(mapping=MAPPING):
    """Return the catalogue pin from the catalogue block of the shared mapping, its only configured place."""
    with open(mapping, encoding="utf-8") as handle:
        block = json.load(handle)["catalogue"]
    return {mine: block[theirs] for mine, theirs in PIN_FIELDS.items()}


def load(path=DOCTRINE, archetypes=ARCHETYPES, mapping=MAPPING):
    """Read the doctrine, take the catalogue pin from the shared mapping and merge each archetype's enforcement field."""
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    copied = sorted(set(doc["catalogue"]) & (set(PIN_FIELDS) | set(PIN_FIELDS.values())))
    if copied:
        raise ValueError(f"{path}: catalogue pin fields {copied} belong only in the catalogue block of {Path(mapping).name}")
    doc["catalogue"].update(catalogue_pin(mapping))
    with open(archetypes, encoding="utf-8") as handle:
        shared = json.load(handle)
    doc["archetypes"] = {}
    for arch in shared["archetypes"]:
        enforcement = arch.get("enforcement", {})
        doc["archetypes"][arch["id"]] = {
            "displayName": arch["title"],
            "description": arch["description"],
            "assignmentName": enforcement.get("assignment_name"),
            "parameters": arch.get("parameters", {}),
            "bindings": enforcement.get("bindings", {}),
            "remediationApproved": enforcement.get("remediation_approved", []),
        }
    for theme in doc["themes"]:
        key = theme["key"]
        theme["binding"] = {a: m["bindings"][key] for a, m in doc["archetypes"].items() if key in m["bindings"]}
        theme["remediationApproved"] = [a for a, m in doc["archetypes"].items() if key in m["remediationApproved"]]
    return doc


def read_applicable(path):
    """Return (applicable IDs, archetype or None, assessed IDs or None) from the output of challenge 1.

    Accepts the applicability JSON of tools/gspp/applicability.py, a CSV with an 'id' column,
    or one ID per line. Only the JSON says which requirements were assessed at all.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        ids = {r["id"] for r in data["requirements"] if r.get("applicable")}
        return ids, (data.get("archetype") or {}).get("id"), {r["id"] for r in data["requirements"]}
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if lines and "id" in [c.strip().strip('"').lower() for c in lines[0].split(",")]:
        return {row["id"].strip() for row in csv.DictReader(lines) if (row.get("id") or "").strip()}, None, None
    return {line.replace(",", " ").split()[0] for line in lines}, None, None


def applicable_from(doc, path):
    """Return (requirement IDs to keep, archetype, kept-unassessed IDs).

    A doctrine requirement that challenge 1 did not assess stays in: dropping it would hide a control.
    """
    ids, archetype, assessed = read_applicable(path)
    kept = set()
    if assessed is not None:
        kept = {r for t in doc["themes"] for r in t["requirements"]} - assessed
    return ids | kept, archetype, sorted(kept)


def scope(theme):
    return theme.get("scope", "initiative")


def strongest(verbs):
    return max(verbs, key=VERB_RANK.__getitem__)


def theme_verb(doc, theme):
    return strongest(doc["requirements"][r]["verb"] for r in theme["requirements"])


def group_names(theme):
    names = list(theme["requirements"])
    if theme.get("obligation") and theme["obligation"] not in names:
        names.append(theme["obligation"])
    return names


def selected_themes(doc, applicable=None):
    if applicable is None:
        return list(doc["themes"])
    return [t for t in doc["themes"] if any(r in applicable for r in t["requirements"])]


def classify(doc, applicable=None):
    rows = []
    for theme in selected_themes(doc, applicable):
        verb = theme_verb(doc, theme)
        for archetype in doc["archetypes"]:
            effect, deviation, notes = decide(
                verb, theme["check"], theme["binding"][archetype], archetype in theme["remediationApproved"]
            )
            policies = {}
            for policy in theme["policies"]:
                fitted, note = fit_effect(effect, policy["allowedEffects"]) if effect else ("Disabled", None)
                policies[policy["referenceId"]] = fitted
                if note:
                    notes.append(f"{policy['referenceId']}: {note}")
            platform_effect = None
            if scope(theme) == "platform" and effect:
                definition = doc["platformDefinitions"][theme["platformDefinition"]]
                platform_effect, note = fit_effect(effect, definition["allowedEffects"])
                notes.append(note or "assigned once at platform scope, outside this initiative")
            elif effect and not theme["policies"]:
                notes.append("no definition chosen yet (coverage gap)")
            rows.append({
                "theme": theme["key"],
                "requirements": {r: doc["requirements"][r]["verb"] for r in theme["requirements"]},
                "archetype": archetype,
                "binding": theme["binding"][archetype],
                "check": theme["check"],
                "route": theme["route"],
                "scope": scope(theme),
                "effect": effect,
                "policies": policies,
                "platformEffect": platform_effect,
                "deviation": deviation,
                "notes": notes,
            })
    return rows


def unmapped(doc, applicable):
    covered = {r for t in doc["themes"] for r in t["requirements"]} | {
        t["obligation"] for t in doc["themes"] if t.get("obligation")
    }
    return sorted(applicable - covered)


def default_effect(allowed):
    return next(e for e in REPORTING_DEFAULTS if e in allowed)


def build_policyset(doc, applicable=None):
    meta = doc["policySet"]
    parameters, references, groups = {}, [], {}
    for theme in selected_themes(doc, applicable):
        for name in group_names(theme):
            if theme["policies"] and name not in groups:
                req = doc["requirements"][name]
                groups[name] = {
                    "name": name,
                    "category": req["verb"],
                    "displayName": f"{name} ({req['verb']}): {req['paraphrase']}",
                    "description": (
                        f"GS++ requirement ID at catalogue commit {doc['catalogue']['commit'][:7]}; "
                        "own paraphrase, not catalogue text; candidate mapping."
                    ),
                }
        for policy in theme["policies"]:
            parameters[policy["effectParameter"]] = {
                "type": "String",
                "metadata": {
                    "displayName": f"Effect: {policy['referenceId']}",
                    "description": f"Set per archetype in {ASSIGNMENTS_FILE}; theme {theme['key']}.",
                },
                "allowedValues": policy["allowedEffects"],
                "defaultValue": default_effect(policy["allowedEffects"]),
            }
            values = {"effect": {"value": f"[parameters('{policy['effectParameter']}')]"}}
            for set_name, spec in policy["parameters"].items():
                param = {"type": spec["type"], "metadata": {"displayName": set_name, "description": spec["description"]}}
                for key in ("strongType", "assignPermissions"):
                    if key in spec:
                        param["metadata"][key] = spec[key]
                if "allowedValues" in spec:
                    param["allowedValues"] = spec["allowedValues"]
                if "default" in spec:
                    param["defaultValue"] = spec["default"]
                parameters[set_name] = param
                values[spec["definitionParameter"]] = {"value": f"[parameters('{set_name}')]"}
            for name, value in policy.get("fixedParameters", {}).items():
                values[name] = {"value": value}
            references.append({
                "policyDefinitionReferenceId": policy["referenceId"],
                "policyDefinitionId": f"/providers/Microsoft.Authorization/policyDefinitions/{policy['definitionId']}",
                "parameters": values,
                "groupNames": group_names(theme),
            })
    return {
        "name": meta["name"],
        "type": "Microsoft.Authorization/policySetDefinitions",
        "properties": {
            "displayName": meta["displayName"],
            "description": meta["description"],
            "policyType": "Custom",
            "metadata": {
                "version": meta["version"],
                "category": meta["category"],
                "status": doc["status"],
                "generatedFrom": SOURCES,
                "catalogueCommit": doc["catalogue"]["commit"],
                "builtInDefinitionsCommit": doc["builtInDefinitions"]["commit"],
            },
            "parameters": parameters,
            "policyDefinitionGroups": list(groups.values()),
            "policyDefinitions": references,
        },
    }


def archetype_value(spec, archetype):
    """Return the set-parameter value an archetype's shared parameter gives, mapped to the definition's vocabulary."""
    value = archetype["parameters"].get(spec["archetypeParameter"])
    if value is None:
        return None
    return spec.get("valueMap", {}).get(str(value), value)


def build_assignments(doc, applicable=None):
    rows = classify(doc, applicable)
    themes = {t["key"]: t for t in doc["themes"]}
    site = []
    archetypes = {}
    for key, meta in doc["archetypes"].items():
        parameters, roles, messages = {}, set(), []
        for row in (r for r in rows if r["archetype"] == key):
            theme = themes[row["theme"]]
            for policy in theme["policies"]:
                effect = row["policies"][policy["referenceId"]]
                parameters[policy["effectParameter"]] = {"value": effect}
                for set_name, spec in policy["parameters"].items():
                    if "archetypeParameter" in spec:
                        parameters[set_name] = {"value": archetype_value(spec, meta)}
                    elif "default" in spec:
                        parameters[set_name] = {"value": spec["default"]}
                    elif set_name not in site:
                        site.append(set_name)
                if effect in REMEDIATING:
                    roles.update(policy["roleDefinitionIds"])
                if effect != "Disabled":
                    cited = ", ".join(f"{g} ({doc['requirements'][g]['verb']})" for g in group_names(theme))
                    messages.append({
                        "policyDefinitionReferenceId": policy["referenceId"],
                        "message": f"GS++ {cited}: {policy['displayName']}. Deviation: {DEVIATIONS[row['deviation']]}.",
                    })
        archetypes[key] = {
            "assignmentName": meta["assignmentName"],
            "displayName": f"{doc['policySet']['displayName']}: {meta['displayName']}",
            "description": meta["description"],
            "parameters": parameters,
            "roleDefinitionIds": sorted(roles),
            "nonComplianceMessages": messages,
        }
    return {
        "policySetName": doc["policySet"]["name"],
        "generatedFrom": SOURCES,
        "siteParameters": site,
        "archetypes": archetypes,
    }


def dump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def rule_table():
    rows = [("MUSS", "any", "bound")]
    rows += [("SOLLTE", label, b) for label, b in (("external obligation", "obligation"), ("bound", "bound"), ("not bound", "not-bound"))]
    rows += [("KANN", label, b) for label, b in (("external obligation", "obligation"), ("selected", "bound"), ("not selected", "not-bound"))]
    out = [
        "| Modal verb | Binding for the archetype | Checkable: resource property | Checkable: related resource exists | Not checkable | Deviation path |",
        "|---|---|---|---|---|---|",
    ]
    for verb, label, binding in rows:
        cells = []
        for check in ("property", "existence"):
            plain, _, _ = decide(verb, check, binding, False)
            fixed, _, _ = decide(verb, check, binding, True)
            cells.append(f"`{plain}`" if plain == fixed else f"`{plain}`, or `{fixed}` if remediation is approved")
        _, dev_checkable, _ = decide(verb, "property", binding, False)
        _, dev_none, _ = decide(verb, "none", binding, False)
        cells.append("no effect; named human decision" if verb == "MUSS" else "no effect; route to its owner")
        deviation = DEVIATIONS[dev_checkable]
        if dev_none != dev_checkable:
            deviation += f" (not checkable: {DEVIATIONS[dev_none]})"
        out.append(f"| {verb} | {label} | " + " | ".join(cells) + f" | {deviation} |")
    return "\n".join(out)


def theme_table(doc):
    names = [doc["archetypes"][a]["displayName"] for a in doc["archetypes"]]
    out = [
        "| Theme | Requirements | Check | Route | " + " | ".join(names) + " |",
        "|---|---|---|---|" + "---|" * len(names),
    ]
    rows = classify(doc)
    for theme in doc["themes"]:
        reqs = ", ".join(f"{r} ({doc['requirements'][r]['verb']})" for r in theme["requirements"])
        if theme.get("obligation"):
            reqs += f"; bound by {theme['obligation']} (MUSS)"
        cells = []
        for archetype in doc["archetypes"]:
            row = next(r for r in rows if r["theme"] == theme["key"] and r["archetype"] == archetype)
            effects = sorted(set(row["policies"].values()))
            if row["platformEffect"]:
                shown = f"`{row['platformEffect']}` at platform scope"
            else:
                shown = " + ".join(f"`{e}`" for e in effects) if effects else "no effect"
            cells.append(f"{shown}; {row['deviation']}")
        out.append(f"| {theme['key']} | {reqs} | {theme['check']} | {theme['route']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def policy_table(doc):
    archetypes = build_assignments(doc)["archetypes"]
    out = [
        "| Reference ID | Built-in definition (ID prefix, version) | Groups | Effect parameter | "
        + " | ".join(doc["archetypes"][a]["displayName"] for a in doc["archetypes"]) + " |",
        "|---|---|---|---|" + "---|" * len(doc["archetypes"]),
    ]
    for theme in doc["themes"]:
        for p in theme["policies"]:
            effects = " | ".join(f"`{archetypes[a]['parameters'][p['effectParameter']]['value']}`" for a in doc["archetypes"])
            out.append(
                f"| `{p['referenceId']}` | {p['displayName']} (`{p['definitionId'][:8]}`, {p['version']}) | "
                f"{', '.join(group_names(theme))} | `{p['effectParameter']}` | {effects} |"
            )
    return "\n".join(out)


def generated_sections(doc):
    return {"rules": rule_table(), "themes": theme_table(doc), "policies": policy_table(doc)}


def splice(text, sections):
    for name, body in sections.items():
        begin, end = f"<!-- BEGIN GENERATED: {name} -->", f"<!-- END GENERATED: {name} -->"
        if begin not in text or end not in text:
            raise ValueError(f"doctrine.md lacks the markers for '{name}'")
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
        text = f"{head}{begin}\n{body}\n{end}{tail}"
    return text


def invariants(doc):
    errors = []
    archetypes = set(doc["archetypes"])
    reqs = doc["requirements"]
    keys = {t["key"] for t in doc["themes"]}
    refs, params = set(), set()
    for name, meta in doc["archetypes"].items():
        if not meta["assignmentName"]:
            errors.append(f"archetype {name}: needs enforcement.assignment_name in archetypes.json")
        for field, named in (("bindings", meta["bindings"]), ("remediation_approved", meta["remediationApproved"])):
            if set(named) - keys:
                errors.append(f"archetype {name}: enforcement.{field} names unknown themes {sorted(set(named) - keys)}")
    for theme in doc["themes"]:
        key = theme["key"]
        missing = [r for r in group_names(theme) if r not in reqs]
        if missing:
            errors.append(f"{key}: unknown requirement {missing}")
            continue
        if set(theme["binding"]) != archetypes:
            errors.append(f"{key}: binding must name every archetype")
        if any(b not in BINDINGS for b in theme["binding"].values()):
            errors.append(f"{key}: binding must be one of {BINDINGS}")
        if theme["check"] not in CHECKS:
            errors.append(f"{key}: check must be one of {CHECKS}")
        if theme["route"] not in doc["routes"]:
            errors.append(f"{key}: unknown route {theme['route']}")
        if scope(theme) not in SCOPES:
            errors.append(f"{key}: scope must be one of {SCOPES}")
        if scope(theme) == "platform":
            if theme["check"] == "none" or theme["policies"]:
                errors.append(f"{key}: a platform-scope theme is checkable and adds no policies to the initiative")
            if theme.get("platformDefinition") not in doc.get("platformDefinitions", {}):
                errors.append(f"{key}: a platform-scope theme names a definition in platformDefinitions")
            if len(set(theme["binding"].values())) > 1 or set(theme["remediationApproved"]) not in (set(), archetypes):
                errors.append(f"{key}: one platform assignment serves every archetype, so binding and remediation must not differ")
        elif (theme["check"] == "none") != (not theme["policies"]):
            errors.append(f"{key}: a checkable theme needs policies; a non-checkable theme has none")
        if (theme["check"] == "none") == (theme["route"] == "azure-policy"):
            errors.append(f"{key}: checkable themes route to azure-policy, others route elsewhere")
        obligated = [a for a, b in theme["binding"].items() if b == "obligation"]
        if bool(obligated) != bool(theme.get("obligation")):
            errors.append(f"{key}: an 'obligation' binding needs an obligation requirement, and vice versa")
        if obligated and len(obligated) != len(archetypes):
            errors.append(f"{key}: policy groups are shared, so an obligation must bind every archetype")
        if theme.get("obligation") and reqs[theme["obligation"]]["verb"] != "MUSS":
            errors.append(f"{key}: the obligation requirement must be MUSS")
        if theme_verb(doc, theme) == "MUSS" and theme["check"] == "none" and theme["route"] != "named-decision":
            errors.append(f"{key}: a MUSS that Azure Policy cannot check routes to a named decision")
        for policy in theme["policies"]:
            if policy["referenceId"] in refs:
                errors.append(f"{key}: duplicate reference ID {policy['referenceId']}")
            refs.add(policy["referenceId"])
            for name in [policy["effectParameter"], *policy["parameters"]]:
                if name in params:
                    errors.append(f"{key}: duplicate set parameter {name}")
                params.add(name)
            for name, spec in policy["parameters"].items():
                if "archetypeParameter" not in spec:
                    continue
                for arch, meta in doc["archetypes"].items():
                    value = archetype_value(spec, meta)
                    if value is None:
                        errors.append(f"{name}/{arch}: archetype lacks parameter {spec['archetypeParameter']}")
                    elif "allowedValues" in spec and value not in spec["allowedValues"]:
                        errors.append(f"{name}/{arch}: {spec['archetypeParameter']} gives {value}, the definition allows {spec['allowedValues']}")
    if errors:
        return errors
    themes = {t["key"]: t for t in doc["themes"]}
    for row in classify(doc):
        theme = themes[row["theme"]]
        verbs = {reqs[g]["verb"] for g in group_names(theme)}
        if row["deviation"] == "exemption" and verbs != {"SOLLTE"}:
            errors.append(f"{row['theme']}/{row['archetype']}: exemption offered but a group is {sorted(verbs - {'SOLLTE'})}")
        for ref, effect in row["policies"].items():
            policy = next(p for p in theme["policies"] if p["referenceId"] == ref)
            if effect not in policy["allowedEffects"]:
                errors.append(f"{ref}/{row['archetype']}: {effect} not allowed by the definition")
            if effect in REMEDIATING and not policy["roleDefinitionIds"]:
                errors.append(f"{ref}/{row['archetype']}: {effect} needs roleDefinitionIds")
        if row["platformEffect"]:
            definition = doc["platformDefinitions"][theme["platformDefinition"]]
            if row["platformEffect"] in REMEDIATING and not definition["roleDefinitionIds"]:
                errors.append(f"{row['theme']}/{row['archetype']}: {row['platformEffect']} needs roleDefinitionIds")
    for name, param in build_policyset(doc)["properties"]["parameters"].items():
        if name.endswith("Effect") and param["defaultValue"] not in REPORTING_DEFAULTS:
            errors.append(f"{name}: default effect must not block or change resources")
    return errors


def doctrine_controls(doc):
    """Return {definition GUID: (facts, requirement IDs it serves, theme keys)} for every definition the doctrine uses."""
    controls = {}
    for theme in doc["themes"]:
        if scope(theme) == "platform":
            definition = doc["platformDefinitions"][theme["platformDefinition"]]
            facts = {"name": definition["displayName"], "version": definition["version"], "effects": definition["allowedEffects"]}
            entry = controls.setdefault(theme["platformDefinition"], (facts, set(), set()))
            entry[1].update(theme["requirements"])
            entry[2].add(theme["key"])
        for policy in theme["policies"]:
            facts = {"name": policy["displayName"], "version": policy["version"], "effects": policy["allowedEffects"]}
            entry = controls.setdefault(policy["definitionId"], (facts, set(), set()))
            entry[1].update(group_names(theme))
            entry[2].add(theme["key"])
    return controls


def check_mapping(doc, mapping):
    """Cross-check the doctrine against the shared catalogue mapping. Return (errors, notes)."""
    errors, notes = [], []
    themes_of = {}
    for theme in doc["themes"]:
        for rid in theme["requirements"]:
            themes_of[rid] = theme
    controls = doctrine_controls(doc)
    mapped_ids = set()
    for req in mapping["requirements"]:
        rid = req["id"]
        mapped_ids.add(rid)
        theme = themes_of.get(rid)
        if theme is None:
            errors.append(f"{rid}: in the catalogue mapping but in no doctrine theme")
            continue
        mine = doc["requirements"][rid]
        if req["modal_verb"] != mine["verb"] or req["security_level"] != mine["level"]:
            errors.append(f"{rid}: mapping says {req['modal_verb']}/{req['security_level']}, doctrine says {mine['verb']}/{mine['level']}")
        if (req["route"] == "azure-policy") != (theme["route"] == "azure-policy"):
            errors.append(f"{rid}: mapping route {req['route']}, doctrine theme {theme['key']} routes to {theme['route']}")
        for control in req["controls"]:
            if control["kind"] != "policy-definition" or control["id"] not in controls:
                continue
            facts, served, theme_keys = controls[control["id"]]
            label = f"{rid}/{control['id'][:8]}"
            if control["version"] != facts["version"]:
                errors.append(f"{label}: mapping pins version {control['version']}, doctrine {facts['version']}")
            if sorted(control["effects"]) != sorted(facts["effects"]):
                errors.append(f"{label}: mapping lists effects {control['effects']}, doctrine {facts['effects']}")
            if control["name"] != facts["name"]:
                errors.append(f"{label}: mapping names it '{control['name']}', doctrine '{facts['name']}'")
            if rid not in served:
                errors.append(f"{label}: the doctrine uses this definition but not for {rid}")
            allowed = control.get("archetypes")
            if allowed:
                for row in classify(doc):
                    if row["theme"] not in theme_keys or row["archetype"] in allowed:
                        continue
                    effects = [e for ref, e in row["policies"].items() if ref in policy_refs(doc, control["id"])]
                    if any(e not in REPORTING_DEFAULTS for e in effects):
                        errors.append(f"{label}: mapping limits it to {allowed}, doctrine enforces it in {row['archetype']}")
    extra_reqs = sorted(set(themes_of) - mapped_ids)
    if extra_reqs:
        notes.append(f"requirements in the doctrine but not in the mapping: {', '.join(extra_reqs)}")
    mapped_controls = {c["id"] for r in mapping["requirements"] for c in r["controls"] if c["kind"] == "policy-definition"}
    extra_controls = sorted(g[:8] for g in controls if g not in mapped_controls)
    if extra_controls:
        notes.append(f"definitions in the doctrine but not in the mapping: {', '.join(extra_controls)}")
    return errors, notes


def policy_refs(doc, definition_id):
    return {p["referenceId"] for t in doc["themes"] for p in t["policies"] if p["definitionId"] == definition_id}


def check_catalogue(doc, path, levels):
    errors = []
    with open(path, encoding="utf-8") as handle:
        rows = {r["id"]: r for r in csv.DictReader(handle)}
    for rid, req in doc["requirements"].items():
        row = rows.get(rid)
        if row is None:
            errors.append(f"{rid}: not in the catalogue extract")
            continue
        if row["modal_verb"] != req["verb"]:
            errors.append(f"{rid}: verb {req['verb']} but catalogue says {row['modal_verb']}")
        level = levels.get(row["security_level"], row["security_level"])
        if level != req["level"]:
            errors.append(f"{rid}: level {req['level']} but catalogue says {row['security_level']}")
        if row["source_commit"] != doc["catalogue"]["commit"]:
            errors.append(f"{rid}: extract is from commit {row['source_commit'][:7]}, the mapping pins {doc['catalogue']['commit'][:7]}")
    return errors


def check_online(doc):
    errors = []
    base = (
        "https://raw.githubusercontent.com/Azure/azure-policy/"
        f"{doc['builtInDefinitions']['commit']}/built-in-policies/policyDefinitions/"
    )
    entries = [(p["referenceId"], p["definitionId"], p) for t in doc["themes"] for p in t["policies"]]
    entries += [
        (f"platform {guid[:8]}", guid, {**d, "parameters": {}}) for guid, d in doc.get("platformDefinitions", {}).items()
    ]
    for label, guid, p in entries:
        with urllib.request.urlopen(base + urllib.parse.quote(p["path"]), timeout=60) as response:
            definition = json.load(response)
        props = definition["properties"]
        effect = next(v for k, v in props["parameters"].items() if k.lower() == "effect")
        details = props["policyRule"]["then"].get("details")
        roles = details.get("roleDefinitionIds", []) if isinstance(details, dict) else []
        facts = {
            "name": (definition["name"], guid),
            "displayName": (props["displayName"], p["displayName"]),
            "version": (props["metadata"].get("version"), p["version"]),
            "allowedEffects": (sorted(effect["allowedValues"]), sorted(p["allowedEffects"])),
            "roles": (sorted(r.rsplit("/", 1)[-1].lower() for r in roles), sorted(p["roleDefinitionIds"])),
        }
        errors += [f"{label}: {k} is {got}, doctrine says {want}" for k, (got, want) in facts.items() if got != want]
        wanted = {s["definitionParameter"] for s in p["parameters"].values()} | set(p.get("fixedParameters", {}))
        if not wanted <= set(props["parameters"]):
            errors.append(f"{label}: definition lacks parameters {sorted(wanted - set(props['parameters']))}")
    return errors


def cmd_classify(args):
    doc = load(args.doctrine, args.archetypes)
    applicable, archetype, kept = applicable_from(doc, args.applicable) if args.applicable else (None, None, [])
    archetype = args.archetype or archetype
    rows = classify(doc, applicable)
    if archetype:
        rows = [r for r in rows if r["archetype"] == archetype]
    if args.format == "json":
        print(dump({"rows": rows, "unmapped": unmapped(doc, applicable) if applicable else [], "unassessed": kept}), end="")
        return 0
    print("| Theme | Archetype | Requirements | Check | Route | Effect | Deviation | Notes |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        reqs = ", ".join(f"{k} ({v})" for k, v in r["requirements"].items())
        effects = ", ".join(f"{k}={v}" for k, v in r["policies"].items())
        effects = effects or (f"platform={r['platformEffect']}" if r["platformEffect"] else "no effect")
        print(f"| {r['theme']} | {r['archetype']} | {reqs} | {r['check']} | {r['route']} | {effects} | {r['deviation']} | {'; '.join(r['notes'])} |")
    if applicable:
        missing = unmapped(doc, applicable)
        print(f"\nApplicable requirements with no theme yet (coverage gap): {len(missing)}")
        if missing:
            print(", ".join(missing))
        if kept:
            print(f"Kept because challenge 1 does not assess them: {', '.join(kept)}")
    return 0


def cmd_generate(args):
    doc = load(args.doctrine, args.archetypes)
    applicable = applicable_from(doc, args.applicable)[0] if args.applicable else None
    if applicable is not None and args.out is None:
        print("generate --applicable needs --out, so the committed initiative stays unchanged", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / POLICYSET_FILE).write_text(dump(build_policyset(doc, applicable)), encoding="utf-8", newline="\n")
    (out / ASSIGNMENTS_FILE).write_text(dump(build_assignments(doc, applicable)), encoding="utf-8", newline="\n")
    print(f"wrote {out / POLICYSET_FILE} and {out / ASSIGNMENTS_FILE}")
    if applicable is None and args.out is None:
        DOC.write_text(splice(DOC.read_text(encoding="utf-8"), generated_sections(doc)), encoding="utf-8", newline="\n")
        print(f"updated the generated tables in {DOC}")
    return 0


def cmd_check(args):
    doc = load(args.doctrine, args.archetypes, args.mapping or MAPPING)
    errors, notes = invariants(doc), []
    if not errors:
        expected = {POLICYSET_FILE: dump(build_policyset(doc)), ASSIGNMENTS_FILE: dump(build_assignments(doc))}
        for name, text in expected.items():
            path = OUT_DIR / name
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                errors.append(f"resources/archetype-initiative/{name} is stale: run 'doctrine.py generate'")
        doc_text = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        try:
            if splice(doc_text, generated_sections(doc)) != doc_text:
                errors.append("resources/doctrine.md tables are stale: run 'doctrine.py generate'")
        except ValueError as exc:
            errors.append(str(exc))
        if args.mapping:
            with open(args.mapping, encoding="utf-8") as handle:
                mapping_errors, notes = check_mapping(doc, json.load(handle))
            errors += mapping_errors
    if args.catalogue:
        errors += check_catalogue(doc, args.catalogue, doc["catalogue"].get("levels", {}))
    if args.online:
        errors += check_online(doc)
    for note in notes:
        print(f"NOTE {note}")
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    if errors:
        return 1
    policies = sum(len(t["policies"]) for t in doc["themes"])
    extra = " + catalogue mapping" if args.mapping else ""
    extra += " + catalogue" if args.catalogue else ""
    extra += " + built-in definitions" if args.online else ""
    print(f"OK: {len(doc['themes'])} themes, {policies} policies, {len(doc['archetypes'])} archetypes; invariants + drift{extra}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--doctrine", default=DOCTRINE, help="doctrine as data (default: resources/doctrine.json)")
    parser.add_argument("--archetypes", default=ARCHETYPES, help="shared archetypes (default: resources/archetypes.json)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("classify", help="effect and deviation path per theme and archetype")
    p.add_argument(
        "--applicable",
        help="output of challenge 1: applicability JSON from tools/gspp/applicability.py, a CSV with an 'id' column, or one ID per line",
    )
    p.add_argument("--archetype", help="only this archetype (default: the one named in the applicability JSON)")
    p.add_argument("--format", choices=("table", "json"), default="table")
    p.set_defaults(func=cmd_classify)
    p = sub.add_parser("generate", help="write the archetype initiative and the doctrine.md tables")
    p.add_argument("--applicable", help="only themes with an applicable requirement (needs --out)")
    p.add_argument("--out", help="output folder (default: resources/archetype-initiative)")
    p.set_defaults(func=cmd_generate)
    p = sub.add_parser("check", help="invariants, drift and the catalogue mapping; optional catalogue and built-in definition checks")
    p.add_argument("--mapping", default=MAPPING, help="shared catalogue mapping to cross-check and read the catalogue pin from (default: resources/catalogue-mapping.json; '' skips the cross-check, the pin still comes from the default)")
    p.add_argument("--catalogue", help="CSV written by tools/gspp/extract.py, to check IDs, verbs and levels")
    p.add_argument("--online", action="store_true", help="check built-in definitions at the pinned Azure/azure-policy commit")
    p.set_defaults(func=cmd_check)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
