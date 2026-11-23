# Enforcement decision rule

> **Status: proposed (20 Nov 2026).** Validated offline: classifier tests, `check` against the pinned catalogue and the pinned built-in definitions, Bicep build. The sandbox deployment and the per-effect demonstrations ran live on 23 Nov 2026 ([validation record](../walkthrough/validation-run.md)). Every mapping is a candidate until an information-security expert reviews it; nothing here is a compliance statement.

**Answer.** A GS++ requirement gets an Azure Policy effect only when Azure Policy can check it on a resource. Its modal verb and its binding for the archetype then decide how hard the effect is and how a deviation is approved. Everything Azure Policy cannot check routes to a named owner who produces their own evidence. A MUSS requirement that is a process duty never gets a policy effect. It needs a named human decision.

The rule as data is [`doctrine.json`](doctrine.json): themes, routes and the built-in definitions. The catalogue pin is not copied there: the tool reads it from the `catalogue` block of [`catalogue-mapping.json`](catalogue-mapping.json). Each archetype's binding choices live in its `enforcement` field in the shared [`archetypes.json`](archetypes.json), next to the facts and parameters that challenge 1 uses. The tool [`tools/doctrine/doctrine.py`](../tools/doctrine/doctrine.py) applies the rule and generates the [archetype initiative](archetype-initiative/) and the tables below. Do not edit the generated tables by hand.

## Inputs

| Input | Values | Where it comes from |
|---|---|---|
| Applicable requirements | requirement IDs | output of challenge 1 (`tools/gspp/out/applicability-<profile>.json`). A doctrine requirement that challenge 1 does not assess stays in, so no control is dropped silently |
| Modal verb | MUSS (must), SOLLTE (should), KANN (may) | GS++ catalogue at the pinned commit; `check --catalogue` verifies it |
| Checkable by Azure Policy | `property`: a resource property; `existence`: a related resource exists (for example a diagnostic setting); `none` | the mapping: a built-in definition reads that property, or nothing does |
| Binding for the archetype | `obligation`: an external obligation makes it binding; `bound`: the archetype adopts it; `not-bound`: the archetype documents why not (for KANN: selected or not selected) | `enforcement.bindings` of the archetype, plus the obligation register: obligations from law or contract enter the requirement package through STM.2.1.7 (MUSS) |
| Remediation approved | per archetype and theme | `enforcement.remediation_approved` of the archetype, set by its owner. `Modify` and `DeployIfNotExists` change resources, so the owner agrees first |
| Parameter values | regions, minimum TLS version | `parameters` of the archetype, shared with challenge 1 (see [Parameter values](#parameter-values)) |

When a theme bundles several requirements, the strongest verb counts.

## The rule

<!-- BEGIN GENERATED: rules -->
| Modal verb | Binding for the archetype | Checkable: resource property | Checkable: related resource exists | Not checkable | Deviation path |
|---|---|---|---|---|---|
| MUSS | any | `Deny`, or `Modify` if remediation is approved | `AuditIfNotExists`, or `DeployIfNotExists` if remediation is approved | no effect; named human decision | none: cannot be waived |
| SOLLTE | external obligation | `Deny`, or `Modify` if remediation is approved | `AuditIfNotExists`, or `DeployIfNotExists` if remediation is approved | no effect; route to its owner | none: cannot be waived |
| SOLLTE | bound | `Deny`, or `Modify` if remediation is approved | `AuditIfNotExists`, or `DeployIfNotExists` if remediation is approved | no effect; route to its owner | time-boxed Azure Policy exemption via a reviewed pull request (not checkable: time-boxed exception outside Azure Policy via a reviewed pull request) |
| SOLLTE | not bound | `Audit` | `AuditIfNotExists` | no effect; route to its owner | reviewed change to the archetype |
| KANN | external obligation | `Deny`, or `Modify` if remediation is approved | `AuditIfNotExists`, or `DeployIfNotExists` if remediation is approved | no effect; route to its owner | none: cannot be waived |
| KANN | selected | `Deny`, or `Modify` if remediation is approved | `AuditIfNotExists`, or `DeployIfNotExists` if remediation is approved | no effect; route to its owner | reviewed change to the archetype |
| KANN | not selected | `Audit` | `AuditIfNotExists` | no effect; route to its owner | none needed |
<!-- END GENERATED: rules -->

The MUSS rows for checkable requirements are defensive: no MUSS in the pinned catalogue reads as a resource property (inferred from the titles), so in practice every MUSS goes to a named decision. A MUSS still shapes effects as an obligation: STM.2.1.7 makes a SOLLTE binding, and the policy cites it as a group.

If the built-in definition lacks the chosen effect, the tool falls back to the strongest weaker one (`Deny` to `Audit`; `Modify` to `Deny`, then `Audit`; `DeployIfNotExists` to `AuditIfNotExists`) and flags an enforcement gap. Effect parameters in the initiative default to a reporting effect, so assigning the set without an archetype never blocks or changes anything.

**Platform scope.** Some checks belong to the subscription, not to a workload: the activity log is streamed to a workspace once per subscription or management group. Such a theme has `"scope": "platform"`. The rule still chooses its effect, but the platform team assigns the definition outside this initiative, so the initiative's compliance does not show it. One platform assignment serves every archetype, so `check` refuses a platform theme whose binding or remediation differs between archetypes.

## Deviation paths

| Key | Path | Used when | Approved by | Evidence |
|---|---|---|---|---|
| `none` | cannot be waived | MUSS, or a requirement bound by an external obligation | not applicable | deny event or named decision |
| `exemption` | Azure Policy exemption | a bound SOLLTE that Azure Policy checks | named approver in a reviewed pull request, with an expiry date ([challenge 3](../challenges/challenge-03.md)) | exemption object; compliance state "exempt" |
| `attestation-exception` | exception outside Azure Policy | a bound SOLLTE that Azure Policy cannot check | named approver in a reviewed pull request, with an expiry date | exception record next to the owner's evidence |
| `archetype-change` | change to the archetype | a SOLLTE the archetype does not adopt, or a KANN it selects | archetype owner in a reviewed pull request | archetype record with its justification |
| `not-required` | none needed | a KANN the archetype does not select | not applicable | not applicable |

An exemption is offered only when every group of the waived policy is a SOLLTE. A policy that also cites a MUSS (an obligation) or a KANN (an archetype selection) cannot be exempted; the exemption check in challenge 3 reads the groups from the initiative.

## Applied to the baseline

Three reference archetypes from [`archetypes.json`](archetypes.json): **Corp** (internal, private connectivity; the lab archetype), **Online** (serves the public internet), **Confidential Corp** (internal, elevated protection needs). Cell: effect; deviation key from the table above. 20 themes: 12 checked by Azure Policy (2 of them at platform scope), 8 routed to other owners.

<!-- BEGIN GENERATED: themes -->
| Theme | Requirements | Check | Route | Corp | Online | Confidential Corp |
|---|---|---|---|---|---|---|
| residency | BES.2.2 (SOLLTE); bound by STM.2.1.7 (MUSS) | property | azure-policy | `Deny`; none | `Deny`; none | `Deny`; none |
| transport-encryption | KONF.14.1 (SOLLTE), KONF.14.1.1 (SOLLTE) | property | azure-policy | `Deny`; exemption | `Deny`; exemption | `Deny`; exemption |
| internal-exposure | ARCH.5.2 (SOLLTE) | property | azure-policy | `Deny`; exemption | `Audit`; archetype-change | `Deny`; exemption |
| segmentation | ARCH.5.1 (SOLLTE) | existence | azure-policy | `AuditIfNotExists`; exemption | `AuditIfNotExists`; exemption | `AuditIfNotExists`; exemption |
| anonymous-access | BER.4.6 (SOLLTE) | property | azure-policy | `Modify`; exemption | `Modify`; exemption | `Modify`; exemption |
| encryption-at-rest | KONF.11.8 (KANN) | property | azure-policy | `Audit`; not-required | `Audit`; not-required | `Deny`; archetype-change |
| security-logging | DET.3.1 (SOLLTE) | existence | azure-policy | `DeployIfNotExists`; exemption | `DeployIfNotExists`; exemption | `DeployIfNotExists`; exemption |
| activity-logging | DET.3.1.8 (SOLLTE) | existence | azure-policy | `DeployIfNotExists` at platform scope; exemption | `DeployIfNotExists` at platform scope; exemption | `DeployIfNotExists` at platform scope; exemption |
| cloud-log-integration | DET.3.2 (KANN) | existence | azure-policy | `DeployIfNotExists` at platform scope; archetype-change | `DeployIfNotExists` at platform scope; archetype-change | `DeployIfNotExists` at platform scope; archetype-change |
| patch-assessment | DET.5.10.2 (SOLLTE) | property | azure-policy | `Deny`; exemption | `Deny`; exemption | `Deny`; exemption |
| backup | NOT.4.3 (SOLLTE) | existence | azure-policy | `AuditIfNotExists`; exemption | `AuditIfNotExists`; exemption | `AuditIfNotExists`; exemption |
| geo-redundancy | NOT.4.12 (KANN) | property | azure-policy | `Audit`; not-required | `Audit`; not-required | `Audit`; archetype-change |
| restore-test | NOT.4.16.1 (SOLLTE) | none | process-owner | no effect; attestation-exception | no effect; attestation-exception | no effect; attestation-exception |
| strong-authentication | BER.5.8 (SOLLTE), BER.5.9 (SOLLTE) | none | entra | no effect; attestation-exception | no effect; attestation-exception | no effect; attestation-exception |
| data-classification | ASST.2.1 (SOLLTE), ASST.2.4 (SOLLTE) | none | data-catalogue | no effect; attestation-exception | no effect; attestation-exception | no effect; attestation-exception |
| vulnerability-handling | DET.5.3 (SOLLTE) | none | process-owner | no effect; attestation-exception | no effect; attestation-exception | no effect; attestation-exception |
| provider-agreement | BES.2.3 (KANN) | none | provider-attestation | no effect; not-required | no effect; not-required | no effect; archetype-change |
| provider-assurance | BES.4.8.2 (SOLLTE), DLS.3.1.1 (SOLLTE) | none | provider-attestation | no effect; attestation-exception | no effect; attestation-exception | no effect; attestation-exception |
| obligation-register | GC.3.1.1 (MUSS), STM.2.1.7 (MUSS) | none | named-decision | no effect; none | no effect; none | no effect; none |
| exception-authorisation | UMS.5.1 (MUSS), UMS.5.2 (MUSS) | none | named-decision | no effect; none | no effect; none | no effect; none |
<!-- END GENERATED: themes -->

Policies in the initiative `gspp-archetype-baseline`. Built-in definitions verified at Azure/azure-policy commit `f096d8d` (checked 20 Nov 2026).

<!-- BEGIN GENERATED: policies -->
| Reference ID | Built-in definition (ID prefix, version) | Groups | Effect parameter | Corp | Online | Confidential Corp |
|---|---|---|---|---|---|---|
| `residency-allowed-locations` | Allowed locations (`e56962a6`, 1.1.0) | BES.2.2, STM.2.1.7 | `residencyEffect` | `Deny` | `Deny` | `Deny` |
| `transport-secure-transfer` | Secure transfer to storage accounts should be enabled (`404c3081`, 2.0.0) | KONF.14.1, KONF.14.1.1 | `secureTransferEffect` | `Deny` | `Deny` | `Deny` |
| `transport-minimum-tls` | Storage accounts should have the specified minimum TLS version (`fe83a0eb`, 1.0.0) | KONF.14.1, KONF.14.1.1 | `minimumTlsEffect` | `Deny` | `Deny` | `Deny` |
| `exposure-public-network-access` | Storage accounts should disable public network access (`b2982f36`, 1.1.0) | ARCH.5.2 | `publicNetworkAccessEffect` | `Deny` | `Audit` | `Deny` |
| `segmentation-subnet-nsg` | Subnets should be associated with a Network Security Group (`e71308d3`, 3.0.0) | ARCH.5.1 | `subnetNsgEffect` | `AuditIfNotExists` | `AuditIfNotExists` | `AuditIfNotExists` |
| `exposure-anonymous-blob-access` | Configure your Storage account public access to be disallowed (`13502221`, 1.0.0) | BER.4.6 | `anonymousBlobAccessEffect` | `Modify` | `Modify` | `Modify` |
| `encryption-infrastructure` | Storage accounts should have infrastructure encryption (`4733ea7b`, 1.1.0) | KONF.11.8 | `infrastructureEncryptionEffect` | `Audit` | `Audit` | `Deny` |
| `logging-key-vault-diagnostics` | Enable logging by category group for Key vaults (microsoft.keyvault/vaults) to Log Analytics (`6b359d8f`, 1.1.0) | DET.3.1 | `keyVaultDiagnosticsEffect` | `DeployIfNotExists` | `DeployIfNotExists` | `DeployIfNotExists` |
| `patching-periodic-assessment` | Machines should be configured to periodically check for missing system updates (`bd876905`, 3.10.0) | DET.5.10.2 | `periodicAssessmentEffect` | `Deny` | `Deny` | `Deny` |
| `backup-virtual-machines` | Azure Backup should be enabled for Virtual Machines (`013e242c`, 3.0.0) | NOT.4.3 | `backupEffect` | `AuditIfNotExists` | `AuditIfNotExists` | `AuditIfNotExists` |
| `backup-geo-redundant-storage` | Geo-redundant storage should be enabled for Storage Accounts (`bf045164`, 1.0.0) | NOT.4.12 | `geoRedundancyEffect` | `Audit` | `Audit` | `Audit` |
<!-- END GENERATED: policies -->

## Parameter values

STM.5.1 asks the organisation to set the values that requirements leave open. They come from the `parameters` of the archetype, so challenge 1 and this initiative use the same values, and nothing is taken from the catalogue:

| Set parameter | Archetype parameter | Mapping | Requirement it parameterises |
|---|---|---|---|
| `allowedLocations` | `allowed_locations` | as is | BES.2.2 data location |
| `minimumTlsVersion` | `minimum_tls_version` | `1.2` to `TLS1_2`; `1.3` is refused because the definition offers no `TLS1_3` | KONF.14.1 "recognised standard", with HTTPS only |
| `logAnalyticsWorkspaceId` | none: set per site at assignment | | DET.3.1; the workspace retention sets its "set period" |

`assignment.bicep` may override the regions for one assignment; leave the override empty to use the archetype value.

## Relation to the catalogue mapping

The catalogue mapping of challenge 1 ([`catalogue-mapping.json`](catalogue-mapping.json)) says, per requirement, which controls could serve it. The doctrine picks one built-in per need and decides its effect per archetype. `check` cross-checks the two and fails on disagreement:

| Cross-check | Fails when |
|---|---|
| Coverage | a mapped requirement has no doctrine theme |
| Facts | modal verb or protection level differ |
| Route | one says Azure Policy and the other does not |
| Shared definition | name, version or effects differ, or the doctrine uses the definition but not for that requirement |
| Archetype filter | the mapping limits a definition to some archetypes and the doctrine enforces it in another |

Themes are finer than the mapping's themes: one mapping theme can split where verbs or checks differ (for example `logging` into security, activity and cloud log themes). The deviation path is refined per archetype and is not cross-checked: an obligation removes the exemption (BES.2.2 becomes `none`), and a KANN never gets an exemption or an attestation exception (KONF.11.8, DET.3.2, NOT.4.12 and BES.2.3 become `not-required` or `archetype-change`). `check` lists, as notes, requirements and definitions the doctrine adds beyond the mapping.

## Worked examples

| Requirement | Reasoning | Result |
|---|---|---|
| BES.2.2 data location (SOLLTE) | Checkable property (resource location). Law or contract fixes the location, so STM.2.1.7 makes it an obligation for every archetype. | `Deny` everywhere; no exemption. The allowed-locations policy cites BES.2.2 and STM.2.1.7 |
| KONF.14.1 transport encryption (SOLLTE) | Checkable property; every archetype adopts it; no obligation | `Deny`; time-boxed exemption possible |
| ARCH.5.2 internal exposure (SOLLTE) | Checkable property (public network access). Online serves the internet by design and records why it does not adopt it | Corp and Confidential Corp `Deny`; Online `Audit`, deviation in the archetype record |
| KONF.11.8 encryption at rest (KANN) | Checkable property; only Confidential Corp selects it | Confidential Corp `Deny`; others `Audit`, nothing to approve |
| DET.3.1 security logging (SOLLTE) | Existence check (diagnostic setting); remediation approved | `DeployIfNotExists` adds the setting; existence cannot be denied |
| DET.3.1.8 activity logging (SOLLTE) | Existence check on the subscription; remediation approved | `DeployIfNotExists` at platform scope, assigned once by the platform team; not in this initiative |
| BER.5.9 multi-factor authentication (SOLLTE) | Azure Policy cannot see sign-in policy | No effect; routes to the identity team; deviation by attestation exception |
| UMS.5.1 exception authorisation (MUSS) | Process duty | No effect; named decision in a reviewed pull request |

## Where Azure Policy alone gives false assurance

| Limit | Consequence | What the kit does |
|---|---|---|
| Azure Policy reads resource configuration only | "100 % compliant" means the assigned checks pass, not that the requirements are met: 8 of the 20 baseline themes are outside its view | Every requirement has a route and an owner; non-Policy routes produce their own evidence |
| Platform assignments are elsewhere | The activity-log themes are assigned once per subscription, so this initiative's compliance never shows them | Their evidence is the platform assignment's compliance state |
| Existence cannot be prevented | `AuditIfNotExists` and `DeployIfNotExists` act after the resource exists | Remediate where approved; otherwise report |
| Evaluation is not instant | About 5 minutes for a new assignment, about 15 minutes for a changed resource, and a full cycle every 24 hours ([Microsoft Learn, updated 18 Mar 2026](https://learn.microsoft.com/azure/governance/policy/how-to/get-compliance-data)) | Demonstrations wait or trigger an on-demand scan |
| Exemption expiry is optional in Azure | A waiver without an end date never comes back for review | Challenge 3 refuses an exemption without an expiry date |
| Policy groups are shared by all archetypes | An obligation must bind every archetype that uses the set | `check` fails otherwise; a different obligation needs its own set |
| Allowed locations reads the resource's own region | Geo-redundant storage copies data to the paired region, which the policy does not see; Germany West Central pairs with Germany North ([Microsoft Learn, updated 8 Nov 2026](https://learn.microsoft.com/azure/reliability/regions-paired)) | Before an archetype selects geo-redundancy (NOT.4.12), check that the paired region is in its `allowed_locations` |
| The mapping is a candidate | A built-in can cover more or less than the requirement; BER.4.6 asks to document unauthenticated functions, the policy switches anonymous blob access off (inferred mapping) | Mapping marked candidate; expert review before use |
| Built-in definitions change | The set references built-ins without a pinned `definitionVersion` | `check --online` compares version, effects, roles and parameters with the pinned commit |

## Rationale and rejected alternatives

| Alternative | Why not |
|---|---|
| Deny every SOLLTE | Blocks archetypes that legitimately differ (Online needs public endpoints) and pushes teams to workarounds |
| Audit everything | Nothing is prevented; compliance becomes report reading |
| Treat the Azure Policy compliance score as the requirement status | False assurance: 8 of the 20 baseline themes are invisible to it, and 2 more sit in a platform assignment |
| Defender for Cloud regulatory compliance as the authority | No C5 or IT-Grundschutz standard in its list, and non-default standards need a paid plan ([Microsoft Learn, updated 17 Jun 2026](https://learn.microsoft.com/azure/defender-for-cloud/concept-regulatory-compliance-standards)) |
| A Purview Compliance Manager template | No IT-Grundschutz template in its list; a custom template would duplicate this mapping outside the code path ([Microsoft Learn, 6 Mar 2025](https://learn.microsoft.com/purview/compliance-manager-regulations-list)) |
| One policy set per archetype | Duplicates definitions and drifts; one set with per-archetype effect parameters keeps one place for groups and evidence |

## Sovereignty notes (checked 20 Nov 2026)

| Cloud | Azure Policy | Source |
|---|---|---|
| Azure public, EU Data Boundary | Available. Policy entities and compliance information are a temporary exclusion from the EU Data Boundary | [Microsoft Learn, EUDB temporary transfers, updated 27 Mar 2026](https://learn.microsoft.com/privacy/eudb/eu-data-boundary-temporary-transfers-from-services) |
| Microsoft Sovereign Public Cloud | Available (inferred); its landing zone ships sovereignty baseline initiatives | [Microsoft Learn, built-in initiatives, checked 18 Nov 2026](https://learn.microsoft.com/azure/governance/policy/samples/built-in-initiatives) |
| Microsoft Sovereign Private Cloud (Azure Local, disconnected) | Policy and Azure Resource Manager documented; parity of effects and built-ins unverified | [Microsoft Learn, disconnected operations, checked 18 Nov 2026](https://learn.microsoft.com/azure/azure-sovereign-clouds/private/azure-local/disconnected-operations-overview) |
| Delos Cloud | Listed as planned on a non-binding portfolio; built-in definitions and effects unverified | [Delos Cloud portfolio, accessed 12 Nov 2026](https://www.deloscloud.de/products/portfolio.html) |

Before using the initiative outside Azure public, confirm each built-in exists there (`az policy definition show --name <id>`).

## Use and change

Run from the repository root with Python 3.10 or later; no packages needed.

```powershell
python tools/doctrine/doctrine.py classify --applicable tools/gspp/out/applicability-<profile>.json   # effect and deviation per theme, for the profile's archetype
python tools/doctrine/doctrine.py generate                                                          # rewrite the initiative and these tables
python tools/doctrine/doctrine.py check --catalogue tools/gspp/out/gspp-extract.csv --online         # invariants, drift, mapping, catalogue, built-ins
python -m unittest discover -s tools/doctrine
```

To change the rule, its themes or definitions, edit `doctrine.json`; to change what an archetype binds or which remediation it approves, edit its `enforcement` field in `archetypes.json`. Then run `generate` and `check`, and open a pull request. The contract for importers is stable within a major version: group `name` is the GS++ requirement ID, group `category` is its modal verb, and `policyDefinitionReferenceId`s do not change. Compliance states carry `policyDefinitionGroupNames`, so evidence maps to requirements without a separate mapping file.
