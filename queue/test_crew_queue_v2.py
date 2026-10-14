#!/usr/bin/env python3
"""Acceptance tests for crew_queue_v2.py against crew-queue-v2-SPEC.md
rev 3 (sha256 c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3).

One or more tests per spec acceptance case A1-A15, plus binding/conflict
tests for section 1 and section 11. Concurrency cases (A9, A13) are
simulated deterministically with barrier-synchronized threads over two
store instances on the same path — the store's flock-serialized
read-modify-write is what makes the outcome deterministic. Crash cases
(A11, A12) use injected sender/hook fakes. Fully offline; runs in seconds.

Fix pass 2026-10-14 (Rivet review rivet-crewqueue-impl-review-20261014
-1732-v1): TestFix1..TestFix6 cover the six blocking fixes. They are
written against the post-fix API; run against the pre-fix module they
fail (missing methods raise AttributeError, missing validation lets the
operation through), which is the failing-then-passing evidence for the
review.

Round-2 fix pass 2026-10-14 (Rivet re-review
rivet-crew-rereview-verdict-20261014-2002-v1; round-1 fixes 1 and 4
accepted as addressed): TestFix2Round2LateCallbacks (cancel-during-
callback preservation; pending/dispatched-to-resolved cancellation
recovery), TestFix3Round2FailClosedNoView (repeat notify without a
view; restart recovery through the ordinary watcher path without a
view; the local-outbox route as the valid exception),
TestFix5Round2CrossRevisionFencing (no second execution/effect until
earlier ownership is safely resolved), and the rewritten
test_unconfigured_default_is_the_spec_default, which now asserts the
60-second target-lane cadence behaviorally instead of comparing the
module constant to itself. Run against the round-1 module
(af731fb3...), the round-2 tests fail; see
IMPL-FIX-REPORT-20261014-ROUND2.md.

Round-3 fix pass 2026-10-14 (Rivet verdict
rivet-crew-round2-verdict-20261014-2022-v1; round-2 fixes 1, 3, 4, 6
and the rest of 2/5 accepted as addressed): TestRound3Residuals
covers the two residual races — (1) fencing retained through the
cancellation interval (open effects or an unconfirmed cancellation
on another revision) for the admission-effect path and for the start
gate of an already-admitted later revision; (2) a late admission
callback, clean or failed, preserving an authoritative resolution
and a confirmed cancellation that landed while it was outstanding.
Run against the round-2 module (e36d46be...), the round-3 tests
fail; see IMPL-FIX-REPORT-20261014-ROUND3.md.

Run: python3 test_crew_queue_v2.py
"""

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crew_queue_v2 import (  # noqa: E402
    AuthorityError, CrewQueue, CrewQueueError, InvalidTransition,
    MissingVerification, PayloadConflict, ReplayForbidden, StaleRevision,
    payload_sha256,
)

try:
    from crew_queue_v2 import StoreCorrupt  # noqa: E402
except ImportError:  # pre-fix module: no fail-closed store error exists
    StoreCorrupt = CrewQueueError

try:
    from crew_queue_v2 import OwnershipFenced  # noqa: E402
except ImportError:  # pre-round-2 module: no fencing error exists
    OwnershipFenced = CrewQueueError

T0 = 1_800_000_000  # fixed base time for determinism


class FakeDestination:
    """A section 7 destination: dedups by notification_id."""

    def __init__(self):
        self.seen = set()
        self.received = []
        self.lock = threading.Lock()

    def deliver(self, notification_id, payload):
        with self.lock:
            if notification_id in self.seen:
                return "duplicate-ignored"
            self.seen.add(notification_id)
            self.received.append((notification_id, payload))
            return "delivered"

    def has_seen(self, notification_id):
        return notification_id in self.seen


class QueueTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "queue.json")
        self.q = CrewQueue(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def admit_simple(self, task="task-a", revision=1, payload=None, **kw):
        kw.setdefault("route", "doc")
        kw.setdefault("owner", "medic")
        # Fix 6: admission requires at least one deadline; the helper
        # supplies a far-future completion deadline unless a test sets
        # its own deadline(s).
        kw.setdefault("completion_deadline_ts", T0 + 100_000)
        return self.q.admit(task, revision,
                            {"spec": "x"} if payload is None else payload,
                            **kw)

    def rev(self, task="task-a", revision=None):
        return self.q.get_rev(task, revision)

    def kinds(self, task="task-a", revision=None):
        return [r["kind"] for r in self.rev(task, revision)["records"]]


class TestA1DeliveryIsNotWork(QueueTestBase):
    def test_chat_delivery_creates_no_work(self):
        # A1: an ask/delivery in a lane is NOT work — no item, no owner,
        # no admission, no ETA clock, nothing for escalate_check to fire on.
        self.q.record_delivery("chat-ask-1", 1, {"ask": "please do x"},
                               receipt="msg-id-123", route="chat", now=T0)
        self.assertIsNone(self.q.get_item("chat-ask-1"))
        self.assertEqual(len(self.q.deliveries()), 1)
        sends = []

        def sender(nid, dest, payload):
            sends.append(nid)
            return "ok"

        actions = self.q.escalate_check(now=T0 + 10_000_000, sender=sender)
        self.assertEqual(actions, [])
        self.assertEqual(sends, [])


class TestA2EvidenceClasses(QueueTestBase):
    def test_admission_pickup_start_are_separate_records(self):
        res = self.admit_simple(completion_deadline_ts=T0 + 500)
        attempt = res["attempt_id"]
        rev = self.rev()
        self.assertEqual(rev["state"], "admitted")
        adm = [r for r in rev["records"] if r["kind"] == "admission"]
        self.assertEqual(len(adm), 1)
        self.assertEqual(adm[0]["owner"], "medic")
        self.assertEqual(adm[0]["attempt_id"], attempt)
        self.assertEqual(rev["deadlines"]["completion"][-1]["ts"], T0 + 500)
        # Pickup: separate record, state unchanged (pickup is not start).
        self.q.pickup("task-a", by="medic", now=T0 + 10)
        self.assertEqual(self.rev()["state"], "admitted")
        self.assertEqual(self.kinds(), ["admission", "pickup"])
        # Start: execution-start record bound to the attempt moves state.
        self.q.start("task-a", by="medic", evidence="runner-claim-1",
                     now=T0 + 20)
        rev = self.rev()
        self.assertEqual(rev["state"], "started")
        start_rec = [r for r in rev["records"]
                     if r["kind"] == "execution-start"][0]
        self.assertEqual(start_rec["attempt_id"], attempt)
        # Every record is bound to task + revision + payload hash.
        for rec in rev["records"]:
            self.assertEqual(rec["task_id"], "task-a")
            self.assertEqual(rec["revision"], 1)
            self.assertIn("payload_sha256", rec)


class TestA3CompletionClaim(QueueTestBase):
    def test_pickup_alone_is_not_completion(self):
        res = self.admit_simple()
        self.q.pickup("task-a", now=T0 + 1)
        # Admitted + pickup ack but no execution-start: remains ADMITTED,
        # and a completion claim is rejected (A3, rev 3 wording).
        self.assertEqual(self.rev()["state"], "admitted")
        with self.assertRaises(InvalidTransition):
            self.q.complete_claim("task-a", attempt_id=res["attempt_id"],
                                  artifact={"done": True}, now=T0 + 2)
        self.assertEqual(self.rev()["state"], "admitted")

    def test_started_item_stays_started_until_claim(self):
        res = self.admit_simple()
        self.q.start("task-a", now=T0 + 1)
        self.assertEqual(self.rev()["state"], "started")
        # A claim bound to the WRONG attempt is not a completion claim.
        with self.assertRaises(InvalidTransition):
            self.q.complete_claim("task-a", attempt_id="task-a/r1/a99",
                                  artifact="x", now=T0 + 2)
        self.assertEqual(self.rev()["state"], "started")
        claim = self.q.complete_claim("task-a", attempt_id=res["attempt_id"],
                                      artifact={"result": 42}, now=T0 + 3)
        self.assertEqual(self.rev()["state"], "reported-complete")
        self.assertEqual(claim["artifact_sha256"],
                         payload_sha256({"result": 42}))
        self.assertEqual(claim["attempt_id"], res["attempt_id"])


class TestA4TwoChecksOneExecution(QueueTestBase):
    def test_two_deadlines_one_attempt(self):
        res = self.admit_simple(pickup_deadline_ts=T0 + 100,
                                completion_deadline_ts=T0 + 200)
        sent = []

        def sender(nid, dest, payload):
            sent.append((nid, payload))
            return "ok"

        actions = self.q.escalate_check(now=T0 + 300, sender=sender)
        escalations = [a for a in actions if a["action"] == "escalated"]
        self.assertEqual(len(escalations), 2)  # pickup + completion checks
        rev = self.rev()
        # Checks are check-only: still exactly ONE attempt, never started.
        self.assertEqual(len(rev["attempts"]), 1)
        self.assertEqual(rev["attempts"][0]["attempt_id"], res["attempt_id"])
        self.assertEqual(rev["state"], "admitted")


class TestA5EscalateOnceAndRearm(QueueTestBase):
    def test_escalate_once_restart_no_rearm_then_material_rearm(self):
        self.admit_simple(completion_deadline_ts=T0 + 100)
        sends = []

        def sender(nid, dest, payload):
            sends.append(nid)
            return "ok"

        self.q.escalate_check(now=T0 + 200, sender=sender)
        self.assertEqual(len(sends), 1)
        # Restart the watcher (fresh instance over the same file): the
        # escalation state survived; no second escalation.
        q2 = CrewQueue(self.path)
        q2.escalate_check(now=T0 + 300, sender=sender)
        self.assertEqual(len(sends), 1)
        # Unrelated change (another task admitted) does NOT re-arm.
        q2.admit("other-task", 1, {"z": 1}, route="doc", owner="rivet",
                 now=T0 + 300, completion_deadline_ts=T0 + 100_000)
        q2.escalate_check(now=T0 + 400, sender=sender)
        self.assertEqual(len(sends), 1)
        # Material change: deadline revision WITH reason re-arms for the
        # NEW deadline only.
        q2.revise_deadline("task-a", kind="completion", new_ts=T0 + 500,
                           reason="owner extended", now=T0 + 400)
        q2.escalate_check(now=T0 + 450, sender=sender)
        self.assertEqual(len(sends), 1)  # new deadline not yet missed
        q2.escalate_check(now=T0 + 600, sender=sender)
        self.assertEqual(len(sends), 2)
        # Original deadline preserved alongside the revised one.
        entries = q2.get_rev("task-a")["deadlines"]["completion"]
        self.assertEqual([e["ts"] for e in entries], [T0 + 100, T0 + 500])
        self.assertTrue(entries[0]["original"])
        self.assertEqual(entries[1]["reason"], "owner extended")


class TestA6CancelWithUncertainEffect(QueueTestBase):
    def test_cancel_requested_stops_dispatch_and_blocks_confirm(self):
        self.admit_simple()
        self.q.start("task-a", now=T0 + 1)
        self.q.register_effect("task-a", effect_id="eff-1", owner="medic",
                               uncertain=True, now=T0 + 2)
        self.q.cancel_request("task-a", by="bruce", now=T0 + 3)
        rev = self.rev()
        self.assertEqual(rev["state"], "cancellation-requested")
        self.assertFalse(self.q.can_dispatch("task-a"))
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-a", by="bruce", now=T0 + 4)
        # NOT canceled; reconciliation + ownership retained.
        rev = self.rev()
        self.assertEqual(rev["state"], "cancellation-requested")
        eff = rev["effects"][0]
        self.assertEqual(eff["state"], "uncertain")
        self.assertEqual(eff["owner"], "medic")


class TestA7AdmissionUncertain(QueueTestBase):
    def test_timeout_after_effect_keeps_ownership_no_replay(self):
        def boom(effect_id):
            raise TimeoutError("effect may have landed")

        res = self.q.admit_with_effect(
            "task-u", 1, {"job": "send"}, route="mq", owner="medic",
            attempter="medic", effect_fn=boom, effect_id="eff-u", now=T0,
            completion_deadline_ts=T0 + 5000)
        self.assertEqual(res["status"], "admission-uncertain")
        rev = self.q.get_rev("task-u")
        self.assertEqual(rev["state"], "admission-uncertain")
        self.assertEqual(rev["effects"][0]["owner"], "medic")
        # Receiver absence never permits replay...
        with self.assertRaises(ReplayForbidden):
            self.q.replay_effect("task-u", "eff-u")
        # ...and an absence observation resolves nothing.
        self.q.reconcile_effect("task-u", "eff-u", found=False,
                                detail="receiver inbox empty", now=T0 + 10)
        rev = self.q.get_rev("task-u")
        self.assertEqual(rev["state"], "admission-uncertain")
        self.assertEqual(rev["effects"][0]["state"], "uncertain")
        with self.assertRaises(ReplayForbidden):
            self.q.replay_effect("task-u", "eff-u")
        # Reconciliation against the effect's own record resolves it.
        self.q.reconcile_effect("task-u", "eff-u", found=True,
                                detail="server table row present",
                                now=T0 + 20)
        rev = self.q.get_rev("task-u")
        self.assertEqual(rev["state"], "admitted")
        self.assertEqual(rev["effects"][0]["state"], "resolved")

    def test_clean_effect_finalizes_admission(self):
        res = self.q.admit_with_effect(
            "task-ok", 1, {"job": "noop"}, route="doc", owner="medic",
            attempter="medic", effect_fn=lambda eid: None,
            effect_id="eff-ok", now=T0,
            completion_deadline_ts=T0 + 5000)
        self.assertEqual(res["status"], "admitted")
        self.assertEqual(self.q.get_rev("task-ok")["state"], "admitted")


class TestA8Blocked(QueueTestBase):
    def test_blocked_keeps_deadline_and_obligation(self):
        self.admit_simple(completion_deadline_ts=T0 + 100)
        self.q.block("task-a", reason="waiting on dependency", now=T0 + 10,
                     blocker_check_interval_s=50)
        sends = []

        def sender(nid, dest, payload):
            sends.append(nid)
            return "ok"

        # Past the deadline while blocked: NO missed-ETA escalation, but
        # blocker-check events run on their own cadence.
        actions = self.q.escalate_check(now=T0 + 220, sender=sender)
        self.assertEqual(sends, [])
        checks = [a for a in actions if a["action"] == "blocker-check"]
        self.assertGreaterEqual(len(checks), 1)
        rev = self.rev()
        self.assertEqual(rev["state"], "blocked")
        # Original deadline still on the record, unchanged.
        self.assertEqual(rev["deadlines"]["completion"][-1]["ts"], T0 + 100)
        # Unblock: the obligation was not postponed — escalation fires.
        self.q.unblock("task-a", now=T0 + 230)
        self.assertEqual(self.rev()["state"], "admitted")
        self.q.escalate_check(now=T0 + 240, sender=sender)
        self.assertEqual(len(sends), 1)


class TestA9ConcurrentAdmission(QueueTestBase):
    def test_two_watchers_exactly_one_admission(self):
        barrier = threading.Barrier(2)
        results, errors = {}, {}

        def worker(name, queue):
            try:
                barrier.wait(timeout=10)
                results[name] = queue.admit(
                    "task-c", 1, {"shared": "payload"}, route="doc",
                    owner="medic", now=T0,
                    completion_deadline_ts=T0 + 1000)
            except Exception as exc:  # noqa: BLE001
                errors[name] = exc

        t1 = threading.Thread(target=worker,
                              args=("w1", CrewQueue(self.path)))
        t2 = threading.Thread(target=worker,
                              args=("w2", CrewQueue(self.path)))
        t1.start(); t2.start(); t1.join(20); t2.join(20)
        self.assertEqual(errors, {})
        statuses = sorted(r["status"] for r in results.values())
        self.assertEqual(statuses, ["admitted", "existing"])
        # Exactly one admission record, one attempt_id, shared by both.
        rev = self.rev("task-c")
        admissions = [r for r in rev["records"] if r["kind"] == "admission"]
        self.assertEqual(len(admissions), 1)
        self.assertEqual(len(rev["attempts"]), 1)
        self.assertEqual(results["w1"]["attempt_id"],
                         results["w2"]["attempt_id"])


class TestA10CrossRouteDedup(QueueTestBase):
    def test_doc_and_board_collapse_to_one_admission(self):
        payload = {"contract": "same-bytes"}
        r1 = self.q.admit("task-x", 1, payload, route="doc", owner="rivet",
                          now=T0, completion_deadline_ts=T0 + 1000)
        r2 = self.q.admit("task-x", 1, payload, route="Board",
                          owner="rivet", now=T0 + 5,
                          completion_deadline_ts=T0 + 1000)
        self.assertEqual(r1["status"], "admitted")
        self.assertEqual(r2["status"], "existing")
        self.assertEqual(r1["attempt_id"], r2["attempt_id"])
        rev = self.rev("task-x")
        self.assertEqual(len(rev["attempts"]), 1)
        admissions = [r for r in rev["records"] if r["kind"] == "admission"]
        self.assertEqual(len(admissions), 1)
        dups = [r for r in rev["records"]
                if r["kind"] == "duplicate-delivery"]
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["route"], "Board")


class TestPayloadConflict(QueueTestBase):
    def test_differing_hash_is_rejected_conflict(self):
        self.q.admit("task-k", 1, {"v": 1}, route="doc", owner="medic",
                     now=T0, completion_deadline_ts=T0 + 1000)
        with self.assertRaises(PayloadConflict):
            self.q.admit("task-k", 1, {"v": 2}, route="Board",
                         owner="medic", now=T0 + 1,
                         completion_deadline_ts=T0 + 1000)
        rev = self.rev("task-k")
        # Admission stands; conflict recorded; no second attempt.
        self.assertEqual(rev["state"], "admitted")
        self.assertEqual(len(rev["attempts"]), 1)
        self.assertEqual(len(rev["conflicts"]), 1)
        self.assertIn("conflict-rejected", self.kinds("task-k"))
        # Resolution requires a NEW revision.
        res = self.q.admit("task-k", 2, {"v": 2}, route="doc", owner="medic",
                           now=T0 + 2, completion_deadline_ts=T0 + 2000)
        self.assertEqual(res["status"], "admitted")
        self.assertEqual(self.q.get_item("task-k")["current_revision"], 2)
        with self.assertRaises(StaleRevision):
            self.q.admit("task-k", 1, {"v": 1}, route="doc", owner="medic",
                         now=T0 + 3, completion_deadline_ts=T0 + 1000)


class CrashAfterIntent:
    def __init__(self):
        self.calls = 0

    def after_intent(self, record):
        self.calls += 1
        raise RuntimeError("simulated crash after intent persisted")


class TestA11CrashBeforeSend(QueueTestBase):
    def test_recovery_sends_exactly_once_with_persisted_id(self):
        dest = FakeDestination()
        sent = []

        def sender(nid, destination, payload):
            sent.append(nid)
            return dest.deliver(nid, payload)

        hooks = CrashAfterIntent()
        with self.assertRaises(RuntimeError):
            self.q.notify("owner:medic", {"msg": "eta missed"},
                          sender=sender, hooks=hooks, kind="eta-escalation",
                          task_id="t", revision=1, deadline_kind="pickup",
                          deadline_ts=T0, material_epoch=0, now=T0)
        self.assertEqual(hooks.calls, 1)
        self.assertEqual(sent, [])          # send never happened
        self.assertEqual(dest.received, [])  # destination saw nothing
        # Recovery (a fresh store instance, as after a restart): the
        # destination is queried, found unseen, and the notification is
        # sent exactly once under the persisted notification_id.
        q2 = CrewQueue(self.path)
        actions = q2.recover_notifications(sender=sender,
                                           destination_view=dest)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "sent-on-recovery")
        self.assertEqual(len(dest.received), 1)
        self.assertEqual(dest.received[0][0], sent[0])
        # A second recovery is a no-op: no duplicate.
        actions = q2.recover_notifications(sender=sender,
                                           destination_view=dest)
        self.assertEqual(actions, [])
        self.assertEqual(len(dest.received), 1)


class TestA12CrashAfterSend(QueueTestBase):
    def test_recovery_queries_destination_and_never_duplicates(self):
        dest = FakeDestination()
        calls = []

        def crashing_sender(nid, destination, payload):
            calls.append(nid)
            dest.deliver(nid, payload)      # the send lands...
            raise ConnectionError("crash before outcome recorded")

        notif = self.q.notify("owner:medic", {"msg": "eta missed"},
                              sender=crashing_sender, kind="eta-escalation",
                              task_id="t", revision=1,
                              deadline_kind="completion", deadline_ts=T0,
                              material_epoch=0, now=T0)
        self.assertEqual(notif["state"], "uncertain")
        self.assertEqual(len(dest.received), 1)
        # Recovery: destination HAS seen the id -> confirmed, NO resend.
        def good_sender(nid, destination, payload):
            calls.append("RESEND")
            return dest.deliver(nid, payload)

        actions = self.q.recover_notifications(
            sender=good_sender, destination_view=dest)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "confirmed-at-destination")
        self.assertFalse(actions[0]["resent"])
        self.assertNotIn("RESEND", calls)
        self.assertEqual(len(dest.received), 1)  # still exactly one copy


class TestA13ConcurrentEscalation(QueueTestBase):
    def test_two_watchers_one_escalation(self):
        self.admit_simple(completion_deadline_ts=T0 + 100)
        dest = FakeDestination()
        send_count = []
        lock = threading.Lock()

        def sender(nid, destination, payload):
            with lock:
                send_count.append(nid)
            return dest.deliver(nid, payload)

        barrier = threading.Barrier(2)
        errors = {}

        def watcher(name, queue):
            try:
                barrier.wait(timeout=10)
                queue.escalate_check(now=T0 + 200, sender=sender)
            except Exception as exc:  # noqa: BLE001
                errors[name] = exc

        t1 = threading.Thread(target=watcher,
                              args=("w1", CrewQueue(self.path)))
        t2 = threading.Thread(target=watcher,
                              args=("w2", CrewQueue(self.path)))
        t1.start(); t2.start(); t1.join(20); t2.join(20)
        self.assertEqual(errors, {})
        self.assertEqual(len(send_count), 1)
        self.assertEqual(len(dest.received), 1)
        rev = self.rev()
        self.assertEqual(len(rev["escalations"]), 1)


class TestA14ApprovalHold(QueueTestBase):
    def test_time_alone_never_releases_or_approves(self):
        self.admit_simple(completion_deadline_ts=T0 + 100)
        self.q.hold("task-a", condition="awaiting rivet approval",
                    release_authority="rivet",
                    next_due="rivet reviews rev 3 artifacts", now=T0 + 10)
        sends = []

        def sender(nid, dest, payload):
            sends.append(nid)
            return "ok"

        # Far past the deadline, still held: no escalation, no approval,
        # no state drift of any kind.
        self.q.escalate_check(now=T0 + 10_000_000, sender=sender)
        rev = self.rev()
        self.assertEqual(sends, [])
        self.assertIsNotNone(rev["hold"])
        self.assertEqual(rev["state"], "admitted")
        self.assertIsNone(rev["acceptance"])
        # Only the named authority can release.
        with self.assertRaises(AuthorityError):
            self.q.release("task-a", by="medic", now=T0 + 10_000_001)
        self.q.release("task-a", by="rivet", now=T0 + 10_000_002)
        self.assertIsNone(self.rev()["hold"])


class TestA15UncertainEffectPlusCancel(QueueTestBase):
    def test_reconciliation_retained_until_effect_resolves(self):
        self.q.admit_with_effect(
            "task-z", 1, {"job": "x"}, route="mq", owner="medic",
            attempter="medic",
            effect_fn=lambda eid: (_ for _ in ()).throw(
                TimeoutError("maybe landed")),
            effect_id="eff-z", now=T0,
            completion_deadline_ts=T0 + 5000)
        self.q.cancel_request("task-z", by="bruce", now=T0 + 1)
        # Confirm is blocked while the effect is uncertain...
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-z", by="bruce", now=T0 + 2)
        # ...absence does not resolve it, and replay stays forbidden.
        self.q.reconcile_effect("task-z", "eff-z", found=False, now=T0 + 3)
        with self.assertRaises(ReplayForbidden):
            self.q.replay_effect("task-z", "eff-z")
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-z", by="bruce", now=T0 + 4)
        rev = self.q.get_rev("task-z")
        self.assertEqual(rev["state"], "cancellation-requested")
        self.assertEqual(rev["effects"][0]["owner"], "medic")
        # Only resolving the effect lets the cancellation complete.
        self.q.reconcile_effect("task-z", "eff-z", found=True,
                                detail="journal shows effect landed",
                                now=T0 + 5)
        self.q.cancel_confirm("task-z", by="bruce", now=T0 + 6)
        self.assertEqual(self.q.get_rev("task-z")["state"], "canceled")


class TestSection11VerifyAccept(QueueTestBase):
    def _complete(self):
        res = self.admit_simple(requester="bruce")
        self.q.start("task-a", now=T0 + 1)
        art = {"report": "done"}
        self.q.complete_claim("task-a", attempt_id=res["attempt_id"],
                              artifact=art, now=T0 + 2)
        return payload_sha256(art)

    def test_acceptance_requires_passed_verification_first(self):
        sha = self._complete()
        with self.assertRaises(MissingVerification):
            self.q.accept("task-a", artifact_sha256=sha, criteria="spec-4",
                          by="bruce", now=T0 + 3)
        self.assertEqual(self.rev()["state"], "reported-complete")

    def test_verification_binds_exact_artifact(self):
        self._complete()
        with self.assertRaises(InvalidTransition):
            self.q.verify("task-a", artifact_sha256="0" * 64,
                          criteria="spec-4", verifier="rivet", now=T0 + 3)

    def test_two_separate_records_then_verified_accepted(self):
        sha = self._complete()
        # A FAILED verification cannot support acceptance.
        self.q.verify("task-a", artifact_sha256=sha, criteria="spec-4",
                      verifier="rivet", passed=False, now=T0 + 3)
        with self.assertRaises(MissingVerification):
            self.q.accept("task-a", artifact_sha256=sha, criteria="spec-4",
                          by="bruce", now=T0 + 4)
        # Passed verification by the verifier role...
        self.q.verify("task-a", artifact_sha256=sha, criteria="spec-4",
                      verifier="rivet", passed=True, now=T0 + 5)
        # ...does not itself accept (separate roles, separate records):
        self.assertEqual(self.rev()["state"], "reported-complete")
        with self.assertRaises(AuthorityError):
            self.q.accept("task-a", artifact_sha256=sha, criteria="spec-4",
                          by="rivet", now=T0 + 6)
        self.q.accept("task-a", artifact_sha256=sha, criteria="spec-4",
                      by="bruce", now=T0 + 7)
        rev = self.rev()
        self.assertEqual(rev["state"], "verified-accepted")
        self.assertEqual(rev["verification"]["role"], "verifier")
        self.assertEqual(rev["acceptance"]["role"],
                         "acceptance-authority")
        self.assertIn("verification", self.kinds())
        self.assertIn("acceptance", self.kinds())


class TestFix1DispatchGates(QueueTestBase):
    """Fix 1 (review 1732): dispatch/start reject held, blocked, and
    admission-uncertain items — A14 hold semantics at the gate."""

    def test_held_item_cannot_start_until_released(self):
        self.admit_simple()
        self.q.hold("task-a", condition="awaiting rivet approval",
                    release_authority="rivet", next_due="rivet reviews",
                    now=T0 + 1)
        self.assertFalse(self.q.can_dispatch("task-a"))
        with self.assertRaises(InvalidTransition):
            self.q.start("task-a", now=T0 + 2)
        self.assertEqual(self.rev()["state"], "admitted")
        self.q.release("task-a", by="rivet", now=T0 + 3)
        self.assertTrue(self.q.can_dispatch("task-a"))
        self.q.start("task-a", now=T0 + 4)
        self.assertEqual(self.rev()["state"], "started")

    def test_blocked_item_cannot_start(self):
        self.admit_simple()
        self.q.block("task-a", reason="dependency down", now=T0 + 1,
                     blocker_check_interval_s=60)
        self.assertFalse(self.q.can_dispatch("task-a"))
        with self.assertRaises(InvalidTransition):
            self.q.start("task-a", now=T0 + 2)
        self.q.unblock("task-a", now=T0 + 3)
        self.assertTrue(self.q.can_dispatch("task-a"))

    def test_admission_uncertain_item_cannot_start(self):
        def boom(effect_id):
            raise TimeoutError("maybe landed")

        self.q.admit_with_effect(
            "task-u", 1, {"job": "send"}, route="mq", owner="medic",
            attempter="medic", effect_fn=boom, effect_id="eff-u", now=T0,
            completion_deadline_ts=T0 + 5000)
        self.assertFalse(self.q.can_dispatch("task-u"))
        with self.assertRaises(InvalidTransition):
            self.q.start("task-u", now=T0 + 1)
        self.assertEqual(self.q.get_rev("task-u")["state"],
                         "admission-uncertain")

    def test_plain_admitted_and_started_can_dispatch(self):
        self.admit_simple()
        self.assertTrue(self.q.can_dispatch("task-a"))
        self.q.start("task-a", now=T0 + 1)
        self.assertTrue(self.q.can_dispatch("task-a"))


class TestFix2CancellationReconciliation(QueueTestBase):
    """Fix 2 (review 1732): cancellation reconciles pending AND
    dispatched effects, terminal states survive late callbacks, and
    crash-left pending cancellations recover."""

    def test_dispatched_effect_blocks_confirm(self):
        self.admit_simple()
        self.q.start("task-a", now=T0 + 1)
        self.q.register_effect("task-a", effect_id="eff-d", owner="medic",
                               now=T0 + 2)  # state: dispatched (in-flight)
        self.q.cancel_request("task-a", by="bruce", now=T0 + 3)
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-a", by="bruce", now=T0 + 4)
        rev = self.rev()
        self.assertEqual(rev["state"], "cancellation-requested")
        self.assertEqual(rev["effects"][0]["state"], "dispatched")
        # Recovery sees it too: still pending, never force-confirmed.
        actions = self.q.recover_cancellations(now=T0 + 5)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "cancellation-still-pending")
        self.assertEqual(actions[0]["open_effects"], ["eff-d"])
        self.assertEqual(self.rev()["state"], "cancellation-requested")

    def test_pending_effect_blocks_confirm_and_recovery(self):
        def crash(effect_id):
            raise KeyboardInterrupt("process died mid-effect")

        # BaseException is not caught by admit_with_effect: the intent
        # (and its pending effect) is exactly what a crash leaves behind.
        with self.assertRaises(KeyboardInterrupt):
            self.q.admit_with_effect(
                "task-p", 1, {"job": "x"}, route="mq", owner="medic",
                attempter="medic", effect_fn=crash, effect_id="eff-p",
                now=T0, completion_deadline_ts=T0 + 5000)
        rev = self.q.get_rev("task-p")
        self.assertEqual(rev["effects"][0]["state"], "pending")
        self.q.cancel_request("task-p", by="bruce", now=T0 + 1)
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-p", by="bruce", now=T0 + 2)
        actions = self.q.recover_cancellations(now=T0 + 3)
        self.assertEqual(actions[0]["action"], "cancellation-still-pending")
        self.assertEqual(actions[0]["open_effects"], ["eff-p"])
        self.assertEqual(self.q.get_rev("task-p")["state"],
                         "cancellation-requested")

    def test_terminal_states_preserved_against_late_callbacks(self):
        # Drive one item to verified-accepted.
        res = self.admit_simple(requester="bruce")
        self.q.start("task-a", now=T0 + 1)
        art = {"report": "done"}
        self.q.complete_claim("task-a", attempt_id=res["attempt_id"],
                              artifact=art, now=T0 + 2)
        sha = payload_sha256(art)
        self.q.verify("task-a", artifact_sha256=sha, criteria="spec-4",
                      verifier="rivet", passed=True, now=T0 + 3)
        self.q.accept("task-a", artifact_sha256=sha, criteria="spec-4",
                      by="bruce", now=T0 + 4)
        self.assertEqual(self.rev()["state"], "verified-accepted")
        # Late cancellation callbacks change nothing.
        with self.assertRaises(InvalidTransition):
            self.q.cancel_request("task-a", by="bruce", now=T0 + 5)
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-a", by="bruce", now=T0 + 6)
        self.assertEqual(self.rev()["state"], "verified-accepted")
        self.assertIsNone(self.rev()["cancellation"])
        # Same for a canceled item: late callbacks preserve "canceled".
        self.admit_simple(task="task-c2")
        self.q.cancel_request("task-c2", by="bruce", now=T0 + 1)
        self.q.cancel_confirm("task-c2", by="bruce", now=T0 + 2)
        self.assertEqual(self.rev("task-c2")["state"], "canceled")
        with self.assertRaises(InvalidTransition):
            self.q.cancel_request("task-c2", by="bruce", now=T0 + 3)
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-c2", by="bruce", now=T0 + 4)
        self.assertEqual(self.rev("task-c2")["state"], "canceled")

    def test_crash_left_pending_cancellation_recovers(self):
        def boom(effect_id):
            raise TimeoutError("maybe landed")

        self.q.admit_with_effect(
            "task-r", 1, {"job": "x"}, route="mq", owner="medic",
            attempter="medic", effect_fn=boom, effect_id="eff-r", now=T0,
            completion_deadline_ts=T0 + 5000)
        self.q.cancel_request("task-r", by="bruce", now=T0 + 1)
        # Watcher restarts (fresh instance); before the effect resolves,
        # recovery leaves the cancellation pending.
        q2 = CrewQueue(self.path)
        actions = q2.recover_cancellations(now=T0 + 2)
        self.assertEqual(actions[0]["action"], "cancellation-still-pending")
        self.assertEqual(q2.get_rev("task-r")["state"],
                         "cancellation-requested")
        # The effect resolves by reconciliation; recovery then confirms.
        q2.reconcile_effect("task-r", "eff-r", found=True,
                            detail="journal shows effect landed",
                            now=T0 + 3)
        actions = q2.recover_cancellations(now=T0 + 4)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "cancellation-confirmed")
        rev = q2.get_rev("task-r")
        self.assertEqual(rev["state"], "canceled")
        self.assertIsNotNone(rev["cancellation"]["confirmed_ts"])
        # A second recovery is a no-op.
        self.assertEqual(q2.recover_cancellations(now=T0 + 5), [])


class TestFix3RepeatNotifyReconciliation(QueueTestBase):
    """Fix 3 (review 1732): a repeat notify reconciles against the
    destination before any re-send, not only in crash recovery."""

    KW = dict(kind="eta-escalation", task_id="t", revision=1,
              deadline_kind="completion", deadline_ts=T0, material_epoch=0)

    def test_repeat_notify_confirms_at_destination_no_resend(self):
        dest = FakeDestination()

        def crashing_sender(nid, destination, payload):
            dest.deliver(nid, payload)      # the send lands...
            raise ConnectionError("crash before outcome recorded")

        notif = self.q.notify("owner:medic", {"msg": "x"},
                              sender=crashing_sender, now=T0, **self.KW)
        self.assertEqual(notif["state"], "uncertain")
        self.assertEqual(len(dest.received), 1)
        # Repeat notify (e.g. the watcher re-fires after a restart):
        # the destination is queried FIRST; seen -> confirmed, and the
        # sender is never invoked again.
        calls = []

        def good_sender(nid, destination, payload):
            calls.append(nid)
            return dest.deliver(nid, payload)

        notif = self.q.notify("owner:medic", {"msg": "x"},
                              sender=good_sender, now=T0 + 10,
                              destination_view=dest, **self.KW)
        self.assertEqual(notif["state"], "sent-confirmed")
        self.assertEqual(calls, [])
        self.assertEqual(len(dest.received), 1)

    def test_repeat_notify_unseen_destination_sends_exactly_once(self):
        def failing_sender(nid, destination, payload):
            raise ConnectionError("never landed")

        notif = self.q.notify("owner:medic", {"msg": "x"},
                              sender=failing_sender, now=T0, **self.KW)
        self.assertEqual(notif["state"], "uncertain")
        dest = FakeDestination()

        def good_sender(nid, destination, payload):
            return dest.deliver(nid, payload)

        # Destination has NOT seen the id: one send under the persisted
        # notification_id, no more.
        notif = self.q.notify("owner:medic", {"msg": "x"},
                              sender=good_sender, now=T0 + 10,
                              destination_view=dest, **self.KW)
        self.assertEqual(notif["state"], "sent")
        self.assertEqual(len(dest.received), 1)
        notif = self.q.notify("owner:medic", {"msg": "x"},
                              sender=good_sender, now=T0 + 20,
                              destination_view=dest, **self.KW)
        self.assertEqual(notif["state"], "sent")
        self.assertEqual(len(dest.received), 1)


class TestFix4CorruptStoreFailsClosed(QueueTestBase):
    """Fix 4 (review 1732): a corrupt/unreadable store fails closed.
    It is never silently replaced with an empty ledger."""

    def _corrupt(self, content):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_garbage_store_raises_and_is_left_untouched(self):
        self.admit_simple()
        self._corrupt("this is not json {{{")
        with self.assertRaises(StoreCorrupt):
            self.q.get_item("task-a")
        with self.assertRaises(StoreCorrupt):
            CrewQueue(self.path).get_item("task-a")
        # The corrupt bytes are evidence: left exactly as found, no
        # side-aside copy, no empty ledger written over them.
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "this is not json {{{")
        siblings = [n for n in os.listdir(self.tmp.name)
                    if "corrupt" in n]
        self.assertEqual(siblings, [])

    def test_wrong_shape_and_truncated_store_raise(self):
        self._corrupt('{"hello": 1}')
        with self.assertRaises(StoreCorrupt):
            self.q.deliveries()
        self._corrupt('{"version": 2, "items": {')
        with self.assertRaises(StoreCorrupt):
            self.q.escalate_check(now=T0)

    def test_missing_store_is_still_a_fresh_queue(self):
        # Fail-closed applies to EXISTING-but-unreadable stores; a path
        # that does not exist yet is a legitimately empty queue.
        self.assertIsNone(self.q.get_item("nothing-here"))
        res = self.admit_simple()
        self.assertEqual(res["status"], "admitted")


class TestFix5AllUnresolvedRevisions(QueueTestBase):
    """Fix 5 (review 1732): the watcher view covers ALL unresolved
    revisions, not only current_revision."""

    def test_older_revision_still_escalates(self):
        self.q.admit("task-m", 1, {"v": 1}, route="doc", owner="medic",
                     now=T0, completion_deadline_ts=T0 + 100)
        self.q.admit("task-m", 2, {"v": 2}, route="doc", owner="medic",
                     now=T0 + 10, completion_deadline_ts=T0 + 100_000)
        sent = []

        def sender(nid, dest, payload):
            sent.append(payload)
            return "ok"

        actions = self.q.escalate_check(now=T0 + 200, sender=sender)
        escalated = [a for a in actions if a["action"] == "escalated"]
        # Revision 1's missed deadline escalates even though revision 2
        # is the current revision and its deadline is far away.
        self.assertEqual(len(escalated), 1)
        self.assertEqual(escalated[0]["revision"], 1)
        self.assertEqual(sent[0]["revision"], 1)
        self.assertEqual(self.q.get_rev("task-m", 1)["escalations"][0]
                         ["key"][1], 1)

    def test_unresolved_revisions_view(self):
        self.q.admit("task-m", 1, {"v": 1}, route="doc", owner="medic",
                     now=T0, completion_deadline_ts=T0 + 100)
        res2 = self.q.admit("task-m", 2, {"v": 2}, route="doc",
                            owner="medic", requester="bruce", now=T0 + 10,
                            completion_deadline_ts=T0 + 100_000)
        view = self.q.unresolved_revisions()
        mine = [v for v in view if v["task_id"] == "task-m"]
        self.assertEqual([v["revision"] for v in mine], [1, 2])
        self.assertFalse(mine[0]["is_current"])
        self.assertTrue(mine[1]["is_current"])
        self.assertEqual(mine[0]["completion_deadline_ts"], T0 + 100)
        # Resolve revision 2 completely; it leaves the view, while the
        # still-open revision 1 remains visible to the watcher.
        self.q.start("task-m", revision=2, now=T0 + 20)
        art = {"done": 2}
        self.q.complete_claim("task-m", revision=2,
                              attempt_id=res2["attempt_id"], artifact=art,
                              now=T0 + 21)
        sha = payload_sha256(art)
        self.q.verify("task-m", revision=2, artifact_sha256=sha,
                      criteria="c", verifier="rivet", passed=True,
                      now=T0 + 22)
        self.q.accept("task-m", revision=2, artifact_sha256=sha,
                      criteria="c", by="bruce", now=T0 + 23)
        mine = [v for v in self.q.unresolved_revisions()
                if v["task_id"] == "task-m"]
        self.assertEqual([v["revision"] for v in mine], [1])


class TestFix6DeadlinesAndCadence(QueueTestBase):
    """Fix 6 (review 1732): admission requires at least one deadline;
    blocker cadence is validated positive and honors configuration."""

    def test_admission_requires_a_deadline(self):
        with self.assertRaises(CrewQueueError):
            self.q.admit("task-n", 1, {"v": 1}, route="doc", owner="medic",
                         now=T0)
        self.assertIsNone(self.q.get_item("task-n"))
        with self.assertRaises(CrewQueueError):
            self.q.admit_with_effect(
                "task-n2", 1, {"v": 1}, route="mq", owner="medic",
                attempter="medic", effect_fn=lambda eid: None, now=T0)
        self.assertIsNone(self.q.get_item("task-n2"))
        # Either deadline alone satisfies the requirement.
        res = self.q.admit("task-n3", 1, {"v": 1}, route="doc",
                           owner="medic", now=T0, pickup_deadline_ts=T0 + 5)
        self.assertEqual(res["status"], "admitted")

    def test_blocker_cadence_validated_positive(self):
        self.admit_simple()
        with self.assertRaises(CrewQueueError):
            self.q.block("task-a", reason="x", now=T0 + 1,
                         blocker_check_interval_s=0)
        with self.assertRaises(CrewQueueError):
            self.q.block("task-a", reason="x", now=T0 + 1,
                         blocker_check_interval_s=-50)
        with self.assertRaises(CrewQueueError):
            CrewQueue(self.path, blocker_check_interval_s=0)
        # The failed blocks changed nothing.
        self.assertEqual(self.rev()["state"], "admitted")

    def test_configured_cadence_is_honored(self):
        path2 = os.path.join(self.tmp.name, "queue2.json")
        q2 = CrewQueue(path2, blocker_check_interval_s=42)
        q2.admit("task-cfg", 1, {"v": 1}, route="doc", owner="medic",
                 now=T0, completion_deadline_ts=T0 + 1000)
        q2.block("task-cfg", reason="waiting", now=T0 + 10)
        blk = q2.get_rev("task-cfg")["blocked"]
        self.assertEqual(blk["interval_s"], 42)
        self.assertEqual(blk["next_check_ts"], T0 + 10 + 42)
        # An explicit per-call interval still wins over configuration.
        q2.unblock("task-cfg", now=T0 + 11)
        q2.block("task-cfg", reason="waiting again", now=T0 + 12,
                 blocker_check_interval_s=7)
        self.assertEqual(q2.get_rev("task-cfg")["blocked"]["interval_s"], 7)

    def test_unconfigured_default_is_the_spec_default(self):
        # Round-2 fix 6: the target requirement is the queue lane's
        # 60-second cadence, asserted BEHAVIORALLY — an unconfigured
        # queue blocks at a 60 s cadence and the blocker-check fires
        # when 60 s have elapsed, not before. (The round-1 version of
        # this test compared the module constant to itself, which
        # could not catch a wrong default.)
        self.admit_simple()
        self.q.block("task-a", reason="waiting", now=T0 + 1)
        blk = self.rev()["blocked"]
        self.assertEqual(blk["interval_s"], 60)
        self.assertEqual(blk["next_check_ts"], T0 + 1 + 60)

        def blocker_checks(actions):
            return [a for a in actions if a["action"] == "blocker-check"]

        self.assertEqual(blocker_checks(
            self.q.escalate_check(now=T0 + 1 + 59)), [])
        self.assertEqual(len(blocker_checks(
            self.q.escalate_check(now=T0 + 1 + 60))), 1)
        # The cadence repeats at the same 60 s interval.
        self.assertEqual(blocker_checks(
            self.q.escalate_check(now=T0 + 1 + 119)), [])
        self.assertEqual(len(blocker_checks(
            self.q.escalate_check(now=T0 + 1 + 120))), 1)


class TestFix2Round2LateCallbacks(QueueTestBase):
    """Round-2 fix 2 (re-review 2002): cancellation/recovery
    visibility is preserved across late admission callbacks, and
    authoritative reconciliation covers ALL unresolved effect states
    (pending and dispatched, not only uncertain)."""

    def test_cancel_during_effect_callback_is_preserved(self):
        q = self.q

        def effect_that_cancels_mid_flight(effect_id):
            # The cancellation request lands while the admission
            # effect is in flight: the callback runs outside the
            # store lock, so this is the ordinary interleaving.
            q.cancel_request("task-cc", by="bruce", now=T0 + 1)
            return None  # the effect itself then returns cleanly

        res = self.q.admit_with_effect(
            "task-cc", 1, {"job": "send"}, route="mq", owner="medic",
            attempter="medic", effect_fn=effect_that_cancels_mid_flight,
            effect_id="eff-cc", now=T0,
            completion_deadline_ts=T0 + 5000)
        # The clean callback must NOT overwrite cancellation-requested
        # with admitted (the round-1 bug: the record existed but the
        # clobbered state hid it from recovery).
        self.assertEqual(res["status"], "cancellation-requested")
        rev = self.q.get_rev("task-cc")
        self.assertEqual(rev["state"], "cancellation-requested")
        self.assertIsNotNone(rev["cancellation"])
        self.assertIsNone(rev["cancellation"]["confirmed_ts"])
        # The effect evidence was still finalized as dispatched, and
        # the cancellation waits on it.
        self.assertEqual(rev["effects"][0]["state"], "dispatched")
        self.assertFalse(self.q.can_dispatch("task-cc"))
        # Recovery SEES the pending cancellation and reports it.
        actions = self.q.recover_cancellations(now=T0 + 2)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"],
                         "cancellation-still-pending")
        self.assertEqual(actions[0]["open_effects"], ["eff-cc"])
        # Reconcile the dispatched effect; recovery then confirms the
        # cancellation under the retained request.
        self.q.reconcile_effect("task-cc", "eff-cc", found=True,
                                detail="destination journal has it",
                                now=T0 + 3)
        actions = self.q.recover_cancellations(now=T0 + 4)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "cancellation-confirmed")
        rev = self.q.get_rev("task-cc")
        self.assertEqual(rev["state"], "canceled")
        self.assertIsNotNone(rev["cancellation"]["confirmed_ts"])

    def test_dispatched_effect_reconciles_for_cancellation(self):
        self.admit_simple()
        self.q.start("task-a", now=T0 + 1)
        self.q.register_effect("task-a", effect_id="eff-dr",
                               owner="medic",
                               now=T0 + 2)  # dispatched (in-flight)
        self.q.cancel_request("task-a", by="bruce", now=T0 + 3)
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-a", by="bruce", now=T0 + 4)
        # An absence observation resolves nothing (found=False).
        self.q.reconcile_effect("task-a", "eff-dr", found=False,
                                detail="not in journal yet", now=T0 + 5)
        self.assertEqual(self.rev()["effects"][0]["state"], "dispatched")
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-a", by="bruce", now=T0 + 6)
        # Authoritative reconciliation of a DISPATCHED effect (round-1
        # code rejected every non-uncertain effect here, deadlocking
        # the cancellation).
        eff = self.q.reconcile_effect("task-a", "eff-dr", found=True,
                                      detail="destination ack located",
                                      now=T0 + 7)
        self.assertEqual(eff["state"], "resolved")
        self.q.cancel_confirm("task-a", by="bruce", now=T0 + 8)
        self.assertEqual(self.rev()["state"], "canceled")
        # Reconciling an already-resolved effect is rejected.
        with self.assertRaises(InvalidTransition):
            self.q.reconcile_effect("task-a", "eff-dr", found=True,
                                    now=T0 + 9)

    def test_pending_effect_reconciles_for_cancellation(self):
        def crash(effect_id):
            raise KeyboardInterrupt("process died mid-effect")

        # The crash leaves the admission effect PENDING (intent
        # persisted, outcome never recorded).
        with self.assertRaises(KeyboardInterrupt):
            self.q.admit_with_effect(
                "task-pc", 1, {"job": "x"}, route="mq", owner="medic",
                attempter="medic", effect_fn=crash, effect_id="eff-pc",
                now=T0, completion_deadline_ts=T0 + 5000)
        self.assertEqual(
            self.q.get_rev("task-pc")["effects"][0]["state"], "pending")
        self.q.cancel_request("task-pc", by="bruce", now=T0 + 1)
        with self.assertRaises(InvalidTransition):
            self.q.cancel_confirm("task-pc", by="bruce", now=T0 + 2)
        actions = self.q.recover_cancellations(now=T0 + 3)
        self.assertEqual(actions[0]["action"],
                         "cancellation-still-pending")
        self.assertEqual(actions[0]["open_effects"], ["eff-pc"])
        # The PENDING effect is authoritatively reconcilable too.
        self.q.reconcile_effect("task-pc", "eff-pc", found=True,
                                detail="server table row present",
                                now=T0 + 4)
        actions = self.q.recover_cancellations(now=T0 + 5)
        self.assertEqual(actions[0]["action"], "cancellation-confirmed")
        self.assertEqual(self.q.get_rev("task-pc")["state"], "canceled")


class TestFix3Round2FailClosedNoView(QueueTestBase):
    """Round-2 fix 3 (re-review 2002): an unresolved EXTERNAL
    notification fails closed without the matching destination query —
    on repeat notify and on restart recovery alike. The local outbox
    view remains valid only for actual local-outbox delivery."""

    KW = dict(kind="eta-escalation", task_id="t", revision=1,
              deadline_kind="completion", deadline_ts=T0,
              material_epoch=0)

    def _store(self):
        import json
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def _uncertain_external(self):
        def crashing_sender(nid, destination, payload):
            raise ConnectionError("outcome unknown")

        notif = self.q.notify("owner:medic", {"msg": "x"},
                              sender=crashing_sender, now=T0, **self.KW)
        self.assertEqual(notif["state"], "uncertain")
        return notif["notification_id"]

    def test_repeat_notify_without_view_fails_closed(self):
        nid = self._uncertain_external()
        calls = []

        def good_sender(nid_, destination, payload):
            calls.append(nid_)
            return "ok"

        # No destination_view supplied: the repeat notify must NOT
        # re-send on hope (round-1 code fell through and re-sent).
        with self.assertRaises(CrewQueueError):
            self.q.notify("owner:medic", {"msg": "x"},
                          sender=good_sender, now=T0 + 10, **self.KW)
        self.assertEqual(calls, [])
        # The record is untouched: still unresolved, awaiting its
        # destination query.
        self.assertEqual(
            self._store()["notifications"][nid]["state"], "uncertain")
        # And WITH the matching view the same repeat notify proceeds
        # exactly as before (seen -> confirmed, no resend).
        dest = FakeDestination()
        dest.deliver(nid, {"msg": "x"})
        notif = self.q.notify("owner:medic", {"msg": "x"},
                              sender=good_sender, now=T0 + 20,
                              destination_view=dest, **self.KW)
        self.assertEqual(notif["state"], "sent-confirmed")
        self.assertEqual(calls, [])

    def test_restart_recovery_without_view_fails_closed(self):
        nid = self._uncertain_external()
        # The ordinary watcher restart path: a fresh instance runs
        # recovery with neither a destination view nor an external
        # sender. Round-1 code substituted the local outbox view and
        # re-sent into the wrong destination.
        q2 = CrewQueue(self.path)
        actions = q2.recover_notifications(now=T0 + 10)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["notification_id"], nid)
        self.assertEqual(actions[0]["action"],
                         "fail-closed-no-destination-view")
        self.assertFalse(actions[0]["resent"])
        # Nothing was sent anywhere; the record is unchanged.
        store = self._store()
        self.assertEqual(store["notifications"][nid]["state"],
                         "uncertain")
        self.assertEqual(store["outbox"], {})
        # Recovery WITH the matching view proceeds normally.
        dest = FakeDestination()

        def sender(nid_, destination, payload):
            return dest.deliver(nid_, payload)

        actions = q2.recover_notifications(sender=sender,
                                           destination_view=dest,
                                           now=T0 + 20)
        self.assertEqual(actions[0]["action"], "sent-on-recovery")
        self.assertEqual(len(dest.received), 1)

    def test_local_outbox_route_needs_no_external_view(self):
        # A notification actually delivered via the store's own
        # outbox is the valid exception: the local view IS its
        # destination view, so recovery without a supplied view still
        # works. (Regression guard: this also passes on round-1 code.)
        hooks = CrashAfterIntent()
        with self.assertRaises(RuntimeError):
            self.q.notify("owner:medic", {"msg": "local"}, hooks=hooks,
                          now=T0, **self.KW)
        # Intent persisted; the send never ran. Restart + recovery
        # with no view sends exactly once into the local outbox.
        q2 = CrewQueue(self.path)
        actions = q2.recover_notifications(now=T0 + 10)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "sent-on-recovery")
        self.assertTrue(actions[0]["resent"])
        store = self._store()
        nid = actions[0]["notification_id"]
        self.assertIn(nid, store["outbox"])
        self.assertEqual(store["notifications"][nid]["state"], "sent")
        self.assertEqual(store["notifications"][nid]["delivery"],
                         "local-outbox")


class TestFix5Round2CrossRevisionFencing(QueueTestBase):
    """Round-2 fix 5 (re-review 2002): cross-revision ownership
    fencing — no second execution or effect while an earlier
    revision's ownership is started or uncertain."""

    def _resolve_rev1_terminally(self, task="task-a"):
        rev = self.q.get_rev(task, 1)
        art = {"done": 1}
        self.q.complete_claim(task, revision=1,
                              attempt_id=rev["current_attempt_id"],
                              artifact=art, now=T0 + 30)
        sha = payload_sha256(art)
        self.q.verify(task, revision=1, artifact_sha256=sha,
                      criteria="c", verifier="rivet", passed=True,
                      now=T0 + 31)
        self.q.accept(task, revision=1, artifact_sha256=sha,
                      criteria="c", by="medic", now=T0 + 32)

    def test_started_revision_fences_new_admission_and_effect(self):
        self.admit_simple()
        self.q.start("task-a", now=T0 + 1)
        with self.assertRaises(OwnershipFenced):
            self.q.admit("task-a", 2, {"v": 2}, route="doc",
                         owner="medic", now=T0 + 2,
                         completion_deadline_ts=T0 + 9000)
        with self.assertRaises(OwnershipFenced):
            self.q.admit_with_effect(
                "task-a", 2, {"v": 2}, route="mq", owner="medic",
                attempter="medic", effect_fn=lambda eid: None,
                now=T0 + 2, completion_deadline_ts=T0 + 9000)
        # Revision 2 was never created; revision 1 still owns it.
        item = self.q.get_item("task-a")
        self.assertEqual(item["current_revision"], 1)
        self.assertNotIn("2", item["revisions"])
        # Safely resolve revision 1 to a terminal state: the fence
        # lifts, and revision 2 may be admitted and started.
        self._resolve_rev1_terminally()
        res2 = self.q.admit("task-a", 2, {"v": 2}, route="doc",
                            owner="medic", now=T0 + 40,
                            completion_deadline_ts=T0 + 9000)
        self.assertEqual(res2["status"], "admitted")
        self.q.start("task-a", revision=2, now=T0 + 41)
        self.assertEqual(self.q.get_rev("task-a", 2)["state"], "started")

    def test_uncertain_revision_fences_until_safely_resolved(self):
        def boom(effect_id):
            raise TimeoutError("maybe landed")

        self.q.admit_with_effect(
            "task-f", 1, {"v": 1}, route="mq", owner="medic",
            attempter="medic", effect_fn=boom, effect_id="eff-f",
            now=T0, completion_deadline_ts=T0 + 9000)
        self.assertEqual(self.q.get_rev("task-f")["state"],
                         "admission-uncertain")
        with self.assertRaises(OwnershipFenced):
            self.q.admit("task-f", 2, {"v": 2}, route="doc",
                         owner="medic", now=T0 + 1,
                         completion_deadline_ts=T0 + 9000)
        self.assertNotIn("2", self.q.get_item("task-f")["revisions"])
        # Resolve the uncertainty, then cancel revision 1 to its
        # terminal state: ownership is safely resolved, fence lifts.
        self.q.reconcile_effect("task-f", "eff-f", found=True, now=T0 + 2)
        self.assertEqual(self.q.get_rev("task-f")["state"], "admitted")
        self.q.cancel_request("task-f", by="bruce", now=T0 + 3)
        self.q.cancel_confirm("task-f", by="bruce", now=T0 + 4)
        self.assertEqual(self.q.get_rev("task-f")["state"], "canceled")
        res = self.q.admit("task-f", 2, {"v": 2}, route="doc",
                           owner="medic", now=T0 + 5,
                           completion_deadline_ts=T0 + 9000)
        self.assertEqual(res["status"], "admitted")

    def test_start_gate_fences_second_execution(self):
        # Both revisions admitted while neither owns execution: fine.
        self.admit_simple()
        self.q.admit("task-a", 2, {"v": 2}, route="doc", owner="medic",
                     now=T0 + 1, completion_deadline_ts=T0 + 9000)
        self.q.start("task-a", revision=1, now=T0 + 2)
        # A second execution while revision 1 is started: fenced at
        # the start gate and at can_dispatch.
        self.assertFalse(self.q.can_dispatch("task-a", revision=2))
        with self.assertRaises(OwnershipFenced):
            self.q.start("task-a", revision=2, now=T0 + 3)
        self.assertEqual(self.q.get_rev("task-a", 2)["state"],
                         "admitted")
        # Resolve revision 1 terminally; revision 2 may now start.
        self._resolve_rev1_terminally()
        self.assertTrue(self.q.can_dispatch("task-a", revision=2))
        self.q.start("task-a", revision=2, now=T0 + 40)
        self.assertEqual(self.q.get_rev("task-a", 2)["state"], "started")

    def test_blocked_from_started_still_fences(self):
        self.admit_simple()
        self.q.start("task-a", now=T0 + 1)
        self.q.block("task-a", reason="dependency down", now=T0 + 2,
                     blocker_check_interval_s=60)
        self.assertEqual(self.rev()["state"], "blocked")
        # Started work that is merely paused still owns the task.
        with self.assertRaises(OwnershipFenced):
            self.q.admit("task-a", 2, {"v": 2}, route="doc",
                         owner="medic", now=T0 + 3,
                         completion_deadline_ts=T0 + 9000)
        self.q.unblock("task-a", now=T0 + 4)
        self.assertEqual(self.rev()["state"], "started")
        with self.assertRaises(OwnershipFenced):
            self.q.admit("task-a", 2, {"v": 2}, route="doc",
                         owner="medic", now=T0 + 5,
                         completion_deadline_ts=T0 + 9000)


class TestRound3Residuals(QueueTestBase):
    """Round-3 (Rivet verdict rivet-crew-round2-verdict-20261014-2022
    -v1): the two residual races left after round 2. Residual 1: the
    round-2 fence keyed off revision STATE, but cancel_request moves
    a revision to cancellation-requested without resolving its
    effects — fencing must persist through that interval while open
    effects or an unconfirmed cancellation remain. Residual 2: an
    admission callback still outstanding while its effect is
    authoritatively resolved and the cancellation confirmed must not
    reopen the ledger when it finally completes — in either branch,
    including the returned status."""

    # ---- residual 1: fencing through the cancellation interval

    def test_cancellation_interval_fences_second_effect(self):
        q = self.q

        def timeout(effect_id):
            raise TimeoutError("admission effect timed out")

        # Revision 1's admission effect times out: uncertain
        # ownership, effect unresolved.
        res = q.admit_with_effect(
            "task-r3a", 1, {"v": 1}, route="mq", owner="medic",
            attempter="medic", effect_fn=timeout, effect_id="eff-r3a",
            now=T0, completion_deadline_ts=T0 + 9000)
        self.assertEqual(res["status"], "admission-uncertain")
        self.assertEqual(q.get_rev("task-r3a", 1)["effects"][0]["state"],
                         "uncertain")
        # The cancellation lands WITHOUT resolving the effect. The
        # state string leaves the round-2 fence's vocabulary — the
        # interval this regression exists for.
        q.cancel_request("task-r3a", revision=1, by="bruce", now=T0 + 1)
        rev1 = q.get_rev("task-r3a", 1)
        self.assertEqual(rev1["state"], "cancellation-requested")
        self.assertEqual(rev1["effects"][0]["state"], "uncertain")
        self.assertIsNone(rev1["cancellation"]["confirmed_ts"])
        # Revision 2's admission effect must NEVER run.
        invoked = []

        def second(effect_id):
            invoked.append(effect_id)

        with self.assertRaises(OwnershipFenced):
            q.admit_with_effect(
                "task-r3a", 2, {"v": 2}, route="mq", owner="medic",
                attempter="medic", effect_fn=second,
                effect_id="eff-r3a-2", now=T0 + 2,
                completion_deadline_ts=T0 + 9000)
        self.assertEqual(invoked, [])
        self.assertNotIn("2", q.get_item("task-r3a")["revisions"])
        # Plain admission of revision 2 is fenced in the interval too.
        with self.assertRaises(OwnershipFenced):
            q.admit("task-r3a", 2, {"v": 2}, route="doc", owner="medic",
                    now=T0 + 2, completion_deadline_ts=T0 + 9000)
        # Resolve the effect and confirm the cancellation: ownership
        # is safely resolved and the fence lifts.
        q.reconcile_effect("task-r3a", "eff-r3a", found=True, now=T0 + 3)
        q.cancel_confirm("task-r3a", revision=1, by="bruce", now=T0 + 4)
        self.assertEqual(q.get_rev("task-r3a", 1)["state"], "canceled")
        res2 = q.admit("task-r3a", 2, {"v": 2}, route="doc",
                       owner="medic", now=T0 + 5,
                       completion_deadline_ts=T0 + 9000)
        self.assertEqual(res2["status"], "admitted")

    def test_cancellation_interval_fences_start_of_admitted_revision(self):
        q = self.q
        # Both revisions admitted while neither owns execution.
        q.admit("task-r3b", 1, {"v": 1}, route="doc", owner="medic",
                now=T0, completion_deadline_ts=T0 + 9000)
        q.admit("task-r3b", 2, {"v": 2}, route="doc", owner="medic",
                now=T0 + 1, completion_deadline_ts=T0 + 9000)
        # Revision 1 takes an externally visible effect (uncertain
        # ownership recorded against it) and is then cancelled — the
        # request lands without resolving the effect.
        q.register_effect("task-r3b", revision=1, effect_id="eff-r3b",
                          owner="medic", uncertain=True, now=T0 + 2)
        q.cancel_request("task-r3b", revision=1, by="bruce", now=T0 + 3)
        rev1 = q.get_rev("task-r3b", 1)
        self.assertEqual(rev1["state"], "cancellation-requested")
        self.assertEqual(rev1["effects"][0]["state"], "uncertain")
        # The already-admitted later revision may not start: fenced
        # at can_dispatch and at the start gate.
        self.assertFalse(q.can_dispatch("task-r3b", revision=2))
        with self.assertRaises(OwnershipFenced):
            q.start("task-r3b", revision=2, now=T0 + 4)
        self.assertEqual(q.get_rev("task-r3b", 2)["state"], "admitted")
        # Resolve revision 1 terminally; revision 2 may now start.
        q.reconcile_effect("task-r3b", "eff-r3b", found=True, revision=1,
                           now=T0 + 5)
        q.cancel_confirm("task-r3b", revision=1, by="bruce", now=T0 + 6)
        self.assertEqual(q.get_rev("task-r3b", 1)["state"], "canceled")
        self.assertTrue(q.can_dispatch("task-r3b", revision=2))
        q.start("task-r3b", revision=2, now=T0 + 7)
        self.assertEqual(q.get_rev("task-r3b", 2)["state"], "started")

    # ---- residual 2: late callback preserves authoritative state

    def _resolve_and_confirm(self, q, task, effect_id, observed):
        """Inside the outstanding admission callback: request the
        cancellation, resolve the pending effect against destination
        evidence, then confirm the cancellation — all BEFORE the
        callback completes. The state of record at that instant is
        captured in `observed`."""
        q.cancel_request(task, by="bruce", now=T0 + 1)
        q.reconcile_effect(task, effect_id, found=True,
                           detail="destination journal has it",
                           now=T0 + 2)
        q.cancel_confirm(task, by="bruce", now=T0 + 3)
        rev = q.get_rev(task)
        observed["state"] = rev["state"]
        observed["effect_state"] = rev["effects"][0]["state"]

    def test_late_success_callback_preserves_resolution(self):
        q = self.q
        observed = {}

        def effect_fn(effect_id):
            self._resolve_and_confirm(q, "task-r3c", effect_id, observed)
            return None  # the callback then returns cleanly, late

        res = q.admit_with_effect(
            "task-r3c", 1, {"job": "send"}, route="mq", owner="medic",
            attempter="medic", effect_fn=effect_fn, effect_id="eff-r3c",
            now=T0, completion_deadline_ts=T0 + 9000)
        # The authoritative sequence really did complete first.
        self.assertEqual(observed, {"state": "canceled",
                                    "effect_state": "resolved"})
        # The late clean callback reopened nothing: effect stays
        # resolved, item stays canceled, returned status is the
        # terminal state of record.
        self.assertEqual(res["status"], "canceled")
        rev = q.get_rev("task-r3c")
        self.assertEqual(rev["state"], "canceled")
        self.assertEqual(rev["effects"][0]["state"], "resolved")
        self.assertIsNotNone(rev["cancellation"]["confirmed_ts"])
        # Recovery has nothing to reopen either.
        self.assertEqual(q.recover_cancellations(now=T0 + 9), [])
        self.assertEqual(q.get_rev("task-r3c")["effects"][0]["state"],
                         "resolved")

    def test_late_exception_callback_preserves_resolution(self):
        q = self.q
        observed = {}

        def effect_fn(effect_id):
            self._resolve_and_confirm(q, "task-r3d", effect_id, observed)
            raise TimeoutError("callback reports failure, late")

        res = q.admit_with_effect(
            "task-r3d", 1, {"job": "send"}, route="mq", owner="medic",
            attempter="medic", effect_fn=effect_fn, effect_id="eff-r3d",
            now=T0, completion_deadline_ts=T0 + 9000)
        self.assertEqual(observed, {"state": "canceled",
                                    "effect_state": "resolved"})
        # The late failure must not overwrite resolved with uncertain
        # (the round-2 exception branch did exactly that), nor disturb
        # the confirmed cancellation; the returned status is the
        # terminal state of record.
        self.assertEqual(res["status"], "canceled")
        rev = q.get_rev("task-r3d")
        self.assertEqual(rev["state"], "canceled")
        self.assertEqual(rev["effects"][0]["state"], "resolved")
        self.assertIsNotNone(rev["cancellation"]["confirmed_ts"])
        self.assertEqual(q.recover_cancellations(now=T0 + 9), [])
        self.assertEqual(q.get_rev("task-r3d")["effects"][0]["state"],
                         "resolved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
