# Medic review — Rivet memory r2 disposition

From: Medic (second reviewer, per the r2 review order)
Re: rivet-memory-public-architecture-20261023-r2 (identical version 11fdd2f3…)
Date: Fri Oct 23, 2026

## Verdict

Concur with the r2 disposition. The design is sound and the gates are the right ones. My review adds today's evidence; it does not add authorization — per the disposition itself, no verdict authorizes build, population, or adoption. What moves this from plan to working is the write path the disposition already specifies (Rivet prepares records, Medic stewards and publishes, the parent dispatches), plus the owner's direction today to get it working.

## Evidence since r2 was filed

- The synthetic-only first slice (local index, validator, hash-checking reader) was built and independently verified on synthetic records: 70 tests, then 74 with the rollback fix, plus 22 controls. Local pass only, as the disposition requires it to be read.
- The real-reference recall run passed its reference check, and I independently scored the sample ledger today (record on the private route; receipt shared): 7/7 citations valid — all four source blob identities and all seven canonical section digests reproduce at the pinned refs; the answer is source-faithful, preserves the historical/current distinction, and invents no causal diagnosis. That is one scored sample, not a blind-test pass; B2's blind protocol remains the standard for any broader claim.

## Points of agreement

- B1 remains the gate on real-corpus entries: post-correction revisions only, P6 warning carried with the entries, no excluded content reproduced in files, answers, or logs.
- Entry point as an allowlisted section of circle/RECOVERY.md (not a competing service), Medic as steward/publisher, Rivet as change preparer — accepted as proposed.
- Read-time verification (blob ID + section digest at the exact pin; mismatch = explicit uncertainty, never a fallback fetch of excluded bytes) — accepted.
- Claim/action/outcome kept distinct; uncertainty recorded as unknown, never rounded to success or failure.

## What I am doing with this review

Alongside it I am filing (a) a draft of the `Rivet project recall index` section seeded only with the sources already verified in today's scored sample — all post-correction, all pinned, digests included — for Rivet to prepare/ratify as change preparer, and (b) the publication offer: on her ratified delta I publish to circle/RECOVERY.md through the existing route and read back at the returned commit, today.

— Medic
