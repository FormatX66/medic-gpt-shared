#!/usr/bin/env python3
"""Tests for crew_queue_import_v1.py (activation gate G1) and the
rollback drill for ROLLBACK-RUNBOOK-crew-queue-v2.md (gate G2).

All fixtures are SYNTHETIC, shaped like the v1 store of record
(top-level {version, updated_ts, evidence_baseline, items}; items with
id/title/owner/created_ts/eta_ts/escalate_ts/pickup_lanes/keywords/
pickup_evidence/state/notes, plus the later status overlay some items
carry). No real store contents are used. The live store is only ever
READ (its hash is taken before/after the refusal test to prove the
importer did not touch it).

The rollback drill executes the runbook's step 2 (reconcile before any
restore) against synthetic v2 stores built with the module's public
API, and proves: unresolved effects and notifications are surfaced by
the reconcile step; reconciled items are not lost (recorded in the
evidence file written before restore) and never replayed (the sender
is never re-invoked); and missing destination evidence aborts the
drill BEFORE any restore write.
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crew_queue_import_v1 as imp
from crew_queue_v2 import (SPEC_SHA256, CrewQueue, InvalidTransition,
                           MissingVerification, payload_sha256)

T0 = 1791900000
NOW = 1791950000


def synthetic_v1():
    """Synthetic v1 store covering every state present in the real
    store's shape: done, picked-up, open, cancelled, missed, the
    dual-field overlays (picked-up+blocked, missed+verified-accepted),
    a status-only item, a cancellation-requested pass-through, an
    unrecognized state, and an item with no state at all."""
    def item(id_, **kw):
        base = {"id": id_, "title": "synthetic %s" % id_,
                "owner": "medic", "created_ts": T0,
                "eta_ts": None, "escalate_ts": None,
                "pickup_lanes": ["shared-outbox"], "keywords": ["fx"],
                "pickup_evidence": None, "notes": "synthetic fixture"}
        base.update(kw)
        return base
    return {
        "version": 1, "updated_ts": T0 + 50,
        "evidence_baseline": {"shared-outbox": ["fx-baseline.md"]},
        "items": [
            item("fx-done", state="done", eta_ts=T0 + 7200,
                 escalate_ts=T0 + 3600,
                 pickup_evidence="synthetic receipt fx-done"),
            item("fx-picked", state="picked-up",
                 escalate_ts=T0 + 1800,
                 pickup_evidence="synthetic ack fx-picked"),
            item("fx-open", state="open", eta_ts=T0 + 7200),
            item("fx-cancelled", state="cancelled"),
            item("fx-missed", state="missed", eta_ts=T0 - 100),
            item("fx-blocked", state="picked-up", status="blocked",
                 pickup_evidence="synthetic ack fx-blocked"),
            item("fx-dual-verified", state="missed",
                 status="verified-accepted"),
            item("fx-status-only", status="verified-accepted"),
            item("fx-cancelreq", state="cancellation-requested"),
            item("fx-unknown", state="in-flight"),
            item("fx-nostate"),
        ],
    }


EXPECTED_STATES = {
    "fx-done": "reported-complete",
    "fx-picked": "admitted",
    "fx-open": "assigned",
    "fx-cancelled": "canceled",
    "fx-missed": "assigned",
    "fx-blocked": "blocked",
    "fx-dual-verified": "verified-accepted",
    "fx-status-only": "verified-accepted",
    "fx-cancelreq": "cancellation-requested",
    "fx-unknown": "assigned",
    "fx-nostate": "assigned",
}


def _load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class ImportTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cq-import-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = os.path.join(self.tmp, "v1.json")
        with open(self.src, "w", encoding="utf-8") as fh:
            json.dump(synthetic_v1(), fh)
        self.target = os.path.join(self.tmp, "v2.json")

    def apply(self):
        code, report = imp.import_v1(self.src, target=self.target,
                                     apply=True, now=NOW)
        self.assertEqual(code, 0, report)
        return report


class TestFullMapping(ImportTestBase):
    def test_states_map_per_spec_vocabulary(self):
        self.apply()
        q = CrewQueue(self.target)
        for task_id, want in EXPECTED_STATES.items():
            rev = q.get_rev(task_id)
            self.assertEqual(rev["state"], want, task_id)
            self.assertEqual(rev["revision"], 1, task_id)

    def test_import_record_preserves_v1_item_verbatim(self):
        self.apply()
        q = CrewQueue(self.target)
        fixture = {i["id"]: i for i in synthetic_v1()["items"]}
        for task_id in EXPECTED_STATES:
            rev = q.get_rev(task_id)
            imports = [r for r in rev["records"]
                       if r["kind"] == "import"]
            self.assertEqual(len(imports), 1, task_id)
            self.assertEqual(imports[0]["v1_item"], fixture[task_id],
                             task_id)
            self.assertEqual(imports[0]["mapped_state"],
                             EXPECTED_STATES[task_id], task_id)

    def test_deadlines_carried_with_v1_origin(self):
        self.apply()
        q = CrewQueue(self.target)
        rev = q.get_rev("fx-done")
        self.assertEqual(rev["deadlines"]["completion"][-1]["ts"],
                         T0 + 7200)
        self.assertIn("v1 eta_ts",
                      rev["deadlines"]["completion"][-1]["reason"])
        self.assertEqual(rev["deadlines"]["pickup"][-1]["ts"],
                         T0 + 3600)
        self.assertIn("v1 escalate_ts",
                      rev["deadlines"]["pickup"][-1]["reason"])
        entries = imp.analyze(synthetic_v1())
        by_id = {e["id"]: e for e in entries}
        self.assertIn("NO-DEADLINE", by_id["fx-cancelled"]["flags"])
        self.assertNotIn("NO-DEADLINE", by_id["fx-done"]["flags"])
        self.assertIn("DUAL-FIELD(status-over-state)",
                      by_id["fx-blocked"]["flags"])
        self.assertIn("MISSED-CARRIED", by_id["fx-missed"]["flags"])

    def test_terminal_and_nonterminal_visibility(self):
        self.apply()
        q = CrewQueue(self.target)
        unresolved_ids = {e["task_id"]
                          for e in q.unresolved_revisions()}
        for terminal in ("fx-dual-verified", "fx-status-only",
                         "fx-cancelled"):
            self.assertNotIn(terminal, unresolved_ids)
        for open_ in ("fx-done", "fx-unknown", "fx-nostate",
                      "fx-missed", "fx-cancelreq"):
            self.assertIn(open_, unresolved_ids)

    def test_no_fabricated_section11_evidence(self):
        self.apply()
        q = CrewQueue(self.target)
        rev = q.get_rev("fx-dual-verified")
        self.assertEqual(rev["state"], "verified-accepted")
        self.assertIsNone(rev["verification"])
        self.assertIsNone(rev["acceptance"])
        rev = q.get_rev("fx-done")
        self.assertIsNone(rev["completion_claim"])


class TestHashPreservation(ImportTestBase):
    def test_payload_hashes_preserved_and_recomputable(self):
        self.apply()
        q = CrewQueue(self.target)
        for item in synthetic_v1()["items"]:
            want = payload_sha256(item)
            rev = q.get_rev(item["id"])
            self.assertEqual(rev["payload_sha256"], want, item["id"])
            preserved = [r for r in rev["records"]
                         if r["kind"] == "import"][0]["v1_item"]
            self.assertEqual(payload_sha256(preserved), want,
                             item["id"])


class TestUnresolvedVisibility(ImportTestBase):
    def test_unresolved_items_carried_visibly(self):
        entries = imp.analyze(synthetic_v1())
        by_id = {e["id"]: e for e in entries}
        for task_id in ("fx-unknown", "fx-nostate"):
            self.assertTrue(by_id[task_id]["unresolved"], task_id)
            self.assertEqual(by_id[task_id]["v2_state"], "assigned")
        code, report = imp.import_v1(self.src, apply=False, now=NOW)
        self.assertEqual(code, 0)
        self.assertIn("UNRESOLVED (carried visibly, non-terminal)",
                      report)
        self.assertIn("fx-unknown", report)
        self.assertIn("fx-nostate", report)
        self.apply()
        q = CrewQueue(self.target)
        for task_id in ("fx-unknown", "fx-nostate"):
            rev = q.get_rev(task_id)
            self.assertIn("import_unresolved", rev)
            self.assertIn("reason", rev["import_unresolved"])
        data = _load_json(self.target)
        self.assertEqual(sorted(data["import"]["unresolved"]),
                         ["fx-nostate", "fx-unknown"])


class TestDryRunWritesNothing(ImportTestBase):
    def test_dry_run_creates_no_files_and_prints_full_mapping(self):
        before = set(os.listdir(self.tmp))
        code, report = imp.import_v1(self.src, apply=False, now=NOW)
        self.assertEqual(code, 0)
        self.assertEqual(set(os.listdir(self.tmp)), before)
        for task_id in EXPECTED_STATES:
            self.assertIn(task_id, report)

    def test_live_store_target_refused_and_live_store_untouched(self):
        live = imp.LIVE_STORE_PATH
        before = _sha256_file(live)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = imp.main(["--source", self.src, "--apply",
                             "--target", live])
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", err.getvalue())
        self.assertEqual(_sha256_file(live), before)

    def test_source_as_target_refused(self):
        code = imp.main(["--source", self.src, "--apply",
                         "--target", self.src])
        self.assertEqual(code, 2)


class TestCorruptInputFailsClosed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cq-corrupt-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = os.path.join(self.tmp, "v2.json")

    def _write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_truncated_json(self):
        src = self._write("bad.json", '{"version": 1, "items": [{"id"')
        with self.assertRaises(imp.ImportFailure):
            imp.load_v1(src)
        self.assertEqual(imp.main(["--source", src]), 3)
        self.assertFalse(os.path.exists(self.target))

    def test_top_level_list(self):
        src = self._write("list.json", '[{"id": "x"}]')
        with self.assertRaises(imp.ImportFailure):
            imp.load_v1(src)

    def test_items_not_a_list(self):
        src = self._write("shape.json",
                          '{"version": 1, "items": {"x": {}}}')
        with self.assertRaises(imp.ImportFailure):
            imp.load_v1(src)

    def test_item_without_id_not_dropped(self):
        src = self._write("noid.json",
                          '{"version": 1, "items": [{"title": "x"}]}')
        with self.assertRaises(imp.ImportFailure):
            imp.load_v1(src)

    def test_own_output_is_clean_rejection(self):
        src = os.path.join(self.tmp, "v1.json")
        with open(src, "w", encoding="utf-8") as fh:
            json.dump(synthetic_v1(), fh)
        code, _ = imp.import_v1(src, target=self.target, apply=True,
                                now=NOW)
        self.assertEqual(code, 0)
        with self.assertRaises(imp.ImportFailure):
            imp.load_v1(self.target)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = imp.main(["--source", self.target])
        self.assertEqual(code, 3)
        self.assertIn("already a v2 store", err.getvalue())


class TestConflictsAndIdempotency(ImportTestBase):
    def _variant(self, items):
        path = os.path.join(self.tmp, "variant.json")
        doc = synthetic_v1()
        doc["items"] = items
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def test_duplicate_id_differing_payload_is_rejected_conflict(self):
        a = {"id": "fx-dup", "title": "one", "owner": "medic",
             "state": "open"}
        b = {"id": "fx-dup", "title": "two", "owner": "medic",
             "state": "open"}
        src = self._variant([a, b])
        with self.assertRaises(imp.ImportFailure):
            imp.analyze(_load_json(src))
        code = imp.main(["--source", src, "--apply",
                         "--target", self.target])
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(self.target))

    def test_duplicate_id_identical_payload_deduped(self):
        a = {"id": "fx-dup", "title": "same", "owner": "medic",
             "state": "open", "created_ts": T0}
        src = self._variant([a, dict(a)])
        code, report = imp.import_v1(src, target=self.target,
                                     apply=True, now=NOW)
        self.assertEqual(code, 0)
        self.assertIn("DUPLICATE deduped", report)
        q = CrewQueue(self.target)
        self.assertIsNotNone(q.get_item("fx-dup"))
        data = _load_json(self.target)
        self.assertEqual(len(data["items"]), 1)

    def test_reapply_is_noop_and_bytes_unchanged(self):
        self.apply()
        before = _sha256_file(self.target)
        code, report = imp.import_v1(self.src, target=self.target,
                                     apply=True, now=NOW + 999)
        self.assertEqual(code, 0)
        self.assertIn("no-op", report)
        self.assertEqual(_sha256_file(self.target), before)

    def test_apply_refuses_foreign_target(self):
        foreign = os.path.join(self.tmp, "foreign.json")
        with open(foreign, "w", encoding="utf-8") as fh:
            fh.write('{"version": 1, "items": []}')
        before = _sha256_file(foreign)
        with self.assertRaises(imp.ImportFailure):
            imp.import_v1(self.src, target=foreign, apply=True,
                          now=NOW)
        self.assertEqual(_sha256_file(foreign), before)


class TestImportedStoreOperable(ImportTestBase):
    def test_module_operates_imported_store(self):
        self.apply()
        q = CrewQueue(self.target)
        # Blocked import unblocks back to its underlying admitted state.
        rev = q.unblock("fx-blocked", now=NOW + 10)
        self.assertEqual(rev["state"], "admitted")
        # Admitted import accepts pickup + start through the live API.
        q.pickup("fx-picked", by="medic", now=NOW + 20)
        q.start("fx-picked", by="medic", now=NOW + 30)
        self.assertEqual(q.get_rev("fx-picked")["state"], "started")
        # Imported cancellation-requested is visible to recovery and
        # confirms once no effects are open.
        actions = q.recover_cancellations(now=NOW + 40)
        confirmed = [a for a in actions
                     if a["task_id"] == "fx-cancelreq"]
        self.assertEqual(confirmed[0]["action"],
                         "cancellation-confirmed")
        self.assertEqual(q.get_rev("fx-cancelreq")["state"],
                         "canceled")
        # The watcher evaluation runs over the imported store.
        self.assertIsInstance(q.escalate_check(now=NOW + 50), list)


# ------------------------------------------------------- correction round
# Regression tests for Rivet's verdict rivet-g1g2-verdict-20261014-2253-v1.
# Each class names the repair it pins; the importer-side classes fail
# against the pre-correction importer (f6836f4a...) and pass against
# the corrected one.

class TestTargetClassifiedUnderLock(ImportTestBase):
    """Fix 1 (TOCTOU): the pre-existing-target classification must
    happen UNDER the destination lock, on the store as loaded there.
    Previously the importer classified the target outside the lock and
    then cleared whatever the transaction loaded — a foreign store
    inserted between the two steps was silently deleted."""

    def test_foreign_store_inserted_at_write_time_survives(self):
        real_cq = imp.CrewQueue
        target = self.target
        inserted = []

        class InsertingQueue(real_cq):
            def _txn(self):
                if not inserted:
                    inserted.append(True)
                    foreign = CrewQueue(target)
                    foreign.admit("foreign-item", 1,
                                  {"task": "foreign"}, route="test",
                                  owner="rivet", now=NOW,
                                  completion_deadline_ts=NOW + 3600)
                return super()._txn()

        imp.CrewQueue = InsertingQueue
        try:
            with self.assertRaises(imp.ImportFailure):
                imp.import_v1(self.src, target=self.target,
                              apply=True, now=NOW)
        finally:
            imp.CrewQueue = real_cq
        data = _load_json(self.target)
        self.assertIn("foreign-item", data["items"])
        self.assertNotIn("fx-done", data["items"])


class TestImportedWatcherSemantics(ImportTestBase):
    """Fix 2: imported items must carry OPERATIONAL history the
    watcher consumes — a pickup record for items v1 shows as picked
    up, and import-marked escalation keys for items v1 marked
    missed — so neither re-escalates after migration, while deadlines
    set AFTER import re-arm and escalate normally."""

    def _variant(self, items):
        path = os.path.join(self.tmp, "variant2.json")
        doc = synthetic_v1()
        doc["items"] = items
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def test_picked_up_import_never_reescalates_across_restart(self):
        self.apply()
        q = CrewQueue(self.target)
        rev = q.get_rev("fx-picked")
        pickups = [r for r in rev["records"] if r["kind"] == "pickup"]
        self.assertEqual(len(pickups), 1)
        self.assertTrue(pickups[0]["imported"])
        a1 = q.escalate_check(now=NOW + 100000)
        q2 = CrewQueue(self.target)  # fresh instance == watcher restart
        a2 = q2.escalate_check(now=NOW + 200000)
        for actions in (a1, a2):
            hits = [a for a in actions
                    if a["task_id"] == "fx-picked"
                    and a["action"] == "escalated"]
            self.assertEqual(hits, [])

    def test_missed_import_marked_no_reescalation_new_deadline_rearms(
            self):
        m = {"id": "fx-missed-dual", "title": "synthetic missed dual",
             "owner": "medic", "created_ts": T0, "eta_ts": T0 + 100,
             "escalate_ts": T0 + 50, "pickup_lanes": ["shared-outbox"],
             "keywords": ["fx"],
             "pickup_evidence": "synthetic ack fx-missed-dual",
             "notes": "synthetic fixture", "state": "picked-up",
             "status": "missed"}
        src = self._variant([m])
        code, report = imp.import_v1(src, target=self.target,
                                     apply=True, now=NOW)
        self.assertEqual(code, 0, report)
        q = CrewQueue(self.target)
        rev = q.get_rev("fx-missed-dual")
        self.assertEqual(rev["state"], "admitted")
        self.assertTrue(
            any(e.get("imported") for e in rev["escalations"]))
        a = q.escalate_check(now=NOW + 100000)
        hits = [x for x in a if x["task_id"] == "fx-missed-dual"
                and x["action"] == "escalated"]
        self.assertEqual(hits, [])
        q.revise_deadline("fx-missed-dual", kind="completion",
                          new_ts=NOW + 150000,
                          reason="post-import re-plan", now=NOW + 100001)
        a2 = q.escalate_check(now=NOW + 200000)
        hits2 = [x for x in a2 if x["task_id"] == "fx-missed-dual"
                 and x["action"] == "escalated"]
        self.assertEqual(len(hits2), 1)
        self.assertEqual(hits2[0]["check"], "completion")


class TestClaimlessContinuation(ImportTestBase):
    """Fix 3: claim-less imported states (open->assigned,
    done->reported-complete) reject the live lifecycle on revision 1
    — that rejection is the safety property, not a dead end: the
    importer marks them and documents the continuation path (admit
    revision 2 through the public API). No claim is ever fabricated
    on revision 1."""

    def test_rev1_claimless_transitions_reject(self):
        self.apply()
        q = CrewQueue(self.target)
        with self.assertRaises(InvalidTransition):
            q.start("fx-open", by="medic", now=NOW + 10)
        rev = q.get_rev("fx-done")
        with self.assertRaises(InvalidTransition):
            q.complete_claim(
                "fx-done", attempt_id=rev["current_attempt_id"],
                artifact={"x": 1}, by="medic", now=NOW + 10)
        with self.assertRaises(InvalidTransition):
            q.verify("fx-done", artifact_sha256="0" * 64, now=NOW + 10)
        with self.assertRaises(MissingVerification):
            q.accept("fx-done", artifact_sha256="0" * 64,
                     criteria="synthetic", by="medic", now=NOW + 10)

    def test_continuation_marker_and_report(self):
        code, report = imp.import_v1(self.src, apply=False, now=NOW)
        self.assertEqual(code, 0)
        self.assertIn("CLAIM-LESS", report)
        self.assertIn("CONTINUATION", report)
        self.apply()
        q = CrewQueue(self.target)
        for tid in ("fx-open", "fx-done"):
            rev = q.get_rev(tid)
            self.assertIn("import_continuation", rev, tid)
            self.assertEqual(rev["import_continuation"]["path"],
                             "new-revision", tid)

    def test_continuation_new_revision_lifecycle_rev1_untouched(self):
        self.apply()
        q = CrewQueue(self.target)
        for tid in ("fx-open", "fx-done"):
            before = q.get_rev(tid, revision=1)
            payload = [r for r in before["records"]
                       if r["kind"] == "import"][0]["v1_item"]
            res = q.admit(tid, 2, payload, route="import-continuation",
                          owner="medic", acceptance_authority="medic",
                          now=NOW + 100,
                          pickup_deadline_ts=NOW + 1000,
                          completion_deadline_ts=NOW + 2000)
            self.assertEqual(res["status"], "admitted", tid)
            q.pickup(tid, revision=2, by="medic", now=NOW + 110)
            q.start(tid, revision=2, by="medic", now=NOW + 120)
            art = {"artifact": "synthetic continuation %s" % tid}
            claim = q.complete_claim(
                tid, revision=2, attempt_id=res["attempt_id"],
                artifact=art, by="medic", now=NOW + 130)
            q.verify(tid, revision=2,
                     artifact_sha256=claim["artifact_sha256"],
                     criteria="synthetic", verifier="rivet",
                     passed=True, now=NOW + 140)
            q.accept(tid, revision=2,
                     artifact_sha256=claim["artifact_sha256"],
                     criteria="synthetic", by="medic", now=NOW + 150)
            self.assertEqual(q.get_rev(tid, revision=2)["state"],
                             "verified-accepted", tid)
            after = q.get_rev(tid, revision=1)
            self.assertEqual(after["state"], before["state"], tid)
            self.assertEqual(len(after["records"]),
                             len(before["records"]), tid)
            self.assertIsNone(after["completion_claim"], tid)


class TestInvalidIds(unittest.TestCase):
    """Fix 6: ids are validated as non-empty strings at load, BEFORE
    anything is built or written. Previously a numeric id passed
    validation, the target was written, and only the post-write
    lookup failed — and list/dict ids raised unhandled errors."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cq-badid-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.target = os.path.join(self.tmp, "v2.json")

    def _src_with_id(self, id_value):
        path = os.path.join(self.tmp, "badid.json")
        doc = {"version": 1, "updated_ts": T0,
               "items": [{"id": id_value, "title": "x",
                          "owner": "medic", "state": "open",
                          "created_ts": T0}]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path

    def test_non_string_or_blank_ids_fail_closed_in_loader(self):
        for bad in (1, True, ["x"], {"k": "v"}, "", "   "):
            src = self._src_with_id(bad)
            with self.assertRaises(imp.ImportFailure, msg=repr(bad)):
                imp.load_v1(src)

    def test_bad_id_apply_writes_nothing_and_exits_3(self):
        for bad in (1, ["x"], {"k": "v"}):
            src = self._src_with_id(bad)
            code = imp.main(["--source", src, "--apply",
                             "--target", self.target])
            self.assertEqual(code, 3, repr(bad))
            self.assertFalse(os.path.exists(self.target), repr(bad))


# ---------------------------------------------------------------- drill

class _DestinationView:
    """Fake destination: has seen exactly the given notification ids."""

    def __init__(self, seen):
        self._seen = set(seen)

    def has_seen(self, notification_id):
        return notification_id in self._seen


class DrillAbort(Exception):
    """The rollback drill fails closed: restore must not proceed."""


EXPECTED_RESTORE_MEMBERS = (
    "crew-queue-v1-baseline.json",
    "clock-tower-state-baseline.json",
    "clock_tower_agent-v1.1-baseline.py",
)
"""The COMPLETE restore set (residual R3): exactly the files step 3
of the runbook restores — the v1 queue baseline, the Tower state
baseline, and the pinned Tower source baseline. A manifest that
verifies beautifully for a SUBSET of these restores a subset, which
is a partial rollback wearing a passed gate."""


def _verify_baseline_manifest(baseline_dir):
    """Residual R3: verify the baseline manifest as a complete,
    pinned SET — not as 'whatever entries it happens to contain'.

    The pre-R3 check verified each listed entry's hash and nothing
    else: a manifest listing only the v1 queue baseline (both Tower
    members omitted) passed, an EMPTY manifest passed, and the
    manifest itself was trusted because it was there. Now, before
    any reconcile or restore write:
      * MANIFEST.sha256 must exist, parse, and be non-empty;
      * its member set must equal EXPECTED_RESTORE_MEMBERS exactly —
        a missing member, an unlisted extra member, or a duplicate
        (conflicting) entry aborts;
      * every listed member must exist on disk and hash-match;
      * MANIFEST.json — the trusted pin, written when the baseline
        was snapshotted — must exist, pin the same complete set,
        and agree with MANIFEST.sha256 on every member's hash, so
        the manifest's own integrity is checked against a second
        record rather than asserted."""
    manifest_path = os.path.join(baseline_dir, "MANIFEST.sha256")
    if not os.path.exists(manifest_path):
        raise DrillAbort(
            "gate condition 0 (preflight): baseline manifest %s "
            "is missing; restore forbidden" % manifest_path)
    problems = []
    entries = {}
    with open(manifest_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                problems.append("malformed manifest line %r" % line)
                continue
            want = parts[0]
            name = parts[1].lstrip("*").strip()
            if name in entries:
                problems.append(
                    "conflicting manifest: duplicate entry for %s"
                    % name)
                continue
            entries[name] = want
    if not entries:
        problems.append("manifest is empty; an empty manifest "
                        "verifies nothing")
    missing = [m for m in EXPECTED_RESTORE_MEMBERS
               if m not in entries]
    if missing:
        problems.append(
            "manifest is incomplete: required restore member(s) "
            "missing: %s" % (missing,))
    extra = [n for n in entries if n not in EXPECTED_RESTORE_MEMBERS]
    if extra:
        problems.append(
            "manifest lists member(s) outside the restore set: %s"
            % (extra,))
    for name, want in entries.items():
        fpath = os.path.join(baseline_dir, name)
        if not os.path.exists(fpath):
            problems.append("restore member %s is missing on disk"
                            % name)
        elif _sha256_file(fpath) != want:
            problems.append("restore member %s fails its manifest "
                            "hash" % name)
    pin_path = os.path.join(baseline_dir, "MANIFEST.json")
    if not os.path.exists(pin_path):
        problems.append(
            "MANIFEST.json is missing; the manifest's integrity "
            "is unpinned and untrusted")
    else:
        try:
            pin = _load_json(pin_path)
        except (ValueError, OSError) as exc:
            problems.append("MANIFEST.json is unreadable (%s)"
                            % type(exc).__name__)
            pin = None
        if pin is not None:
            pin_entries = {}
            for f in pin.get("files") or []:
                if isinstance(f, dict) and f.get("copy"):
                    pin_entries[f["copy"]] = f.get("sha256")
            if set(pin_entries) != set(EXPECTED_RESTORE_MEMBERS):
                problems.append(
                    "MANIFEST.json does not pin the complete "
                    "restore set (pins %s)"
                    % (sorted(pin_entries),))
            else:
                for name, want in entries.items():
                    if pin_entries.get(name) != want:
                        problems.append(
                            "manifest pin conflict for %s: "
                            "MANIFEST.sha256 and MANIFEST.json "
                            "disagree" % name)
    if problems:
        raise DrillAbort(
            "gate condition 0 (preflight): baseline manifest "
            "failure — %s; restore forbidden" % (problems,))


def rollback_preflight(store_path, baseline_dir=None):
    """Gate condition 0 (correction fix 5): READ-ONLY preflight, run
    before any reconcile write. A missing v2 ledger must NEVER be
    opened through CrewQueue and reconciled as an empty substitute
    (opening a missing path yields an empty store, against which every
    recovery trivially 'succeeds'); an unreadable or unrecognized
    ledger likewise fails closed. When a baseline dir is given, its
    MANIFEST.sha256 integrity is verified HERE — before any restore
    write — never only after one; and (residual R3) the manifest is
    verified as the COMPLETE expected restore set, cross-pinned
    against MANIFEST.json, not as whatever subset it lists."""
    if not os.path.exists(store_path):
        raise DrillAbort(
            "gate condition 0 (preflight): v2 ledger %s is missing; "
            "refusing to reconcile a missing ledger as an empty store"
            % store_path)
    try:
        data = _load_json(store_path)
    except (ValueError, OSError) as exc:
        raise DrillAbort(
            "gate condition 0 (preflight): v2 ledger %s is unreadable "
            "(%s); failing closed" % (store_path, type(exc).__name__))
    if not isinstance(data, dict) or data.get("version") != 2 or \
            not isinstance(data.get("items"), dict) or \
            data.get("spec_sha256") != SPEC_SHA256:
        raise DrillAbort(
            "gate condition 0 (preflight): %s is not a recognized v2 "
            "ledger (version / items / spec_sha256); failing closed"
            % store_path)
    if baseline_dir is not None:
        _verify_baseline_manifest(baseline_dir)
    return True


def rollback_reconcile(q, destination_view=None, effect_evidence=None,
                       sender=None, baseline_dir=None, preflight=True):
    """ROLLBACK-RUNBOOK step 2, executed: surface every unresolved
    effect / cancellation / notification, reconcile each against
    destination evidence, and enforce ALL FOUR of the runbook's 2e
    fail-closed gate conditions — each abort is tagged with the
    condition that fired:
      1. a final re-surface shows no open effects and no requested
         cancellations (an effect reconciled with found=False is
         STILL OPEN and aborts here even with no cancellation in
         play — correction fix 4);
      2. recover_cancellations reports no cancellation-still-pending;
      3. notification recovery reports no fail-closed-* and no
         still-uncertain action;
      4. coverage: every effect surfaced is resolved in the final
         store, every notification unresolved at surface time is in a
         terminal state, and no notification is left in a
         non-terminal state by any path.
    Returns the reconciliation evidence dict the runbook requires to
    be recorded BEFORE any restore."""
    effect_evidence = effect_evidence or {}
    if preflight:
        rollback_preflight(q.path, baseline_dir=baseline_dir)
    surfaced = {"open_effects": [], "cancellations": []}
    for entry in q.unresolved_revisions():
        for eid in entry["open_effects"]:
            surfaced["open_effects"].append(
                {"task_id": entry["task_id"], "effect_id": eid})
        if entry["cancellation_requested"]:
            surfaced["cancellations"].append(
                {"task_id": entry["task_id"],
                 "revision": entry["revision"]})
    data = _load_json(q.path)
    open_notifs_before = sorted(
        nid for nid, n in (data.get("notifications") or {}).items()
        if n.get("state") in ("intent", "uncertain"))
    actions = q.recover_notifications(
        sender=sender, destination_view=destination_view)
    for a in actions:
        if a["action"].startswith("fail-closed") or \
                a["action"] == "still-uncertain":
            raise DrillAbort(
                "gate condition 3: notification %s unreconciled "
                "(%s); restore forbidden"
                % (a["notification_id"], a["action"]))
    for oe in surfaced["open_effects"]:
        if oe["effect_id"] not in effect_evidence:
            raise DrillAbort(
                "gate condition 1: no destination evidence for effect "
                "%s; restore forbidden" % oe["effect_id"])
        q.reconcile_effect(oe["task_id"], oe["effect_id"],
                           found=bool(
                               effect_evidence[oe["effect_id"]]),
                           detail="drill: destination query by "
                                  "effect_id")
    cancel_actions = q.recover_cancellations()
    for a in cancel_actions:
        if a["action"] == "cancellation-still-pending":
            raise DrillAbort(
                "gate condition 2: cancellation for %s still pending "
                "(open effects %s); restore forbidden"
                % (a["task_id"], a["open_effects"]))
    final = q.unresolved_revisions()
    remaining_fx = [(e["task_id"], eid) for e in final
                    for eid in e["open_effects"]]
    remaining_cx = [e["task_id"] for e in final
                    if e["cancellation_requested"]]
    if remaining_fx or remaining_cx:
        raise DrillAbort(
            "gate condition 1: unreconciled after recovery — open "
            "effects %s, cancellations %s; restore forbidden"
            % (remaining_fx, remaining_cx))
    data = _load_json(q.path)
    effect_states = {}
    for item in (data.get("items") or {}).values():
        for rev in (item.get("revisions") or {}).values():
            for eff in rev.get("effects", []):
                effect_states[eff["effect_id"]] = eff["state"]
    bad_fx = [oe["effect_id"] for oe in surfaced["open_effects"]
              if effect_states.get(oe["effect_id"]) != "resolved"]
    notif_states = {nid: n.get("state") for nid, n in
                    (data.get("notifications") or {}).items()}
    bad_nt = [nid for nid in open_notifs_before
              if notif_states.get(nid) not in
              ("sent", "sent-confirmed")]
    stray_nt = [nid for nid, st_ in notif_states.items()
                if st_ in ("intent", "uncertain")]
    if bad_fx or bad_nt or stray_nt:
        raise DrillAbort(
            "gate condition 4: coverage failure — effects without a "
            "resolved outcome %s, surfaced notifications without a "
            "terminal outcome %s, notifications in non-terminal "
            "states %s; restore forbidden" % (bad_fx, bad_nt, stray_nt))
    return {"surfaced": surfaced, "notification_actions": actions,
            "cancellation_actions": cancel_actions}


class TestRollbackDrill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cq-drill-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = os.path.join(self.tmp, "drill-v2.json")
        self.baseline = os.path.join(self.tmp, "baseline-v1.json")
        with open(self.baseline, "w", encoding="utf-8") as fh:
            json.dump(synthetic_v1(), fh)
        self.baseline_sha = _sha256_file(self.baseline)

    def _drill_store(self):
        """Synthetic v2 store holding one unresolved effect (uncertain)
        under a pending cancellation, and one unresolved EXTERNAL
        notification (send attempted, outcome unknown)."""
        q = CrewQueue(self.store)
        q.admit("drill-item", 1, {"task": "synthetic drill"},
                route="test", owner="medic", now=T0,
                completion_deadline_ts=T0 + 3600)
        eff = q.register_effect("drill-item", uncertain=True,
                                now=T0 + 1)
        q.cancel_request("drill-item", by="medic", now=T0 + 2)
        sends = []

        def failing_sender(nid, dest, payload):
            sends.append(nid)
            raise RuntimeError("destination unreachable (drill)")

        notif = q.notify("board:drill", {"msg": "synthetic"},
                         sender=failing_sender, kind="manual",
                         task_id="drill-item", revision=1, now=T0 + 3)
        self.assertEqual(notif["state"], "uncertain")
        return q, eff["effect_id"], notif["notification_id"], sends

    def test_reconcile_then_restore_loses_and_replays_nothing(self):
        q, eid, nid, sends = self._drill_store()
        evidence = rollback_reconcile(
            q, destination_view=_DestinationView({nid}),
            effect_evidence={eid: True})
        # (a) the reconcile step surfaced both unresolved records.
        self.assertEqual(
            [o["effect_id"] for o in
             evidence["surfaced"]["open_effects"]], [eid])
        self.assertEqual(
            [c["task_id"] for c in
             evidence["surfaced"]["cancellations"]], ["drill-item"])
        # Notification confirmed at destination, never re-sent.
        na = evidence["notification_actions"]
        self.assertEqual(len(na), 1)
        self.assertEqual(na[0]["action"], "confirmed-at-destination")
        self.assertFalse(na[0]["resent"])
        self.assertEqual(len(sends), 1)  # only the original attempt
        # Effect resolved by evidence; cancellation confirmed.
        rev = q.get_rev("drill-item")
        self.assertEqual(rev["state"], "canceled")
        self.assertEqual(rev["effects"][0]["state"], "resolved")
        # Evidence recorded BEFORE restore (runbook step 5).
        evidence_path = os.path.join(self.tmp,
                                     "rollback-evidence.json")
        record = {"reconciled_effects": [eid],
                  "reconciled_notifications": [nid],
                  "cancellations_confirmed": ["drill-item"],
                  "detail": evidence["surfaced"]}
        with open(evidence_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        # (b) restore: baseline lands byte-exact, evidence survives,
        # nothing is replayed by the restore itself.
        shutil.copyfile(self.baseline, self.store)
        self.assertEqual(_sha256_file(self.store), self.baseline_sha)
        self.assertEqual(_load_json(self.store)["version"], 1)
        saved = _load_json(evidence_path)
        self.assertEqual(saved["reconciled_effects"], [eid])
        self.assertEqual(saved["reconciled_notifications"], [nid])
        self.assertEqual(len(sends), 1)

    def test_missing_notification_evidence_fails_closed(self):
        q, eid, nid, sends = self._drill_store()
        with self.assertRaises(DrillAbort):
            rollback_reconcile(q, destination_view=None,
                               effect_evidence={eid: True})
        # No restore write happened: the store is still the v2 drill
        # store and both records remain unresolved on disk.
        data = _load_json(self.store)
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["notifications"][nid]["state"],
                         "uncertain")
        rev = data["items"]["drill-item"]["revisions"]["1"]
        self.assertEqual(rev["effects"][0]["state"], "uncertain")
        self.assertEqual(rev["state"], "cancellation-requested")
        self.assertEqual(len(sends), 1)

    def test_absent_effect_evidence_fails_closed(self):
        q, eid, nid, sends = self._drill_store()
        with self.assertRaises(DrillAbort):
            rollback_reconcile(
                q, destination_view=_DestinationView({nid}),
                effect_evidence={eid: False})
        # Absence never resolves: effect stays uncertain, item stays
        # cancellation-requested, no restore write occurred.
        rev = q.get_rev("drill-item")
        self.assertEqual(rev["effects"][0]["state"], "uncertain")
        self.assertEqual(rev["state"], "cancellation-requested")
        data = _load_json(self.store)
        self.assertEqual(data["version"], 2)


class TestRollbackGateConditions(unittest.TestCase):
    """Fix 4: the executable drill implements ALL FOUR of the
    runbook's 2e fail-closed conditions. The pre-correction drill
    returned success whenever no cancellation happened to be pending
    and no notification action happened to start with 'fail-closed'
    — each test below isolates one condition."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cq-gate-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = os.path.join(self.tmp, "gate-v2.json")

    def _effect_store(self, with_cancellation):
        q = CrewQueue(self.store)
        q.admit("gate-item", 1, {"task": "synthetic gate"},
                route="test", owner="medic", now=T0,
                completion_deadline_ts=T0 + 3600)
        eff = q.register_effect("gate-item", uncertain=True,
                                now=T0 + 1)
        if with_cancellation:
            q.cancel_request("gate-item", by="medic", now=T0 + 2)
        return q, eff["effect_id"]

    def test_gate1_absent_effect_without_cancellation_aborts(self):
        # Rivet's reproduced case: uncertain effect, destination
        # says found=False, NO cancellation in play. The old drill
        # returned success; the final re-surface (condition 1) must
        # abort because the effect is still open.
        q, eid = self._effect_store(with_cancellation=False)
        with self.assertRaises(DrillAbort) as cm:
            rollback_reconcile(q, effect_evidence={eid: False})
        self.assertIn("gate condition 1", str(cm.exception))
        rev = q.get_rev("gate-item")
        self.assertEqual(rev["effects"][0]["state"], "uncertain")
        data = _load_json(self.store)
        self.assertEqual(data["version"], 2)  # no restore write

    def test_gate2_pending_cancellation_aborts(self):
        q, eid = self._effect_store(with_cancellation=True)
        with self.assertRaises(DrillAbort) as cm:
            rollback_reconcile(q, effect_evidence={eid: False})
        self.assertIn("gate condition 2", str(cm.exception))
        rev = q.get_rev("gate-item")
        self.assertEqual(rev["state"], "cancellation-requested")

    def test_gate3_still_uncertain_notification_aborts(self):
        q, eid = self._effect_store(with_cancellation=False)

        def bad_sender(nid, dest, payload):
            raise RuntimeError("destination down (gate drill)")

        notif = q.notify("board:gate", {"msg": "synthetic"},
                         sender=bad_sender, kind="manual",
                         task_id="gate-item", revision=1, now=T0 + 3)
        self.assertEqual(notif["state"], "uncertain")
        with self.assertRaises(DrillAbort) as cm:
            rollback_reconcile(
                q, destination_view=_DestinationView(set()),
                effect_evidence={eid: True}, sender=bad_sender)
        self.assertIn("gate condition 3", str(cm.exception))

    def test_gate4_notification_without_outcome_aborts(self):
        # A notification minted DURING recovery (a writer that was
        # not frozen) has no reconciled outcome: conditions 1-3 all
        # pass, and only the coverage sweep (condition 4) catches it.
        q = CrewQueue(self.store)
        q.admit("gate-item", 1, {"task": "synthetic gate"},
                route="test", owner="medic", now=T0,
                completion_deadline_ts=T0 + 3600)
        eff = q.register_effect("gate-item", uncertain=True, now=T0 + 1)
        eid = eff["effect_id"]
        q.cancel_request("gate-item", by="medic", now=T0 + 2)

        def bad_sender(nid, dest, payload):
            raise RuntimeError("destination down (gate drill)")

        notif = q.notify("board:gate", {"msg": "synthetic"},
                         sender=bad_sender, kind="manual",
                         task_id="gate-item", revision=1, now=T0 + 3)
        nid = notif["notification_id"]
        self.assertEqual(notif["state"], "uncertain")
        real_recover = q.recover_notifications

        def injecting_recover(sender=None, destination_view=None,
                              now=None):
            actions = real_recover(sender=sender,
                                   destination_view=destination_view,
                                   now=now)
            q.notify("board:late", {"msg": "late"}, sender=bad_sender,
                     kind="manual", task_id="gate-item", revision=1,
                     now=T0 + 9)
            return actions

        q.recover_notifications = injecting_recover
        try:
            with self.assertRaises(DrillAbort) as cm:
                rollback_reconcile(
                    q, destination_view=_DestinationView({nid}),
                    effect_evidence={eid: True})
        finally:
            q.recover_notifications = real_recover
        self.assertIn("gate condition 4", str(cm.exception))


class TestRollbackPreflight(unittest.TestCase):
    """Fix 5: the rollback path preflights read-only. A missing v2
    ledger is never 'reconciled' as an empty substitute (the old
    drill's recoveries simply created and succeeded against an empty
    store), and baseline manifest integrity is verified BEFORE any
    restore write, not only after one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cq-preflight-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = os.path.join(self.tmp, "pre-v2.json")

    def _store_with_uncertain_notification(self):
        q = CrewQueue(self.store)
        q.admit("pre-item", 1, {"task": "synthetic preflight"},
                route="test", owner="medic", now=T0,
                completion_deadline_ts=T0 + 3600)

        def bad_sender(nid, dest, payload):
            raise RuntimeError("destination down (preflight drill)")

        notif = q.notify("board:pre", {"msg": "synthetic"},
                         sender=bad_sender, kind="manual",
                         task_id="pre-item", revision=1, now=T0 + 1)
        self.assertEqual(notif["state"], "uncertain")
        return q, notif["notification_id"]

    def _baseline_dir(self, tamper=False):
        """The COMPLETE synthetic baseline (residual R3): all three
        restore members on disk, a three-line MANIFEST.sha256, and
        MANIFEST.json pinning the same set. (The pre-R3 fixture
        listed only the v1 queue baseline — that one-member
        manifest passing was the defect, not a success case.)"""
        bdir = os.path.join(self.tmp, "baseline")
        os.makedirs(bdir, exist_ok=True)
        contents = {
            "crew-queue-v1-baseline.json":
                '{"version": 1, "items": []}\n',
            "clock-tower-state-baseline.json":
                '{"watermarks": {}}\n',
            "clock_tower_agent-v1.1-baseline.py":
                "# synthetic pinned tower source\n",
        }
        digests = {}
        for name, content in contents.items():
            with open(os.path.join(bdir, name), "w",
                      encoding="utf-8") as fh:
                fh.write(content)
            digests[name] = hashlib.sha256(
                content.encode()).hexdigest()
        with open(os.path.join(bdir, "MANIFEST.sha256"), "w",
                  encoding="utf-8") as fh:
            for name in EXPECTED_RESTORE_MEMBERS:
                fh.write("%s  %s\n" % (digests[name], name))
        pin = {"files": [{"copy": name, "sha256": digests[name]}
                         for name in EXPECTED_RESTORE_MEMBERS]}
        with open(os.path.join(bdir, "MANIFEST.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(pin, fh)
        if tamper:
            with open(os.path.join(bdir,
                                   "crew-queue-v1-baseline.json"),
                      "a", encoding="utf-8") as fh:
                fh.write(" ")
        return bdir

    def test_missing_ledger_aborts_and_creates_nothing(self):
        missing = os.path.join(self.tmp, "no-such-v2.json")
        q = CrewQueue(missing)
        with self.assertRaises(DrillAbort) as cm:
            rollback_reconcile(q)
        self.assertIn("preflight", str(cm.exception))
        self.assertFalse(os.path.exists(missing))

    def test_manifest_tamper_aborts_before_any_reconcile(self):
        q, nid = self._store_with_uncertain_notification()
        bdir = self._baseline_dir(tamper=True)
        with self.assertRaises(DrillAbort) as cm:
            rollback_reconcile(
                q, destination_view=_DestinationView({nid}),
                baseline_dir=bdir)
        self.assertIn("preflight", str(cm.exception))
        data = _load_json(self.store)
        self.assertEqual(data["notifications"][nid]["state"],
                         "uncertain")

    def test_manifest_intact_lets_reconcile_proceed(self):
        q, nid = self._store_with_uncertain_notification()
        bdir = self._baseline_dir(tamper=False)
        evidence = rollback_reconcile(
            q, destination_view=_DestinationView({nid}),
            baseline_dir=bdir)
        na = evidence["notification_actions"]
        self.assertEqual(len(na), 1)
        self.assertEqual(na[0]["action"], "confirmed-at-destination")


# ------------------------------------------------------- residual round
# Regression tests for Rivet's verdict
# rivet-g1g2-corrected-verdict-20261014-2332-v1. Fixes 2/4/6 were
# verified addressed; fixes 1/3/5 were partial, with residuals
# R1/R2/R3. Each class below names its residual; the R1/R2 classes
# fail against the corrected importer (50e562ed...) and pass against
# this one; the R3 tests fail against the pre-residual preflight
# (which verified whatever a manifest happened to list).

class TestEmptyIsNotAbsent(ImportTestBase):
    """Residual R1: empty is not absent. The corrected importer
    classified any content-free loaded store 'empty' and filled it:
    an existing empty wrong-spec ledger and a valid empty ledger
    carrying critical provenance both returned 0, changed bytes, and
    deleted provenance. New initialization is allowed ONLY for a
    genuinely absent destination; existing exact import stays a
    byte-preserving no-op; every other existing target refuses,
    decided under the destination lock."""

    def _write_store(self, doc):
        with open(self.target, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
        return _sha256_file(self.target)

    def test_existing_valid_empty_ledger_refused_bytes_preserved(self):
        q = CrewQueue(self.target)
        with q._txn():
            pass  # the module itself saves a valid, empty ledger
        self.assertTrue(os.path.exists(self.target))
        before = _sha256_file(self.target)
        with self.assertRaises(imp.ImportFailure) as cm:
            imp.import_v1(self.src, target=self.target, apply=True,
                          now=NOW)
        self.assertIn("empty is not absent", str(cm.exception))
        self.assertEqual(_sha256_file(self.target), before)

    def test_existing_empty_wrong_spec_refused(self):
        before = self._write_store(
            {"version": 2, "spec_sha256": "0" * 64,
             "created_ts": T0, "updated_ts": T0, "items": {},
             "notifications": {}, "outbox": {}, "deliveries": []})
        with self.assertRaises(imp.ImportFailure):
            imp.import_v1(self.src, target=self.target, apply=True,
                          now=NOW)
        self.assertEqual(_sha256_file(self.target), before)

    def test_existing_empty_with_provenance_refused_and_preserved(self):
        before = self._write_store(
            {"version": 2, "spec_sha256": SPEC_SHA256,
             "created_ts": T0, "updated_ts": T0, "items": {},
             "notifications": {}, "outbox": {}, "deliveries": [],
             "critical_provenance": {
                 "snapshot_of": "synthetic ledger",
                 "operator": "rivet", "do_not_delete": True}})
        with self.assertRaises(imp.ImportFailure):
            imp.import_v1(self.src, target=self.target, apply=True,
                          now=NOW)
        self.assertEqual(_sha256_file(self.target), before)
        self.assertIn("critical_provenance",
                      _load_json(self.target))

    def test_competing_empty_import_is_refused_not_noop(self):
        # Two different EMPTY sources produce the same (empty) item
        # set, so the item-level comparison is vacuous: only the
        # store-level provenance binding keeps the second import
        # from being mistaken for a no-op re-apply of the first.
        empty_a = os.path.join(self.tmp, "empty-a.json")
        with open(empty_a, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "updated_ts": T0, "items": []},
                      fh)
        code, _ = imp.import_v1(empty_a, target=self.target,
                                apply=True, now=NOW)
        self.assertEqual(code, 0)
        before = _sha256_file(self.target)
        empty_b = os.path.join(self.tmp, "empty-b.json")
        with open(empty_b, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "updated_ts": T0 + 1,
                       "items": []}, fh)
        with self.assertRaises(imp.ImportFailure):
            imp.import_v1(empty_b, target=self.target, apply=True,
                          now=NOW)
        self.assertEqual(_sha256_file(self.target), before)
        # Re-applying the SAME source is still a byte-preserving
        # no-op.
        code, report = imp.import_v1(empty_a, target=self.target,
                                     apply=True, now=NOW + 5)
        self.assertEqual(code, 0)
        self.assertIn("no-op", report)
        self.assertEqual(_sha256_file(self.target), before)


class TestContinuationReconciliation(ImportTestBase):
    """Residual R2: the fix-3 continuation marker is not operational
    retirement — after the rev2 lifecycle, unresolved_revisions
    still listed rev1 'assigned' (imported open) and
    'reported-complete' (imported done). Retirement is a defined
    administrative reconciliation: only a verified-accepted
    successor carrying the same payload authorizes it; it links
    predecessor/successor on rev1 and cancels rev1 through the
    public operations, preserving every historical record and
    fabricating no completion evidence."""

    def _run_rev2_lifecycle(self, q, tid):
        rev1 = q.get_rev(tid, revision=1)
        payload = [r for r in rev1["records"]
                   if r["kind"] == "import"][0]["v1_item"]
        res = q.admit(tid, 2, payload, route="import-continuation",
                      owner="medic", acceptance_authority="medic",
                      now=NOW + 100,
                      pickup_deadline_ts=NOW + 1000,
                      completion_deadline_ts=NOW + 2000)
        q.pickup(tid, revision=2, by="medic", now=NOW + 110)
        q.start(tid, revision=2, by="medic", now=NOW + 120)
        art = {"artifact": "synthetic reconciliation %s" % tid}
        claim = q.complete_claim(
            tid, revision=2, attempt_id=res["attempt_id"],
            artifact=art, by="medic", now=NOW + 130)
        q.verify(tid, revision=2,
                 artifact_sha256=claim["artifact_sha256"],
                 criteria="synthetic", verifier="rivet",
                 passed=True, now=NOW + 140)
        q.accept(tid, revision=2,
                 artifact_sha256=claim["artifact_sha256"],
                 criteria="synthetic", by="medic", now=NOW + 150)
        return claim

    def test_rev1_unresolved_until_reconciled_then_retired(self):
        self.apply()
        q = CrewQueue(self.target)
        for tid, pre_state in (("fx-open", "assigned"),
                               ("fx-done", "reported-complete")):
            claim = self._run_rev2_lifecycle(q, tid)
            # The residual, reproduced: rev2 is verified-accepted,
            # yet rev1 still sits in the unresolved view.
            unres = {(e["task_id"], e["revision"])
                     for e in q.unresolved_revisions()}
            self.assertIn((tid, 1), unres, tid)
            rev1_before = q.get_rev(tid, revision=1)
            outcomes = imp.reconcile_import_continuations(
                q, by="medic", now=NOW + 500)
            mine = [o for o in outcomes if o["task_id"] == tid]
            self.assertEqual(len(mine), 1, tid)
            self.assertEqual(mine[0]["status"], "retired", tid)
            self.assertEqual(mine[0]["successor_revision"], 2, tid)
            rev1 = q.get_rev(tid, revision=1)
            # Retired, terminal, out of the unresolved view; rev2
            # untouched and still current/accepted.
            self.assertEqual(rev1["state"], "canceled", tid)
            self.assertEqual(
                rev1["cancellation"]["pre_request_state"],
                pre_state, tid)
            unres = {(e["task_id"], e["revision"])
                     for e in q.unresolved_revisions()}
            self.assertNotIn((tid, 1), unres, tid)
            self.assertEqual(q.get_rev(tid, revision=2)["state"],
                             "verified-accepted", tid)
            # No fabricated section-11 evidence on rev1, ever.
            self.assertIsNone(rev1["completion_claim"], tid)
            self.assertIsNone(rev1["verification"], tid)
            self.assertIsNone(rev1["acceptance"], tid)
            # History is append-only: every pre-reconciliation
            # record is an unchanged prefix of the final record
            # list.
            self.assertEqual(
                rev1["records"][:len(rev1_before["records"])],
                rev1_before["records"], tid)
            # The linkage record ties rev1 to its successor and
            # cites the successor's real acceptance artifact.
            links = [r for r in rev1["records"]
                     if r["kind"] == "import-reconciliation"]
            self.assertEqual(len(links), 1, tid)
            self.assertEqual(links[0]["predecessor_revision"], 1,
                             tid)
            self.assertEqual(links[0]["successor_revision"], 2, tid)
            self.assertEqual(
                links[0]["successor_acceptance_artifact_sha256"],
                claim["artifact_sha256"], tid)
            self.assertEqual(links[0]["predecessor_state"],
                             pre_state, tid)
            # No double-escalation: the retired rev1 fires nothing,
            # and the accepted rev2 is terminal.
            hits = [a for a in q.escalate_check(now=NOW + 100000)
                    if a["task_id"] == tid
                    and a["action"] == "escalated"]
            self.assertEqual(hits, [], tid)

    def test_no_retirement_before_successor_acceptance(self):
        self.apply()
        q = CrewQueue(self.target)
        rev1 = q.get_rev("fx-open", revision=1)
        payload = [r for r in rev1["records"]
                   if r["kind"] == "import"][0]["v1_item"]
        q.admit("fx-open", 2, payload, route="import-continuation",
                owner="medic", acceptance_authority="medic",
                now=NOW + 100, pickup_deadline_ts=NOW + 1000,
                completion_deadline_ts=NOW + 2000)
        outcomes = imp.reconcile_import_continuations(
            q, by="medic", now=NOW + 500)
        by_id = {o["task_id"]: o for o in outcomes}
        # Successor merely admitted: not authorized.
        self.assertEqual(by_id["fx-open"]["status"],
                         "awaiting-continuation")
        # No successor at all: not authorized either.
        self.assertEqual(by_id["fx-done"]["status"],
                         "awaiting-continuation")
        for tid in ("fx-open", "fx-done"):
            rev1 = q.get_rev(tid, revision=1)
            self.assertIsNone(rev1["cancellation"], tid)
            self.assertIn(
                (tid, 1),
                {(e["task_id"], e["revision"])
                 for e in q.unresolved_revisions()}, tid)
        rev1 = q.get_rev("fx-open", revision=1)
        self.assertEqual(
            [r for r in rev1["records"]
             if r["kind"] == "import-reconciliation"], [])

    def test_reconcile_idempotent_and_scoped_to_imports(self):
        self.apply()
        q = CrewQueue(self.target)
        # A live (non-import) item whose rev2 completes: its rev1
        # is NOT an import continuation and must never be retired
        # by this step.
        q.admit("live-item", 1, {"task": "live"}, route="test",
                owner="medic", acceptance_authority="medic", now=NOW,
                completion_deadline_ts=NOW + 900)
        res = q.admit("live-item", 2, {"task": "live v2"},
                      route="test", owner="medic",
                      acceptance_authority="medic", now=NOW + 10,
                      completion_deadline_ts=NOW + 1900)
        q.pickup("live-item", revision=2, by="medic", now=NOW + 20)
        q.start("live-item", revision=2, by="medic", now=NOW + 30)
        claim = q.complete_claim(
            "live-item", revision=2, attempt_id=res["attempt_id"],
            artifact={"artifact": "live"}, by="medic", now=NOW + 40)
        q.verify("live-item", revision=2,
                 artifact_sha256=claim["artifact_sha256"],
                 criteria="synthetic", verifier="rivet",
                 passed=True, now=NOW + 50)
        q.accept("live-item", revision=2,
                 artifact_sha256=claim["artifact_sha256"],
                 criteria="synthetic", by="medic", now=NOW + 60)
        for tid in ("fx-open", "fx-done"):
            self._run_rev2_lifecycle(q, tid)
        imp.reconcile_import_continuations(q, by="medic",
                                           now=NOW + 500)
        live1 = q.get_rev("live-item", revision=1)
        self.assertEqual(live1["state"], "admitted")
        self.assertIsNone(live1["cancellation"])
        self.assertIn(
            ("live-item", 1),
            {(e["task_id"], e["revision"])
             for e in q.unresolved_revisions()})
        # Second run: retired revisions are terminal and untouched
        # (record counts stable, no duplicate link record).
        counts = {tid: len(q.get_rev(tid, revision=1)["records"])
                  for tid in ("fx-open", "fx-done")}
        outcomes = imp.reconcile_import_continuations(
            q, by="medic", now=NOW + 600)
        self.assertEqual(
            [o for o in outcomes if o["status"] == "retired"], [])
        for tid, n in counts.items():
            rev1 = q.get_rev(tid, revision=1)
            self.assertEqual(len(rev1["records"]), n, tid)
            self.assertEqual(
                len([r for r in rev1["records"]
                     if r["kind"] == "import-reconciliation"]), 1,
                tid)


class TestRollbackManifestCompleteness(unittest.TestCase):
    """Residual R3: the preflight verified whatever entries a
    manifest happened to contain — a manifest listing only the v1
    queue baseline (both Tower members omitted) passed, an empty
    manifest passed, and the manifest's own integrity was unpinned.
    The manifest is now verified as the COMPLETE expected restore
    set, cross-pinned against MANIFEST.json, before any write."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cq-manifest-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.store = os.path.join(self.tmp, "r3-v2.json")
        self.q = CrewQueue(self.store)
        self.q.admit("r3-item", 1, {"task": "synthetic r3"},
                     route="test", owner="medic", now=T0,
                     completion_deadline_ts=T0 + 3600)

        def bad_sender(nid, dest, payload):
            raise RuntimeError("destination down (r3 drill)")

        self.nid = self.q.notify(
            "board:r3", {"msg": "synthetic"}, sender=bad_sender,
            kind="manual", task_id="r3-item", revision=1,
            now=T0 + 1)["notification_id"]

    def _baseline(self, listed=EXPECTED_RESTORE_MEMBERS,
                  pin_listed=None, with_pin=True, manifest_text=None,
                  pin_hash_override=None):
        bdir = os.path.join(self.tmp, "baseline-r3")
        os.makedirs(bdir, exist_ok=True)
        contents = {name: "synthetic baseline member %s\n" % name
                    for name in EXPECTED_RESTORE_MEMBERS}
        contents["extra-member.txt"] = "synthetic extra member\n"
        digests = {}
        for name, content in contents.items():
            with open(os.path.join(bdir, name), "w",
                      encoding="utf-8") as fh:
                fh.write(content)
            digests[name] = hashlib.sha256(
                content.encode()).hexdigest()
        if manifest_text is None:
            manifest_text = "".join(
                "%s  %s\n" % (digests[n], n) for n in listed)
        with open(os.path.join(bdir, "MANIFEST.sha256"), "w",
                  encoding="utf-8") as fh:
            fh.write(manifest_text)
        if with_pin:
            pin_names = listed if pin_listed is None else pin_listed
            override = pin_hash_override or {}
            pin = {"files": [
                {"copy": n,
                 "sha256": override.get(n, digests[n])}
                for n in pin_names]}
            with open(os.path.join(bdir, "MANIFEST.json"), "w",
                      encoding="utf-8") as fh:
                json.dump(pin, fh)
        return bdir

    def _assert_aborts_in_preflight(self, bdir):
        with self.assertRaises(DrillAbort) as cm:
            rollback_reconcile(
                self.q,
                destination_view=_DestinationView({self.nid}),
                baseline_dir=bdir)
        self.assertIn("preflight", str(cm.exception))
        # The abort happened before any reconcile write.
        data = _load_json(self.store)
        self.assertEqual(data["notifications"][self.nid]["state"],
                         "uncertain")

    def test_rivet_repro_only_v1_member_listed_aborts(self):
        # Her exact reproduction: manifest lists only the valid v1
        # queue baseline, omitting both Tower members. sha256sum -c
        # returns 0 on it; the old preflight returned True.
        bdir = self._baseline(
            listed=("crew-queue-v1-baseline.json",))
        self._assert_aborts_in_preflight(bdir)

    def test_each_member_omission_aborts(self):
        for omitted in EXPECTED_RESTORE_MEMBERS:
            with self.subTest(omitted=omitted):
                listed = tuple(
                    n for n in EXPECTED_RESTORE_MEMBERS
                    if n != omitted)
                bdir = self._baseline(listed=listed)
                self._assert_aborts_in_preflight(bdir)

    def test_empty_manifest_aborts(self):
        bdir = self._baseline(manifest_text="")
        self._assert_aborts_in_preflight(bdir)

    def test_missing_manifest_pin_aborts(self):
        bdir = self._baseline(with_pin=False)
        self._assert_aborts_in_preflight(bdir)

    def test_manifest_pin_conflict_aborts(self):
        bdir = self._baseline(pin_hash_override={
            "clock-tower-state-baseline.json": "0" * 64})
        self._assert_aborts_in_preflight(bdir)

    def test_extra_listed_member_aborts(self):
        bdir = self._baseline(
            listed=EXPECTED_RESTORE_MEMBERS + ("extra-member.txt",))
        self._assert_aborts_in_preflight(bdir)

    def test_duplicate_manifest_entry_aborts(self):
        lines = []
        for name in EXPECTED_RESTORE_MEMBERS:
            digest = hashlib.sha256(
                ("synthetic baseline member %s\n" % name)
                .encode()).hexdigest()
            lines.append("%s  %s\n" % (digest, name))
        lines.append(lines[0])  # same member listed twice
        bdir = self._baseline(manifest_text="".join(lines))
        self._assert_aborts_in_preflight(bdir)


if __name__ == "__main__":
    unittest.main()
