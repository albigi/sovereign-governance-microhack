#!/usr/bin/env python3
"""Check the kit's Grundschutz++ requirement IDs against the pinned catalogue.

Reads the local extract written by extract.py; nothing is downloaded. Fails when
a requirement ID does not exist, when a mapped requirement's modal verb or
security level differs from the catalogue, or when a catalogue title or
statement has been copied into a kit file (the kit consumes the catalogue and
does not redistribute it).
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

from extract import OUTPUT, load_catalogue


TOOLS = Path(__file__).resolve().parent
KIT = TOOLS.parents[1]
RESOURCES = KIT / "resources"
DEFAULT_FILES = (
    RESOURCES / "catalogue-mapping.json",
    RESOURCES / "archetypes.json",
    RESOURCES / "azure-component-definition.json",
)
ID_KEYS = {"id", "control-id", "parameters_basis"}
REQUIREMENT_ID = re.compile(r"^[A-Z]{2,6}(\.[0-9]+)+$")
LEVELS = {"normal-SdT": "normal", "erhöht": "elevated"}
SCAN_SUFFIXES = {".md", ".json", ".py", ".bicep", ".ps1", ".yml", ".yaml", ".txt"}
SKIP_DIRS = {"out", "__pycache__", ".git", "img"}
MIN_TITLE = 20
STATEMENT_FRAGMENT = 60


def load_extract(path, pin=None):
    pin = pin or load_catalogue()
    with Path(path).open(encoding="utf-8", newline="") as source:
        rows = {row["id"]: row for row in csv.DictReader(source)}
    if not rows:
        raise ValueError(f"{path} holds no controls")
    built_from = {(row["source_commit"], row["source_sha256"]) for row in rows.values()}
    if built_from != {(pin["revision"], pin["sha256"])}:
        found = ", ".join(f"{commit[:12]} / {digest[:12]}" for commit, digest in sorted(built_from))
        raise ValueError(
            f"{path} was not built from the pinned catalogue ({pin['revision'][:12]} / {pin['sha256'][:12]}; "
            f"the extract says {found}). The catalogue configuration changed: run python tools/gspp/extract.py again"
        )
    return rows


def references(node, pointer=""):
    """Yield (JSON pointer, value, enclosing object) for every requirement ID in a document."""
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{pointer}/{key}"
            if key in ID_KEYS and isinstance(value, str) and REQUIREMENT_ID.match(value):
                yield path, value, node
            else:
                yield from references(value, path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from references(value, f"{pointer}/{index}")


def check_document(document, rows):
    """Return (number of IDs checked, list of errors) for one JSON document."""
    errors = []
    count = 0
    for pointer, identifier, holder in references(document):
        count += 1
        row = rows.get(identifier)
        if row is None:
            errors.append(f"{pointer}: {identifier} is not in the pinned catalogue")
            continue
        if "modal_verb" in holder and holder["modal_verb"] != row["modal_verb"]:
            errors.append(f"{pointer}: {identifier} modal verb is {row['modal_verb']}, not {holder['modal_verb']}")
        level = LEVELS.get(row["security_level"], row["security_level"])
        if "security_level" in holder and holder["security_level"] != level:
            errors.append(f"{pointer}: {identifier} security level is {level}, not {holder['security_level']}")
    return count, errors


def fragments(rows):
    for row in rows.values():
        if len(row["title"]) >= MIN_TITLE:
            yield row["id"], "title", row["title"].casefold()
        statement = " ".join(row["statement_300"].split())
        if len(statement) >= STATEMENT_FRAGMENT:
            yield row["id"], "statement", statement[:STATEMENT_FRAGMENT].casefold()


def kit_files(root):
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories if name not in SKIP_DIRS)
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix in SCAN_SUFFIXES:
                yield path


def scan_text(root, rows):
    """Return (number of files scanned, list of findings) for catalogue text copied into the kit."""
    needles = list(fragments(rows))
    findings = []
    count = 0
    for path in kit_files(root):
        count += 1
        text = " ".join(path.read_text(encoding="utf-8", errors="replace").split()).casefold()
        for identifier, kind, needle in needles:
            if needle in text:
                findings.append(f"{path.relative_to(root)}: contains the catalogue {kind} of {identifier}")
    return count, findings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help="More JSON files to check, for example an applicability result")
    parser.add_argument("--extract", type=Path, default=OUTPUT, help="Catalogue extract written by extract.py")
    parser.add_argument("--config", help="catalogue-mapping.json holding the catalogue pin (default: resources/catalogue-mapping.json)")
    parser.add_argument("--no-text-scan", action="store_true", help="Skip the scan for copied catalogue text")
    args = parser.parse_args()
    if not args.extract.exists():
        sys.exit(f"{args.extract} not found: run python tools/gspp/extract.py first")
    try:
        rows = load_extract(args.extract, load_catalogue(args.config))
    except ValueError as error:
        sys.exit(f"error: {error}")
    errors = []
    total = 0
    files = [path for path in DEFAULT_FILES if path.exists()] + args.files
    for path in files:
        count, problems = check_document(json.loads(path.read_text(encoding="utf-8")), rows)
        total += count
        errors += [f"{path.name}{problem}" for problem in problems]
    print(f"Checked {total} requirement IDs in {len(files)} files against {len(rows)} catalogue controls.")
    if not args.no_text_scan:
        scanned, findings = scan_text(KIT, rows)
        errors += findings
        print(f"Scanned {scanned} kit files for copied catalogue text.")
    for error in errors:
        print(f"ERROR {error}")
    if errors:
        sys.exit(1)
    print("OK: every ID exists, verbs and levels match, no catalogue text found.")


if __name__ == "__main__":
    main()
