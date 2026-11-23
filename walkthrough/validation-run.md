# Live validation record

**Status (23 Nov 2026): the functional path through challenges 1 to 4 was exercised by the maintainer.** Challenge 1 ran locally; challenges 2 to 4 used live Azure and GitHub with lab self-approval. Branch protection was unavailable, so required-check merge blocking was not validated. Full lab teardown, attributable cost and a first-time participant's clean-subscription run remain pending. This is a lab observation, not an assurance or compliance claim.

## Live Azure results

The run used one disposable resource group in Germany West Central. Identifiers and raw logs are intentionally omitted.

| Check | Observation | Result |
|---|---|---|
| Corp policy assignment | Deployed at the lab resource-group scope; all 13 parameters match the generated archetype | Pass |
| Secure transfer disabled | Storage-account request rejected; matching Azure Policy Deny event recorded | Pass |
| Disallowed region | Storage-account request rejected; matching Azure Policy Deny event recorded | Pass |
| Anonymous blob access | Creation requested public blob access; resulting `allowBlobPublicAccess` was `false`. A separate retest excluded the lab account from inherited Modify policies and again requested `true`; Azure returned `false`. The temporary exclusion was removed and public network access remained disabled | Pass |
| Infrastructure encryption | Compliant test account reports infrastructure encryption enabled | Pass |
| Public network access | Original activity log: inherited Modify rewrote `Enabled` to `Disabled`. Retest at 10:49 UTC on 23 Nov: the excluded test request returned HTTP 403 `RequestDisallowedByPolicy`. The retained ARM response names assignment `gspp-corp`, reference `exposure-public-network-access`, effect `Deny`, and evaluated value `Enabled`. The resource was absent before and after the request | Pass |
| Key Vault diagnostics | The `setByPolicy-LogAnalytics` diagnostic setting appeared, with the audit category routed to the lab workspace | Pass |
| Compliance scan | All `gspp-corp` states match the challenge 2 table: only `encryption-infrastructure` (B) and `backup-geo-redundant-storage` (B, C) are non-compliant | Pass |
| Challenge 3, task 1 | Compliant account created; disabling secure transfer rejected by `transport-secure-transfer` | Pass |
| Challenge 3, task 2 | Exception repository created with lab self-approval. Branch protection on a private repository under GitHub Free returned HTTP 403; the run continued without it | Setup passed; merge gate unvalidated |
| Challenge 3, task 3 | In GitHub Actions, `validate` passed and `decision` reported `WAITING` with the `/approve` hint | Pass |
| Challenge 3, task 4 | Residency request refused (STM.2.1.7 is MUSS); request without expiry refused; both closed unmerged | Pass |
| Challenge 3, task 5 | A Comment review starting `/approve` started a second run whose `decision` reported `APPROVED … (lab self-approval)`. The first run's failed `decision` stayed listed until re-run; the re-run also passed | Pass |
| Challenge 3, task 6 | `apply` created the Waiver with expiry, decision link, approver and `approvalMode: lab-self-approval`; the update denied in task 1 then succeeded; `transport-secure-transfer` became `Exempt` | Pass |
| Challenge 3, task 7 | After the expiry, a scan showed `transport-secure-transfer` `NonCompliant`; `apply --dry-run` reported `EXPIRED` and created nothing; secure transfer restored | Pass |
| Challenge 3, task 8 | Exemption and exception storage account deleted; no exemption left in the group | Pass |
| Challenge 4, tasks 2 and 3 | Snapshot: 1 exemption (none inherited), 3 exception pull requests. Pack: 2 fulfilled, 6 not applicable, 2 not fulfilled, 13 unresolved | Pass |
| Challenge 4, task 4 | KONF.14.1 recorded as `approved-temporary`, its basis disclosing lab self-approval; UMS.5.1 fulfilled with 2 refused requests counted | Pass |
| Challenge 4, task 5 | Regenerating gave byte-identical output; evaluating 48 hours later turned 4 statuses `unresolved` | Pass |
| Challenge 4, task 6 | After the expiry, KONF.14.1 and KONF.14.1.1 lost the approved deviation; UMS.5.1 counted 0 exemptions in force | Pass |
| Lab teardown and attributable cost | Not yet run; billing data not yet attributable | Pending |

Hosting tenants can assign their own Modify or Deny policies that run before or beside the lab's. A successful property change is not enough to attribute an effect to the lab: inspect the policy assignment in the activity log or ARM denial response. Retest requests, raw responses and HTTP metadata are retained privately; tenant identifiers and tenant-specific exclusion mechanisms are not published. The tests touched only resources created for this run; pre-existing resources were not changed.

## Timing

Measured by the maintainer, not by a first-time participant:

| Step | Duration |
|---|---|
| One `az policy state trigger-scan` on the lab group | About 12 minutes, twice |
| Challenge 3 tasks 2 to 6, scripted, excluding scans | About 10 minutes |
| GitHub Actions run of both checks | Under 1 minute |
| Wait from task 6 to the exemption expiry | The expiry you choose; the walkthrough uses 3 hours, the validation run used 100 minutes |

## Local checks

From the repository root, the four focused suites passed: GS++ (30 tests), doctrine (32), OSCAL (7, 2 skipped), and exemptions (49, 1 skipped). The lab automation safety harness passed. Challenge 1 extracted the pinned catalogue, generated all 10 profiles, checked 81 requirement-ID uses across four files, and found no copied catalogue text. The doctrine check passed.

```powershell
python -m unittest discover -s tools\gspp -p test_*.py -q
python -m unittest discover -s tools\doctrine -p test_*.py -q
python -m unittest discover -s tools\oscal -p test_*.py -q
python -m unittest discover -s tools\exemptions -p test_*.py -q
pwsh -NoProfile -File labautomation\test-lab.ps1
```

These are maintainer-run checks, not an independent novice run. Learner time, expert agreement and time saved against manual work have not been measured.

## Cost and limits

Azure Policy has no direct charge. A pre-deployment shared-subscription total is not the lab's cost. This run's attributable cost is pending billing data. Log Analytics ingestion and the sandbox's already-enabled Defender plans can incur usage-based charges; their settings were not changed.

Do not treat an empty billing view as zero cost. Keep actual cost pending until usage posts and can be attributed. Before ending the run, complete the [lab teardown](../labautomation/README.md#finish-including-after-a-failure) and record what remains.
