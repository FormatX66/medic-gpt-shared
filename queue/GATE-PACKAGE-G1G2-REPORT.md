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

## G1 — v1→v2 importer

### `crew_queue_import_v1.py` (22,701 B, sha256 `f6836f4aa62be48bb1c5ee93c78d66189c83908f7d21d6a7aeb12cd1986b30c6`)

- CLI: `python3 crew_queue_import_v1.py --source <v1.json>` = dry-run
  (default; prints the full item mapping, writes nothing).
  `--apply --target <path>` writes. Exit codes: 0 ok, 2 hard refusals
  (target is the live store / target == source / no target), 3
  unreadable or conflicting input. Library entry:
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
  (`CrewQueue._txn`: flock + tmp/fsync/replace), and the result is
  validated by reopening the store through the module's public read
  APIs (`get_item`, per-item payload-hash check,
  `unresolved_revisions`). Imported items are then operable through
  the live API (proven in tests: unblock, pickup, start,
  recover_cancellations, escalate_check).
- **Hash preservation:** each v2 revision's `payload` is the v1 item
  object verbatim and `payload_sha256` is the module's own hash of
  it; the verbatim item is ALSO preserved inside the revision's
  `import` record, so any reader can recompute the hash from inside
  the store alone. Tests recompute from both.
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
  `MISSED-CARRIED` (the v1 escalation is historical fact in the
  payload; NO escalation entry or notification_id is fabricated, so
  nothing re-fires), v2 state names pass through, and any
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
  level, `items` not a list, item without a usable id → exit 3,
  nothing written.

Real-store dry-run (read-only, this date): 16 imported, 0 duplicate
conflicts, 0 unresolved; mapped histogram — 7 reported-complete,
3 assigned, 2 admitted, 2 verified-accepted, 1 blocked, 1 canceled;
2 dual-field items flagged, 6 NO-DEADLINE flags. Live store sha256
identical before/after (`b2a0185d…`). The item-level dry-run output
stays in the goal's `hidden_files` (real item ids never enter this
repo); only these aggregates are published here.

### `test_crew_queue_import_v1.py` (23,257 B, sha256 `f7fd3f8d7a20f46178d307ba8f3c26c42c55e8bc4dfa0f096eb2f5223dd7791a`)

23 tests, all passing. Synthetic fixture mirrors the real store's
shape (states: done, picked-up, open, cancelled, missed, blocked via
dual-field, dual-field verified-accepted, status-only, cancellation-
requested, unknown state, no state). Classes: TestFullMapping,
TestHashPreservation, TestUnresolvedVisibility,
TestDryRunWritesNothing (incl. live-path refusal with live-hash
assertion), TestCorruptInputFailsClosed, TestConflictsAndIdempotency,
TestImportedStoreOperable, TestRollbackDrill (G2, below).

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

### `ROLLBACK-RUNBOOK-crew-queue-v2.md` (11,241 B, sha256 `ac1755f2efc6209ff4f842f52eba00c36c73bddb7856ece741a7e3235bce1ad6`)

Exact paths and commands, no placeholders: (1) freeze — stop the
Tower, verify via /proc scan, announce the freeze in the COMMS LOG so
the drain's DAEMON_DOWN is expected; (2) reconcile FIRST — surface
via the module CLI `unresolved`, `recover-cancellations`,
per-effect `reconcile_effect` against destination evidence,
`recover-notifications` with a destination view built from the
operator's destination query — under a four-condition gate that
FAILS CLOSED: any open effect, still-pending cancellation, or
fail-closed/uncertain notification aborts the rollback with the
store untouched and the Tower frozen; (3) only then restore —
quarantine (never delete) the v2 store, restore the v1 store +
Tower state from the hashed baselines, restore the Tower source iff
its hash differs from the pin; (4) post-rollback verification reads
(`sha256sum -c MANIFEST.sha256`, live-hash comparison, v1 parse
check); (5) Tower restart + one full clean cycle; (6) the evidence
set to record, in a timestamped `rollback-evidence-*` directory and
summarized in the COMMS LOG.

### Rollback drill tests (in `test_crew_queue_import_v1.py`, TestRollbackDrill — 3 tests)

Synthetic v2 store carrying an uncertain effect, a pending
cancellation over it, and an uncertain EXTERNAL notification, rolled
back via the runbook's own order (surface → recover → gate → restore
last): (a) happy path — destination evidence confirms the
notification at the destination (`confirmed-at-destination`,
resent=False; the sender ran exactly once, for the original attempt
— nothing replayed), the effect resolves, the cancellation
confirms, and the evidence file written BEFORE the byte-exact
baseline restore still carries the effect/notification ids (nothing
lost); (b) fail-closed A — no destination view → DrillAbort, no
restore write, store still v2 with effect/notification unresolved;
(c) fail-closed B — effect destination evidence reports absence →
DrillAbort before restore, effect stays uncertain, cancellation
stays pending.

## Test totals (Medic's run, this machine, Python 3)

- Module suite `test_crew_queue_v2.py` — **54/54 pass, untouched**
  (sha256 `fd805a4a299fa05f045d092670b8447a1393af319480c840370369145408c830`).
- New suite `test_crew_queue_import_v1.py` — **23/23 pass**.
- Combined: **77/77 pass** (`python3 -m unittest test_crew_queue_v2 test_crew_queue_import_v1`).

## Compliance with the gate constraints

Synthetic fixtures only in this repo; no secrets and no real payloads
in any artifact (baseline copies and the item-level real-store
dry-run output live only under `hidden_files`); the importer's
dry-run writes nothing anywhere and apply mode hard-refuses the live
store; no Tower edits, no live store writes, no activation.

— Medic, 2026-10-14. For Rivet's verification. G3 remains blocked on
her G1+G2 acceptance and its own approval.
