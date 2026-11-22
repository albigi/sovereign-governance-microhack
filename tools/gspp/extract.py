#!/usr/bin/env python3
"""Flatten the pinned BSI Grundschutz++ OSCAL catalogue into a UTF-8 CSV.

The catalogue is BSI's, published at https://github.com/BSI-Bund/Stand-der-Technik-Bibliothek.
The pin (repository, path, revision and SHA-256) is configured in one place, the
"catalogue" block of resources/catalogue-mapping.json. The download is checked
against that digest, so a run never follows "latest". To move to a newer BSI
release, run "--pin <commit>" and follow "Upgrade the catalogue" in
resources/README.md.

The kit consumes the catalogue and never redistributes it. The default output
folder tools/gspp/out/ is git-ignored; do not commit the generated CSV.
This file also works as a standalone copy next to its own catalogue-mapping.json.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen


HERE = Path(__file__).resolve().parent
CONFIG_NAME = "catalogue-mapping.json"
OUTPUT = HERE / "out" / "gspp-extract.csv"
REPOSITORY = re.compile(r"^https://github\.com/([A-Za-z0-9-]+)/((?!\.+$)[A-Za-z0-9_.-]+)$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
FIELDS = (
    "source_commit", "source_sha256", "id", "title", "practice", "group",
    "parent_control", "modal_verb",
    "target_object_categories", "security_level", "statement_300", "parameters",
)


def find_config(explicit=None):
    candidates = [Path(explicit)] if explicit else [HERE / CONFIG_NAME, HERE.parent.parent / "resources" / CONFIG_NAME]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError(
        "Catalogue configuration not found (looked for "
        + ", ".join(str(candidate) for candidate in candidates)
        + f"). Pass --config <{CONFIG_NAME}>."
    )


def pin_problems(pin):
    """Return what is wrong with a catalogue pin; an empty list means it can be used."""
    if not isinstance(pin, dict):
        return ["there is no catalogue block"]
    problems = [
        f"{key} is missing" for key in ("repository", "path", "revision", "sha256")
        if not isinstance(pin.get(key), str) or not pin[key]
    ]
    if problems:
        return problems
    if not REPOSITORY.match(pin["repository"]):
        problems.append("repository must be https://github.com/<owner>/<repository>")
    if not COMMIT.match(pin["revision"]):
        problems.append("revision must be a full 40-character lowercase commit hash, not a branch or tag")
    if not DIGEST.match(pin["sha256"]):
        problems.append("sha256 must be 64 lowercase hexadecimal characters")
    path = pin["path"]
    if path.startswith("/") or "\\" in path or "?" in path or "#" in path or ".." in path.split("/"):
        problems.append("path must be a relative path inside the repository")
    return problems


def load_catalogue(config=None):
    """Return the validated catalogue pin: the "catalogue" block of the mapping, or a file holding only that block."""
    path = find_config(config)
    document = json.loads(path.read_text(encoding="utf-8"))
    pin = document.get("catalogue", document) if isinstance(document, dict) else None
    problems = pin_problems(pin)
    if problems:
        raise ValueError(f"Invalid catalogue configuration in {path}: " + "; ".join(problems))
    return pin


def catalogue_url(pin):
    owner, repository = REPOSITORY.match(pin["repository"]).groups()
    return f"https://raw.githubusercontent.com/{owner}/{repository}/{pin['revision']}/{quote(pin['path'])}"


def download(pin, opener=urlopen):
    with opener(catalogue_url(pin), timeout=60) as response:
        return response.read()


def verify(data, pin):
    actual = hashlib.sha256(data).hexdigest()
    if actual != pin["sha256"]:
        raise ValueError(f"Catalogue SHA-256 mismatch: expected {pin['sha256']} (sha256 in the configuration), got {actual}")
    return actual


def metadata_problems(catalog, pin):
    """Compare the descriptive fields of the pin with the catalogue's own metadata, when both are present."""
    metadata = catalog.get("metadata", {})
    problems = []
    version = metadata.get("oscal-version")
    if version and pin.get("oscal_version") and version != pin["oscal_version"]:
        problems.append(f"oscal_version is {pin['oscal_version']} in the configuration but the catalogue says {version}")
    modified = str(metadata.get("last-modified", ""))[:10]
    if modified and pin.get("last_modified") and modified != pin["last_modified"]:
        problems.append(f"last_modified is {pin['last_modified']} in the configuration but the catalogue says {modified}")
    return problems


def __getattr__(name):
    """Keep REVISION, SOURCE and SHA256 importable; they now come from the configuration."""
    if name in ("REVISION", "SOURCE", "SHA256"):
        pin = load_catalogue()
        return {"REVISION": pin["revision"], "SOURCE": catalogue_url(pin), "SHA256": pin["sha256"]}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def prop_value(props, name):
    values = [prop["value"] for prop in props if prop["name"] == name]
    if len(values) > 1:
        raise ValueError(f"Multiple {name} properties: {values}")
    return values[0] if values else ""


def extract(catalog, pin=None):
    pin = pin or load_catalogue()
    seen = set()

    def control_rows(control, practice, group, parent=""):
        identifier = control["id"]
        if identifier in seen:
            raise ValueError(f"Duplicate control id: {identifier}")
        seen.add(identifier)
        statements = [part for part in control.get("parts", []) if part["name"] == "statement"]
        if len(statements) != 1:
            raise ValueError(f"{identifier} has {len(statements)} statement parts")
        statement = statements[0]
        modal = prop_value(statement.get("props", []), "modal_verb")
        if modal not in {"MUSS", "SOLLTE", "KANN"}:
            raise ValueError(f"Unexpected modal verb for {identifier}: {modal!r}")
        yield {
            "source_commit": pin["revision"],
            "source_sha256": pin["sha256"],
            "id": identifier,
            "title": control["title"],
            "practice": practice,
            "group": group,
            "parent_control": parent,
            "modal_verb": modal,
            "target_object_categories": prop_value(
                statement.get("props", []), "target_object_categories"
            ),
            "security_level": prop_value(control.get("props", []), "sec_level"),
            "statement_300": statement["prose"][:300],
            "parameters": json.dumps(control.get("params", []), ensure_ascii=False, separators=(",", ":")),
        }
        for child in control.get("controls", []):
            yield from control_rows(child, practice, group, identifier)

    def group_rows(group, practice, group_path):
        path = group_path + [group["id"]]
        for control in group.get("controls", []):
            yield from control_rows(control, practice, " / ".join(path))
        for child in group.get("groups", []):
            yield from group_rows(child, practice, path)

    for group in catalog["groups"]:
        yield from group_rows(group, group["id"], [])


def write_csv(rows, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def inspect_revision(pin, revision, opener=urlopen):
    """Download another revision of the configured file and report what to paste into the configuration. Writes nothing."""
    if not COMMIT.match(revision):
        raise ValueError("--pin needs a full 40-character lowercase commit hash, not a branch or tag")
    candidate = {**pin, "revision": revision}
    data = download(candidate, opener)
    digest = hashlib.sha256(data).hexdigest()
    catalog = json.loads(data)["catalog"]
    count = sum(1 for _ in extract(catalog, {**candidate, "sha256": digest}))
    metadata = catalog.get("metadata", {})
    suggestion = {
        "revision": revision,
        "sha256": digest,
        "oscal_version": metadata.get("oscal-version", ""),
        "last_modified": str(metadata.get("last-modified", ""))[:10],
    }
    print(f"{catalogue_url(candidate)}\nParsed {count} controls; the catalogue is {'identical to' if digest == pin['sha256'] else 'different from'} the configured pin.")
    print("Copy these values into the catalogue block of the configuration, then follow the upgrade steps:")
    print(json.dumps(suggestion, indent=2))


def main(argv=None, opener=urlopen):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help=f"{CONFIG_NAME} holding the catalogue pin (default: resources/{CONFIG_NAME})")
    parser.add_argument("--input", type=Path, help="Read the pinned catalogue from a local file instead of downloading; the digest is still checked")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--pin", metavar="COMMIT", help="Look at another catalogue commit and print the values to configure; writes nothing")
    args = parser.parse_args(argv)
    if args.pin and args.input:
        parser.error("--pin downloads a revision and cannot be combined with --input")
    pin = load_catalogue(args.config)
    if args.pin:
        inspect_revision(pin, args.pin, opener)
        return
    if args.input:
        data = args.input.read_bytes()
        origin = str(args.input)
    else:
        origin = catalogue_url(pin)
        data = download(pin, opener)
    actual = verify(data, pin)
    catalog = json.loads(data)["catalog"]
    problems = metadata_problems(catalog, pin)
    if problems:
        raise ValueError("Catalogue configuration does not describe the downloaded file: " + "; ".join(problems))
    rows = list(extract(catalog, pin))
    write_csv(rows, args.output)
    print(f"Catalogue {origin}\nPinned at {pin['revision']} by {find_config(args.config)}")
    print(f"Wrote {len(rows)} controls to {args.output} (SHA-256 {actual})")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        sys.exit(f"error: {error}")
