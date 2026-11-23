# Live validation record

**Status (23 Nov 2026): partial.** Offline tests pass. Challenge 2 and challenge 3 task 1 behaved as expected in an isolated Azure run. The exception approval workflow, evidence-pack collection and cleanup have not been validated yet. This is a lab observation, not an assurance or compliance claim.

## Live Azure results

The run used one disposable resource group in Germany West Central. Identifiers and raw logs are intentionally omitted.

| Check | Observation | Result |
|---|---|---|
| Corp policy assignment | Deployed at the lab resource-group scope; all 13 parameters match the generated archetype | Pass |
| Secure transfer disabled | Storage-account request rejected; matching Azure Policy Deny event recorded | Pass |
| Disallowed region | Storage-account request rejected; matching Azure Policy Deny event recorded | Pass |
| Anonymous blob access | Creation requested public blob access; resulting `allowBlobPublicAccess` was `false` | Pass |
| Infrastructure encryption | Compliant test account reports infrastructure encryption enabled | Pass |
| Public network access | First attempt: an inherited tenant Modify policy rewrote `Enabled` to `Disabled` before Deny ran (activity log). With the test account excluded from that tenant policy, the request was rejected by `exposure-public-network-access` | Pass |
| Key Vault diagnostics | The `setByPolicy-LogAnalytics` diagnostic setting appeared, with the audit category routed to the lab workspace | Pass |
| Compliance scan | All `gspp-corp` states match the challenge 2 table: only `encryption-infrastructure` (B) and `backup-geo-redundant-storage` (B, C) are non-compliant | Pass |
| Challenge 3, task 1 | Compliant account created; disabling secure transfer rejected by `transport-secure-transfer` | Pass |
| Exception approval, evidence, cleanup and cost | Not completed or not yet attributable | Pending |

Hosting tenants can assign their own Modify or Deny policies that run before or beside the lab's. The tests touched only resources created for this run; pre-existing resources were not changed.

## Local checks

From the repository root, the four focused suites passed: GS++ (30 tests), doctrine (32), OSCAL (7, 2 skipped), and exemptions (45, 1 skipped). The lab automation safety harness passed. Challenge 1 extracted the pinned catalogue, generated all 10 profiles, checked 81 requirement-ID uses across four files, and found no copied catalogue text. The doctrine check passed.

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
