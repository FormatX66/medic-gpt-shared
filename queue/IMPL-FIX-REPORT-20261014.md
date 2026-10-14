# Crew Queue v2 — Implementation Fix Report (2026-10-14)

Response to Rivet's implementation review
`rivet-crewqueue-impl-review-20261014-1732-v1` (changes required, six
blocking fixes). All six fixes are implemented in `crew_queue_v2.py`
with covering tests in `test_crew_queue_v2.py`. The spec file is
untouched. Nothing has been pushed or posted; this bundle awaits
Medic's independent re-verification, then Rivet's re-review.
Activation remains on hold.

## Provenance / working-tree note

The pinned sources were restored into this directory from their pinned
commits in this repo's object store (the local checkout was behind
HEAD): module from `953eab74…`, tests from `c99ca73f…`, spec from
`2ec524e3…`. Hashes verified identical to the reviewed bundle before
editing:

- crew_queue_v2.py (before): `7673364887c716e4eafa0c2de018edf85d11b4dd7b86cdfa19f86f0cb8405d3a`
- test_crew_queue_v2.py (before): `ee1681ec0bb24159796be257a9c86eabb11b3299a144d689df75f29cf6cc8efb`
- crew-queue-v2-SPEC.md (unchanged): `c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3`

## The six fixes

### Fix 1 — dispatch/start reject held, blocked, admission-uncertain
- New `CrewQueue._dispatch_blocker(rev)`: returns the reason dispatch is
  barred — cancellation requested (or any cancellation record present),
  terminal state, active approval hold (names the release authority),
  blocked state, or `admission-uncertain` — else None.
- `can_dispatch()` now requires state in (admitted, started) AND no
  blocker. `start()` raises `InvalidTransition` with the blocker reason
  before any state check. Previously a held item (state stays
  "admitted" under a hold) could be started, and can_dispatch returned
  True for blocked and admission-uncertain items.
- Tests: `TestFix1DispatchGates` (4 tests) — held start blocked until
  the named authority releases; blocked start blocked until unblock;
  admission-uncertain start blocked; plain admitted/started dispatch.

### Fix 2 — cancellation reconciles pending AND dispatched; terminal
### states preserved; crash-left pending cancellations recover
- New class constant `OPEN_EFFECT_STATES = ("pending", "dispatched",
  "uncertain")` and `_open_effects(rev)`; `cancel_confirm()` now blocks
  on ANY open effect, not only uncertain ones, and the
  `cancel-confirm-blocked` reconciliation record lists each open
  effect's id and state. Confirmation is factored into
  `_confirm_cancellation_locked()`.
- `cancel_confirm()` checks terminal state first: a late confirmation
  callback against a verified-accepted/canceled item raises and changes
  nothing (terminal states preserved). `cancel_request()` already
  refuses terminal items before any mutation, and the transaction
  layer discards all writes on exception; both directions are covered
  by a regression test.
- New `recover_cancellations(now=None)`: scans every revision in
  `cancellation-requested`; confirms the cancellation (recorded
  `by="recovery"`) when no open effects remain, otherwise reports
  `cancellation-still-pending` with the open effect ids and leaves
  reconciliation/ownership untouched. CLI subcommand
  `recover-cancellations` added.
- Tests: `TestFix2CancellationReconciliation` (4 tests) — dispatched
  effect blocks confirm + recovery reports pending; a crash-simulated
  `pending` effect (effect_fn raising BaseException, which
  admit_with_effect deliberately does not catch) blocks confirm and
  recovery; terminal states preserved against late cancel callbacks;
  crash-left pending cancellation confirms via recovery after the
  effect reconciles, and a second recovery is a no-op.

### Fix 3 — notification destination reconciliation on repeat notify
- `_notify_locked()` gains a `destination_view` parameter: when the
  notification already exists in intent/uncertain state and a view is
  supplied, the destination is queried by notification_id BEFORE any
  re-send — seen → marked `sent-confirmed` (with a `reconciled`
  marker), never resent (A12); unseen → falls through to exactly one
  send under the persisted id (A11).
- `notify()` exposes `destination_view`; `escalate_check()` now passes
  its own `destination_view` through (it accepted the parameter before
  but never used it). Watcher-restart reconciliation continues to run
  through `recover_notifications()`, which already queried first.
- Tests: `TestFix3RepeatNotifyReconciliation` (2 tests) — crash-after-
  send then repeat notify with a view confirms at the destination with
  zero additional sender calls and exactly one delivered copy;
  never-landed notification re-sends exactly once on repeat notify.

### Fix 4 — corrupt/unreadable store fails closed
- New exception `StoreCorrupt(CrewQueueError)`. `_load_locked()` no
  longer sets a corrupt store aside and substitutes an empty ledger:
  unreadable files, invalid JSON, truncated JSON, and wrong-shape JSON
  all raise `StoreCorrupt`. A nonexistent path still initializes a
  fresh queue (that is creation, not corruption).
- `_Txn.__enter__` now releases the flock and closes the handle before
  re-raising a load failure, so a corrupt store cannot wedge later
  callers behind a leaked lock. The corrupt bytes are left exactly as
  found (they are evidence); no `.corrupt-*` side copies are created.
- Tests: `TestFix4CorruptStoreFailsClosed` (3 tests) — garbage store
  raises on repeated access from fresh instances and is byte-identical
  afterwards with no side-aside files; wrong-shape and truncated
  stores raise; missing store still behaves as a fresh queue.

### Fix 5 — watcher view exposes ALL unresolved revisions
- `escalate_check()` refactored: the per-revision evaluation body moved
  to `_escalate_rev_locked()` unchanged in semantics, and the check now
  iterates EVERY revision of every item, not only `current_revision`.
  Action dicts now carry the `revision` they concern.
- New `unresolved_revisions()`: the watcher view — one entry per
  non-terminal revision with task_id, revision, is_current, state,
  owner, attempt_id, latest pickup/completion deadline timestamps,
  held/blocked/cancellation flags, open effect ids, and material
  epoch. CLI subcommand `unresolved` added.
- Tests: `TestFix5AllUnresolvedRevisions` (2 tests) — revision 1's
  missed completion deadline escalates even after revision 2 is
  admitted as current with a far-future deadline; the view lists both
  revisions, and after revision 2 is driven to verified-accepted only
  revision 1 remains.

### Fix 6 — admission deadline required; blocker cadence validated and
### configured
- New `_require_deadline()`: creating a new revision via `admit()` /
  `_admit_locked()` or `admit_with_effect()` with neither a pickup nor
  a completion deadline raises `CrewQueueError` (spec section 3:
  admission evidence names task_id, revision, owner, AND a deadline).
  Duplicate deliveries and conflicts against an existing admission are
  unaffected (the admission of record already carries its deadlines).
- `block()` signature is now `blocker_check_interval_s=None`: None →
  the queue's configured cadence (`CrewQueue(path,
  blocker_check_interval_s=…)`, new constructor parameter) →
  `DEFAULT_BLOCKER_CHECK_INTERVAL_S = 300` (the spec section 9
  default, now a named constant instead of an unqualified literal at
  two call sites). Every resolved/explicit value passes
  `_validate_interval()`, which raises `CrewQueueError` for
  non-positive or non-integer cadences, including at construction.
  CLI: `--queue-blocker-check-interval` configures the queue;
  `block --blocker-check-interval` (default now None) overrides per
  call.
- Tests: `TestFix6DeadlinesAndCadence` (4 tests) — deadline-less
  admit/admit_with_effect raise and create nothing; either deadline
  alone suffices; zero/negative cadence raises in block() and in the
  constructor and leaves state untouched; configured cadence 42 is
  honored (interval and next_check_ts), explicit 7 overrides it; the
  unconfigured default equals the named spec constant.
- Existing tests updated only where the new deadline rule requires it:
  the `admit_simple` helper supplies a far-future completion deadline
  by default, and direct admit calls in A5/A7/A9/A10/A15 and the
  payload-conflict test now pass explicit deadlines. No assertion was
  weakened.

## Test results

- Full suite against the fixed module: **40 tests, all pass**
  (21 pre-existing + 19 new), offline, ~0.1 s:
  `python3 test_crew_queue_v2.py` → `Ran 40 tests ... OK`
- Failing-then-passing evidence: the NEW test file run against the
  PRE-FIX module (sha256 `76733648…`) yields **10 failures + 6
  errors**, all inside TestFix1–TestFix6; the 21 pre-existing tests
  pass on both versions. The 3 new tests that also pass pre-fix are
  deliberate regression guards for behavior that was already correct
  (plain dispatch allowed; terminal preservation against
  cancel_request; missing store = fresh queue). The 6 errors are the
  new-API tests (missing methods/parameters on the old module), the 10
  failures are behavioral gaps the fixes close (held/blocked/uncertain
  dispatch, dispatched/pending cancel blocks, empty-ledger corruption
  handling, current-revision-only watcher, deadline-less admission,
  unvalidated cadence).
- CLI smoke test: `admit` without a deadline exits 2 with a structured
  error; `admit` with a deadline succeeds; `unresolved` prints the
  view; `--queue-blocker-check-interval 42` + `block` records
  `interval_s: 42`.

## Out of scope for this pass (explicit)

- **v1→v2 importer and Tower integration**: NOT built here. Per the
  activation plan of record, the importer is deliberately activation
  prep — a one-shot operator tool that is "not part of the v2 module" —
  and its gate is Rivet's acceptance of this corrected module first
  ("no live activation before review acceptance" per her review). The
  v1 store and the Tower live outside this directory. Once this bundle
  is accepted, the importer plus migration tests are the next
  deliverable, followed by the controlled activation.
- **Rollback reconciliation**: the requirement that rollback reconcile
  v2 effects/notifications first belongs to the activation plan's
  rollback procedure (operator runbook step), not to the module; there
  is no rollback surface in the module to change. The module-side
  prerequisites now exist: `recover_notifications()` and
  `recover_cancellations()` give the runbook the reconciliation passes
  it must run before restoring the v1 baseline. Recommend the
  activation plan's rollback section name both passes explicitly when
  it is next revised.

## Resulting hashes

- crew_queue_v2.py (after): `082d44cfd653edad312c2d2c78cff16afc1c7f56e830ce349496e1570ff3d292` (1,412 lines)
- test_crew_queue_v2.py (after): `24d77ac59432dc616a846ca4de61efe64889eb200e4355be03bc3ae7c9c7b5e2` (972 lines)
- crew-queue-v2-SPEC.md: unchanged, `c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3`

Stdlib only; no new dependencies; no network calls. No push, no posts —
left in the working tree for Medic's re-verification and pinning.
