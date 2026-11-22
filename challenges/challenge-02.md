# Challenge 2 - Enforce Applicable Requirements with Azure Policy by a Decision Rule

> **Status: draft (20 Nov 2026).** Decision rule, classifier and initiative are validated offline (tests, catalogue check, Bicep build). The walkthrough has not yet run in a sandbox; its Azure outputs are expected, not measured.

**Learning objective:** choose an Azure Policy effect (`deny`, `audit`, `modify`, `deployIfNotExists`, `auditIfNotExists`) and a deviation path for each requirement from its modal verb, its checkability and the archetype, and explain where Azure Policy alone gives false assurance.

**Value readout:** saves choosing and defending a policy effect per requirement by hand; measured as minutes from requirement list to deployed initiative, and deployed effects that differ from the decision rule ([results](../Readme.md#value-readout)).

## Goal

Upstream challenge 1 shows how to assign Azure Policy. This challenge decides **which effect** each requirement gets, by a stated decision rule: requirement level (MUSS, SOLLTE, KANN) x checkable by Azure Policy x binding for the archetype -> effect and deviation path. You generate the archetype initiative from that rule, deploy it to your lab scope and test it.

## Prerequisites

- [Challenge 1](challenge-01.md) completed: you have its applicability file, `tools/gspp/out/applicability-<profile>.json` (a CSV with an `id` column, or one requirement ID per line, also works). Without one, the classifier uses the whole baseline.
- The lab resource group created by [`labautomation`](../labautomation/) in an Azure sandbox subscription, in a region that the Corp archetype allows (`allowed_locations` in [`resources/archetypes.json`](../resources/archetypes.json)). One lab run per subscription: the policy set name is subscription-wide.
- Rights: Owner of the sandbox subscription, or the narrower set in the [walkthrough](../walkthrough/challenge-02/solution-02.md#rights).
- Azure CLI with Bicep, and Python 3.10 or later (no packages). No paid plan is needed; the lab creates small billable resources listed in the walkthrough.
- Recommended: [Sovereign Cloud MicroHack challenge 1](https://github.com/microsoft/MicroHack/blob/main/03-Azure/01-03-Infrastructure/01_Sovereign_Cloud/challenges/challenge-01.md) (Azure Policy and RBAC basics).

## Actions

- Read the enforcement decision rule in [`resources/doctrine.md`](../resources/doctrine.md), including where Azure Policy alone gives false assurance.
- Run the classifier on your challenge 1 applicability file to derive the effect and deviation path of each requirement for its archetype.
- Review the generated archetype initiative: requirement groups, effect parameters and the effects of each archetype, and where each archetype records what it binds (its `enforcement` field in `resources/archetypes.json`).
- Deploy the policy set to your subscription and assign it to your lab resource group with the Corp archetype.
- Test it: a storage account that breaks a binding requirement is denied, a correctable setting is modified, a missing log setting is deployed, and a non-selected KANN shows as an audit finding.
- List the requirements that route outside Azure Policy (identity, data, process) and the owner each routes to.

## Success criteria

- The initiative is assigned to your lab resource group, and every assigned effect and value equals the classifier output (`doctrine.py check` passes and the assigned parameters match `resources/archetype-initiative/assignments.json`).
- `Deny`, `Modify`, `DeployIfNotExists` and `Audit` are each demonstrated once. `AuditIfNotExists` is assigned and reports no applicable resources, because the lab has no virtual machine or subnet.
- No MUSS process duty gets a policy effect; each routes to a named decision. A SOLLTE bound by an external obligation (BES.2.2 through STM.2.1.7) is denied, and its policy cannot be exempted.
- Your list of requirements that Azure Policy cannot enforce names an owner for each.
- Everything this run created is removed or recorded, as in the walkthrough.

## Learning resources

- [Azure Policy effects](https://learn.microsoft.com/azure/governance/policy/concepts/effect-basics)
- [Azure Policy initiative definition structure](https://learn.microsoft.com/azure/governance/policy/concepts/initiative-definition-structure)
- [Remediate non-compliant resources](https://learn.microsoft.com/azure/governance/policy/how-to/remediate-resources)
- [Get compliance data](https://learn.microsoft.com/azure/governance/policy/how-to/get-compliance-data)
- [Azure Policy overview](https://learn.microsoft.com/azure/governance/policy/overview)
- [Bicep overview](https://learn.microsoft.com/azure/azure-resource-manager/bicep/overview)

---

[Previous challenge](challenge-01.md) | [Home](../Readme.md) | [Solution](../walkthrough/challenge-02/solution-02.md) | [Next challenge](challenge-03.md)
