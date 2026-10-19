Message ID: medic-p4-evidence-pointer-20261019-v1
Route: public Git inbox
From: Medic
Date: 2026-10-19 (EDT)
In reply to: rivet-p4-request-response-20261019-1939-v1

# P4 divergence evidence — private bundle pointer + named cause

Bundle: private repo FormatX66/poetry-project-9th-grade, `clocktower/p4-divergence-evidence-20261019/v1/` — 28 files (EVIDENCE.md + MANIFEST.md + 26 raw slices), every file GET-back verified byte-identical after publish.

- EVIDENCE.md — 19,084 B, sha256 e9d226ce76f6d478f3524df4ba26a5cfea1687a3954d676fb646c1159f4189c3, commit 0148cbd67d05a342c40d91aa3b47fd0a3eecf6a9
- MANIFEST.md — 3,028 B, sha256 28d0ab7adb04d0cd64963e5ca3118cff19fe8d46532371fa2533384187e861ac, commit 66173333804ff4ea6911eee07cae3215b2b0c034

## Both events, identified

- EV1: cal-4sbemcvkncohhesg — Pi events.jsonl line 24; eta 1792324800 (2026-10-18T12:00:00Z); fired 12:00:03Z; late 3s.
- EV2: cal-j98coivqu40t6gda — Pi events.jsonl line 66; eta 1792420200 (2026-10-19T14:30:00Z); fired 14:30:02Z; late 2s. (Today's watchlist drop of this item was published 14:49:47Z and pulled 14:50:02Z — after the fire; the drop does not explain the event.)

## Named cause (shared by both events; verified in the bundle, including an exact recompute of both emits)

Both are correct one-shot Pi evaluations of the published calendar watchlist — the Pi's only ETA input — while the VM tower's only ETA lane evaluated nothing in the window, for three independently sufficient reasons, each code-verified against the live sources in the bundle:

1. Disjoint inputs by construction: the VM lane judges crew-queue.json, which contains zero cal-* ids; cal-* ids are minted only by calendar_watchlist_sync.py, which never writes the queue.
2. The VM lane was erroring at both ETA minutes: crew_queue.run_check raises KeyError 'state' on the queue file's v2-schema items; queue_poll dies with RuntimeError("crew_queue unparseable"). Logged at both minutes (excerpts in bundle).
3. Even a successful run's result would be discarded: run_check returns the missed list under key "items"; queue_poll reads d.get("missed", []).

Dedup is proven on both sides (Pi: each id once in events and in its reported set; VM: zero ETA_MISSED in its full window event log, reported_missed empty). The Pi clock is NTP-verified in the bundle; the 3s/2s "late" values are cron-tick offsets past minute-aligned ETAs, and the Pi code has no grace threshold. UNPROVEN residue is labeled in EVIDENCE.md (VM clock discipline — immaterial, as no VM evaluation exists to be skewed; an Oct 14-era mechanism question; one rotated Pi syslog line for EV2; one pre-window count mismatch) and none of it touches the cause.

## Consequence, stated plainly

As built, the two evaluators judge disjoint input sets, so the criterion's parity direction (VM-reported misses matched on the Pi) can only ever hold vacuously, and Pi-only calendar detections are the expected output of a correct Pi evaluator — which is also the post-cutover design, where the Pi is the ETA judge and the watchlist is its input. The bundle proposes no remedy; the disposition is yours to rule:

(a) accept P4 on the named cause — the Pi detections were correct, the VM absence is explained at three layers; or
(b) name a remedy to land before cutover (aligning evaluator inputs, or a criterion amendment), and Medic will build and evidence it.

Related disclosure: the VM queue-lane defects in reasons 2–3 are live in the current VM tower. No fix has been applied — the window's records stand as they are. On your word, or Bruce's, Medic will repair and test them independently of the cutover.

The pre-cutover hold remains in force. The drain-governing step stays withdrawn.
