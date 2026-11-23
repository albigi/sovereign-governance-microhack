# Walkthrough Challenge 4 - Generate Audit Evidence as a By-product of Change

> **Status: tasks 1 to 6 validated live (23 Nov 2026).** Task 1 and the JSON example in task 4 use the fixtures in [`tools/exemptions/fixtures/`](../../tools/exemptions/fixtures/); the other outputs match the live run. See the [validation record](../validation-run.md).

**Estimated duration:** to be measured in the [validation run](../validation-run.md).

[Challenge](../../challenges/challenge-04.md) | [Home](../../Readme.md)

## Prerequisites

Complete the [prerequisites of challenge 4](../../challenges/challenge-04.md#prerequisites) before you start. Use the PowerShell 7 session of [walkthrough 3](../challenge-03/solution-03.md), with `$kit`, `$repoDir`, `$sub` and `$group` set. Use `py -3` instead of `python` on Windows if `python` is not on your path.

This challenge creates no Azure resources. It reads policy state, exemptions and pull requests, and writes files to the git-ignored `out/` folder of your exception repository.

Order of work: walkthrough 3 tasks 1 to 6, this walkthrough tasks 1 to 5, then after the expiry walkthrough 3 task 7, task 6 here, and walkthrough 3 task 8.

## Task 1: Try the generator offline

From the repository root, generate a pack from the fixture snapshot. It needs no Azure or GitHub access:

```powershell
Set-Location $kit
$fixtures = 'tools/exemptions/fixtures'
python tools/exemptions/evidence.py generate --snapshot "$fixtures/snapshot.json" `
  --exemptions-dir "$fixtures/exemptions" --initiative "$fixtures/initiative.json" `
  --catalogue "$fixtures/catalogue.csv" --scope "$fixtures/scope.json" `
  --out tools/exemptions/out/fixture.oscal.json --summary tools/exemptions/out/fixture.md
```

Expected:

```text
Wrote tools/exemptions/out/fixture.oscal.json: 4 fulfilled, 1 not-applicable, 2 not-fulfilled, 1 unresolved
```

Open `tools/exemptions/out/fixture.md`. Its rows, shortened:

| Requirement | Verb | Status | Deviation | Basis |
|---|---|---|---|---|
| BES.2.2 | SOLLTE | fulfilled | - | `stmhexample01exc against gspp-corp/residency-allowed-locations: Compliant` |
| DET.3.1.8 | SOLLTE | unresolved | - | activity logs are assessed at platform scope, not by the lab initiative; no observation in the snapshot |
| KONF.11.8 | KANN | not-applicable | - | the reason from the scope file |
| KONF.14.1 | SOLLTE | not-fulfilled | `exc-legacy-client-transfer` until 2026-12-04, decision link | `… Exempt; approved temporary deviation … approved by @risk-owner in …/pull/1` |
| KONF.14.1.1 | SOLLTE | not-fulfilled | same | same |
| STM.2.1.7 | MUSS | fulfilled | - | residency policy `Compliant` |
| UMS.5.1 | MUSS | fulfilled | - | `1 exemption(s) in force and each meets the check (…); 1 request(s) refused, 0 pending` |
| UMS.5.2 | MUSS | fulfilled | - | same count, file-completeness check |

## Task 2: Snapshot the lab

```powershell
Set-Location $repoDir
git switch main
git pull --ff-only
python tools/gspp_extract.py --output tools/out/gspp-extract.csv    # skip if it exists from walkthrough 3
az policy state trigger-scan --resource-group $group                # fresh results; takes minutes
python tools/evidence.py collect
```

Expected:

```text
Wrote out/snapshot.json: <n> policy states, 1 exemptions, 3 exception pull requests
```

`collect` reads the lab resource group from `lab.json`. It records every policy state in the group with its requirement groups, every policy exemption that applies there, and each pull request that touched `exemptions/` with its reviews. The exemption list includes exemptions inherited from the subscription or a management group. If you see more than one, those extra exemptions are in force over your lab without a decision in this repository, and task 4 reports them.

## Task 3: Generate the evidence pack

```powershell
$scopeFile = Join-Path $kit 'tools/gspp/out/applicability-leave-planner.json'
python tools/evidence.py generate --snapshot out/snapshot.json --scope $scopeFile --summary out/evidence.md
```

Expected: `Wrote out/evidence.oscal.json:` followed by counts per status that add up to the requirements in your applicability file: 23 for the leave planner, 6 of them not applicable. The live run gave `2 fulfilled, 6 not-applicable, 2 not-fulfilled, 13 unresolved`, the same counts as the fixture snapshot with the leave-planner scope.

Read two different questions in each finding: **why is it in scope?** (`applicability-reason`, from challenge 1) and **what was observed?** (the finding's basis and linked observations). `policy_coverage` describes candidate definitions, not observations. Even `full` with no matching observation stays unresolved. For BES.2.2, the location check is compliant but covers only part of the requirement. Conversely, `none` does not rule out other sources: the approved pull request provides process evidence for UMS.5.1. This collector does not import Entra logs, Purview records or manual attestations; requirements that need those sources stay unresolved here.

The generator uses the verbs from the pinned catalogue extract (`lab.json`), your initiative and the applicability file. It stops if they disagree. Every input file is listed in the pack's back matter with its SHA-256 hash, relative to the repository or by file name only, so the pack carries no local paths.

## Task 4: Find the deviation and the human decision

Open `out/evidence.md`, or read the findings in the OSCAL file:

```powershell
$pack = Get-Content out/evidence.oscal.json -Raw | ConvertFrom-Json
$pack.'assessment-results'.results[0].findings |
  Where-Object { $_.target.'target-id' -in 'KONF.14.1', 'UMS.5.1' } |
  Select-Object title, description, props | ConvertTo-Json -Depth 5
```

Expected for KONF.14.1 (fixture values shown):

```json
{
  "title": "KONF.14.1 (SOLLTE): not-fulfilled",
  "description": "stmhexample01exc against gspp-corp/transport-secure-transfer: Exempt; approved temporary deviation exc-legacy-client-transfer until 2026-12-04T00:00:00Z, approved by @risk-owner in https://github.com/owner/lab-exceptions/pull/1",
  "props": [
    { "name": "gspp-status", "value": "not-fulfilled" },
    { "name": "modal-verb", "value": "SOLLTE" },
    { "name": "deviation", "value": "approved-temporary" },
    { "name": "exemption", "value": "exc-legacy-client-transfer" },
    { "name": "expires-on", "value": "2026-12-04T00:00:00Z" },
    { "name": "decision-record", "value": "https://github.com/owner/lab-exceptions/pull/1" }
  ]
}
```

(Each property also carries `"ns": "urn:requirement-to-evidence:v1"`.)

An exempt resource does not fulfil the requirement. The pack records an approved deviation only for explicitly cited SOLLTE groups: the named risk owner must have approved the final commit of the merged request, and the Azure exemption must still match its scope, assignment, policy references, category and expiry. Otherwise the finding has no `deviation` property and its basis names the missing evidence or mismatch. UMS.5.1 checks who approved; it does not by itself prove that the deployed exemption still matches the file.

UMS.5.1 (MUSS) has no Azure Policy result at all. It is fulfilled by named human decisions: every exemption in force was approved by its risk owner. The basis counts the refused requests from challenge 3 as well. An exemption without a kit decision record in force over your lab, for example an inherited one, makes UMS.5.1 not fulfilled. Because your exception repository uses lab self-approval, the basis and the deviation say so: an auditor would not accept a self-approved exception, and without `selfApproval` the same pull request leaves UMS.5.1 not fulfilled.

## Task 5: Reproduce, then let the evidence age

```powershell
python tools/evidence.py generate --snapshot out/snapshot.json --scope $scopeFile --out out/second.oscal.json
python tools/evidence.py compare out/evidence.oscal.json out/second.oscal.json
```

Expected:

```text
byte-identical
0 status difference(s)
```

The evaluation time defaults to the snapshot's collection time, and identifiers are derived from content, so the same inputs always give the same bytes. Now evaluate the same snapshot two days later:

```powershell
$later = (Get-Date).ToUniversalTime().AddHours(48).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
python tools/evidence.py generate --snapshot out/snapshot.json --scope $scopeFile --as-of $later --out out/later.oscal.json
python tools/evidence.py compare out/evidence.oscal.json out/later.oscal.json
```

Expected: every status that rested on policy results or exemptions turns `unresolved`, and `compare` exits with code 1. With the leave-planner scope, as in the live run:

```text
files differ in bytes
KONF.14.1: not-fulfilled (approved-temporary until <expiry>) -> unresolved
KONF.14.1.1: not-fulfilled (approved-temporary until <expiry>) -> unresolved
UMS.5.1: fulfilled -> unresolved
UMS.5.2: fulfilled -> unresolved
4 status difference(s)
```

With the fixture scope of task 1, BES.2.2 and STM.2.1.7 also turn `unresolved`: 6 differences.

Evidence older than 36 hours proves nothing about today. Use `--max-age-hours` to set your own limit.

## Task 6: After the expiry

Run this after [walkthrough 3 task 7](../challenge-03/solution-03.md#task-7-after-the-expiry), before you fix the storage account. Then finish with walkthrough 3 task 8.

```powershell
python tools/evidence.py collect --out out/after-expiry.json
python tools/evidence.py generate --snapshot out/after-expiry.json --scope $scopeFile --out out/after.oscal.json
python tools/evidence.py compare out/evidence.oscal.json out/after.oscal.json
```

Expected, as in the live run:

```text
files differ in bytes
KONF.14.1: not-fulfilled (approved-temporary until <expiry>) -> not-fulfilled
KONF.14.1.1: not-fulfilled (approved-temporary until <expiry>) -> not-fulfilled
2 status difference(s)
```

The basis changes from `Exempt` to `NonCompliant`. The deviation ended with its approval. The requirement stays not fulfilled, and is no longer covered by a decision, until someone fixes the resource or a new request is approved. UMS.5.1 now counts 0 exemptions in force.

## Limits of this lab

| Shortcut | Why | Production answer |
|---|---|---|
| A snapshot you collect by hand | Reproducible and easy to inspect | A scheduled workflow with a read-only federated identity collects, generates and publishes the pack |
| The pack is a local file | Keeps the lab self-contained | Store each pack as a signed, retained build artifact |
| Apart from exception decisions, only policy observations are collected | A candidate control is not proof; a record held elsewhere was not examined | Collect dated Entra, Purview or attestation records from the named owner and link them to the requirement |
| 36 hours of freshness | A kit default | Your audit policy sets the limit |
| The catalogue mapping from challenge 1 is a candidate | It is the kit's mapping, not an official one | Confirm the mapping with your information-security officer |
