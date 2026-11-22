# Walkthrough Challenge 1 - Decide Which Sovereign Requirements Apply to an Application

> **Status: tested locally (23 Nov 2026)** with Python 3.13 on Windows. Outputs below are from that run; your paths differ.

**Estimated duration:** to be measured in the [validation run](../validation-run.md).

[Challenge](../../challenges/challenge-01.md) | [Home](../../Readme.md)

## Prerequisites

Complete the [prerequisites of challenge 1](../../challenges/challenge-01.md#prerequisites) before you start. Run every command from the repository root.

## Tasks

### Task 1: Extract the pinned catalogue

```bash
python tools/gspp/extract.py
```

Expected output (the commit and digest are those in the `catalogue` block of `resources/catalogue-mapping.json`):

```text
Catalogue https://raw.githubusercontent.com/BSI-Bund/Stand-der-Technik-Bibliothek/<pinned commit>/control_layer/Grundschutz%2B%2B/Grundschutz%2B%2B-resolved_catalog.json
Pinned at <pinned commit> by .../resources/catalogue-mapping.json
Wrote 1000 controls to .../tools/gspp/out/gspp-extract.csv (SHA-256 <pinned digest>)
```

The script stops if the downloaded file has another digest: the pin protects you from an upstream change you have not reviewed. The pin is the `catalogue` block of `resources/catalogue-mapping.json` (repository, path, commit, SHA-256); to adopt a newer BSI release, follow [Upgrade the catalogue](../../resources/README.md#upgrade-the-catalogue). The CSV holds each control's ID, title, group, parent, modal verb, security level, parameters and the first 300 characters of its statement. It is git-ignored; keep it local.

### Task 2: Read the application profile

`resources/profiles/leave-planner.json` describes the lab application. The facts that decide applicability:

| Fact | Value | Effect |
|---|---|---|
| `archetype` | `corp` | Must satisfy the Corp constraints in `resources/archetypes.json`: not internet-facing, protection need normal |
| `protection_need` | `normal` | Elevated-level requirements do not apply |
| `internet_facing` | `false` | Requirements for access from external networks do not apply |
| `personal_data`, `stores_data` | `true`, `true` | Data requirements apply |
| `resource_types` | App Service, Azure SQL Database, Storage, Key Vault, virtual network | Selects the candidate controls; no virtual machines |

A profile that breaks its archetype's constraints is refused, so every result starts from a consistent description.

### Task 3: Derive the applicable requirements

```bash
python tools/gspp/applicability.py --profile leave-planner
```

The script applies four rules to each of the 23 mapped requirements:

1. The profile must satisfy its archetype's constraints.
2. An elevated-level requirement applies only when the protection need is high.
3. Every `applies_when` condition in the mapping must hold for the profile.
4. Candidate controls are kept when they fit the application's resource types and archetype.

Expected summary and tables (the candidate-controls column is shortened here):

```text
## Leave planner (Corp, protection need normal)

17 of 23 mapped requirements apply. Azure Policy coverage: full 2, partial 7, none 8.
```

| Requirement | Verb | Route | Policy coverage | Candidate controls (shortened) |
|---|---|---|---|---|
| BES.2.2 | SOLLTE | azure-policy | partial | Allowed locations; Allowed locations for resource groups |
| BES.4.8.2 | SOLLTE | attestation | none | Provider's third-party attestation (for example a C5 type 2 report) |
| DLS.3.1.1 | SOLLTE | attestation | none | Recurring review of the provider's attestation |
| KONF.14.1 | SOLLTE | azure-policy | full | Secure transfer to storage accounts; App Service HTTPS only; SQL TLS 1.2 |
| KONF.14.1.1 | SOLLTE | azure-policy | full | Storage minimum TLS version; App Service latest TLS; SQL TLS 1.2 |
| DET.3.1 | SOLLTE | azure-policy | partial | Diagnostic settings for App Service, Key Vault, SQL and Storage |
| DET.3.1.8 | SOLLTE | azure-policy | partial | Activity log to Log Analytics; Entra audit logs to the same workspace |
| BER.5.9 | SOLLTE | entra | partial | Conditional Access with phishing-resistant MFA; PIM; MFA policy for resource writes |
| ARCH.5.2 | SOLLTE | azure-policy | partial | Public network access disabled on Storage, SQL, Key Vault |
| ARCH.5.1 | SOLLTE | azure-policy | partial | Subnets associated with a network security group |
| NOT.4.3 | SOLLTE | azure-policy | none | Azure SQL Database automated backups (platform default) |
| NOT.4.16.1 | SOLLTE | attestation | none | Restore test recorded by the application owner |
| DET.5.3 | SOLLTE | attestation | none | Vulnerability-scan procedure; Defender for Cloud findings (paid) |
| ASST.2.4 | SOLLTE | purview | partial | Protection-need class in the profile; Require a tag; Purview labels (paid) |
| ASST.2.1 | SOLLTE | purview | none | Information inventory with the profile; Resource Graph; Purview data map (paid) |
| UMS.5.1 | MUSS | attestation | none | Exception approved by pull request by a named person in the authorising role |
| UMS.5.2 | MUSS | attestation | none | Exception record with justification, risk owner and expiry; Policy exemption only from that record |

| Not applicable | Verb | Level | Reason |
|---|---|---|---|
| BES.2.3 | KANN | elevated | Elevated-level requirement; the protection need is normal. |
| KONF.11.8 | KANN | elevated | Elevated-level requirement; the protection need is normal. |
| DET.3.2 | KANN | elevated | Elevated-level requirement; the protection need is normal. |
| BER.5.8 | SOLLTE | normal | The application is not reachable from external networks. |
| NOT.4.12 | KANN | elevated | Elevated-level requirement; the protection need is normal. |
| DET.5.10.2 | SOLLTE | normal | No virtual machines: the provider patches the platform of the PaaS services. |

The script also writes `tools/gspp/out/applicability-leave-planner.json`. Challenges 2 to 4 read it. Each entry carries `id`, `applicable` and `reason`, plus route, policy coverage, deviation path, owner, candidate controls, evidence and gap; the format is `resources/schemas/applicability.schema.json`.

Policy coverage means: `full`, a built-in Azure Policy definition checks the requirement as mapped; `partial`, policy checks part of it and the `gap` field names the rest; `none`, no policy definition fits this application.

To compare applications, run `python tools/gspp/applicability.py --all`:

| Profile | Archetype | Applicable of 23 | Policy coverage full / partial / none |
|---|---|---|---|
| leave-planner | Corp | 17 | 2 / 7 / 8 |
| asset-inventory | Corp | 16 | 2 / 6 / 8 |
| build-runners | Corp | 14 | 1 / 7 / 6 |
| document-archive | Corp | 18 | 3 / 9 / 6 |
| team-wiki | Corp | 16 | 2 / 6 / 8 |
| public-website | Online | 13 | 2 / 4 / 7 |
| appointment-booking | Online | 17 | 2 / 5 / 10 |
| open-data-api | Online | 17 | 2 / 5 / 10 |
| case-records | Confidential Corp | 21 | 4 / 8 / 9 |
| fraud-analytics | Confidential Corp | 22 | 5 / 10 / 7 |

### Task 4: Check the IDs against the pinned catalogue

```bash
python tools/gspp/check_ids.py tools/gspp/out/applicability-leave-planner.json
```

Expected output (the file count grows as the kit grows):

```text
Checked 81 requirement IDs in 4 files against 1000 catalogue controls.
Scanned 40 kit files for copied catalogue text.
OK: every ID exists, verbs and levels match, no catalogue text found.
```

It checks the mapping, the archetypes, the Azure component and your result. A wrong ID, modal verb or security level, or a catalogue title or statement copied into the kit, fails the check.

### Task 5: Review three candidate mappings

Print the requirement text from your local extract, for example:

```bash
python -c "import csv; [print(r['id'], r['modal_verb'], r['statement_300'], sep=' | ') for r in csv.DictReader(open('tools/gspp/out/gspp-extract.csv', encoding='utf-8')) if r['id'] in ('BES.2.2', 'ARCH.5.1', 'UMS.5.2')]"
```

Compare each with its candidate controls and `gap` in the result. Examples of what a reviewer finds:

- **BES.2.2:** Allowed locations enforces the region of regional resources; global resources and the provider's jurisdiction still need a written decision.
- **ARCH.5.1:** the policy checks that a network security group exists, not that its rules restrict connections.
- **UMS.5.2:** the evidence is the exception record in the repository; an Azure Policy exemption alone can omit its expiry date.

The mapping is a candidate: no information-security expert has reviewed it. Disagreements are the point of this task.

### Task 6: Name the coverage gaps

Eight applicable requirements have policy coverage `none`. They route elsewhere:

| Route | Requirements | Evidence instead of a policy |
|---|---|---|
| attestation | BES.4.8.2, DLS.3.1.1 | Provider's attestation report and its recorded review |
| attestation | NOT.4.16.1, DET.5.3 | Restore test and vulnerability procedure recorded in the repository |
| attestation | UMS.5.1, UMS.5.2 | Exception pull request with approver, risk owner and expiry |
| purview | ASST.2.1 | Information inventory kept with the profile; Purview optional |
| azure-policy | NOT.4.3 | Platform default backups; no built-in definition in this slice audits the rest |

A sample answer for the success criterion: *UMS.5.2 (MUSS) cannot be enforced by Azure Policy; it routes to the exception process, where a pull-request check requires justification, risk owner and expiry before any Policy exemption is created.*

Why elevated-level requirements drop out: the mapping marks BES.2.3, KONF.11.8, DET.3.2 and NOT.4.12 as elevated level, and the rule applies them only to applications with high protection need. Run `python tools/gspp/applicability.py --profile case-records` to see them apply to a Confidential Corp application.

### Task 7 (optional): Validate the Azure OSCAL component

```bash
python tools/oscal/build_component.py --check
python -m pip install -r tools/oscal/requirements.txt
python tools/oscal/validate.py
```

Expected output:

```text
azure-component-definition.json is up to date with catalogue-mapping.json.
Valid against NIST OSCAL 1.1.3 component schema (SHA-256 9bde069f8f65).
Valid against NIST OSCAL 1.2.2 component schema (SHA-256 3b6e0765c440).
References OK: 49 unique UUIDs, sources resolve to back-matter, roles defined.
```

`resources/azure-component-definition.json` is generated from the same mapping: 6 components (Azure Policy, Microsoft Entra ID, Azure platform defaults, Defender for Cloud, Purview, attestation and exception process) and 34 implemented requirements. The validator downloads the NIST schemas once, checks their digests and caches them in `tools/oscal/out/`.

### Clean up

`git status` shows nothing from `tools/gspp/out/` or `tools/oscal/out/`; both are git-ignored.
