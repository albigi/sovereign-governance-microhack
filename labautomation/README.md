# Set up and remove a lab sandbox

The bootstrap creates **one empty resource group**. It does not install a workload, assign policy, grant permissions or enable paid services. Challenge 2 adds the policy lab; keep its assignments and test resources in this group. The default script action only compiles Bicep.

## Check locally (no subscription)

From the repository root, use PowerShell 7, Azure CLI and its Bicep compiler (`az bicep install` if missing).

```powershell
./deploy-lab.ps1                # compile main.bicep; no sign-in
./test-lab.ps1                  # exercise the CLI wrapper with a test double; check the default region
```

These are not Azure validation, what-if, deployment, or measured challenge results. Use the [run record](../walkthrough/validation-run.md) to distinguish them.

## Rehearse all four handoffs without a sandbox

This path needs the completed files for all four challenges, Python 3 and the tools above, but **no Azure sign-in, GitHub repository or model calls**. "Offline" here permits HTTPS downloads of the pinned public catalogue and NIST schemas; it is not an air-gapped run. Keep downloaded catalogue text and generated outputs local. On Windows, use `py -3.13` in place of `python` if the Store alias masks the installed interpreter. OSCAL validation needs the packages in `tools/oscal/requirements.txt`; install them with `python -m pip install -r tools/oscal/requirements.txt` if missing.

From `kit`, derive the application scope, generate the policy set and compile, without deploying:

```powershell
python tools\gspp\extract.py
python tools\gspp\applicability.py --all
python tools\gspp\check_ids.py tools\gspp\out\applicability-leave-planner.json
python tools\oscal\build_component.py --check
python tools\oscal\validate.py
python tools\doctrine\doctrine.py classify --applicable tools\gspp\out\applicability-leave-planner.json
python tools\doctrine\doctrine.py generate
python tools\doctrine\doctrine.py check
pwsh -NoProfile -File labautomation\deploy-lab.ps1
pwsh -NoProfile -File labautomation\test-lab.ps1
az bicep build --file resources\archetype-initiative\policyset.bicep --stdout | Out-Null
az bicep build --file resources\archetype-initiative\assignment.bicep --stdout | Out-Null
```

Check each command's exit code before continuing; every command above should exit 0. For the exception checks, use the example's synthetic group and a **fixed example clock**, not a real resource or approval. These commands exercise the generated policy set and downloaded catalogue together:

```powershell
$checks = @('--initiative', 'resources\archetype-initiative\policyset.json',
    '--catalogue', 'tools\gspp\out\gspp-extract.csv', '--resource-group', 'rg-mh-example01',
    '--as-of', '2026-11-20T12:00:00Z')
python tools\exemptions\exemptions.py validate resources\exemptions\examples\exc-legacy-client-transfer.json @checks
python tools\exemptions\exemptions.py validate resources\exemptions\examples\exc-residency-outside-region.json @checks
python tools\exemptions\exemptions.py validate resources\exemptions\examples\exc-no-expiry.json @checks
```

Expected exits: 0 (permitted request), 1 (a non-waivable MUSS requirement behind the reference), 1 (missing expiry). This checks request validity, **not approval or creation**. Do not run `apply`, even with `--dry-run`: that command still reads GitHub decision history.

Generate twice using the frozen synthetic snapshot, but the **real outputs of challenges 1 and 2**:

```powershell
$inputs = @('--snapshot', 'tools\exemptions\fixtures\snapshot.json',
    '--exemptions-dir', 'tools\exemptions\fixtures\exemptions',
    '--initiative', 'resources\archetype-initiative\policyset.json',
    '--catalogue', 'tools\gspp\out\gspp-extract.csv',
    '--scope', 'tools\gspp\out\applicability-leave-planner.json')
python tools\exemptions\evidence.py generate @inputs --out tools\exemptions\out\offline.oscal.json --summary tools\exemptions\out\offline.md
python tools\exemptions\evidence.py generate @inputs --out tools\exemptions\out\offline-repeat.oscal.json
python tools\exemptions\evidence.py compare tools\exemptions\out\offline.oscal.json tools\exemptions\out\offline-repeat.oscal.json
```

Expected: 2 fulfilled, 6 not-applicable, 2 not-fulfilled and 13 unresolved; then `byte-identical`, `0 status difference(s)` and exit 0. The snapshot's evaluation time is frozen; its approvals and observations are fixtures, not actions performed by this rehearsal. Run the existing tests separately with `python -m unittest discover -s tools\<gspp|oscal|doctrine|exemptions>` (replace the angle-bracket choice with one directory). For official evidence-schema validation, follow the schema setup in the [run record](../walkthrough/validation-run.md#supplementary-checks).

Do not run the live prerequisite lookups, deployment, collection, policy scan, GitHub workflow or cleanup commands from the challenge solutions during this path. Azure effects, real approval checks, expiry, telemetry and teardown remain **UNVALIDATED**. This path can stand alone as a fixture exercise; it cannot replace the sandbox challenges.

## Start a live run only after approval

Use a disposable sandbox subscription, never a production subscription. Obtain dated approval covering this specific lab, maximum amount, currency, period and cleanup owner/deadline. Check existing assignments for inherited deployments or paid plans; stop if their cost or scope is unclear. The switch below acknowledges approval; it does not enforce a budget.

The bootstrap operator needs permission to read subscription Defender pricing, create subscription deployments and create, read and delete resource groups. Before the first write, Deploy checks that Defender for Storage, Defender for Key Vault and Defender CSPM (cloud security posture management) each report `Free`. An unreadable or paid plan stops setup. The stop comes before any write, so there is nothing to remove; record it as an aborted attempt. Use another sandbox rather than turning protection off or editing the check. Only a sandbox that already pays for these plans, with an owner who has approved that inherited exposure, may use the [explicit opt-in](#if-the-sandbox-already-pays-for-defender-plans). The Free-only check is not a forecast of every inherited cost: a lab estimate that assumes Free plans does not cover a subscription with paid ones.

Before Deploy, check the [prerequisites of challenge 2](../challenges/challenge-02.md#prerequisites): the participant's rights, a region that the Corp archetype allows, and one lab run per subscription at a time, because its policy set name is subscription-wide. Do not grant the lab a tenant-wide role.

```powershell
# After signing in with az login, select the approved subscription locally.
$sub = Read-Host 'Approved sandbox subscription ID'
az account set --subscription $sub
if ($LASTEXITCODE) { throw 'Could not select the sandbox.' }
$run = [guid]::NewGuid()
$run.ToString()                 # keep privately with the target BEFORE deployment
$group = ./deploy-lab.ps1 -Action Deploy -SubscriptionId $sub -RunId $run -SpendApproved
$group                          # pass this group to the challenges
```

The default region is in `lab-defaults.json`; `test-lab.ps1` checks it against `allowed_locations` of the Corp archetype in `resources/archetypes.json`. Use `-Location` on Deploy only for another approved, priced region that Corp allows; otherwise challenge 2 stops at its prerequisites. The group is `rg-mh-` followed by the run ID without hyphens. The script refuses an existing group. Do not retry a partial deployment with a fresh ID until you have checked the old group and cleaned it up. Keep run details locally, not in a public log.

Return to the [kit entry point](../Readme.md). Record the baseline, elapsed times, errors and any scope outside the group as you go. Capture evidence **before** cleanup.

### If the sandbox already pays for Defender plans

The default stays Free-only. If the only sandbox you may use already runs Standard Defender for Storage, Defender for Key Vault or Defender CSPM, the approving owner can accept exactly those plans for one run. The opt-in lets Deploy continue; it never creates, changes or disables a plan, and removal and ownership checks are unchanged.

Before you use it:

- The approval names the inherited exposure in its own currency and has a period that covers the run.
- Take a cost baseline of the subscription (by service or meter) before Deploy. Existing resources keep billing under these plans whether or not the lab runs; without a baseline the lab's share cannot be separated.
- Inherited plan charges are on top of any estimate that assumes Free plans. Each plan charges per resource-hour, so exposure is the hours a lab resource exists times the hourly price below.

| Plan | Meter | List price | Lab resources affected |
|---|---|---|---|
| Defender for Storage | per storage account per hour | USD 0.0134 | storage accounts the challenges create, while they exist |
| Defender for Storage | malware scanning per GB scanned | USD 0.15 | none: the lab uploads no data |
| Defender for Key Vault | per vault per hour | USD 0.00034 | the one vault of challenge 2 |
| Defender CSPM | per billable resource per hour | USD 0.007 | storage accounts; Key Vaults are not billable resources |

Source: [Azure Retail Prices API](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices), `serviceName eq 'Microsoft Defender for Cloud'`, Germany West Central where priced by region, queried 22 Nov 2026. USD list prices exclude agreements, discounts and exchange rates, and a newer CSPM meter is dated 1 Oct 2026: check your own price sheet and which meter applies.

```powershell
$group = ./deploy-lab.ps1 -Action Deploy -SubscriptionId $sub -RunId $run -SpendApproved `
    -AcceptPaidDefenderPlans StorageAccounts, KeyVaults, CloudPosture `
    -ApprovalReference '<where the dated approval is recorded>' `
    -ApprovalExpires '<end of the approved period, as a date and time>' `
    -ApprovalCurrency '<three-letter code from the approval>' `
    -ApprovalCeiling <maximum amount from the approval>
```

Name only the plans the approval covers. Deploy then:

1. Requires all four approval values and `-SpendApproved` before it contacts Azure. It refuses an empty reference, a past expiry, a currency that is not three uppercase letters and a ceiling that is not above zero.
2. Reads all three plans. `Free` passes; `Standard` passes only for a plan you named; any other `Standard` stops setup as before; an unreadable, empty or unrecognised tier stops setup even with the opt-in. Every stop is before any write.
3. Prints a warning listing the inherited plans with your reference, expiry, ceiling and currency, then deploys. The ceiling and currency are recorded for the run, not enforced. A shared ceiling stays shared: monitor aggregate spend and bound the run by resources, duration and cleanup deadline, rather than requiring a separate spending ceiling.

Approval values given without `-AcceptPaidDefenderPlans` are ignored and the Free-only check applies. Record the inherited plans and baseline in the run record before capturing results.

## Finish, including after a failure

1. If you started challenge 2, first run the clean-up task of its [walkthrough](../walkthrough/challenge-02/solution-02.md), also after a failed or partial run. In dependency order and by name or recorded ID, it removes only the policy objects and workspace this run created. That includes the subscription policy set unless another assignment uses it; group removal does not reach it. Never bulk-delete subscription objects.
2. With the original subscription and run ID (restore `$run` from the saved value if necessary), remove the group and everything left inside it:

   ```powershell
   ./deploy-lab.ps1 -Action Remove -SubscriptionId $sub -RunId $run
   ```

   Removal requires the selected subscription and both ownership tags to match. It waits and checks that the group is absent. A missing group on retry is safe; an error or ownership mismatch is not a teardown receipt.
3. Check the original inventory for remaining lab-owned objects, including the subscription policy set. Record the scheduled purge date of each soft-deleted vault or workspace by its run-specific name; purging is not required. Do not purge shared resources or require an entire subscription's deleted-items list to be empty. Setup's subscription deployment record (`mh-` plus the run ID) stays as a receipt, as do the challenges' deployment records. Reconcile this run's cost after usage has posted, including charges outside the group. Record the result, currency and observation window, or mark it pending. Do not equate an empty billing view with zero cost.
