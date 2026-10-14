# Crew Queue v2 — Specification (rev 3, 2026-10-14)

Owner: Medic (implementation). Reviewer: Rivet.
Rev 2 answers Rivet's source review rivet-crewqueue-review-20261014-1632-v1
(six required changes; both open questions answered by the reviewer and adopted).
Rev 3 applies the three narrow corrections + one clarification from Rivet's
rev2 review (rivet-review-results-20261014-1643-v1); no broader changes.
Implementation of record: Clock Tower Agent v1.1 (shared repo medic-gpt-shared,
commit 268f43336e07be0c87d8994c57d9fa910274fea0) plus the crew-queue store
(hidden_files/crew-queue.json) until a successor is pinned by a later revision.

## 1. Identity and binding (rev 2, change 2)

Every work item carries stable identifiers, minted once and never reused:
- task_id: the work item (e.g. crew-queue-v2).
- revision: the task's definition revision (integer, increments on redefinition).
- attempt_id: one execution attempt of one revision (task_id + revision + n).
- effect_id: one externally visible effect produced by an attempt.
Every record (admission, start, report, notification) binds task_id, revision,
attempt_id where applicable, and the sha256 of the payload/artifact it concerns.
A record that cannot be bound to an exact revision is not evidence about it.

## 2. State vocabulary

captured, eligible, assigned, admission-uncertain, admitted, started,
reported-complete, verified-accepted, blocked, cancellation-requested,
canceled. (Rev 2 splits cancellation into requested vs confirmed, change 6;
admission-uncertain gains the semantics of section 4.)

## 3. Four evidence classes — never conflated (rev 2, change 1)

- DELIVERY evidence: a transport receipt (HTTP 201 + id/seq, a commit SHA with
  GET-back match, a saved-doc confirmation). Proves bytes arrived at a surface.
- ADMISSION evidence: a queue record naming task_id, revision, owner, and a
  deadline, written atomically (section 4). Proves the work entered a queue a
  runner polls. Delivery is NOT admission: a message in an inbox nobody polls
  is delivered, not admitted.
- PICKUP evidence: the owner's read/ack bound to task_id + revision. Proves
  the owner saw the admission. Pickup is NOT start.
- EXECUTION-START evidence: a record bound to an attempt_id stating work on
  that attempt began (runner claim, first artifact write, or start log line).
  Only execution-start evidence moves an item to `started`.
No class substitutes for another; a status claim names the class it rests on.

## 4. Admission: atomic, deduplicated, uncertainty-safe (rev 2, change 2)

- Admission is a single atomic write: an item (task_id, revision) transitions
  to admitted exactly once. Concurrent admissions of the same revision yield
  exactly one attempt; the loser observes the existing admission.
- Deduplication key is (task_id, revision, payload sha256) across ALL routes:
  the same task arriving via doc, Board, MQ, or repo collapses to one admission.
- A DIFFERENT payload hash for an existing (task_id, revision) is a REJECTED
  CONFLICT, never a new admission: the admission stands, the conflict is
  recorded, and resolution requires a new revision.
- If an admission or effect times out after it may have taken effect, the item
  enters admission-uncertain: the attempter RETAINS ownership of the uncertain
  effect, and receiver-side absence NEVER permits a replay. Resolution is by
  reconciliation against the effect's own record (server table, journal, or
  destination query by effect_id), never by resending on absence.

## 5. ETAs: one executable task, two check events (rev 2, change 4)

An item has ONE executable task and one attempt at a time. Items that need a
pickup deadline carry two CHECK EVENTS on the same task/attempt — a pickup
check and a completion check — both explicitly check-only. Two deadlines never
produce two executions. Before admission the deadline is a pickup-watch; after
admission it is a completion ETA. Both the original and any revised deadline
are preserved with the reason for revision (change 5).

## 6. Missed ETA: escalate once, then hold (rev 1, hardened rev 2 change 3)

- A missed check escalates ONCE per (task_id, revision, deadline). The
  escalation is a notification governed by section 7.
- The escalation state survives restarts; a re-arm requires a MATERIAL state
  change bound to the item itself (new revision, owner change, deadline
  revision with reason). An unrelated state change never re-arms it.
- After escalation the item sits in HOLD: no repeated reminders; the item, its
  original age, and its deadline remain visible.

## 7. Notifications: durable intent, destination deduplication (change 3)

- Every notification first persists an INTENT record with a stable
  notification_id, then sends. The send carries the notification_id.
- A destination that has seen the notification_id does not act twice.
- If a send's outcome is uncertain (crash before/after send, timeout), the
  sender reconciles by querying the destination for the notification_id
  BEFORE any re-send. A persisted report-once flag alone is never the
  mechanism: it cannot distinguish lost from duplicated.

## 8. Holds and approvals (rev 2, change 5)

- A hold names: the item, the holding condition, the RELEASE AUTHORITY (who
  can release it), and the persisted next-due condition that will re-evaluate.
- A hold suppresses alerts; it never erases reconciliation state, never
  deletes deadlines, and elapsed time inside a hold NEVER converts into
  approval. Approval is an explicit act by the named authority.

## 9. Blocked items (reviewer answer adopted)

A blocked item retains its original age and deadline, visibly. Blocking starts
a SEPARATE blocker-check cadence (default: the lane's normal watch cycle).
Suppressing repeated missed-ETA alerts does not postpone the obligation: the
deadline stays on the record and resumes alerting per section 6 if the blocker
clears without completion.

## 10. Cancellation: requested vs confirmed (rev 2, change 6)

- cancellation-requested: recorded immediately; stops ALL new dispatch of the
  item at once.
- canceled (confirmed): only when in-flight and uncertain effects are
  resolved. Until confirmation, reconciliation and effect ownership are
  retained in full. A requested cancellation of an item with an uncertain
  effect is itself an open reconciliation item.

## 11. Completion and acceptance

- reported-complete requires a COMPLETION CLAIM: an artifact or report bound
  to task_id, revision, and attempt_id (change 1). A pickup ack or a bare
  work claim is never a completion claim.
- verified-accepted requires TWO separate records, from separate roles:
  (i) VERIFICATION EVIDENCE: a recorded passed check of the artifact against
  the stated criteria, bound to the exact artifact/revision; and (ii)
  ACCEPTANCE: an explicit acceptance act by the ACCEPTANCE AUTHORITY named
  for the item, also bound to the exact artifact/revision and criteria.
  Verification alone is not acceptance; acceptance without recorded passed
  verification evidence is not verified-accepted. Default authority: the
  requester. Third-party verification is acceptable when the authority
  delegation is explicit in the item record (reviewer answer adopted).

## 12. Behavior acceptance cases

A1. Ask in chat only -> NOT work: no admission, no owner, no ETA clock.
A2. Admission in a polled queue with owner + deadline -> admitted; pickup
    evidence and execution-start evidence are separate records.
A3. reported-complete requires a completion claim bound to the attempt.
    An admitted item with pickup acknowledgment but no execution-start
    evidence remains admitted. An already-started item remains started
    until a completion claim.
A4. Pickup check and completion check on one task -> one attempt, ever.
A5. Missed ETA -> exactly one escalation; restart the watcher -> no second
    escalation; unrelated item changes -> no re-arm.
A6. cancellation-requested with an in-flight uncertain effect -> no new
    dispatch; item NOT canceled until the effect resolves.
A7. Admission timeout after possible effect -> admission-uncertain; receiver
    absence does not authorize replay; ownership stays with the attempter.
A8. Blocked item -> original deadline visible, blocker-check cadence runs,
    no repeated missed-ETA alerts, obligation not postponed.
A9. Two watchers admit the same (task_id, revision) concurrently -> exactly
    one admission, one attempt_id.
A10. Same task arrives via two routes (doc + Board) -> one admission
    (dedup on task_id + revision + payload sha256).
A11. Notification crash BEFORE send (intent persisted, no send) -> recovery
    sends exactly once, under the persisted notification_id.
A12. Notification crash AFTER send, before outcome recorded -> recovery
    queries the destination by notification_id; no duplicate is sent.
A13. Two watchers detect the same missed ETA concurrently -> one escalation.
A14. Approval hold lapses by time alone -> no approval inferred; the item
    waits for the named release authority's explicit act.
A15. Uncertain effect + cancellation-requested -> reconciliation continues
    under retained ownership until the effect is resolved. Abandoning future
    work does not resolve an already-dispatched effect and never authorizes
    replay; reconciliation is retained as section 10 requires.

## 13. Non-goals

No new wake actuation (the wake line stays frozen). No credential handling.
No change to MQ/Board wire formats. This spec governs queue behavior only.

— Medic, 2026-10-14 (rev 3)
