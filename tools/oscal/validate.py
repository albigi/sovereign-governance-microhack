#!/usr/bin/env python3
"""Validate an OSCAL component definition against the NIST OSCAL JSON schema.

BSI publishes Grundschutz++ in NIST OSCAL and no schema of its own, so the NIST
release schema is the reference. It is downloaded at a pinned SHA-256 and
cached in tools/oscal/out/. Use --schema to validate offline with a schema
file you have already downloaded.

Beyond the schema, the script checks that UUIDs are unique, that every
'#uuid' source resolves to a back-matter resource, and that every
responsible role is defined in the metadata.

Needs: python -m pip install -r tools/oscal/requirements.txt
"""

import argparse
import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen


TOOLS = Path(__file__).resolve().parent
KIT = TOOLS.parents[1]
DEFAULT = KIT / "resources" / "azure-component-definition.json"
CACHE = TOOLS / "out"
RELEASES = "https://github.com/usnistgov/OSCAL/releases/download"
SCHEMAS = {
    "1.1.3": "9bde069f8f65ec82ea626348cc40ae5d42b0f74c1a2a8b9289a1604bf521a15c",
    "1.2.2": "3b6e0765c44037c4d1bfb2cdb972713917d3eca73e566c0e6c6881a565638830",
}


def schema_url(version):
    return f"{RELEASES}/v{version}/oscal_component_schema.json"


def load_schema(version, path=None):
    """Return the pinned NIST component schema: from --schema, the cache or the NIST release."""
    cached = CACHE / f"oscal_component_schema-{version}.json"
    source = Path(path) if path else cached
    if source.exists():
        data = source.read_bytes()
    else:
        with urlopen(schema_url(version), timeout=60) as response:
            data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != SCHEMAS[version]:
        raise ValueError(f"OSCAL {version} schema SHA-256 mismatch: expected {SCHEMAS[version]}, got {actual}")
    if not cached.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return json.loads(data)


def make_validator(schema):
    # The NIST schemas use Unicode classes such as \p{L}; Python's re module rejects them.
    import regex
    from jsonschema import Draft7Validator, ValidationError, validators

    @lru_cache(maxsize=None)
    def compiled(pattern):
        return regex.compile(pattern)

    def pattern(validator, value, instance, schema):
        if validator.is_type(instance, "string") and not compiled(value).search(instance):
            yield ValidationError(f"{instance!r} does not match {value!r}")

    validator = validators.extend(Draft7Validator, {"pattern": pattern})
    return validator(schema, format_checker=Draft7Validator.FORMAT_CHECKER)


def schema_errors(document, schema):
    errors = sorted(make_validator(schema).iter_errors(document), key=lambda error: list(error.absolute_path))
    return [f"/{'/'.join(str(part) for part in error.absolute_path)}: {error.message}" for error in errors]


def walk(node, pointer=""):
    yield pointer, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{pointer}/{index}")


def reference_errors(document):
    definition = document["component-definition"]
    resources = {item["uuid"] for item in definition.get("back-matter", {}).get("resources", [])}
    roles = {item["id"] for item in definition["metadata"].get("roles", [])}
    errors = []
    seen = {}
    for pointer, node in walk(document):
        if not isinstance(node, dict):
            continue
        if isinstance(node.get("uuid"), str):
            if node["uuid"] in seen:
                errors.append(f"{pointer}: uuid {node['uuid']} also used at {seen[node['uuid']]}")
            seen.setdefault(node["uuid"], pointer)
        source = node.get("source")
        if isinstance(source, str) and source.startswith("#") and source[1:] not in resources:
            errors.append(f"{pointer}: source {source} has no back-matter resource")
        for role in node.get("responsible-roles", []):
            if role["role-id"] not in roles:
                errors.append(f"{pointer}: role {role['role-id']} is not defined in metadata.roles")
    return errors, len(seen)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", type=Path, default=DEFAULT)
    parser.add_argument("--oscal-version", action="append", choices=sorted(SCHEMAS), help="Schema version (default: all pinned versions)")
    parser.add_argument("--schema", type=Path, help="Local copy of the schema; needs exactly one --oscal-version")
    args = parser.parse_args()
    versions = args.oscal_version or sorted(SCHEMAS)
    if args.schema and len(versions) != 1:
        parser.error("--schema needs exactly one --oscal-version")
    try:
        import jsonschema  # noqa: F401
        import regex  # noqa: F401
    except ImportError:
        sys.exit("Missing packages: run python -m pip install -r tools/oscal/requirements.txt")
    document = json.loads(args.file.read_text(encoding="utf-8"))
    failed = False
    for version in versions:
        errors = schema_errors(document, load_schema(version, args.schema))
        if errors:
            failed = True
            print(f"INVALID against NIST OSCAL {version} component schema: {len(errors)} errors")
            for error in errors[:20]:
                print(f"  {error}")
        else:
            print(f"Valid against NIST OSCAL {version} component schema (SHA-256 {SCHEMAS[version][:12]}).")
    errors, count = reference_errors(document)
    for error in errors:
        print(f"ERROR {error}")
    if errors:
        failed = True
    else:
        print(f"References OK: {count} unique UUIDs, sources resolve to back-matter, roles defined.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
