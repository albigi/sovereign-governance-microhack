# Challenge 1 - Decide Which Sovereign Requirements Apply to an Application

> **Status: tested locally (23 Nov 2026).** Commands and expected outputs are checked; duration and agreement with expert labels are measured in the validation run ([results](../Readme.md#value-readout)).

**Learning objective:** derive the requirements that apply to one application from a pinned, digest-verified BSI Grundschutz++ (GS++) catalogue, and explain why applicability is decided before anything is enforced.

**Value readout:** saves reading the whole catalogue for each application; measured as minutes from application profile to applicable-requirement list, and agreement with expert-labelled applicability ([results](../Readme.md#value-readout)).

## Goal

A sovereign requirement set is too large to apply whole: the pinned GS++ catalogue holds about 1,000 controls. In this challenge you load the catalogue at a pinned version, describe one synthetic application with an application profile, and derive the short list of requirements that apply to it, each with its requirement level and a candidate Azure control. Challenges 2 to 4 work only on this list.

> **The catalogue.** The requirements are BSI's [Grundschutz++ catalogue](https://github.com/BSI-Bund/Stand-der-Technik-Bibliothek) (OSCAL; [BSI's Grundschutz++ page](https://www.bsi.bund.de/DE/Themen/Unternehmen-und-Organisationen/Standards-und-Zertifizierung/Grundschutz-in-der-Informationssicherheit/Grundschutz-Plus-Plus/grundschutz-plus-plus_node.html)). The kit pins one commit and its SHA-256 digest in the `catalogue` block of [`resources/catalogue-mapping.json`](../resources/catalogue-mapping.json), the only place to configure it; it never follows "latest". To use a newer BSI release, follow [Upgrade the catalogue](../resources/README.md#upgrade-the-catalogue).

## Prerequisites

- Python 3 (validated with 3.13) and Git; no Azure subscription is needed for this challenge.
- Internet access to github.com to download the catalogue.
- Read the [terms](../Readme.md#introduction): GS++, MUSS / SOLLTE / KANN, archetype.
- Run every command from the repository root.
- Optional, for the last action only: `python -m pip install -r tools/oscal/requirements.txt`.

## Actions

- Run `python tools/gspp/extract.py`. It downloads the catalogue at the commit pinned in `resources/catalogue-mapping.json`, checks its SHA-256 digest and writes a local extract to `tools/gspp/out/`. Keep the extract local: this lab consumes the catalogue and does not redistribute it.
- Open `resources/profiles/leave-planner.json`, the lab application, and `resources/archetypes.json`. Note the facts that drive applicability: archetype, protection need, internet exposure, personal data and resource types. Any other profile in `resources/profiles/` works too.
- Run `python tools/gspp/applicability.py --profile leave-planner`. It applies the candidate mapping in `resources/catalogue-mapping.json` to the profile, prints the applicable and not-applicable requirements, and writes `tools/gspp/out/applicability-leave-planner.json` for challenges 2 to 4.
- Run `python tools/gspp/check_ids.py tools/gspp/out/applicability-leave-planner.json`. It confirms every requirement ID, modal verb and security level against your local extract, and that no catalogue text was copied into the kit.
- Read the requirement text of three applicable requirements in your local extract (`tools/gspp/out/gspp-extract.csv`) and decide whether you agree with the candidate control.
- Find the applicable requirements with policy coverage `none`. No Azure Policy definition can check them; they stay visible as coverage gaps in challenges 2 and 4.
- Optional: run `python tools/oscal/build_component.py --check` and `python tools/oscal/validate.py`. The Azure component in `resources/azure-component-definition.json` is generated from the same mapping and validated against the NIST OSCAL schema.

## Success criteria

- The extractor accepts the pinned digest and reports the number of controls it wrote.
- You have an applicable-requirement list for one application, with ID, modal verb, route, policy coverage and candidate control on every row, and a reason for every requirement that does not apply.
- `check_ids.py` ends with `OK`.
- You can name one applicable requirement that Azure Policy cannot enforce and say where it routes instead.
- You can explain why an elevated-level requirement does not apply to an application with normal protection need.
- `git status` shows nothing from `tools/gspp/out/`.

## Learning resources

- [BSI Stand-der-Technik-Bibliothek: the authoritative Grundschutz++ catalogue](https://github.com/BSI-Bund/Stand-der-Technik-Bibliothek) and [BSI's Grundschutz++ page](https://www.bsi.bund.de/DE/Themen/Unternehmen-und-Organisationen/Standards-und-Zertifizierung/Grundschutz-in-der-Informationssicherheit/Grundschutz-Plus-Plus/grundschutz-plus-plus_node.html)
- [OSCAL, NIST](https://pages.nist.gov/OSCAL/)
- [OSCAL component definition model](https://pages.nist.gov/OSCAL/learn/concepts/layer/implementation/component-definition/)
- [Azure landing zones](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/landing-zone/)
- [Regulatory compliance in Azure Policy](https://learn.microsoft.com/azure/governance/policy/concepts/regulatory-compliance)

---

[Home](../Readme.md) | [Solution](../walkthrough/challenge-01/solution-01.md) | [Next challenge](challenge-02.md)
