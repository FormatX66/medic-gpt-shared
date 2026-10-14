#!/usr/bin/env python3
"""Acceptance tests for crew_queue_v2.py against crew-queue-v2-SPEC.md
rev 3 (sha256 c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3).

One or more tests per spec acceptance case A1-A15, plus binding/conflict
tests for section 1 and section 11. Concurrency cases (A9, A13) are
simulated deterministically with barrier-synchronized threads over two
store instances on the same path — the store's flock-serialized
read-modify-write is what makes the outcome deterministic. Crash cases
(A11, A12) use injected sender/hook fakes. Fully offline; runs in seconds.

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
                 now=T0 + 300)
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
            attempter="medic", effect_fn=boom, effect_id="eff-u", now=T0)
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
            effect_id="eff-ok", now=T0)
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
                    owner="medic", now=T0)
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
                          now=T0)
        r2 = self.q.admit("task-x", 1, payload, route="Board",
                          owner="rivet", now=T0 + 5)
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
                     now=T0)
        with self.assertRaises(PayloadConflict):
            self.q.admit("task-k", 1, {"v": 2}, route="Board",
                         owner="medic", now=T0 + 1)
        rev = self.rev("task-k")
        # Admission stands; conflict recorded; no second attempt.
        self.assertEqual(rev["state"], "admitted")
        self.assertEqual(len(rev["attempts"]), 1)
        self.assertEqual(len(rev["conflicts"]), 1)
        self.assertIn("conflict-rejected", self.kinds("task-k"))
        # Resolution requires a NEW revision.
        res = self.q.admit("task-k", 2, {"v": 2}, route="doc", owner="medic",
                           now=T0 + 2)
        self.assertEqual(res["status"], "admitted")
        self.assertEqual(self.q.get_item("task-k")["current_revision"], 2)
        with self.assertRaises(StaleRevision):
            self.q.admit("task-k", 1, {"v": 1}, route="doc", owner="medic",
                         now=T0 + 3)


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
            effect_id="eff-z", now=T0)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
