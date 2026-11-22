# Walkthrough Challenge 2 - Enforce Applicable Requirements with Azure Policy by a Decision Rule

> **Status: partial live validation (23 Nov 2026).** The subscription policy set and Corp assignment are deployed; all 13 assigned parameters match the generated doctrine. TLS and residency deny events were observed, anonymous-access Modify and infrastructure-encryption checks passed, and the Key Vault diagnostic setting appeared. The public-network Deny attempt was inconclusive; full policy evaluation, exceptions, evidence and teardown remain pending. See the [validation record](../validation-run.md).

**Estimated duration:** to be measured in the [validation run](../validation-run.md); its offline rehearsal times commands, not the sandbox tasks. Policy evaluation alone adds waits of about 5 and 15 minutes (task 3 and task 4).

[Challenge](../../challenges/challenge-02.md) | [Home](../../Readme.md)

## Prerequisites

Complete the [prerequisites of challenge 2](../../challenges/challenge-02.md#prerequisites). Then, in PowerShell 7 from the repository root:

```powershell
az account show --query name -o tsv                     # must be your sandbox subscription
$group   = '<lab resource group>'                       # rg-mh-... from labautomation
$loc     = az group show -n $group --query location -o tsv
$id      = $group.Replace('rg-mh-', '').Substring(0, 10) # short run ID for resource names
$receipt = Join-Path ([IO.Path]::GetTempPath()) "gspp-$id.json"
if (az policy set-definition list --query "[?name=='gspp-archetype-baseline'].id" -o tsv) {
  throw 'gspp-archetype-baseline already exists in this subscription. Another run owns it: stop, do not update or remove it.'
}
$allowed = ((Get-Content resources/archetypes.json -Raw | ConvertFrom-Json).archetypes | Where-Object id -eq 'corp').parameters.allowed_locations
if ($loc -notin $allowed) {
  throw "The lab group is in $loc, but Corp allows only $($allowed -join ', '). Create the lab group there, or pass allowedLocations in task 3."
}
```

### Rights

| Scope | Role | Why |
|---|---|---|
| Subscription | Resource Policy Contributor | create the policy set; covers the assignment, remediation and exemptions in the group |
| Subscription | permission to create deployments (`Microsoft.Resources/deployments/*`), for example a custom role | `policyset.bicep` is a subscription deployment |
| Lab resource group | Contributor | workspace, storage accounts, key vault, group deployment |
| Lab resource group | Role Based Access Control Administrator, ideally constrained to the two roles in task 3 | grant the assignment identity its remediation roles |

Owner of the sandbox subscription covers all four.

### What the lab creates

| Resource | Name | Billable meter | Removed by |
|---|---|---|---|
| Log Analytics workspace, pay-as-you-go, 30 days retention | `law-<id>` | data ingestion (key vault audit logs only) | task 7 |
| Two storage accounts, Standard_LRS, empty | `st<id>b`, `st<id>c` | capacity and transactions | lab group removal |
| Key vault, standard | `kv-<id>` | operations | lab group removal; the name stays reserved for 7 days (soft delete) |
| Policy set, policy assignment, two role assignments | `gspp-archetype-baseline`, `gspp-corp` | none | task 7 |

Three further storage accounts are attempted and denied: nothing is created.

## Task 1: Classify your requirements

Read [`resources/doctrine.md`](../../resources/doctrine.md): the rule, the deviation paths and where Azure Policy alone gives false assurance. Then:

The input is the applicability file of [challenge 1](../challenge-01/solution-01.md); the classifier takes the archetype from it (Corp for the lab application):

```powershell
python tools/doctrine/doctrine.py classify --applicable tools/gspp/out/applicability-leave-planner.json
```

Output on 20 Nov 2026:

```text
| Theme | Archetype | Requirements | Check | Route | Effect | Deviation | Notes |
|---|---|---|---|---|---|---|---|
| residency | corp | BES.2.2 (SOLLTE) | property | azure-policy | residency-allowed-locations=Deny | none |  |
| transport-encryption | corp | KONF.14.1 (SOLLTE), KONF.14.1.1 (SOLLTE) | property | azure-policy | transport-secure-transfer=Deny, transport-minimum-tls=Deny | exemption |  |
| internal-exposure | corp | ARCH.5.2 (SOLLTE) | property | azure-policy | exposure-public-network-access=Deny | exemption |  |
| segmentation | corp | ARCH.5.1 (SOLLTE) | existence | azure-policy | segmentation-subnet-nsg=AuditIfNotExists | exemption | existence check: Azure Policy reports but cannot prevent |
| anonymous-access | corp | BER.4.6 (SOLLTE) | property | azure-policy | exposure-anonymous-blob-access=Modify | exemption |  |
| security-logging | corp | DET.3.1 (SOLLTE) | existence | azure-policy | logging-key-vault-diagnostics=DeployIfNotExists | exemption |  |
| activity-logging | corp | DET.3.1.8 (SOLLTE) | existence | azure-policy | platform=DeployIfNotExists | exemption | assigned once at platform scope, outside this initiative |
| backup | corp | NOT.4.3 (SOLLTE) | existence | azure-policy | backup-virtual-machines=AuditIfNotExists | exemption | existence check: Azure Policy reports but cannot prevent |
| restore-test | corp | NOT.4.16.1 (SOLLTE) | none | process-owner | no effect | attestation-exception |  |
| strong-authentication | corp | BER.5.8 (SOLLTE), BER.5.9 (SOLLTE) | none | entra | no effect | attestation-exception |  |
| data-classification | corp | ASST.2.1 (SOLLTE), ASST.2.4 (SOLLTE) | none | data-catalogue | no effect | attestation-exception |  |
| vulnerability-handling | corp | DET.5.3 (SOLLTE) | none | process-owner | no effect | attestation-exception |  |
| provider-assurance | corp | BES.4.8.2 (SOLLTE), DLS.3.1.1 (SOLLTE) | none | provider-attestation | no effect | attestation-exception |  |
| obligation-register | corp | GC.3.1.1 (MUSS), STM.2.1.7 (MUSS) | none | named-decision | no effect | none |  |
| exception-authorisation | corp | UMS.5.1 (MUSS), UMS.5.2 (MUSS) | none | named-decision | no effect | none |  |

Applicable requirements with no theme yet (coverage gap): 0
Kept because challenge 1 does not assess them: BER.4.6, GC.3.1.1, STM.2.1.7
```

| Row | Why |
|---|---|
| residency | SOLLTE, but the obligation register (STM.2.1.7, MUSS) makes it binding: `Deny`, and no exemption |
| transport-encryption | SOLLTE, a resource property, adopted by Corp: `Deny`. A deviation needs a time-boxed exemption ([challenge 3](../../challenges/challenge-03.md)) |
| activity-logging | checked by Azure Policy, but once per subscription by the platform team: not in this initiative |
| strong-authentication | Azure Policy cannot see sign-in policy: no effect; the identity team owns it and attests |
| exception-authorisation | MUSS process duty: no effect; a named person decides, and it cannot be waived |
| coverage gap | 0: every applicable requirement has a theme. A non-zero gap lists IDs to add to `resources/doctrine.json`, or to record as needing none |
| kept | the doctrine needs these, and challenge 1 does not assess them, so they stay rather than drop silently |

The KANN themes (encryption at rest, cloud log integration, geo-redundancy, provider agreement) are absent: their requirements are at the elevated level, and challenge 1 rated the lab application normal. Repeat with `--archetype online`: `internal-exposure` becomes `Audit`, and its deviation is a change to the archetype record, not an exemption, because Online serves the internet by design.

## Task 2: Generate and review the initiative

```powershell
python tools/doctrine/doctrine.py generate
python tools/doctrine/doctrine.py check
python -m unittest discover -s tools/doctrine
az bicep build --file resources/archetype-initiative/policyset.bicep --stdout | Out-Null
az bicep build --file resources/archetype-initiative/assignment.bicep --stdout | Out-Null
git status --short resources
```

Output on 20 Nov 2026: two `NOTE` lines (the doctrine adds BER.4.6, GC.3.1.1, STM.2.1.7 and two definitions beyond the catalogue mapping), then `OK: 20 themes, 11 policies, 3 archetypes; invariants + drift + catalogue mapping`, `Ran 29 tests` and `OK`, both builds without warnings, and no changed files: the committed initiative is current. To review only your subset, run `generate --applicable <file> --out <folder>`; the lab deploys the full baseline so that every effect can be shown.

Review [`policyset.json`](../../resources/archetype-initiative/policyset.json) and [`assignments.json`](../../resources/archetype-initiative/assignments.json):

- Each group in `policyDefinitionGroups` is a GS++ requirement ID; its `category` is the modal verb.
- `residency-allowed-locations` lists BES.2.2 (SOLLTE) and STM.2.1.7 (MUSS) in `groupNames`. Because one group is MUSS, challenge 3 refuses any exemption from it.
- Effect parameters default to `Audit`, `AuditIfNotExists` or `Disabled`: the set assigned without an archetype blocks and changes nothing.
- Each archetype in `assignments.json` holds its effects, its regions and TLS version from `resources/archetypes.json`, the roles that `Modify` and `DeployIfNotExists` need, and non-compliance messages that cite the GS++ IDs and the deviation path.
- What each archetype binds, and which remediation it approves, is its `enforcement` field in [`resources/archetypes.json`](../../resources/archetypes.json). Change it there, not in the generated files.

## Task 3: Deploy and assign

```powershell
$law = az monitor log-analytics workspace create -g $group -n "law-$id" -l $loc --retention-time 30 --query id -o tsv
$set = az deployment sub create --name "gspp-baseline-$id" --location $loc `
  --template-file resources/archetype-initiative/policyset.bicep `
  --query properties.outputs.policySetDefinitionId.value -o tsv
$out = az deployment group create -g $group --name "gspp-corp-$id" `
  --template-file resources/archetype-initiative/assignment.bicep `
  -p archetype=corp logAnalyticsWorkspaceId=$law --query properties.outputs -o json | ConvertFrom-Json
@{ setId = $set; assignmentId = $out.assignmentId.value; roleAssignmentIds = $out.roleAssignmentIds.value } |
  ConvertTo-Json | Set-Content $receipt   # needed for cleanup, also after a failure
```

`allowedLocations` comes from the Corp archetype (`allowed_locations` in `resources/archetypes.json`); the prerequisites checked that the lab group is inside it. To use other regions for one assignment, pass `allowedLocations` as an array; the comparison below then shows that row as a deviation. The assignment identity gets Storage Account Contributor (for `Modify`) and Log Analytics Contributor (for `DeployIfNotExists`) on the lab group only.

Compare the assigned effects and values with the rule:

```powershell
$want = (Get-Content resources/archetype-initiative/assignments.json -Raw | ConvertFrom-Json).archetypes.corp.parameters
$got  = az policy assignment show -n gspp-corp -g $group --query parameters -o json | ConvertFrom-Json
$want.PSObject.Properties | ForEach-Object {
  $rule = ConvertTo-Json @($_.Value.value) -Compress; $assigned = ConvertTo-Json @($got.($_.Name).value) -Compress
  [pscustomobject]@{ parameter = $_.Name; rule = $rule; assigned = $assigned; match = $rule -eq $assigned }
} | Format-Table
```

Expected, not yet measured: 13 rows, `match` is `True` on each. The number of `False` rows is the value readout "deployed effects that differ from the decision rule".

Wait about five minutes before task 4: a new assignment takes about that long to apply ([Microsoft Learn, updated 18 Mar 2026](https://learn.microsoft.com/azure/governance/policy/how-to/get-compliance-data)).

## Task 4: Demonstrate each effect

```powershell
$other = @('swedencentral', 'germanywestcentral', 'westeurope') | Where-Object { $_ -notin $allowed } | Select-Object -First 1
# A1: HTTP allowed
az storage account create -g $group -n "st$($id)a" -l $loc --sku Standard_LRS --https-only false --min-tls-version TLS1_2 --public-network-access Disabled
# A2: region outside allowedLocations
az storage account create -g $group -n "st$($id)a" -l $other --sku Standard_LRS --https-only true --min-tls-version TLS1_2 --public-network-access Disabled
# A3: public endpoint
az storage account create -g $group -n "st$($id)a" -l $loc --sku Standard_LRS --https-only true --min-tls-version TLS1_2 --public-network-access Enabled
# B: anonymous blob access requested, no infrastructure encryption
az storage account create -g $group -n "st$($id)b" -l $loc --sku Standard_LRS --https-only true --min-tls-version TLS1_2 --public-network-access Disabled --allow-blob-public-access true
az storage account show -g $group -n "st$($id)b" --query allowBlobPublicAccess
# C: compliant on every policy that Corp binds
az storage account create -g $group -n "st$($id)c" -l $loc --sku Standard_LRS --https-only true --min-tls-version TLS1_2 --public-network-access Disabled --require-infrastructure-encryption true
# D: key vault without a diagnostic setting
az keyvault create -g $group -n "kv-$id" -l $loc --retention-days 7
```

Expected, not yet measured:

| Step | Result | Effect | Policy reference ID | GS++ groups |
|---|---|---|---|---|
| A1 | `RequestDisallowedByPolicy`; the reason is the non-compliance message citing KONF.14.1 | `Deny` | `transport-secure-transfer` | KONF.14.1, KONF.14.1.1 |
| A2 | `RequestDisallowedByPolicy`; the reason ends "Deviation: none: cannot be waived" | `Deny` | `residency-allowed-locations` | BES.2.2, STM.2.1.7 |
| A3 | `RequestDisallowedByPolicy` | `Deny` | `exposure-public-network-access` | ARCH.5.2 |
| B | created; `allowBlobPublicAccess` is `false` | `Modify` | `exposure-anonymous-blob-access` | BER.4.6 |
| B | created, non-compliant after evaluation | `Audit` | `encryption-infrastructure` | KONF.11.8 |
| B, C | created, non-compliant after evaluation | `Audit` | `backup-geo-redundant-storage` | NOT.4.12 |
| C | created, compliant on every other policy | none | none | none |
| D | diagnostic setting `setByPolicy-LogAnalytics` appears after evaluation | `DeployIfNotExists` | `logging-key-vault-diagnostics` | DET.3.1 |
| none | no applicable resources: the lab has no subnet | `AuditIfNotExists` | `segmentation-subnet-nsg` | ARCH.5.1 |
| none | no applicable resources: the lab has no virtual machine | `Deny`, `AuditIfNotExists` | `patching-periodic-assessment`, `backup-virtual-machines` | DET.5.10.2, NOT.4.3 |

The two `Audit` findings are KANN requirements that Corp does not select: information, not a deviation to approve. Corp deliberately keeps C locally redundant: geo-redundant storage would copy data to the paired region, outside Corp's `allowed_locations`, and the allowed-locations policy would not see it ([doctrine](../../resources/doctrine.md#where-azure-policy-alone-gives-false-assurance)).

Check D after about 15 minutes, the evaluation delay for a new resource:

```powershell
$kv = az keyvault show -g $group -n "kv-$id" --query id -o tsv
az monitor diagnostic-settings list --resource $kv --query "[].name" -o tsv
```

If the list is empty, start a remediation task, which task 7 removes:

```powershell
az policy remediation create -g $group -n "gspp-kv-diag-$id" --policy-assignment $out.assignmentId.value `
  --definition-reference-id logging-key-vault-diagnostics --resource-discovery-mode ReEvaluateCompliance
```

## Task 5: Read the evidence

```powershell
az policy state trigger-scan -g $group   # returns when the scan ends, after several minutes
az policy state list -g $group --filter "policyAssignmentName eq 'gspp-corp'" -o json | ConvertFrom-Json |
  Select-Object policyDefinitionReferenceId, @{ n = 'resource'; e = { ($_.resourceId -split '/')[-1] } }, complianceState,
    @{ n = 'groups'; e = { $_.policyDefinitionGroupNames -join ', ' } } | Sort-Object policyDefinitionReferenceId | Format-Table
az monitor activity-log list -g $group --offset 2h `
  --query "[?operationName.value=='Microsoft.Authorization/policies/deny/action'].{time:eventTimestamp, resource:resourceId}" -o table
```

Expected, not yet measured: every compliance state carries the GS++ groups of its policy, so [challenge 4](../../challenges/challenge-04.md) maps evidence to requirements without a mapping file. `st<id>b` is non-compliant on `encryption-infrastructure` and `backup-geo-redundant-storage`, `st<id>c` on `backup-geo-redundant-storage` only. A denied request creates no resource, so A1 to A3 appear as three deny events in the activity log, not as compliance states.

## Task 6: List what Azure Policy cannot enforce

```powershell
$routes = (Get-Content resources/doctrine.json -Raw | ConvertFrom-Json).routes
python tools/doctrine/doctrine.py classify --archetype corp --format json | ConvertFrom-Json |
  Select-Object -ExpandProperty rows | Where-Object route -ne 'azure-policy' |
  Select-Object theme, @{ n = 'requirements'; e = { $_.requirements.PSObject.Properties.Name -join ', ' } },
    @{ n = 'owner'; e = { $routes.($_.route).owner } }, deviation | Format-Table
```

Output on 20 Nov 2026:

```text
theme                   requirements         owner                    deviation
-----                   ------------         -----                    ---------
restore-test            NOT.4.16.1           named process owner      attestation-exception
strong-authentication   BER.5.8, BER.5.9     identity team            attestation-exception
data-classification     ASST.2.1, ASST.2.4   data owner               attestation-exception
vulnerability-handling  DET.5.3              named process owner      attestation-exception
provider-agreement      BES.2.3              procurement              not-required
provider-assurance      BES.4.8.2, DLS.3.1.1 procurement              attestation-exception
obligation-register     GC.3.1.1, STM.2.1.7  named accountable person none
exception-authorisation UMS.5.1, UMS.5.2     named accountable person none
```

8 of the 20 baseline themes are outside the view of Azure Policy, and 2 more (activity logging, cloud log integration) are checked by a platform assignment, not by `gspp-corp`. A compliance score of 100 % for `gspp-corp` covers the other 10 only; the rest need their owner's evidence, listed per route in `resources/doctrine.json`.

## Task 7: Clean up, also after a failure

Remove what depends on the assignment first, and only objects this run created, by name or recorded ID.

```powershell
$r = Get-Content $receipt -Raw | ConvertFrom-Json
# 1. Remediation task, only if you created one in task 4
az policy remediation delete -g $group -n "gspp-kv-diag-$id"
# 2. Exemptions from challenge 3: follow its walkthrough before going on
# 3. Role assignments by recorded ID, while the assignment and its identity still exist
az role assignment delete --ids @($r.roleAssignmentIds)
# 4. Policy assignment
az policy assignment delete -n gspp-corp -g $group
# 5. Policy set: this run created it (the pre-check passed); delete it only if no assignment uses it
$users = az policy assignment list --disable-scope-strict-match true -o json | ConvertFrom-Json | Where-Object { $_.policyDefinitionId -ieq $r.setId }
if ($users) { $users.id } else { az policy set-definition delete -n gspp-archetype-baseline }
# 6. Workspace, permanently
az monitor log-analytics workspace delete -g $group -n "law-$id" --force true --yes
```

If the receipt is missing because task 3 failed part-way, find the role assignments by the assignment identity: `az role assignment list -g $group --assignee (az policy assignment show -n gspp-corp -g $group --query identity.principalId -o tsv) --query "[].id" -o tsv`.

Then run **Finish** in [`labautomation`](../../labautomation/) to remove the lab group with the storage accounts and the key vault. Afterwards record the key vault's soft-delete expiry; purging is not required:

```powershell
az keyvault show-deleted --name "kv-$id" --query properties.scheduledPurgeDate -o tsv
```

The subscription deployment record `gspp-baseline-<id>` stays as a receipt, as in `labautomation`; it costs nothing.

## Value readout

Record in the [live-run template](../validation-run.md#live-run-template-not-executed) of the validation run: minutes from the start of task 1 to the end of task 3, and the number of `False` rows in task 3.
