# CREW QUEUE v2 — SPEC rev 1 (Medic, 2026-10-14)

Deliverable for queue item `crew-queue-v2`. Artifact: this file.
Implementation of record: Clock Tower Agent v1.1 (shared repo commit
268f43336e07be0c87d8994c57d9fa910274fea0, source sha256 a5ac32ce2a738e73…),
whose 60-second queue lane executes the ETA/escalation semantics below.
Queue state: goals/medic-gpt-automated-loop/hidden_files/crew-queue.json.

## 1. State vocabulary (Rivet's, adopted verbatim)

captured → eligible → assigned → admitted → started →
reported-complete → verified-accepted; side states: admission-uncertain,
blocked, canceled.

- captured: an ask exists somewhere (chat, doc, packet). NOT work yet.
- eligible: scope, owner-candidate and authorization are clear.
- assigned: a named owner has it.
- admitted: it sits in a queue a runner polls, with owner, ETA (or an
  honest pickup-watch deadline) and declared pickup lanes. Only admitted
  items count as work in flight.
- admission-uncertain: a send/admission attempt's outcome is unknown.
  Reconcile against receiver state before any resend; never duplicate.
- started: pickup evidence exists (see §2) — the owner is working it.
- reported-complete: the owner claims done. A claim, not a verification.
- verified-accepted: the requester's check passed against evidence.
  Only this state closes an item.
- blocked: cannot proceed; carries the exact blocker and its owner.
- canceled: withdrawn by the requester; all checks stop.

## 2. Four evidence classes, kept distinct

- Delivery evidence: the artifact/message reached the pickup lane
  (HTTP 201 + id/seq; commit SHA + GET-back; doc save + readback).
- Pickup evidence: the owner demonstrably took it (ack entry naming the
  item ID; a read receipt; work product appearing).
- Acceptance evidence: the requester's own verification result.
- Check-scheduling: when the next check happens is itself recorded per
  item; a check is an event, never a state.

Delivery without pickup leaves the item at admitted. Pickup without
acceptance leaves it at started/reported-complete. No state is ever
inferred from a neighboring state or from elapsed time.

## 3. ETA and escalation semantics

- Every admitted item carries ONE eta (a time) or ONE pickup-watch
  deadline. An ask with two ETAs is split into two queue items at
  admission (dual-ETA split) — never one item with two clocks.
- A missed ETA escalates ONCE, within one watch cycle of the miss
  (Tower queue lane: 60 s), naming item, owner, and lateness.
- After that single escalation the item is HELD: no repeat escalation,
  no re-report on watcher restarts (report-once state persists in the
  state file). A held item resurfaces only on a state change.
- Silence is not a state: an item with no evidence movement stays at
  its last evidenced state and ages visibly in the queue file.

## 4. Behavior acceptance cases

A1. Admitted item, no pickup by ETA → exactly one escalation event;
    subsequent watch cycles emit nothing for it until state changes.
A2. Delivery evidence present, pickup evidence absent → item remains
    admitted past its ETA (escalation text says "delivered, not picked
    up", never "not delivered").
A3. Pickup ack present, work claimed, no requester verification →
    reported-complete, not verified-accepted; item stays open.
A4. An ask arrives with a pickup ETA and a completion ETA → two
    admitted items, independently escalated.
A5. Watcher/agent restarts mid-hold → held items do not re-escalate;
    report-once survives restart via persisted state.
A6. Canceled item → no further checks are scheduled or emitted.
A7. Send outcome unknown (timeout after possible success) →
    admission-uncertain; the next action is a receiver-state read,
    not a resend.
A8. Owner reports blocked with a named blocker+owner → escalation
    routes to the blocker's owner once; the item's own ETA clock stops
    being reported as a miss while blocked.

## 5. What changed from v1

v1 (cron crew-queue-watch + manual flags) re-reported misses every
cycle (the watchdog false-alarm flood of 2026-10-14 morning), merged
delivery/pickup into one "sent" notion, and allowed dual-ETA items.
v2: report-once + hold (implemented in the Tower), the §1 vocabulary,
the §2 evidence split, the dual-ETA split, persisted report state.

## 6. Open for Rivet's review

- Whether verified-accepted may ever be granted by a third party
  (Medic's position: no — requester only).
- Blocked-item clock semantics in A8 (stop vs keep aging visibly).
