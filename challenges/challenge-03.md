# Challenge 3 - Handle a Justified Exception as a Reviewed Pull Request

> **Status: written, not yet run in a sandbox.** The [validation run](../walkthrough/validation-run.md) records the first measured run.

**Learning objective:** raise, review and expire an Azure Policy exemption as code, with the reviewed pull request as the decision record, and explain why a must-level (MUSS) requirement has no exception path.

**Value readout:** saves chasing exception decisions through mail and tickets; measured as minutes from request to approved exemption, and exemptions without approver or expiry ([results](../Readme.md#value-readout)).

## Goal

Some applications cannot meet a requirement yet. In this challenge an exception is a JSON file in a pull request: requirement IDs, policy reference, scope, justification, risk statement, risk owner and expiry. Two pull-request checks guard it:

| Check | Passes only when |
|---|---|
| `validate` | Every requirement behind the named policy reference is listed and is SOLLTE; the expiry is set and at most 90 days ahead; the scope is inside your lab resource group. The requirements come from the initiative of challenge 2, so a request cannot hide a MUSS requirement behind a policy that also implements a SOLLTE one. |
| `decision` | The named risk owner, who did not open the request, approved the current head commit. |

After the merge you create the Azure Policy exemption from `main`. It carries the expiry and a link to its pull request, and stops applying on its expiry date. Azure Policy makes expiry optional; this lab makes it mandatory.

## Prerequisites

- [Challenge 2](challenge-02.md) completed: initiative `gspp-archetype-baseline` is assigned as `gspp-corp` to your lab resource group.
- Your lab resource group from the [lab bootstrap](../labautomation/README.md). Every Azure object in this challenge stays inside it.
- PowerShell 7 with Azure CLI and GitHub CLI signed in, Python 3.9 or later, and Git.
- An Azure identity that can create a storage account and policy exemptions in the lab group, for example Contributor plus Resource Policy Contributor on the group.
- A new GitHub repository you administer whose `main` branch can be protected: public on GitHub Free, or private on GitHub Pro, Team or Enterprise.
- A second person, or a second GitHub account, with write access to that repository as risk owner.

## Actions

- Create a compliant storage account in your lab group. Try to switch off its secure-transfer setting and read why Azure Policy denies it.
- Create your exception repository with `tools/exemptions/exemptions.py init-repo`, push it and protect `main`: one approving review, required checks `validate` and `decision`, no bypass for administrators.
- Request an exemption from the secure-transfer requirements for that one storage account with a short expiry, using the template and schema in `resources/exemptions/`.
- Open two more requests: one for a storage location outside the allowed regions and one without an expiry. Read why the check refuses each.
- Let the risk owner approve the valid request, merge it and create the exemption with `exemptions.py apply` from `main`.
- Confirm that the storage account shows as exempt. After the expiry, confirm that the exemption no longer applies.

## Success criteria

- The residency request and the request without an expiry fail `validate`. The residency failure names the MUSS requirement behind the policy.
- The valid request cannot merge until the risk owner approves its last commit.
- The Azure exemption exists only on the storage account, with the expiry from the file and the pull-request link in its metadata.
- After the expiry, the storage account is evaluated against the secure-transfer policy again.
- From the merged pull request alone you can show who requested and approved the exemption, why, and until when.

## Learning resources

- [Azure Policy exemption structure](https://learn.microsoft.com/azure/governance/policy/concepts/exemption-structure)
- [Require secure transfer for a storage account](https://learn.microsoft.com/azure/storage/common/storage-require-secure-transfer)
- [About protected branches](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Get Azure Policy compliance data](https://learn.microsoft.com/azure/governance/policy/how-to/get-compliance-data)

---

[Previous challenge](challenge-02.md) | [Home](../Readme.md) | [Solution](../walkthrough/challenge-03/solution-03.md) | [Next challenge](challenge-04.md)
