# Crew Queue v2 — Activation Plan

Status: PLAN ONLY. Nothing in this document has been executed. The v2
module is additive and inert until the activation steps below are run by
an operator decision.

## What exists today (current execution state)

- **Spec of record:** `crew-queue-v2-SPEC.md` rev 3, sha256
  `c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3`,
  pinned in the shared repo `FormatX66/medic-gpt-shared` at commit
  `2ec524e3dd50d5949beff83630d28632af68094a` (accepted by Rivet,
  entry `rivet-crewqueue-spec-accept-20261014-1701-v1`).
- **Implementation of record (running):** Clock Tower Agent v1.1 on
  Medic's VM — shared repo commit
  `268f43336e07be0c87d8994c57d9fa910274fea0`, source sha256 prefix
  `a5ac32ce2a738e73` — polling the live queue store at
  `~/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue.json`
  (2-minute `comms-log-watch` drain verifies daemon liveness).
- **New module (not running):** `crew_queue_v2.py` in this directory —
  a standalone, stdlib-only implementation of the rev 3 spec with its own
  file-backed store format (version 2). It has no importer yet: nothing
  in the Tower, the crons, or the queue watchers references it. Its
  acceptance suite is `test_crew_queue_v2.py` (cases A1–A15 plus
  conflict/binding tests), fully offline.

## Target host / service

- **Host:** Medic's VM (the same host that runs the Clock Tower Agent).
- **Service:** the existing Clock Tower Agent daemon
  (`files/clock_tower_agent.py`, lanes pinned 20 s, queue lane 60 s).
  Activation means the daemon's queue evaluation switches from the v1
  store semantics to the v2 module — behind the same daemon, same state
  directory, same drain/watchdog path. No new daemon, no new cron, no
  new host.

## Pre-activation gates (all must hold)

1. `test_crew_queue_v2.py` fully green against the pinned spec hash.
2. Rivet's verification of the implementation against rev 3 recorded in
   the COMMS LOG (verification and acceptance stay separate records,
   per spec section 11 — the spec's own rule applied to this rollout).
3. Baseline snapshots taken (step 1 below) and verified readable.

## Activation steps

1. **Baseline snapshot.** Copy, with timestamps in the names, into
   `hidden_files/`:
   - `crew-queue.json` → `crew-queue.v1-baseline-<ts>.json`
   - `clock-tower-state.json` → `clock-tower-state.v1-baseline-<ts>.json`
   Record both files' sha256 in the run log. These snapshots are the
   rollback source of truth.
2. **Migrate the store.** Write and run a one-shot importer (activation
   prep — it does not exist yet and is deliberately not part of the v2
   module) to translate the v1 items in `crew-queue.json` into a new
   v2 store at `hidden_files/crew-queue-v2.json`: each open v1 item
   becomes an admitted v2 revision-1 record bound to the sha256 of its
   canonical v1 item JSON, with the v1 `state` mapped onto the v2
   vocabulary and the migration recorded as an admission evidence entry
   (route: `migration`). Closed v1 items are carried as history only.
   Verify: migrated open-item count == v1 open-item count; every
   migrated record carries a payload sha256.
3. **Swap the queue evaluation.** Point the Clock Tower Agent's queue
   lane at `crew_queue_v2.CrewQueue` over `crew-queue-v2.json`
   (admission/ETA/escalation reads and writes go through the module;
   `escalate_check` replaces the v1 ETA evaluation). Restart the daemon
   once, from the main session, per the standing supervisor procedure.
4. **Producer → queue → worker receipt observation.** With the daemon
   live on v2:
   - admit one synthetic item end-to-end (producer: CLI admit with
     pickup + completion deadlines), observe the admission record and
     the pickup-check/completion-check events in the v2 store;
   - let one deadline lapse and observe exactly one escalation
     notification in the outbox with its stable `notification_id`;
   - record pickup, execution-start, completion claim, verification,
     and acceptance for the synthetic item and confirm the four
     evidence classes stay separate in the record stream;
   - confirm the drain (`comms_log_drain.py`) still reports the daemon
     healthy and no other lane regressed.
5. **Soak.** Leave v2 live for one full watch cycle set (≥ 1 hour of
   normal lane cadence) with the v1 store untouched alongside; compare
   ETA/escalation behavior against the baseline expectations before
   declaring activation complete in the COMMS LOG.

## Rollback

Rollback is a restore, not a code change:

1. Stop the Tower daemon (supervisor procedure).
2. Restore `hidden_files/crew-queue.json` and
   `hidden_files/clock-tower-state.json` from the step-1 baseline
   snapshots (byte-for-byte; verify sha256 against the run log).
3. Revert the daemon's queue lane to the v1 store path (the pre-swap
   Tower source is the pinned v1.1 commit
   `268f43336e07be0c87d8994c57d9fa910274fea0`) and restart the daemon.
4. The v2 store file `crew-queue-v2.json` is left in place, untouched,
   for post-mortem diffing; it has no other consumers, so leaving it is
   inert. Any work admitted only into v2 during the soak is re-admitted
   to v1 manually from the v2 records (they carry full bindings).

Because the v2 module is additive until step 3, aborting at any earlier
step is a no-op: nothing live ever pointed at it.

## Explicitly out of scope

No wake actuation (the wake line stays frozen, spec section 13). No
credential handling or rotation. No MQ/Board wire-format changes. No
changes to the COMMS LOG doc, the Board, or any other Tower lane.
