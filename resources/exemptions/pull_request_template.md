## Exemption request

<!-- One exemption file per pull request. The file in exemptions/ is the request; this text is for the reviewer. -->

- File: `exemptions/exc-...json`
- Requirement IDs and modal verb (only SOLLTE can be exempted):
- Resource group and resource:
- Expiry (UTC, at most the lab maximum ahead):
- Risk owner (GitHub login, not the author): @

## Why the requirement cannot be met yet

<!-- The justification in the file, plus the plan that ends the exemption before its expiry. -->

## Risk while the exemption applies

<!-- What can go wrong, for whom, and which compensating controls reduce it. -->

## Risk owner checklist

The approving review is the decision record. Approve only when all of these hold:

- [ ] I am the named risk owner and I did not open this pull request.
- [ ] Every requirement behind the named policy references is listed, and none is MUSS or KANN.
- [ ] The scope is the smallest that works: one resource where possible.
- [ ] The expiry is the earliest date that works, and the plan to end the exemption is credible.
- [ ] I accept the stated risk until the expiry.
- [ ] CI job `validate` passed on the commit I approve.
