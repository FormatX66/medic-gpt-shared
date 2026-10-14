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
from crew_queue_v2 import CrewQueue, payload_sha256

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


# ---------------------------------------------------------------- drill

class _DestinationView:
    """Fake destination: has seen exactly the given notification ids."""

    def __init__(self, seen):
        self._seen = set(seen)

    def has_seen(self, notification_id):
        return notification_id in self._seen


class DrillAbort(Exception):
    """The rollback drill fails closed: restore must not proceed."""


def rollback_reconcile(q, destination_view=None, effect_evidence=None):
    """ROLLBACK-RUNBOOK step 2, executed: surface every unresolved
    effect / cancellation / notification, reconcile each against
    destination evidence, and raise DrillAbort (fail closed) if
    anything remains unresolved. Returns the reconciliation evidence
    dict the runbook requires to be recorded BEFORE any restore."""
    effect_evidence = effect_evidence or {}
    surfaced = {"open_effects": [], "cancellations": []}
    for entry in q.unresolved_revisions():
        for eid in entry["open_effects"]:
            surfaced["open_effects"].append(
                {"task_id": entry["task_id"], "effect_id": eid})
        if entry["cancellation_requested"]:
            surfaced["cancellations"].append(
                {"task_id": entry["task_id"],
                 "revision": entry["revision"]})
    actions = q.recover_notifications(
        destination_view=destination_view)
    for a in actions:
        if a["action"].startswith("fail-closed"):
            raise DrillAbort(
                "notification %s unreconciled (%s); restore forbidden"
                % (a["notification_id"], a["action"]))
    for oe in surfaced["open_effects"]:
        if oe["effect_id"] not in effect_evidence:
            raise DrillAbort(
                "no destination evidence for effect %s; restore "
                "forbidden" % oe["effect_id"])
        q.reconcile_effect(oe["task_id"], oe["effect_id"],
                           found=bool(
                               effect_evidence[oe["effect_id"]]),
                           detail="drill: destination query by "
                                  "effect_id")
    cancel_actions = q.recover_cancellations()
    for a in cancel_actions:
        if a["action"] == "cancellation-still-pending":
            raise DrillAbort(
                "cancellation for %s still pending (open effects %s); "
                "restore forbidden"
                % (a["task_id"], a["open_effects"]))
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


if __name__ == "__main__":
    unittest.main()
