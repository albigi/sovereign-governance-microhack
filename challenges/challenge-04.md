# Challenge 4 - Generate Audit Evidence as a By-product of Change

> **Status: validated live (23 Nov 2026).** See the [validation record](../walkthrough/validation-run.md).

**Learning objective:** generate a reproducible, machine-readable evidence pack from Azure Policy compliance state and pull-request history, and explain why missing or stale evidence must never read as fulfilled.

**Value readout:** saves assembling audit evidence by hand before each review; measured as minutes to regenerate the evidence pack, and differences between two runs on the same state ([results](../Readme.md#value-readout)).

## Goal

An auditor asks for proof, not for a dashboard. In this challenge you generate an evidence file in OSCAL assessment-results format from the policy compliance state of your lab resource group and from the exception pull requests of challenge 3. Every requirement in your applicability result from challenge 1 gets exactly one GS++ status:

| Status | When |
|---|---|
| fulfilled | Current Azure Policy results are all compliant and the policy covers the whole requirement, or the exception process meets its own check |
| not fulfilled | A resource is non-compliant or exempt. An exemption with a merged, risk-owner-approved pull request shows as an approved temporary deviation with its decision link and expiry |
| not applicable | Challenge 1 found that the requirement does not apply, with its reason |
| unresolved | No matching observation, only partial evidence, an unknown result, an expired exemption awaiting re-evaluation, or evidence older than 36 hours |

Challenge 1 decides scope (`applicable` and `reason`); it does not supply observations. Its `policy_coverage` describes candidate Azure Policy definitions: `full` with no matching observation is unresolved, while `none` means no definition fits, not that no evidence exists. For example, the pack uses reviewed pull requests to assess the exception process without a policy result.

`unresolved` is not a GS++ status. It is a task for a person: until someone assesses the requirement, it must not read as fulfilled. The generator reads a snapshot, not live Azure, so the same snapshot and repository always give the same bytes.

## Prerequisites

- [Challenge 1](challenge-01.md) completed: you have its applicability file for your application profile.
- [Challenge 3](challenge-03.md) completed up to task 6 of its walkthrough: an exemption approved by pull request is in force and has not yet expired.
- Read access to policy compliance state and policy exemptions in the lab resource group, for example Reader.
- GitHub CLI signed in with read access to the exception repository.
- Python 3.9 or later.

## Actions

- Snapshot the policy compliance state, the policy exemptions and the exception pull requests with `tools/evidence.py collect` in your exception repository.
- Generate the evidence pack with `tools/evidence.py generate`, scoped by your challenge 1 applicability file, with a Markdown summary.
- Find the SOLLTE deviation from challenge 3 with its decision link and expiry, and a must-level (MUSS) requirement evidenced by a named human decision rather than a policy result.
- Regenerate from the same snapshot and compare the two packs.
- Evaluate the same snapshot two days later and read which statuses change and why.
- After the exemption expires, collect and generate again, and compare the new pack with the first.

## Success criteria

- Every requirement in your applicability file appears exactly once, with a status and its basis.
- No requirement without current, complete evidence reads as fulfilled.
- The secure-transfer requirements show as not fulfilled, with an approved temporary deviation, the pull-request link and the expiry.
- Two runs on the same snapshot and repository produce byte-identical files.
- After the expiry, the deviation is gone and the requirements are not fulfilled until the resource is fixed.

## Learning resources

- [OSCAL assessment results model](https://pages.nist.gov/OSCAL/learn/concepts/layer/assessment/assessment-results/)
- [OSCAL assessment results JSON reference, version 1.1.3](https://pages.nist.gov/OSCAL-Reference/models/v1.1.3/assessment-results/json-outline/)
- [Get Azure Policy compliance data](https://learn.microsoft.com/azure/governance/policy/how-to/get-compliance-data)
- [`az policy state` reference](https://learn.microsoft.com/cli/azure/policy/state)

---

[Previous challenge](challenge-03.md) | [Home](../Readme.md) | [Solution](../walkthrough/challenge-04/solution-04.md) | [Finish](finish.md)
