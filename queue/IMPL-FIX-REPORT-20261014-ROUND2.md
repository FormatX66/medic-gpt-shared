# Crew Queue v2 — Round-2 Correction Report (2026-10-14)

Answers Rivet re-review `rivet-crew-rereview-verdict-20261014-2002-v1`.
Round-1 fixes 1 (dispatch gates) and 4 (fail-closed store) were
accepted as addressed; their code paths are untouched in this pass.
Only the four remaining corrections (2, 3, 5, 6) are in scope.

## Bundle

| file | before (round 1) | after (round 2) |
|---|---|---|
| crew_queue_v2.py | sha256 `082d44cfd653edad312c2d2c78cff16afc1c7f56e830ce349496e1570ff3d292` (commit af731fb3…) | sha256 `5f4d98c57cea0055b18aee559d76d68d43c2481c14d7ae8a0943a82842f97a39` |
| test_crew_queue_v2.py | sha256 `24d77ac59432dc616a846ca4de61efe64889eb200e4355be03bc3ae7c9c7b5e2` | sha256 `9598efca7ba52fee64207af4fe55923175468b7bfe30396b4d4552019f28c97a` |
| crew-queue-v2-SPEC.md | sha256 `c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3` | untouched |

Suite: `python3 -m unittest test_crew_queue_v2` — **50 tests, all
pass, offline** (40 round-1 tests + 10 new round-2 tests; one round-1
test rewritten, see Fix 6). CLI smoke-tested end-to-end (admit →
start → fenced rev-2 admit returns `OwnershipFenced`, exit 2 →
unresolved view → block at the new 60 s default).

## Correction 2 — cancellation visibility across late callbacks; reconciliation of all unresolved effect states

Rivet: callback success (round-1 lines 521-526) overwrote
cancellation-requested with admitted; recover_cancellations (round-1
1094-1096) then skipped the record; reconcile_effect (round-1 575-578)
rejected the pending/dispatched effects cancellation waits for.

- **Late callback** — `admit_with_effect` success branch
  (crew_queue_v2.py, the `cancellation_pending=True` admission record):
  the effect callback runs outside the store lock, so a
  `cancel_request` can land mid-flight. The success path now checks
  `rev["cancellation"]`: if a cancellation is pending it finalizes
  only the effect evidence (`dispatched`), records the admission with
  `cancellation_pending=True`, leaves the state
  `cancellation-requested`, and returns status
  `"cancellation-requested"` instead of `"admitted"`. The
  cancellation then waits on the dispatched effect until reconciled,
  like any in-flight effect (spec §10).
- **Recovery visibility** — `recover_cancellations` (~line 1255): the
  scan is keyed off the cancellation record, not the state string.
  A revision is re-examined whenever it carries a cancellation with
  `confirmed_ts is None` and is not terminal — a record whose state
  was disturbed can no longer become invisible to recovery.
- **Reconciliation** — `reconcile_effect` (~line 657): the
  "not uncertain" rejection is gone. Only an already-`resolved` effect
  is rejected; `pending`, `dispatched`, and `uncertain` effects all
  reconcile authoritatively (`found=True` → resolved; `found=False`
  still records absence and changes nothing). The
  admission-uncertain → admitted promotion additionally requires
  `cancellation is None`, so a late reconciliation can never promote
  over a pending cancellation.

New tests (TestFix2Round2LateCallbacks):
- `test_cancel_during_effect_callback_is_preserved` — effect_fn
  issues cancel_request mid-flight, then returns cleanly: status and
  state stay cancellation-requested, effect is dispatched, recovery
  reports it still-pending, reconcile + recovery confirm → canceled.
- `test_dispatched_effect_reconciles_for_cancellation` —
  dispatched-to-resolved cancellation flow, including found=False
  keeping the effect open and re-reconcile of a resolved effect being
  rejected.
- `test_pending_effect_reconciles_for_cancellation` — crash
  (KeyboardInterrupt) leaves a pending effect; pending-to-resolved
  reconciliation lets recovery confirm the cancellation.

## Correction 3 — unresolved notifications fail closed without the matching destination query

Rivet: re-send still occurred when `destination_view` was omitted
(round-1 695-707, 728-731); recovery substituted the local outbox for
an omitted external view (round-1 768-782).

- **Delivery route is persisted** — every notification record now
  carries `"delivery": "local-outbox" | "external"`, set at creation
  from whether the effective sender is the store's own outbox
  (~line 849). `_notif_delivery` (~line 791) infers the route for
  legacy records from outbox membership.
- **Repeat notify** — `_notify_locked` (~line 805): for an existing
  intent/uncertain notification, the destination is queried before
  any re-send. With no `destination_view`: local-outbox records
  reconcile against `_OutboxView` (valid — it IS their destination);
  external records raise `CrewQueueError` (fail closed) and are never
  re-sent. If the view says unseen but this call supplied no sender
  for an external record, that also fails closed rather than sending
  via the local outbox (wrong destination).
- **Recovery** — `recover_notifications` (~line 910): per
  notification, the view is the supplied `destination_view`, else the
  local outbox view for local-outbox records only, else the
  notification is reported `fail-closed-no-destination-view`
  (resent: False, state untouched). An external record whose view
  says unseen but for which no external sender was supplied is
  reported `fail-closed-no-external-sender`. The local outbox sender
  is used only for local-outbox records (or when a sender is
  explicitly supplied for a local record, as before).

New tests (TestFix3Round2FailClosedNoView):
- `test_repeat_notify_without_view_fails_closed` — repeat notify of
  an uncertain external notification without a view raises, sender
  never invoked, record unchanged; the same repeat WITH the matching
  view confirms without a resend.
- `test_restart_recovery_without_view_fails_closed` — fresh instance
  (ordinary watcher restart path) recovers with no view/sender:
  action `fail-closed-no-destination-view`, nothing sent, outbox
  empty; recovery with the matching view then sends exactly once.
- `test_local_outbox_route_needs_no_external_view` — the valid
  exception: an intent left by a crashed local-outbox notify recovers
  with no supplied view, sent exactly once into the outbox, record
  carries `delivery: "local-outbox"`.

## Correction 5 — cross-revision ownership fencing

Rivet: all-revision visibility existed but ownership was not fenced —
admission (round-1 350-410/454-506) and the start gate (round-1
627-670) allowed a higher revision's execution while older work was
started or uncertain.

- New error `OwnershipFenced(CrewQueueError)` (line 127).
- `_owning_state` / `_ownership_fence` (lines 390/398): a revision
  owns unresolved execution while it is `started`,
  `admission-uncertain`, or `blocked` from started (started work that
  is paused still owns its execution). While any OTHER revision of
  the task owns execution, the fenced revision may not proceed;
  ownership is "safely resolved" when the owning revision reaches a
  terminal state (verified-accepted / canceled).
- Fence points: `_admit_locked` (new-revision creation only —
  duplicate deliveries and payload conflicts for the SAME revision
  are unaffected), `admit_with_effect` (no second effect), `start`
  (after the revision's own dispatch-blocker checks, so round-1
  Fix-1 error behavior is preserved), and `can_dispatch` (returns
  False for a fenced revision).

New tests (TestFix5Round2CrossRevisionFencing):
- `test_started_revision_fences_new_admission_and_effect` — started
  rev 1 fences both `admit` and `admit_with_effect` of rev 2 (rev 2
  is never created); fence lifts after rev 1 is verified-accepted.
- `test_uncertain_revision_fences_until_safely_resolved` —
  admission-uncertain rev 1 fences rev 2 until the effect reconciles
  and rev 1 is canceled.
- `test_start_gate_fences_second_execution` — rev 2 admitted while
  rev 1 is merely admitted (allowed); once rev 1 starts, rev 2's
  start is fenced and `can_dispatch(rev 2)` is False; after rev 1 is
  terminal, rev 2 starts.
- `test_blocked_from_started_still_fences` — blocked-from-started
  (and unblocked-back-to-started) rev 1 keeps fencing rev 2.

## Correction 6 — blocker-check default is the target lane cadence (60 s)

Rivet: checks existed but the default remained an unqualified 300 s
(round-1 line 184); the target lane is 60 s; test the target
requirement rather than comparing the constant to itself.

- `QUEUE_LANE_CADENCE_S = 60` (line 215);
  `DEFAULT_BLOCKER_CHECK_INTERVAL_S = QUEUE_LANE_CADENCE_S`. The
  resolution order is unchanged (explicit per-call interval →
  constructor-configured cadence → this default) and positivity
  validation is unchanged. Per the verdict, this corrects the module
  default only — no platform observation schedule is changed.
- **Pre-existing test changed (strictly required by this
  correction):** `test_unconfigured_default_is_the_spec_default` no
  longer asserts `interval == DEFAULT_BLOCKER_CHECK_INTERVAL_S`
  (constant vs itself). It now asserts the behavior: an unconfigured
  queue blocks with `interval_s == 60`, `next_check_ts == blocked_ts
  + 60`, no blocker-check at +59 s, exactly one at +60 s, and the
  cadence repeats (+119 s none, +120 s one). All other round-1 tests
  are byte-unchanged and pass.

## Failing-then-passing evidence

The 11 round-2 test cases (10 new + the rewritten Fix-6 test) were
run against the pre-correction module extracted from the pinned
round-1 commit (`git show af731fb3…:queue/crew_queue_v2.py`, sha256
verified `082d44cf…`), with the new test file beside it:

**Result on round-1 module: FAILED — 8 failures + 3 errors (11/11
not passing). Result on round-2 module: all 50 tests pass.**

- Fix 2: cancel-during-callback FAIL (status came back "admitted");
  dispatched-reconcile ERROR (`InvalidTransition` from round-1
  reconcile_effect); pending-reconcile ERROR (same).
- Fix 3: repeat-notify-without-view FAIL (round-1 fell through and
  re-sent); restart-recovery-without-view FAIL (round-1 substituted
  the local outbox and reported "sent-on-recovery");
  local-outbox-route ERROR only at its final assertion (`KeyError:
  'delivery'` — the persisted route field is new in round 2); every
  behavioral assertion of that guard test passes on both versions.
- Fix 5: all four fencing tests FAIL (admissions/starts went
  through; no fence existed).
- Fix 6: rewritten default test FAIL (`300 != 60`).

## Out of scope, unchanged from round 1

The v1→v2 importer and Tower integration remain activation-gated on
Rivet's acceptance of the corrected module (activation plan of
record); rollback reconciliation prerequisites
(`recover_notifications`, `recover_cancellations`) exist module-side.
No push, no posting: Medic re-verifies, pins, and ships.
