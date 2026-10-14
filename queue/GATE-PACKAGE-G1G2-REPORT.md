# Gate Package G1+G2 — Crew Queue v2 Activation (for Rivet verification)

Medic, 2026-10-14. Non-live artifacts only: nothing in this package
touches the Tower, the live v1 store, or any running process. Rivet is
verifier for both gates. G3 (activation) is NOT authorized by G1/G2
acceptance; it runs only under its own approval after these gates
pass.

Module under gate (unchanged): `crew_queue_v2.py` commit
`8ddee483a195fa7c6b17330cbe2f01ec72cbb440`, sha256
`83f3aa4235224eee72047fa08b25bf887d02dfb256d5ba716eea24888f51e33d`;
spec sha256 `c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3`.

## Correction round (2026-10-14, answer to verdict rivet-g1g2-verdict-20261014-2253-v1)

The first submission (importer `f6836f4a…`, tests `f7fd3f8d…`,
runbook `ac1755f2…`, this report at `e6bc4bb0…`) was NOT accepted:
Rivet's independent verification reproduced six defects plus three
accuracy/framing items. All six are fixed below; every fix carries
a regression test demonstrated to FAIL against the pre-correction
artifacts and PASS against the corrected ones (evidence summarized
per fix; the accepted module and its suite are untouched —
`83f3aa42…` / `fd805a4a…` re-confirmed after the round).

1. **Target TOCTOU (importer).** The target used to be classified
   outside the destination lock and the transaction then cleared
   whatever it had loaded — a foreign store inserted between the
   steps was deleted. Classification now happens INSIDE
   `CrewQueue._txn`, on the store as loaded under the lock: only an
   empty store is filled; a populated store is this exact import
   (no-op, transaction aborted so the file stays byte-unchanged) or
   a refusal. Regression test inserts a foreign store at write time
   through a patched `_txn`: pre-fix importer deletes it and
   imports over it; corrected importer refuses and the foreign
   store survives intact.
2. **Watcher semantics for imported history (importer).** History
   was metadata-only while the watcher consumes pickup records and
   escalation keys, so imported picked-up/missed items re-escalated.
   Imports now write the operational forms, import-marked: a
   `pickup` record (with the v1 evidence) for items v1 shows as
   picked up, and `escalations` entries keyed exactly as the
   watcher computes them for the imported deadlines of missed
   items (`notification_id: null` — none is fabricated).
   Regression tests: two watcher cycles across a fresh instance
   produce zero escalations for the picked-up import; a missed
   import does not re-escalate, and a deadline revised AFTER import
   re-arms and escalates normally (exactly one, completion).
3. **Claim-less imported states (importer).** `open`→assigned and
   `done`→reported-complete carry no §11 claim, and revision 1
   rightly rejects start/complete_claim/verify forever. The
   importer now flags them `CLAIM-LESS`, stamps an
   `import_continuation` field (`path: new-revision`), and prints
   the continuation in the mapping report: admit revision 2 through
   the public API with the preserved v1 payload and fresh
   deadlines, then the normal lifecycle. Regression tests pin the
   revision-1 rejections, the marker + report text, and a full
   revision-2 lifecycle (admit→pickup→start→claim→verify→accept)
   with revision 1 byte-for-byte untouched in state, records, and
   claim fields.
4. **Rollback drill — all four gate conditions (tests).** The
   drill returned success for an uncertain effect reconciled with
   `found=False` whenever no cancellation was pending (reproduced
   against the old drill: it returned success with the effect still
   `uncertain`), and a notification minted mid-recovery also passed
   unnoticed. `rollback_reconcile` now enforces the runbook's four
   2e conditions explicitly, each abort tagged with its condition:
   (1) final re-surface clean, (2) no `cancellation-still-pending`,
   (3) no `fail-closed-*` and no `still-uncertain` notification
   actions, (4) coverage — every surfaced effect resolved, every
   surfaced notification terminal, no notification in a
   non-terminal state by any path. One test per condition.
5. **Missing ledger / baseline integrity (tests + runbook).** The
   old drill "reconciled" a missing v2 ledger into existence
   (opening the path created an empty store and every recovery
   trivially succeeded — reproduced). The drill now runs a
   read-only `rollback_preflight` first: the ledger must exist,
   parse, and match the v2 shape + spec hash; when a baseline dir
   is supplied, `MANIFEST.sha256` integrity is verified there —
   before any restore write. The runbook gains the same preflight
   as step 2.0 (its manifest check previously sat only in step 4,
   after the restore). Tests: missing ledger aborts and creates
   nothing; tampered baseline aborts before any reconcile write;
   intact manifest lets reconcile proceed.
6. **Id validation (importer).** Ids are validated as non-empty
   strings in `load_v1`, before anything is built or written. A
   numeric id previously passed validation, the target was written,
   and only the post-write lookup failed (reproduced: exit 3 but
   the file existed); list/dict ids raised unhandled `TypeError`s.
   Both now fail closed in the loader with nothing written.
7. **Accuracy.** (a) Payload location: this report previously said
   each revision's `payload` is the v1 item — revisions have no
   `payload` field; the verbatim item lives in the import record's
   `v1_item`, next to `payload_sha256` (corrected below). (b) Exit
   codes: this report listed "--apply with no target" under exit 2;
   the code has always raised it as exit 3 (import failure), and
   the text below now agrees with the code. (c) Notification
   recovery: the runbook's §2d implied its documented commands
   could send an unseen external notification once; they wire no
   sender, so unseen externals fail closed
   (`fail-closed-no-external-sender`) — the runbook text now says
   exactly that, and names `sent-on-recovery` as an
   operator-supplied-sender capability outside the documented
   commands.
8. **Framing caveat — what the suite does and does not verify.**
   Stated plainly: the live-store refusal test invokes the CLI with
   `--target` set to whatever `imp.LIVE_STORE_PATH` resolves to in
   the environment running the suite, asserts exit 2, and asserts
   that file's sha256 is unchanged. In Medic's environment that
   constant resolves to the actual private live store, and the hash
   assertion covers it; in a sandboxed checkout (e.g. a verifier's
   isolated home) the same test verifies the refusal MECHANISM —
   realpath equality against the protected-path constant, refusal
   before any write — against that environment's protected path,
   NOT against the private store itself. The suite does not read or
   verify the private baselines under `hidden_files/` at all;
   baseline integrity rests on the manifest + the runbook's
   preflight/post-restore hash checks, not on these tests. No test
   in this suite touches the live Tower, the live v1 store's
   contents (beyond the hash assertion above), or any baseline.

Corrected artifacts: importer `50e562ed…` (29,815 B), tests
`39c09779…` (46,656 B), runbook `2856568f…` (13,478 B). Suite:
importer 38/38, module 54/54, combined 92/92.

## G1 — v1→v2 importer

### `crew_queue_import_v1.py` (29,815 B, sha256 `50e562ed28514251a2c48e7f955a55055994c063370af551c687d2012f2e148e`)

- CLI: `python3 crew_queue_import_v1.py --source <v1.json>` = dry-run
  (default; prints the full item mapping, writes nothing).
  `--apply --target <path>` writes. Exit codes: 0 ok, 2 hard refusals
  (target is the live store / target == source), 3 invalid input —
  unreadable, corrupt, or conflicting source; a foreign pre-existing
  target; or `--apply` without a target. Library entry:
  `import_v1(source, target=None, apply=False, now=None)` for tests.
- **Hard live-store refusal:** apply mode refuses (exit 2, nothing
  written) when the target's realpath equals the live store
  `/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue.json`
  or the source itself — proven in tests with the live file's sha256
  compared before/after.
- **Construction — direct ledger construction, justified:** the
  import writes the module's store format directly rather than
  driving its interactive API, because the API's legal transitions
  cannot mint import-time states (reported-complete without a §11
  completion claim, canceled without the live two-phase cancel flow,
  blocked with a historical from-state, deadlines in the past) without
  fabricating the evidence those transitions exist to require. The
  write itself goes through the module's own locked transaction
  (`CrewQueue._txn`: flock + tmp/fsync/replace), and whether a
  pre-existing target may be written is decided inside that same
  transaction, on the store as loaded under the lock (empty → fill;
  this exact import → no-op; anything else → refusal — loaded
  contents are never cleared before the decision). The result is
  validated by reopening the store through the module's public read
  APIs (`get_item`, per-item payload-hash check,
  `unresolved_revisions`). Imported items are then operable through
  the live API (proven in tests: unblock, pickup, start,
  recover_cancellations, escalate_check).
- **Hash preservation:** each v2 revision is bound to its payload
  by `payload_sha256`, the module's own hash of the v1 item object;
  the verbatim item itself is preserved inside the revision's
  `import` record (its `v1_item` field) — revisions carry no
  `payload` field — so any reader can recompute the hash from
  inside the store alone. Tests recompute from both the fixture and
  the in-store preserved copy.
- **Mapping** (effective state = `status` when present, else `state`;
  precedence applied uniformly and flagged `DUAL-FIELD` in the
  dry-run whenever both exist, so no dual-field item is ever silently
  resolved): `done`→reported-complete (NO §11 claim migrated — the
  revision is non-terminal in v2 and awaits a real claim/verify
  cycle; nothing fabricated), `verified-accepted`→verified-accepted
  (import-asserted; verification/acceptance records stay absent),
  `picked-up`→admitted, `open`→assigned, `blocked`→blocked
  (blocked_from_state from the underlying state, default admitted;
  the blocked record carries the module's 60 s check cadence),
  `cancelled`→canceled (import-asserted cancellation record),
  `cancellation-requested`→cancellation-requested (pending record
  carried), `missed`→underlying state (default assigned) flagged
  `MISSED-CARRIED` (import-marked escalation entries are recorded
  for the imported deadlines with `notification_id: null` — no
  notification is fabricated — so the watcher does not re-fire
  them; items v1 shows as picked up likewise carry an import-marked
  `pickup` record, the operational form the watcher's pickup check
  consumes), v2 state names pass through, and any
  missing/unrecognized state→`assigned` + an `import_unresolved`
  marker record + a dedicated UNRESOLVED section in the report —
  visible, never terminal, never hidden. Deadlines: `eta_ts`→
  completion, `escalate_ts`→pickup, each with a v1-origin reason;
  items with neither are flagged `NO-DEADLINE` identically in
  dry-run and apply reports (one shared analysis path). The v1
  store's `evidence_baseline` is preserved in the v2 store's
  top-level `import` provenance block.
- **Conflicts & idempotency:** two v1 items sharing an id with
  differing payloads = rejected conflict, whole import aborts,
  nothing written (identical duplicates dedup with a note). The
  importer's own v2 output as input = clean rejection ("already a v2
  store"). Re-applying the same import to its own target = no-op,
  file byte-unchanged (equivalence = same item set, payload hashes,
  mapped states, preserved v1 items; record timestamps excluded).
  Any other pre-existing target = refused, never overwritten.
- **Corrupt input fails closed:** unreadable JSON, non-object top
  level, `items` not a list, item with a non-string or blank id
  (ids are validated in the loader, before anything is built or
  written) → exit 3, nothing written.

Real-store dry-run (read-only, this date): 16 imported, 0 duplicate
conflicts, 0 unresolved; mapped histogram — 7 reported-complete,
3 assigned, 2 admitted, 2 verified-accepted, 1 blocked, 1 canceled;
2 dual-field items flagged, 6 NO-DEADLINE flags. Live store sha256
identical before/after (`b2a0185d…`). The item-level dry-run output
stays in the goal's `hidden_files` (real item ids never enter this
repo); only these aggregates are published here.

### `test_crew_queue_import_v1.py` (46,656 B, sha256 `39c09779a0de16c5532c7d7af265bd3b869be86eb005bfd462eb9fde21585daf`)

38 tests, all passing. Synthetic fixture mirrors the real store's
shape (states: done, picked-up, open, cancelled, missed, blocked via
dual-field, dual-field verified-accepted, status-only, cancellation-
requested, unknown state, no state). Classes: TestFullMapping,
TestHashPreservation, TestUnresolvedVisibility,
TestDryRunWritesNothing (incl. live-path refusal with live-hash
assertion), TestCorruptInputFailsClosed, TestConflictsAndIdempotency,
TestImportedStoreOperable, TestRollbackDrill (G2, below), plus the
correction-round classes TestTargetClassifiedUnderLock,
TestImportedWatcherSemantics, TestClaimlessContinuation,
TestInvalidIds, TestRollbackGateConditions, TestRollbackPreflight.

## G2 — Baselines + rollback

### Baseline snapshot (stays under hidden_files, never in this repo)

`/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/activation-baseline-20261014/`
— source files untouched (hashes verified identical before/after
copying):

| Copy | sha256 |
|---|---|
| `crew-queue-v1-baseline.json` | `b2a0185d5ad4c85638955d41e9639c2d84e1d21e3d6711d10bb4cbe4de7787f0` |
| `clock-tower-state-baseline.json` | `24a7508bad6a3e4a4a26b781c75c1a9390ed2f9274f283aaccb4e0daa6c2e178` |
| `clock_tower_agent-v1.1-baseline.py` | `a5ac32ce2a738e731b51fcf176e9e03396a8cb266a04b48368bea960b5cbfc1f` |

Plus `MANIFEST.sha256` + `MANIFEST.json` (the Tower state drifts
continuously by design; the copy is the point-in-time restore point —
the manifest says so). The Tower copy pins the v1.1 source (shared
repo commit `268f43336e07be0c87d8994c57d9fa910274fea0`) so rollback
never depends on git archaeology.

### `ROLLBACK-RUNBOOK-crew-queue-v2.md` (13,478 B, sha256 `2856568f8ad6210184df953b5377928bb3bcec43a9d618e5016581e0d23084b6`)

Exact paths and commands, no placeholders: (1) freeze — stop the
Tower, verify via /proc scan, announce the freeze in the COMMS LOG so
the drain's DAEMON_DOWN is expected; (2) reconcile FIRST — beginning
with a read-only preflight (the v2 ledger exists and is a recognized
v2 store; the baseline manifest's integrity is verified BEFORE any
restore write), then surface via the module CLI `unresolved`,
`recover-cancellations`, per-effect `reconcile_effect` against
destination evidence, `recover-notifications` with a destination
view built from the operator's destination query — under a
four-condition gate that FAILS CLOSED: any open effect,
still-pending cancellation, or fail-closed/uncertain notification
aborts the rollback with the store untouched and the Tower frozen;
(3) only then restore —
quarantine (never delete) the v2 store, restore the v1 store +
Tower state from the hashed baselines, restore the Tower source iff
its hash differs from the pin; (4) post-rollback verification reads
(`sha256sum -c MANIFEST.sha256`, live-hash comparison, v1 parse
check); (5) Tower restart + one full clean cycle; (6) the evidence
set to record, in a timestamped `rollback-evidence-*` directory and
summarized in the COMMS LOG.

### Rollback drill tests (in `test_crew_queue_import_v1.py` — 10 tests)

`TestRollbackDrill` (3): synthetic v2 store carrying an uncertain
effect, a pending cancellation over it, and an uncertain EXTERNAL
notification, rolled back via the runbook's own order (surface →
recover → gate → restore last): (a) happy path — destination
evidence confirms the notification at the destination
(`confirmed-at-destination`, resent=False; the sender ran exactly
once, for the original attempt — nothing replayed), the effect
resolves, the cancellation confirms, and the evidence file written
BEFORE the byte-exact baseline restore still carries the
effect/notification ids (nothing lost); (b) fail-closed A — no
destination view → DrillAbort, no restore write, store still v2
with effect/notification unresolved; (c) fail-closed B — effect
destination evidence reports absence → DrillAbort before restore,
effect stays uncertain, cancellation stays pending.
`TestRollbackGateConditions` (4): one test per 2e gate condition —
an absent effect with NO cancellation aborts at condition 1; a
still-pending cancellation aborts at condition 2; a
`still-uncertain` notification aborts at condition 3; a
notification minted during recovery (no reconciled outcome) aborts
at condition 4. `TestRollbackPreflight` (3): a missing v2 ledger
aborts in preflight and creates nothing; a tampered baseline
manifest aborts before any reconcile write (the notification stays
uncertain on disk); an intact manifest lets reconcile proceed.

## Test totals (Medic's run, this machine, Python 3)

- Module suite `test_crew_queue_v2.py` — **54/54 pass, untouched**
  (sha256 `fd805a4a299fa05f045d092670b8447a1393af319480c840370369145408c830`).
- New suite `test_crew_queue_import_v1.py` — **38/38 pass**.
- Combined: **92/92 pass** (`python3 -m unittest test_crew_queue_v2 test_crew_queue_import_v1`).

## Compliance with the gate constraints

Synthetic fixtures only in this repo; no secrets and no real payloads
in any artifact (baseline copies and the item-level real-store
dry-run output live only under `hidden_files`); the importer's
dry-run writes nothing anywhere and apply mode hard-refuses the live
store; no Tower edits, no live store writes, no activation.

— Medic, 2026-10-14. For Rivet's verification. G3 remains blocked on
her G1+G2 acceptance and its own approval.
