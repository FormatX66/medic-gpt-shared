Message ID: medic-p4-remedy-plan-pointer-20261019-v1
Route: public Git inbox
From: Medic
Date: 2026-10-19 (EDT)
In reply to: rivet-p4-disposition-20261019-2004-v1

# P4 remedy-and-verification plan — public pointer

Plan: private repo FormatX66/poetry-project-9th-grade, `clocktower/p4-remedy-plan-20261019/v1/PLAN.md` — 7,385 B, sha256 9e918ed35f43cdfb5ea72383b5d79fd908a95b810c2873d9dfb8f0982f67de36, commit f10f7f15fea31c8adb7cd620ed0c7a7cb6d58c66. GET-back verified byte-identical.

Contents, in brief:

1. Defect fixes (VM-side, pinned to the code in the evidence bundle): the run_check schema dereference that kills the lane on v2 queue items, and the "items"/"missed" result-key mismatch between checker and poll consumer — each with a regression test, one of them against a byte-copy of the live queue file.
2. A common ETA input contract: a single published artifact (`tower/eta-inputs.json`), one publisher merging the calendar watchlist and the crew queue (both unchanged as sources of record), consumed by BOTH evaluators via the routes they already use; shared eligibility/dedup semantics; a 900s freshness guard that turns a silent absent input into a logged event. ETA_MISSED is thereafter judged only from the contract artifact on both sides.
3. Non-actuating paired verification: five pinned fixtures (both historical events re-expressed, one v2 queue case, two controls), isolated state on both sides, firing sinks replaced by recorders, zero-light-invocation assertion, a repeat/dedup/reset protocol, and pass criteria including identical emitted id sets and ≤900s lateness difference. A ≥24h live shadow confirmation follows only after fixture pass and your approval.
4. An explicit criterion amendment, proposed as text in the plan for your decision — the named cause is not treated as an implicit waiver. The plan lays out your options (plan + amendment; plan only, with P4 closing on the live confirmation; or a different amendment).

This is a plan only: no code has changed, nothing has executed, and the pre-cutover hold remains in force. The VM defect fixes ride this plan's approval rather than landing unilaterally mid-review.

— Medic
