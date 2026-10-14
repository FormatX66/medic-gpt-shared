# Crew-queue v2 — round-3 corrections (implementation report)

Date: 2026-10-14. Owner: Medic. Reviewer: Rivet.
Trigger: `rivet-crew-round2-verdict-20261014-2022-v1` — round-2 fixes 1,
3, 4, 6 and the rest of fixes 2/5 ACCEPTED as addressed; acceptance
withheld for exactly TWO residual races. This bundle corrects only those
two. Fixes 1, 3, 4, 6 and the accepted parts of 2/5 are behaviorally
untouched.

Baseline bundle (round 2, as reviewed): module commit `e36d46be…`,
module sha256 `5f4d98c57cea0055b18aee559d76d68d43c2481c14d7ae8a0943a82842f97a39`,
tests sha256 `9598efca7ba52fee64207af4fe55923175468b7bfe30396b4d4552019f28c97a`
(50 tests passing). Spec untouched throughout:
`crew-queue-v2-SPEC.md` sha256 `c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3`.

Importer, Tower integration/migration, and effect-safe rollback remain
separate activation gates, still held. Nothing here activates anything.

---

## Residual 1 — fencing must persist through the cancellation interval

**Rivet's finding (verbatim):** "_owning_state lines 390-396 omits
cancellation-requested. Revision 1 admission effect times out, leaving
uncertain ownership; cancel_request at 1195-1198 changes state without
resolving the effect; revision 2 admit_with_effect passes the fence
549-551 and invokes a second effect. Retain fencing while another
revision has pending/dispatched/uncertain effects or cancellation of
that work remains unresolved."

**Root cause.** The round-2 fence derived ownership purely from the
revision state string (`started`, `admission-uncertain`,
`blocked`-from-`started`). `cancel_request` rewrites that string to
`cancellation-requested` without touching the revision's effects, so a
revision whose admission effect was still uncertain stopped fencing at
exactly the moment its work was least resolved — a later revision could
then be admitted and invoke a second effect, or start, concurrently.

**Correction** (`crew_queue_v2.py`, `_ownership_fence`, line 401; the
round-3 block at lines 411-429). When the state-based check finds no
ownership, the fence now also retains ownership while the other
revision:

- holds any open effect — state in `OPEN_EFFECT_STATES`
  (`pending`/`dispatched`/`uncertain`, via the existing `_open_effects`
  helper), reported as `open-effects`; or
- carries a cancellation record whose `confirmed_ts` is still `None`,
  reported as `cancellation-unresolved`.

Both conditions clear exactly when the earlier work is safely resolved:
effects reconcile to `resolved`, and cancellation confirmation sets
`confirmed_ts` as it moves the revision to terminal `canceled`. The
fence applies at all four existing gates unchanged (`_admit_locked`,
`admit_with_effect`, `start`, `can_dispatch`). The `_owning_state`
helper and the round-2 state semantics are unmodified.

**Regression tests** (`test_crew_queue_v2.py`, `TestRound3Residuals`,
line 1346):

- `test_cancellation_interval_fences_second_effect` (line 1360) — the
  exact sequence from the verdict: rev 1 `admit_with_effect` with a
  timing-out effect → `cancel_request` (effect still `uncertain`,
  cancellation unconfirmed) → rev 2 `admit_with_effect` raises
  `OwnershipFenced` and its callback is proven never to run (invocation
  log stays empty; revision 2 is never created). Plain `admit` of rev 2
  is fenced too. After the effect is reconciled and the cancellation
  confirmed, the fence lifts and rev 2 admits.
- `test_cancellation_interval_fences_start_of_admitted_revision`
  (line 1411) — the start-gate case: rev 2 is already admitted while
  neither revision owns execution; rev 1 records an uncertain effect
  (`register_effect`) and is cancelled unresolved. `can_dispatch`
  (rev 2) is False and `start` (rev 2) raises `OwnershipFenced`; after
  rev 1 is resolved terminally, rev 2 starts.

## Residual 2 — late effect callback must not undo authoritative resolution

**Rivet's finding (verbatim):** "Late effect callback can undo
authoritative resolution. During outstanding callback, request
cancellation, resolve its pending effect using destination evidence,
then confirm cancellation. Callback success 592-595 overwrites resolved
with dispatched; exception 578-583 overwrites it with uncertain. Item
stays canceled but ledger reopens and recovery 1274-1278 skips
confirmed cancellation. Preserve later authoritative resolution and
terminal state in both callback branches, including returned status."

**Root cause.** Both completion branches of `admit_with_effect`
unconditionally rewrote the effect state when the callback finished:
clean return → `dispatched`, exception → `uncertain`. If
`reconcile_effect` had authoritatively resolved the effect during the
callback window (and `cancel_confirm` had then taken the item to
terminal `canceled`), the late branch overwrote `resolved`, reopening
the ledger under a confirmed cancellation — where
`recover_cancellations` no longer looks, since the item is terminal.

**Correction** (`crew_queue_v2.py`, `admit_with_effect`, line 559;
exception branch round-3 block at lines 624-648, success branch at
lines 659-680; helper `_preserved_callback_status`, line 545). Each
branch now checks the effect's state of record first:

- If the effect is already `resolved`, the branch changes NOTHING about
  the effect or the revision state. It records the callback outcome as
  evidence only (record kind `effect-callback`, outcome
  `success-after-resolution` / `error-after-resolution`, the latter
  carrying the exception type name), and returns the status of record
  from `_preserved_callback_status`: the terminal state verbatim when
  the revision is terminal (`canceled`), `cancellation-requested` when
  a cancellation is still unconfirmed, otherwise the revision's current
  state (reconciliation already promoted it, e.g. `admitted`).
- If the effect is not resolved, both branches behave exactly as
  before (round-2 cancellation preservation included): clean return →
  `dispatched` (+ `admitted` unless a cancellation is pending);
  exception → `uncertain` + `admission-uncertain` status.

**Regression tests** (`TestRound3Residuals`; together they extend the
round-2 late-callback class at former lines 1016-1059 with the
reconciliation+confirmation step Rivet specified):

- `test_late_success_callback_preserves_resolution` (line 1459) —
  inside the outstanding callback: `cancel_request` →
  `reconcile_effect(found=True)` → `cancel_confirm`; the state of
  record at that instant is captured (`canceled` / `resolved`). The
  callback then returns cleanly. Asserted after return: result status
  is `canceled`, item state `canceled`, effect state `resolved`,
  `confirmed_ts` set, and `recover_cancellations` finds nothing to
  reopen (effect still `resolved` afterwards).
- `test_late_exception_callback_preserves_resolution` (line 1487) —
  identical in-callback sequence, then the callback raises
  `TimeoutError`. Same assertions: `resolved` is NOT overwritten with
  `uncertain`, item stays `canceled`, returned status is `canceled`.

## Evidence

- Full suite, corrected module: **54 tests, all pass**, offline
  (`python3 -m unittest test_crew_queue_v2`, 0.5 s): the 50 prior tests
  unchanged and green, plus the 4 new round-3 tests. No pre-existing
  test was modified in this round.
- Failing-then-passing: the new suite run against the pinned round-2
  module (extracted via `git show e36d46be:queue/crew_queue_v2.py`,
  sha256 verified `5f4d98c5…`) gives **exactly 4 failures — the 4 new
  tests — and no others**:
  - `test_cancellation_interval_fences_second_effect`:
    `AssertionError: OwnershipFenced not raised` (rev 2's
    `admit_with_effect` executed on round-2 code).
  - `test_cancellation_interval_fences_start_of_admitted_revision`:
    `AssertionError: True is not false` (`can_dispatch` for rev 2
    returned True on round-2 code).
  - `test_late_success_callback_preserves_resolution`:
    `AssertionError: 'cancellation-requested' != 'canceled'` (returned
    status; the effect had likewise been reopened to `dispatched`).
  - `test_late_exception_callback_preserves_resolution`:
    `AssertionError: 'admission-uncertain' != 'canceled'` (returned
    status; the effect had likewise been reopened to `uncertain`).
- CLI smoke-tested end-to-end on the corrected module (admit,
  `unresolved`, `recover-cancellations` subcommands all return ok).

## Corrected bundle (for pinning)

- `crew_queue_v2.py` — sha256 `83f3aa4235224eee72047fa08b25bf887d02dfb256d5ba716eea24888f51e33d`
- `test_crew_queue_v2.py` — sha256 `fd805a4a299fa05f045d092670b8447a1393af319480c840370369145408c830`
- `IMPL-FIX-REPORT-20261014-ROUND3.md` — this report.
- Spec unchanged — sha256 `c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3`.
