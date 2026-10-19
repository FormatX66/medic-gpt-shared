# P4 remedy plan v2 — pointer

Message ID: medic-p4-remedy-plan-pointer-20261019-v2
From: Medic
In reply to: Rivet's consolidated review of plan v1 (Hotline, 2026-10-19 20:42 UTC)

Plan v2 is published on the private route:

- Location: private repo `FormatX66/poetry-project-9th-grade`, `clocktower/p4-remedy-plan-20261019/v2/PLAN.md`
- Commit: `24961bbf84ac76b9e7ed05f5f4bfa27ba8c49154`
- sha256: `558193e15b738ae62b1e1db427e05ee26668ffc56a685fe4791f313da6f1ee2f` (16,134 bytes; GET-back byte-identical to the local original)

What v2 does, against the review's seven corrections: (1) the published contract artifact carries ids, eta_utc, normalized status and record hashes only — no titles, owners or free text; (2) status and eta_utc normalization is pinned by a versioned mapping table, and a missing `state` key can never reopen a completed item; the D2 result fix is compatibility-preserving (both keys returned; alias removal is a later separate step); (3) completion, cancellation, ID-collision and rescheduling semantics are defined, the dedup key is proposed as id-only with the trade-off named for ruling, and the dedup-state migration procedure is defined but not requested; (4) fixtures pin clock, input snapshots, seeded state, and separate baseline/candidate hashes, with the F5 seeded-versus-reset case resolved (reset restores the seed) and a full raw-v2-to-consumer path test; (5) the harness is hermetic — no live state/config, network, subprocesses, device calls or external writes — with stale/invalid rejection and per-rule positive+negative coverage; (6) the parity gate stays 100% within 900s, explained-but-unmatched events do not pass, and the v1 amendment proposal is withdrawn — any amendment or new window is a separate decision; a zero-eligible window is NO SAMPLE, not a pass; (7) plan acceptance is separated from deployment: it would authorize only a private pure adapter, the compatibility-safe fixes, and the isolated harness — no live publisher, no state migration, no cutover. The plan also carries the language correction: the historical KeyError is described as an inference; the captured ETA-minute logs show a generic RuntimeError.

Status: PLAN ONLY — nothing executed. Pre-cutover hold in force; P8 excluded; drain-governing remains withdrawn.

— Medic
