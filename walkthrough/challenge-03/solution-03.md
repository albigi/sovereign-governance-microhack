# Walkthrough Challenge 3 - Handle a Justified Exception as a Reviewed Pull Request

> **Status: tasks 1 to 8 validated live (23 Nov 2026)** with lab self-approval and a private exception repository without branch protection. Outputs below match that run; your names and times differ. See the [validation record](../validation-run.md).

**Estimated duration:** to be measured in the [validation run](../validation-run.md).

[Challenge](../../challenges/challenge-03.md) | [Home](../../Readme.md)

## Prerequisites

Complete the [prerequisites of challenge 3](../../challenges/challenge-03.md#prerequisites) before you start. Run every command in PowerShell 7 from the repository root, in the session where you set `$sub` and `$group` during the [lab bootstrap](../../labautomation/README.md). Use `py -3` instead of `python` on Windows if `python` is not on your path.

### What this challenge creates

| Object | Where | Expected charge | Removed in |
|---|---|---|---|
| Storage account `st…exc`, Standard_LRS StorageV2, no data | Lab resource group | Capacity and transactions only; near zero without data (not yet measured) | Task 8, or the group removal |
| Policy exemption `exc-legacy-client-transfer` | On that storage account | None expected (not yet measured) | Task 8 |
| Repository `lab-exceptions` and its Actions runs | GitHub, outside Azure | No Azure charge; Actions minutes on private repositories count against your GitHub plan | Optional, task 8 |

Nothing in Azure is created outside your lab resource group.

## Task 1: Create a compliant storage account and meet the deny

```powershell
$account  = 'st' + $group.Substring(6, 19) + 'exc'     # 24 lowercase characters, unique per run
$location = az group show --name $group --query location --output tsv
az storage account create --name $account --resource-group $group --location $location `
  --sku Standard_LRS --kind StorageV2 --https-only true --min-tls-version TLS1_2 `
  --public-network-access Disabled --output none
az policy state trigger-scan --resource-group $group     # waits until the scan completes: about 12 minutes in the validation run
az policy state list --resource-group $group --filter "policyAssignmentName eq 'gspp-corp'" `
  --query "[?contains(resourceId, '$account')].{reference: policyDefinitionReferenceId, state: complianceState}" `
  --output table
```

Expected: `transport-secure-transfer` and `residency-allowed-locations` are `Compliant`.

The policy set is defined at subscription scope, but its assignment `gspp-corp` belongs to the lab resource group. Check `resources/archetype-initiative/assignments.json` under `archetypes.corp.parameters` for the effective values: `secureTransferEffect` and `residencyEffect` are both `Deny`. The defaults in `policyset.json` are not the assignment values.

Now act as the application team whose legacy batch client cannot use TLS:

```powershell
az storage account update --name $account --resource-group $group --https-only false
```

Expected: the request fails with `RequestDisallowedByPolicy`, naming assignment `gspp-corp`. Secure transfer implements two SOLLTE requirements, KONF.14.1 and KONF.14.1.1. They allow a justified, documented deviation, which is what the rest of this challenge builds.

## Task 2: Create and protect the exception repository

```powershell
$kit       = (Get-Location).Path
$repoDir   = Join-Path $HOME 'lab-exceptions'
$owner     = gh api user --jq .login
$riskOwner = $owner     # lab self-approval: you are the risk owner
python tools/exemptions/exemptions.py init-repo $repoDir --resource-group $group `
  --initiative resources/archetype-initiative/policyset.json --self-approval
Set-Location $repoDir
python tools/gspp_extract.py --output tools/out/gspp-extract.csv   # pinned catalogue for the modal-verb cross-check
git init --initial-branch main
git add .
git commit -m "Exception repository"
gh repo create lab-exceptions --private --source . --push     # --public on GitHub Free
```

`init-repo` copies the tools (with the catalogue pin next to the extractor), the [workflow](../../resources/exemptions/exemption-check.yml), the [pull-request template](../../resources/exemptions/pull_request_template.md), the [schema](../../resources/exemptions/exemption.schema.json) and your initiative. It writes `lab.json` with your resource group as the only allowed scope and `"selfApproval": true`. The repository holds no subscription or tenant ID.

Protect `main` so that nobody, including you as administrator, can merge an exemption without a pull request that passes both checks:

```powershell
@'
{
  "required_status_checks": { "strict": false, "checks": [ { "context": "validate" }, { "context": "decision" } ] },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 0, "dismiss_stale_reviews": true },
  "restrictions": null
}
'@ | gh api --method PUT "repos/$owner/lab-exceptions/branches/main/protection" --input -
```

Administrators bypass branch protection unless `enforce_admins` is set ([GitHub Docs](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)). The required approval is the `decision` check, not a GitHub approving review, because GitHub does not let you approve your own pull request.

On GitHub Free, a private repository refuses this call with HTTP 403 `Upgrade to GitHub Pro or make this repository public`. Either create the repository with `--public`, or keep it private without protection: both checks still run and report on every pull request, but nothing then blocks a merge, so you must wait for them yourself.

**With a separate risk owner (production):** omit `--self-approval`, set `$riskOwner` to the other person's login, invite them with `gh api --method PUT "repos/$owner/lab-exceptions/collaborators/$riskOwner" -f permission=push`, and set `required_approving_review_count` to `1`. `decision` then refuses any request that its author approves.

## Task 3: Request the exemption

```powershell
git switch -c exc/legacy-client-transfer
$expires = (Get-Date).ToUniversalTime().AddHours(3).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
$doc = Get-Content "$kit/resources/exemptions/examples/exc-legacy-client-transfer.json" -Raw | ConvertFrom-Json
$doc.'$schema'      = '../schema/exemption.schema.json'
$doc.resourceGroup  = $group
$doc.resource       = "Microsoft.Storage/storageAccounts/$account"
$doc.expiresOn      = $expires
$doc.riskOwner      = $riskOwner
$doc | ConvertTo-Json -Depth 5 | Set-Content exemptions/exc-legacy-client-transfer.json -Encoding utf8NoBOM
python tools/exemptions.py validate
```

Three hours leaves time for [challenge 4](../../challenges/challenge-04.md) before the expiry. Expected:

```text
PASS    exemptions/exc-legacy-client-transfer.json
```

```powershell
git add exemptions
git commit -m "Request exemption exc-legacy-client-transfer"
git push --set-upstream origin exc/legacy-client-transfer
gh pr create --web
```

Fill in the template in the browser and create the pull request. Expected: `validate` passes; `decision` fails with `WAITING  exemptions/exc-legacy-client-transfer.json: awaiting approval by risk owner @<login>: submit a Comment review whose first line is /approve`, and the merge button stays blocked.

## Task 4: Two requests the check must refuse

```powershell
foreach ($name in 'exc-residency-outside-region', 'exc-no-expiry') {
  git switch main
  git switch -c "exc/$name"
  $doc = Get-Content "$kit/resources/exemptions/examples/$name.json" -Raw | ConvertFrom-Json
  $doc.'$schema'     = '../schema/exemption.schema.json'
  $doc.resourceGroup = $group
  $doc.riskOwner     = $riskOwner
  if ($doc.PSObject.Properties['resource']) { $doc.resource = "Microsoft.Storage/storageAccounts/$account" }
  if ($doc.PSObject.Properties['expiresOn']) { $doc.expiresOn = $expires }
  $doc | ConvertTo-Json -Depth 5 | Set-Content "exemptions/$name.json" -Encoding utf8NoBOM
  git add exemptions
  git commit -m "Request exemption $name"
  git push --set-upstream origin "exc/$name"
  gh pr create --title "Exemption: $name" --body "Exemption request $name; see the file."
}
```

Expected `validate` output in the two pull requests:

```text
REFUSED exemptions/exc-residency-outside-region.json
  - policy reference 'residency-allowed-locations' also implements STM.2.1.7: name every requirement the exemption deviates from
  - STM.2.1.7 is MUSS: no exception or risk acceptance is possible; fix the resource instead

REFUSED exemptions/exc-no-expiry.json
  - missing required fields: expiresOn
```

The residency request names only BES.2.2 (SOLLTE). The check reads the policy groups of the initiative, finds the binding external obligation STM.2.1.7 (MUSS) behind the same policy, and refuses. Adding STM.2.1.7 to the request does not help, because MUSS has no exception path. `decision` also stays at `WAITING` on both, because nobody approved them. Close both pull requests unmerged: they stay in the history as refused requests.

The two KANN (optional) references, `encryption-infrastructure` (KONF.11.8) and `backup-geo-redundant-storage` (NOT.4.12), also cannot be waived. Optional requirements are selected through the archetype, not through an exemption. The offline tests exercise both; you do not need to open more pull requests.

## Task 5: Approve as risk owner and merge

As the risk owner, open the first pull request and work through the checklist in its description. Then record the decision as a **Comment** review on the current head commit, starting with `/approve`:

```powershell
gh pr review exc/legacy-client-transfer --comment --body "/approve
I accept the risk of plain-HTTP access to this one account until the expiry."
```

Expected: the review starts a second workflow run, whose `decision` reports `APPROVED exemptions/exc-legacy-client-transfer.json by its risk owner on <commit> (lab self-approval)`. The first run's failed `decision` stays listed on the same commit. Re-run it so that every `decision` check on the head is green before you merge:

```powershell
$run = gh run list --branch exc/legacy-client-transfer --event pull_request --limit 1 --json databaseId --jq '.[0].databaseId'
gh run rerun $run --failed
gh pr checks exc/legacy-client-transfer --watch
```

Then merge:

```powershell
gh pr merge exc/legacy-client-transfer --merge
```

A new commit after the approval makes `decision` fail again until the risk owner approves the new head. A plain comment, or a comment that does not start with `/approve`, is not an approval. With a separate risk owner, that person submits a normal **Approve** review instead.

## Task 6: Create the exemption from main

```powershell
git switch main
git pull --ff-only
python tools/exemptions.py apply --dry-run      # prints the request; changes nothing
python tools/exemptions.py apply
```

Expected:

```text
APPLIED  exc-legacy-client-transfer (decision https://github.com/<owner>/lab-exceptions/pull/1, expires <expiry>)
```

`apply` creates only files that pass `validate`, whose latest merged pull request carries the risk owner's approval of its final commit, and that have not expired. Check the result:

```powershell
$scope = "/subscriptions/$sub/resourceGroups/$group/providers/Microsoft.Storage/storageAccounts/$account"
az rest --method get `
  --url "$scope/providers/Microsoft.Authorization/policyExemptions/exc-legacy-client-transfer?api-version=2022-07-01-preview" `
  --query "properties.{category: exemptionCategory, expiresOn: expiresOn, decision: metadata.decisionRecord, approvedBy: metadata.approvedBy}"
az storage account update --name $account --resource-group $group --https-only false --output none
az policy state trigger-scan --resource-group $group
az policy state list --resource-group $group --filter "policyAssignmentName eq 'gspp-corp'" `
  --query "[?contains(resourceId, '$account')].{reference: policyDefinitionReferenceId, state: complianceState}" `
  --output table
```

Expected: category `Waiver`, your expiry, the pull-request link and the risk owner's login. Under lab self-approval the metadata also carries `approvalMode: lab-self-approval`. The update that was denied in task 1 now succeeds, because the resource is exempt from that assignment's secure-transfer policy ([exemption structure](https://learn.microsoft.com/azure/governance/policy/concepts/exemption-structure)). `transport-secure-transfer` shows `Exempt`; `residency-allowed-locations` stays `Compliant`. The state can update before `trigger-scan` returns; the list command shows it as soon as it does.

Continue with [challenge 4](../../challenges/challenge-04.md) now, while the exemption is in force, then come back for task 7.

## Task 7: After the expiry

```powershell
az policy state trigger-scan --resource-group $group
az policy state list --resource-group $group --filter "policyAssignmentName eq 'gspp-corp'" `
  --query "[?contains(resourceId, '$account')].{reference: policyDefinitionReferenceId, state: complianceState}" `
  --output table
python tools/exemptions.py apply --dry-run
```

Expected: `transport-secure-transfer` is `NonCompliant`, because HTTPS-only is still off and the expired exemption is no longer honoured. Azure keeps the expired exemption as a record. `apply` reports `EXPIRED  exc-legacy-client-transfer` and does not recreate it. The deviation did not disappear when it expired: it became visible as non-compliance. Fix the resource or raise a new, separately approved request:

```powershell
az storage account update --name $account --resource-group $group --https-only true --output none
```

## Task 8: Clean up

Remove this run's exemption before the [lab teardown](../../labautomation/README.md#finish-including-after-a-failure). Delete the exact storage-account exemption rather than everything returned by the resource-group list, which can include unrelated or inherited exemptions:

```powershell
$accountId = "/subscriptions/$sub/resourceGroups/$group/providers/Microsoft.Storage/storageAccounts/$account"
$exemptionId = "$accountId/providers/Microsoft.Authorization/policyExemptions/exc-legacy-client-transfer"
az rest --method delete --url "$($exemptionId)?api-version=2022-07-01-preview" --output none
az storage account delete --name $account --resource-group $group --yes
```

Keep `lab-exceptions` as the decision record for challenge 4, or delete it when you are done: `gh repo delete "$owner/lab-exceptions"` (needs the `delete_repo` scope: `gh auth refresh -s delete_repo`).

## Limits of this lab

| Shortcut | Why | Production answer |
|---|---|---|
| The requester approves as risk owner (`selfApproval` in `lab.json`) | One GitHub account can run the lab | A different, accountable risk owner: no `--self-approval`, one required approving review, risk owners as code owners for `exemptions/` |
| `apply` runs from your shell after the merge | No pipeline identity to set up in a lab | A workflow on `main` with a federated identity that can only write policy exemptions in the target scope |
| Required checks accept any source | Simpler protection setup | Pin GitHub Actions as the source of `validate` and `decision` |
| A pull request can change `.github/` itself; the rules come from the base commit | Keeps the repository self-contained | Required workflows through rulesets, and code owners for `.github/` and `tools/` |
| The approving review is the decision log | GitHub keeps it with the change | Export decisions to the records system that your audit requires |
| At most 90 days to expiry | A kit default (`maxDays` in `lab.json`) | Your exception policy sets the maximum |
