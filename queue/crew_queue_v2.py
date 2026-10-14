#!/usr/bin/env python3
"""Crew Queue v2 — implementation of crew-queue-v2-SPEC.md rev 3.

Spec: ~/workspace/goals/medic-gpt-automated-loop/files/crew-queue-v2-SPEC.md
Spec sha256: c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3
Spec commit (shared repo medic-gpt-shared): 2ec524e3dd50d5949beff83630d28632af68094a

Single-file, stdlib-only, file-backed (JSON) store implementing:
  - stable IDs (task_id / revision / attempt_id / effect_id) + payload
    sha256 binding on every record (spec section 1);
  - the section 2 state vocabulary;
  - four separated evidence classes: delivery / admission / pickup /
    execution-start (section 3) — delivery alone never admits work (A1);
  - atomic, deduplicated admission across routes on
    (task_id, revision, payload sha256), with a differing payload hash for
    an existing (task_id, revision) REJECTED as a conflict (section 4);
  - admission-uncertain semantics: ownership retained by the attempter,
    receiver-side absence never permits replay (section 4, A7/A15);
  - one executable task per item with pickup/completion CHECK-ONLY events
    (section 5, A4);
  - escalate-once per (task_id, revision, deadline, material epoch), with
    re-arm only on a material item-bound change (section 6, A5/A13);
  - durable notification intent + stable notification_id + destination
    deduplication + query-before-resend reconciliation (section 7,
    A11/A12);
  - approval holds with a named release authority and a persisted next-due
    condition; elapsed time never converts into approval (section 8, A14);
  - blocked items retaining their original deadline, with a separate
    blocker-check cadence (section 9, A8);
  - two-phase cancellation: requested stops dispatch immediately,
    confirmed only when in-flight/uncertain effects resolve (section 10,
    A6/A15);
  - completion by completion claim, and verified-accepted as TWO separate
    records — passed verification evidence + explicit acceptance act by
    the named acceptance authority, both hash-bound (section 11, A3).

No network calls. No credentials. This module is ADDITIVE: it is not wired
into the live Clock Tower Agent or the live crew-queue.json store. See
ACTIVATION-PLAN-crew-queue-v2.md.

Concurrency: every public mutating method runs its whole read-modify-write
under an exclusive flock on "<store>.lock", reloading from disk inside the
lock, and persists via tmp-file + fsync + os.replace + dir fsync. That is
what makes admission exactly-once (A9) and escalation exactly-once (A13)
across concurrent watchers.
"""

import argparse
import copy
import fcntl
import hashlib
import json
import os
import sys
import time
import uuid

SPEC_SHA256 = "c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3"

STATES = (
    "captured", "eligible", "assigned", "admission-uncertain", "admitted",
    "started", "reported-complete", "verified-accepted", "blocked",
    "cancellation-requested", "canceled",
)
TERMINAL_STATES = ("verified-accepted", "canceled")


# ---------------------------------------------------------------- errors

class CrewQueueError(Exception):
    """Base class for all crew-queue errors."""


class PayloadConflict(CrewQueueError):
    """A different payload hash arrived for an existing (task_id, revision)."""


class StaleRevision(CrewQueueError):
    """Admission attempted for a revision older than the current revision."""


class InvalidTransition(CrewQueueError):
    """The requested transition is not legal from the item's current state."""


class ReplayForbidden(CrewQueueError):
    """Replay of an uncertain (or already resolved) effect was attempted."""


class AuthorityError(CrewQueueError):
    """The actor is not the named authority for this act."""


class MissingVerification(CrewQueueError):
    """Acceptance was attempted without prior passed verification evidence."""


# ---------------------------------------------------------------- helpers

def canonical_bytes(payload):
    """Canonical byte form of a payload for hashing: dicts are JSON with
    sorted keys and compact separators; str is UTF-8; bytes pass through."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def payload_sha256(payload):
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _now(now):
    return int(time.time()) if now is None else int(now)


def _attempt_id(task_id, revision, n):
    return "%s/r%d/a%d" % (task_id, revision, n)


def _notification_id(destination, kind, task_id, revision, deadline_kind,
                     deadline_ts, material_epoch):
    seed = "|".join(str(x) for x in (destination, kind, task_id, revision,
                                     deadline_kind, deadline_ts,
                                     material_epoch))
    return "ntf-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


class _OutboxView:
    """Default destination view over the store's own outbox (offline
    destination used by the CLI and by escalate_check when no destination
    is injected). Dedup is by notification_id, per spec section 7."""

    def __init__(self, store_dict):
        self._store = store_dict

    def has_seen(self, notification_id):
        return notification_id in self._store.get("outbox", {})


def _outbox_sender(store_dict):
    def send(notification_id, destination, payload):
        outbox = store_dict.setdefault("outbox", {})
        if notification_id in outbox:
            return {"receipt": "duplicate-ignored", "notification_id": notification_id}
        outbox[notification_id] = {"destination": destination,
                                   "payload": payload, "ts": int(time.time())}
        return {"receipt": "outbox", "notification_id": notification_id}
    return send


# ---------------------------------------------------------------- store

class CrewQueue:
    """File-backed crew queue v2 store. All public methods reload state
    from disk inside the lock, so multiple CrewQueue instances (watchers)
    over the same path stay consistent."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.lock_path = self.path + ".lock"

    # ---- persistence plumbing

    def _empty(self):
        return {"version": 2, "spec_sha256": SPEC_SHA256,
                "created_ts": int(time.time()), "updated_ts": int(time.time()),
                "items": {}, "notifications": {}, "outbox": {},
                "deliveries": []}

    def _load_locked(self):
        if not os.path.exists(self.path):
            return self._empty()
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or "items" not in data:
                raise ValueError("bad store shape")
            return data
        except (ValueError, OSError):
            # Mirror the Tower convention: set a corrupt store aside and
            # rebuild rather than crashing the watcher.
            aside = self.path + ".corrupt-" + str(int(time.time()))
            try:
                os.replace(self.path, aside)
            except OSError:
                pass
            return self._empty()

    def _save_locked(self, st):
        st["updated_ts"] = int(time.time())
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        tmp = os.path.join(directory, ".tmp-" + uuid.uuid4().hex)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    class _Txn:
        def __init__(self, queue):
            self.queue = queue
            self.lock_fh = None
            self.st = None

        def __enter__(self):
            q = self.queue
            os.makedirs(os.path.dirname(q.path), exist_ok=True)
            self.lock_fh = open(q.lock_path, "a+")
            fcntl.flock(self.lock_fh.fileno(), fcntl.LOCK_EX)
            self.st = q._load_locked()
            return self.st

        def __exit__(self, exc_type, exc, tb):
            try:
                if exc_type is None:
                    self.queue._save_locked(self.st)
            finally:
                fcntl.flock(self.lock_fh.fileno(), fcntl.LOCK_UN)
                self.lock_fh.close()
            return False

    def _txn(self):
        return CrewQueue._Txn(self)

    # ---- record helpers (operate on a loaded store dict)

    @staticmethod
    def _record(rev, kind, ts, **fields):
        rec = {"kind": kind, "ts": ts, "task_id": rev["task_id"],
               "revision": rev["revision"]}
        rec.update(fields)
        rev["records"].append(rec)
        return rec

    @staticmethod
    def _get_rev(st, task_id, revision):
        item = st["items"].get(task_id)
        if item is None:
            raise CrewQueueError("unknown task: %s" % task_id)
        rev_no = item["current_revision"] if revision is None else int(revision)
        rev = item["revisions"].get(str(rev_no))
        if rev is None:
            raise CrewQueueError("unknown revision %s for task %s"
                                 % (rev_no, task_id))
        return item, rev

    @staticmethod
    def _new_rev(task_id, revision, sha, owner, requester, authority, ts):
        return {
            "task_id": task_id, "revision": revision, "payload_sha256": sha,
            "state": "admitted", "owner": owner, "requester": requester,
            "acceptance_authority": authority or requester,
            "admitted_ts": ts, "material_epoch": 0,
            "attempts": [], "current_attempt_id": None,
            "records": [], "effects": [], "conflicts": [], "escalations": [],
            "deadlines": {"pickup": [], "completion": []},
            "hold": None, "blocked": None, "blocked_from_state": None,
            "completion_claim": None, "verification": None,
            "acceptance": None, "cancellation": None,
            "alerts_suppressed": False,
        }

    def _admit_locked(self, st, task_id, revision, payload, route, owner,
                      requester, authority, ts, pickup_deadline_ts,
                      completion_deadline_ts):
        sha = payload_sha256(payload)
        item = st["items"].get(task_id)
        if item is None:
            item = {"task_id": task_id, "created_ts": ts,
                    "current_revision": revision, "revisions": {}}
            st["items"][task_id] = item
        current = item["current_revision"]
        if revision < current:
            raise StaleRevision(
                "task %s is at revision %d; admission for revision %d is stale"
                % (task_id, current, revision))
        existing = item["revisions"].get(str(revision))
        if existing is not None:
            if existing["payload_sha256"] != sha:
                # Section 4: a DIFFERENT payload hash for an existing
                # (task_id, revision) is a REJECTED CONFLICT, never a new
                # admission. The admission stands; the conflict is recorded.
                conflict = {"ts": ts, "route": route, "by": owner,
                            "existing_sha256": existing["payload_sha256"],
                            "rejected_sha256": sha}
                existing["conflicts"].append(conflict)
                self._record(existing, "conflict-rejected", ts,
                             route=route, rejected_sha256=sha,
                             payload_sha256=existing["payload_sha256"])
                # Returned, not raised, so the transaction commits the
                # recorded conflict; the public caller raises PayloadConflict
                # after commit.
                return {"status": "conflict", "task_id": task_id,
                        "revision": revision,
                        "existing_sha256": existing["payload_sha256"],
                        "rejected_sha256": sha}
            # Dedup: same (task_id, revision, payload sha256) via any route
            # collapses to the one admission. No second attempt is minted.
            self._record(existing, "duplicate-delivery", ts, route=route,
                         payload_sha256=sha,
                         attempt_id=existing["current_attempt_id"])
            return {"status": "existing", "task_id": task_id,
                    "revision": revision,
                    "attempt_id": existing["current_attempt_id"],
                    "payload_sha256": sha}
        rev = self._new_rev(task_id, revision, sha, owner,
                            requester or owner, authority, ts)
        attempt_id = _attempt_id(task_id, revision, 1)
        rev["attempts"].append({"attempt_id": attempt_id, "n": 1,
                                "state": "admitted", "started_ts": None})
        rev["current_attempt_id"] = attempt_id
        if pickup_deadline_ts is not None:
            rev["deadlines"]["pickup"].append(
                {"ts": int(pickup_deadline_ts), "reason": None,
                 "original": True})
        if completion_deadline_ts is not None:
            rev["deadlines"]["completion"].append(
                {"ts": int(completion_deadline_ts), "reason": None,
                 "original": True})
        item["revisions"][str(revision)] = rev
        item["current_revision"] = revision
        self._record(rev, "admission", ts, route=route, owner=owner,
                     attempt_id=attempt_id, payload_sha256=sha)
        return {"status": "admitted", "task_id": task_id,
                "revision": revision, "attempt_id": attempt_id,
                "payload_sha256": sha}

    # ---- delivery evidence (section 3: delivery is NOT admission)

    def record_delivery(self, task_id, revision, payload, receipt, route,
                        now=None):
        """Record DELIVERY evidence only. Creates no item, no owner, no
        admission, no ETA clock (A1)."""
        ts = _now(now)
        entry = {"task_id": task_id, "revision": int(revision),
                 "payload_sha256": payload_sha256(payload),
                 "receipt": receipt, "route": route, "ts": ts}
        with self._txn() as st:
            st["deliveries"].append(entry)
        return entry

    def deliveries(self):
        with self._txn() as st:
            return copy.deepcopy(st["deliveries"])

    # ---- admission (section 4)

    def admit(self, task_id, revision, payload, route, owner, requester=None,
              acceptance_authority=None, now=None, pickup_deadline_ts=None,
              completion_deadline_ts=None):
        ts = _now(now)
        with self._txn() as st:
            result = self._admit_locked(
                st, task_id, int(revision), payload, route, owner, requester,
                acceptance_authority, ts, pickup_deadline_ts,
                completion_deadline_ts)
        if result["status"] == "conflict":
            raise PayloadConflict(
                "payload conflict for %s revision %d: existing %s, "
                "rejected %s (resolution requires a new revision)"
                % (task_id, revision, result["existing_sha256"],
                   result["rejected_sha256"]))
        return result

    def admit_with_effect(self, task_id, revision, payload, route, owner,
                          attempter, effect_fn, effect_id=None, now=None,
                          pickup_deadline_ts=None,
                          completion_deadline_ts=None):
        """Admission whose externally visible effect may time out after it
        has taken effect (section 4). Intent is persisted FIRST with the
        item in admission-uncertain and the effect owned by the attempter;
        only a clean effect_fn return finalizes the admission. A timeout
        leaves ownership with the attempter and never permits replay."""
        ts = _now(now)
        effect_id = effect_id or ("eff-" + uuid.uuid4().hex[:16])
        with self._txn() as st:
            sha = payload_sha256(payload)
            item = st["items"].get(task_id)
            if item is not None and str(revision) in item["revisions"]:
                raise CrewQueueError(
                    "admit_with_effect requires a fresh (task_id, revision); "
                    "%s revision %s already exists" % (task_id, revision))
            if item is None:
                item = {"task_id": task_id, "created_ts": ts,
                        "current_revision": int(revision), "revisions": {}}
                st["items"][task_id] = item
            if int(revision) < item["current_revision"]:
                raise StaleRevision("stale revision for %s" % task_id)
            rev = self._new_rev(task_id, int(revision), sha, owner, owner,
                                None, ts)
            rev["state"] = "admission-uncertain"
            attempt_id = _attempt_id(task_id, int(revision), 1)
            rev["attempts"].append({"attempt_id": attempt_id, "n": 1,
                                    "state": "admission-uncertain",
                                    "started_ts": None})
            rev["current_attempt_id"] = attempt_id
            if pickup_deadline_ts is not None:
                rev["deadlines"]["pickup"].append(
                    {"ts": int(pickup_deadline_ts), "reason": None,
                     "original": True})
            if completion_deadline_ts is not None:
                rev["deadlines"]["completion"].append(
                    {"ts": int(completion_deadline_ts), "reason": None,
                     "original": True})
            rev["effects"].append(
                {"effect_id": effect_id, "attempt_id": attempt_id,
                 "state": "pending", "owner": attempter, "ts": ts})
            item["revisions"][str(revision)] = rev
            item["current_revision"] = int(revision)
            self._record(rev, "admission-intent", ts, route=route,
                         owner=owner, attempt_id=attempt_id,
                         effect_id=effect_id, payload_sha256=sha)
        try:
            effect_fn(effect_id)
        except Exception as exc:  # timeout or any post-effect failure
            with self._txn() as st:
                _, rev = self._get_rev(st, task_id, revision)
                eff = self._find_effect(rev, effect_id)
                eff["state"] = "uncertain"
                eff["error"] = type(exc).__name__
                self._record(rev, "effect-uncertain", ts,
                             effect_id=effect_id, attempt_id=rev[
                                 "current_attempt_id"],
                             payload_sha256=rev["payload_sha256"],
                             owner=attempter)
            return {"status": "admission-uncertain", "task_id": task_id,
                    "revision": int(revision), "effect_id": effect_id,
                    "attempt_id": rev["current_attempt_id"]}
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            eff = self._find_effect(rev, effect_id)
            eff["state"] = "dispatched"
            rev["state"] = "admitted"
            rev["attempts"][-1]["state"] = "admitted"
            self._record(rev, "admission", ts, route=route, owner=owner,
                         attempt_id=rev["current_attempt_id"],
                         effect_id=effect_id,
                         payload_sha256=rev["payload_sha256"])
            attempt_id = rev["current_attempt_id"]
        return {"status": "admitted", "task_id": task_id,
                "revision": int(revision), "effect_id": effect_id,
                "attempt_id": attempt_id}

    # ---- effects and reconciliation (sections 4, 10)

    @staticmethod
    def _find_effect(rev, effect_id):
        for eff in rev["effects"]:
            if eff["effect_id"] == effect_id:
                return eff
        raise CrewQueueError("unknown effect %s on %s revision %s"
                             % (effect_id, rev["task_id"], rev["revision"]))

    def register_effect(self, task_id, revision=None, attempt_id=None,
                        effect_id=None, owner=None, uncertain=False,
                        now=None):
        ts = _now(now)
        effect_id = effect_id or ("eff-" + uuid.uuid4().hex[:16])
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            eff = {"effect_id": effect_id,
                   "attempt_id": attempt_id or rev["current_attempt_id"],
                   "state": "uncertain" if uncertain else "dispatched",
                   "owner": owner or rev["owner"], "ts": ts}
            rev["effects"].append(eff)
            self._record(rev, "effect-uncertain" if uncertain
                         else "effect-dispatched", ts, effect_id=effect_id,
                         attempt_id=eff["attempt_id"],
                         payload_sha256=rev["payload_sha256"],
                         owner=eff["owner"])
        return eff

    def reconcile_effect(self, task_id, effect_id, found, detail=None,
                         revision=None, now=None):
        """Reconcile an uncertain effect against its own record (server
        table / journal / destination query). found=True resolves it.
        found=False (receiver absence) is recorded but changes nothing:
        absence NEVER permits replay and ownership is retained (A7/A15)."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            eff = self._find_effect(rev, effect_id)
            if eff["state"] != "uncertain":
                raise InvalidTransition(
                    "effect %s is %s, not uncertain" % (effect_id,
                                                        eff["state"]))
            if found:
                eff["state"] = "resolved"
                eff["resolved_ts"] = ts
                self._record(rev, "reconciliation", ts, effect_id=effect_id,
                             outcome="found", detail=detail,
                             attempt_id=eff["attempt_id"],
                             payload_sha256=rev["payload_sha256"])
                if rev["state"] == "admission-uncertain" and not any(
                        e["state"] == "uncertain" for e in rev["effects"]):
                    rev["state"] = "admitted"
                    rev["attempts"][-1]["state"] = "admitted"
            else:
                self._record(rev, "reconciliation", ts, effect_id=effect_id,
                             outcome="absent-observed",
                             detail=detail or
                             "absence never permits replay",
                             attempt_id=eff["attempt_id"],
                             payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(eff)

    def replay_effect(self, task_id, effect_id, revision=None):
        """Guard rail: replaying an uncertain effect is forbidden, and
        replaying a resolved effect would duplicate it (section 4)."""
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            eff = self._find_effect(rev, effect_id)
            raise ReplayForbidden(
                "effect %s is %s; replay is forbidden (uncertain effects "
                "resolve by reconciliation, resolved effects must not "
                "duplicate)" % (effect_id, eff["state"]))

    # ---- pickup and execution start (section 3)

    def pickup(self, task_id, revision=None, by=None, now=None):
        """PICKUP evidence. Proves the owner saw the admission. Does NOT
        start work and does NOT change state (A3)."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["state"] != "admitted":
                raise InvalidTransition(
                    "pickup requires state admitted, not %s" % rev["state"])
            rec = self._record(rev, "pickup", ts, by=by or rev["owner"],
                               attempt_id=rev["current_attempt_id"],
                               payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rec)

    def can_dispatch(self, task_id, revision=None):
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            return rev["state"] not in (
                "cancellation-requested", "canceled", "verified-accepted")

    def start(self, task_id, revision=None, by=None, evidence=None, now=None):
        """EXECUTION-START evidence, bound to the attempt. The only record
        class that moves an item to started (section 3). Blocked by a
        cancellation request (section 10)."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["state"] == "cancellation-requested":
                raise InvalidTransition(
                    "cancellation requested: all new dispatch is stopped")
            if rev["state"] != "admitted":
                raise InvalidTransition(
                    "start requires state admitted, not %s" % rev["state"])
            attempt = rev["attempts"][-1]
            attempt["state"] = "started"
            attempt["started_ts"] = ts
            rev["state"] = "started"
            rec = self._record(rev, "execution-start", ts, by=by or rev["owner"],
                               attempt_id=attempt["attempt_id"],
                               evidence=evidence,
                               payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rec)

    # ---- notifications (section 7)

    def _notify_locked(self, st, destination, payload, sender, hooks, ts,
                       kind, task_id, revision, deadline_kind, deadline_ts,
                       material_epoch):
        nid = _notification_id(destination, kind, task_id, revision,
                               deadline_kind, deadline_ts, material_epoch)
        existing = st["notifications"].get(nid)
        if existing is not None and existing["state"] in (
                "sent", "sent-confirmed"):
            return copy.deepcopy(existing)
        if existing is None:
            existing = {"notification_id": nid, "destination": destination,
                        "kind": kind, "task_id": task_id,
                        "revision": revision, "deadline_kind": deadline_kind,
                        "deadline_ts": deadline_ts,
                        "material_epoch": material_epoch,
                        "payload": payload,
                        "payload_sha256": payload_sha256(payload),
                        "state": "intent", "created_ts": ts,
                        "updated_ts": ts, "receipt": None}
            st["notifications"][nid] = existing
            # Durable intent BEFORE any send (section 7), and before the
            # crash-injection hook fires.
            self._save_locked(st)
        if hooks and getattr(hooks, "after_intent", None):
            try:
                hooks.after_intent(copy.deepcopy(existing))
            except Exception:
                self._save_locked(st)  # leave the durable intent on disk
                raise
        if sender is None:
            sender = _outbox_sender(st)
        try:
            receipt = sender(nid, destination, payload)
        except Exception as exc:
            # Outcome uncertain: NEVER auto-resend. Reconciliation (query
            # the destination by notification_id) is the only way forward.
            existing["state"] = "uncertain"
            existing["updated_ts"] = ts
            existing["error"] = type(exc).__name__
            return copy.deepcopy(existing)
        existing["state"] = "sent"
        existing["receipt"] = receipt
        existing["updated_ts"] = ts
        return copy.deepcopy(existing)

    def notify(self, destination, payload, sender=None, hooks=None, now=None,
               kind="manual", task_id=None, revision=None, deadline_kind=None,
               deadline_ts=None, material_epoch=0):
        ts = _now(now)
        with self._txn() as st:
            return self._notify_locked(st, destination, payload, sender,
                                       hooks, ts, kind, task_id, revision,
                                       deadline_kind, deadline_ts,
                                       material_epoch)

    def recover_notifications(self, sender=None, destination_view=None,
                              now=None):
        """Crash recovery for notifications in intent/uncertain state.
        The destination is queried by notification_id BEFORE any re-send:
        seen -> sent-confirmed, no duplicate (A12); unseen -> send exactly
        once under the persisted notification_id (A11)."""
        ts = _now(now)
        actions = []
        with self._txn() as st:
            view = destination_view or _OutboxView(st)
            snd = sender or _outbox_sender(st)
            for nid, notif in sorted(st["notifications"].items()):
                if notif["state"] not in ("intent", "uncertain"):
                    continue
                if view.has_seen(nid):
                    notif["state"] = "sent-confirmed"
                    notif["updated_ts"] = ts
                    actions.append({"notification_id": nid,
                                    "action": "confirmed-at-destination",
                                    "resent": False})
                    continue
                try:
                    receipt = snd(nid, notif["destination"],
                                  notif["payload"])
                except Exception as exc:
                    notif["state"] = "uncertain"
                    notif["error"] = type(exc).__name__
                    actions.append({"notification_id": nid,
                                    "action": "still-uncertain",
                                    "resent": False})
                    continue
                notif["state"] = "sent"
                notif["receipt"] = receipt
                notif["updated_ts"] = ts
                actions.append({"notification_id": nid,
                                "action": "sent-on-recovery",
                                "resent": True})
        return actions

    # ---- ETA evaluation: checks, escalation, blocker cadence (5, 6, 9)

    def escalate_check(self, now=None, sender=None, destination_view=None):
        """Evaluate pickup/completion CHECK events for every item. Checks
        are check-only: evaluating them never mints attempts or executes
        work (A4). A missed check escalates exactly once per (task_id,
        revision, deadline, material epoch) via the section 7 machinery.
        Holds suppress alerts (section 8). Blocked items get blocker-check
        events on their own cadence and NO ETA escalation (section 9)."""
        ts = _now(now)
        actions = []
        with self._txn() as st:
            for task_id in sorted(st["items"]):
                item = st["items"][task_id]
                rev = item["revisions"][str(item["current_revision"])]
                state = rev["state"]
                if state in TERMINAL_STATES or \
                        state == "cancellation-requested":
                    continue
                if state == "blocked":
                    blk = rev["blocked"]
                    while blk and ts >= blk["next_check_ts"]:
                        blk["checks"].append(blk["next_check_ts"])
                        blk["next_check_ts"] += blk["interval_s"]
                        self._record(rev, "blocker-check", ts,
                                     payload_sha256=rev["payload_sha256"])
                        actions.append({"task_id": task_id,
                                        "action": "blocker-check"})
                    continue
                if rev["hold"] is not None:
                    continue  # alerts suppressed; time alone changes nothing
                for kind in ("pickup", "completion"):
                    entries = rev["deadlines"][kind]
                    if not entries:
                        continue
                    due = entries[-1]["ts"]
                    if ts <= due:
                        continue
                    if kind == "pickup":
                        if state != "admitted":
                            continue
                        if any(r["kind"] == "pickup" for r in rev["records"]):
                            continue
                    if kind == "completion":
                        if state not in ("admitted", "started"):
                            continue
                        if rev["completion_claim"] is not None:
                            continue
                    key = (task_id, rev["revision"], kind, due,
                           rev["material_epoch"])
                    if any(tuple(e["key"]) == key
                           for e in rev["escalations"]):
                        continue  # escalated once for this key already
                    destination = "owner:%s" % rev["owner"]
                    payload = {"kind": "eta-escalation", "task_id": task_id,
                               "revision": rev["revision"],
                               "check": kind, "deadline_ts": due,
                               "attempt_id": rev["current_attempt_id"]}
                    notif = self._notify_locked(
                        st, destination, payload, sender, None, ts,
                        "eta-escalation", task_id, rev["revision"], kind,
                        due, rev["material_epoch"])
                    rev["escalations"].append(
                        {"key": list(key),
                         "notification_id": notif["notification_id"],
                         "ts": ts})
                    rev["alerts_suppressed"] = True
                    self._record(rev, "escalation", ts, check=kind,
                                 deadline_ts=due,
                                 notification_id=notif["notification_id"],
                                 attempt_id=rev["current_attempt_id"],
                                 payload_sha256=rev["payload_sha256"])
                    actions.append({"task_id": task_id,
                                    "action": "escalated", "check": kind,
                                    "notification_id":
                                        notif["notification_id"]})
        return actions

    # ---- material changes (re-arm, section 6) and deadlines (section 5)

    def set_owner(self, task_id, revision=None, new_owner=None, reason=None,
                  now=None):
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            old = rev["owner"]
            rev["owner"] = new_owner
            rev["material_epoch"] += 1  # material change: re-arm (A5)
            self._record(rev, "owner-change", ts, old_owner=old,
                         new_owner=new_owner, reason=reason,
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rev)

    def revise_deadline(self, task_id, revision=None, kind=None, new_ts=None,
                        reason=None, now=None):
        """Revise a deadline, preserving the original with its reason
        history (section 5). A deadline revision is a material change and
        re-arms escalation for the NEW deadline (section 6)."""
        ts = _now(now)
        if kind not in ("pickup", "completion"):
            raise CrewQueueError("deadline kind must be pickup or completion")
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            rev["deadlines"][kind].append(
                {"ts": int(new_ts), "reason": reason, "original": False})
            rev["material_epoch"] += 1
            self._record(rev, "deadline-revised", ts, check=kind,
                         new_ts=int(new_ts), reason=reason,
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rev)

    # ---- holds and approvals (section 8)

    def hold(self, task_id, revision=None, condition=None,
             release_authority=None, next_due=None, now=None):
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["state"] in TERMINAL_STATES:
                raise InvalidTransition("cannot hold a terminal item")
            rev["hold"] = {"condition": condition,
                           "release_authority": release_authority,
                           "next_due": next_due, "held_ts": ts}
            self._record(rev, "hold", ts, condition=condition,
                         release_authority=release_authority,
                         next_due=next_due,
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rev["hold"])

    def release(self, task_id, revision=None, by=None, now=None):
        """Release a hold. Only the named release authority may act;
        elapsed time is never a release (A14)."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["hold"] is None:
                raise InvalidTransition("item is not held")
            if by != rev["hold"]["release_authority"]:
                raise AuthorityError(
                    "hold on %s may only be released by %s, not %s"
                    % (task_id, rev["hold"]["release_authority"], by))
            rev["hold"] = None
            self._record(rev, "release", ts, by=by,
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rev)

    # ---- blocked (section 9)

    def block(self, task_id, revision=None, reason=None, now=None,
              blocker_check_interval_s=300):
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["state"] not in ("admitted", "started"):
                raise InvalidTransition(
                    "block requires admitted or started, not %s"
                    % rev["state"])
            rev["blocked_from_state"] = rev["state"]
            rev["state"] = "blocked"
            rev["blocked"] = {"reason": reason, "since_ts": ts,
                              "interval_s": int(blocker_check_interval_s),
                              "next_check_ts": ts +
                              int(blocker_check_interval_s),
                              "checks": []}
            self._record(rev, "blocked", ts, reason=reason,
                         attempt_id=rev["current_attempt_id"],
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rev)

    def unblock(self, task_id, revision=None, now=None):
        """Clear the blocker, restoring the pre-block state. The ORIGINAL
        deadline stays on the record and alerting resumes per section 6 —
        suppressing alerts while blocked never postponed the obligation
        (A8). Unblocking is NOT a material change and does not by itself
        re-arm an already-fired escalation."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["state"] != "blocked":
                raise InvalidTransition("item is not blocked")
            rev["state"] = rev["blocked_from_state"]
            rev["blocked_from_state"] = None
            rev["blocked"] = None
            self._record(rev, "unblocked", ts,
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rev)

    # ---- cancellation (section 10)

    def cancel_request(self, task_id, revision=None, by=None, now=None):
        """Phase one: recorded immediately; stops ALL new dispatch at
        once. The item is NOT canceled yet (A6)."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["state"] in TERMINAL_STATES:
                raise InvalidTransition(
                    "cannot cancel a terminal item (%s)" % rev["state"])
            if rev["cancellation"] is not None:
                raise InvalidTransition("cancellation already requested")
            rev["cancellation"] = {"requested_ts": ts, "by": by,
                                   "confirmed_ts": None,
                                   "pre_request_state": rev["state"]}
            rev["state"] = "cancellation-requested"
            self._record(rev, "cancel-requested", ts, by=by,
                         attempt_id=rev["current_attempt_id"],
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rev)

    def cancel_confirm(self, task_id, revision=None, by=None, now=None):
        """Phase two: confirm cancellation ONLY when no in-flight or
        uncertain effects remain. With an uncertain effect the request
        stays open as a reconciliation item and ownership is retained
        in full (A6/A15)."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["cancellation"] is None:
                raise InvalidTransition("no cancellation was requested")
            if rev["state"] == "canceled":
                raise InvalidTransition("already canceled")
            open_effects = [e for e in rev["effects"]
                            if e["state"] == "uncertain"]
            if open_effects:
                self._record(rev, "reconciliation", ts,
                             outcome="cancel-confirm-blocked",
                             detail="uncertain effects unresolved: %s"
                                    % [e["effect_id"] for e in open_effects],
                             payload_sha256=rev["payload_sha256"])
                raise InvalidTransition(
                    "cannot confirm cancellation: %d uncertain effect(s) "
                    "unresolved; reconciliation and ownership retained"
                    % len(open_effects))
            rev["cancellation"]["confirmed_ts"] = ts
            rev["state"] = "canceled"
            self._record(rev, "cancel-confirmed", ts, by=by,
                         attempt_id=rev["current_attempt_id"],
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(rev)

    # ---- completion and acceptance (section 11)

    def complete_claim(self, task_id, revision=None, attempt_id=None,
                       artifact=None, by=None, now=None):
        """A COMPLETION CLAIM: an artifact bound to task_id, revision and
        attempt_id. A pickup ack or a bare work claim is never a claim
        (A3)."""
        ts = _now(now)
        art_sha = payload_sha256(artifact)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["state"] != "started":
                raise InvalidTransition(
                    "completion claim requires state started, not %s"
                    % rev["state"])
            if attempt_id != rev["current_attempt_id"]:
                raise InvalidTransition(
                    "completion claim bound to attempt %s, but the current "
                    "attempt is %s" % (attempt_id, rev["current_attempt_id"]))
            claim = {"attempt_id": attempt_id, "artifact_sha256": art_sha,
                     "by": by or rev["owner"], "ts": ts}
            rev["completion_claim"] = claim
            rev["attempts"][-1]["state"] = "reported-complete"
            rev["state"] = "reported-complete"
            self._record(rev, "completion-claim", ts, attempt_id=attempt_id,
                         artifact_sha256=art_sha,
                         payload_sha256=rev["payload_sha256"])
            return copy.deepcopy(claim)

    def verify(self, task_id, revision=None, artifact_sha256=None,
               criteria=None, verifier=None, passed=True, now=None):
        """VERIFICATION EVIDENCE: a recorded check of the artifact
        against the criteria, bound to the exact artifact and revision.
        A separate record from acceptance (section 11)."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["completion_claim"] is None:
                raise InvalidTransition(
                    "verification requires a completion claim first")
            if artifact_sha256 != rev["completion_claim"]["artifact_sha256"]:
                raise InvalidTransition(
                    "verification artifact %s does not match the completion "
                    "claim artifact %s"
                    % (artifact_sha256,
                       rev["completion_claim"]["artifact_sha256"]))
            recd = {"artifact_sha256": artifact_sha256, "criteria": criteria,
                    "verifier": verifier, "role": "verifier",
                    "passed": bool(passed), "ts": ts,
                    "attempt_id": rev["current_attempt_id"]}
            rev["verification"] = recd
            self._record(rev, "verification", ts,
                         **{k: v for k, v in recd.items() if k != "ts"})
            return copy.deepcopy(recd)

    def accept(self, task_id, revision=None, artifact_sha256=None,
               criteria=None, by=None, now=None):
        """ACCEPTANCE: an explicit act by the named acceptance authority,
        bound to the exact artifact/revision/criteria. Without a prior
        PASSED verification record there is no verified-accepted
        (section 11)."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            ver = rev["verification"]
            if ver is None or not ver["passed"]:
                raise MissingVerification(
                    "acceptance requires recorded PASSED verification "
                    "evidence first (verification and acceptance are "
                    "separate records from separate roles)")
            if artifact_sha256 != ver["artifact_sha256"]:
                raise InvalidTransition(
                    "acceptance artifact does not match the verified "
                    "artifact")
            if criteria != ver["criteria"]:
                raise InvalidTransition(
                    "acceptance criteria do not match the verified criteria")
            if by != rev["acceptance_authority"]:
                raise AuthorityError(
                    "acceptance authority for %s is %s, not %s"
                    % (task_id, rev["acceptance_authority"], by))
            recd = {"artifact_sha256": artifact_sha256, "criteria": criteria,
                    "by": by, "role": "acceptance-authority", "ts": ts,
                    "attempt_id": rev["current_attempt_id"]}
            rev["acceptance"] = recd
            rev["state"] = "verified-accepted"
            self._record(rev, "acceptance", ts,
                         **{k: v for k, v in recd.items() if k != "ts"})
            return copy.deepcopy(recd)

    # ---- read

    def get_item(self, task_id):
        with self._txn() as st:
            item = st["items"].get(task_id)
            return copy.deepcopy(item) if item is not None else None

    def get_rev(self, task_id, revision=None):
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            return copy.deepcopy(rev)


# ---------------------------------------------------------------- CLI

def _default_store_path():
    env = os.environ.get("CQ2_STORE")
    if env:
        return env
    return os.path.expanduser(
        "~/workspace/goals/medic-gpt-automated-loop/hidden_files/"
        "crew-queue-v2.json")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Crew Queue v2 (spec rev 3) — file-backed store CLI. "
                    "Additive module; not the live queue.")
    parser.add_argument("--store", default=_default_store_path())
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("admit")
    p.add_argument("--task", required=True)
    p.add_argument("--revision", type=int, required=True)
    p.add_argument("--payload", required=True)
    p.add_argument("--route", default="cli")
    p.add_argument("--owner", required=True)
    p.add_argument("--requester", default=None)
    p.add_argument("--acceptance-authority", default=None)
    p.add_argument("--pickup-deadline", type=int, default=None)
    p.add_argument("--completion-deadline", type=int, default=None)

    for name in ("pickup", "start"):
        p = sub.add_parser(name)
        p.add_argument("--task", required=True)
        p.add_argument("--revision", type=int, default=None)
        p.add_argument("--by", default=None)

    p = sub.add_parser("complete-claim")
    p.add_argument("--task", required=True)
    p.add_argument("--revision", type=int, default=None)
    p.add_argument("--attempt", required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--by", default=None)

    p = sub.add_parser("verify")
    p.add_argument("--task", required=True)
    p.add_argument("--revision", type=int, default=None)
    p.add_argument("--artifact-sha256", required=True)
    p.add_argument("--criteria", required=True)
    p.add_argument("--verifier", required=True)
    p.add_argument("--failed", action="store_true")

    p = sub.add_parser("accept")
    p.add_argument("--task", required=True)
    p.add_argument("--revision", type=int, default=None)
    p.add_argument("--artifact-sha256", required=True)
    p.add_argument("--criteria", required=True)
    p.add_argument("--by", required=True)

    p = sub.add_parser("block")
    p.add_argument("--task", required=True)
    p.add_argument("--revision", type=int, default=None)
    p.add_argument("--reason", required=True)
    p.add_argument("--blocker-check-interval", type=int, default=300)

    p = sub.add_parser("hold")
    p.add_argument("--task", required=True)
    p.add_argument("--revision", type=int, default=None)
    p.add_argument("--condition", required=True)
    p.add_argument("--release-authority", required=True)
    p.add_argument("--next-due", required=True)

    p = sub.add_parser("release")
    p.add_argument("--task", required=True)
    p.add_argument("--revision", type=int, default=None)
    p.add_argument("--by", required=True)

    for name in ("cancel-request", "cancel-confirm"):
        p = sub.add_parser(name)
        p.add_argument("--task", required=True)
        p.add_argument("--revision", type=int, default=None)
        p.add_argument("--by", default=None)

    sub.add_parser("escalate-check")
    sub.add_parser("recover-notifications")

    p = sub.add_parser("show")
    p.add_argument("--task", required=True)

    args = parser.parse_args(argv)
    q = CrewQueue(args.store)
    try:
        if args.cmd == "admit":
            out = q.admit(args.task, args.revision, args.payload, args.route,
                          args.owner, requester=args.requester,
                          acceptance_authority=args.acceptance_authority,
                          pickup_deadline_ts=args.pickup_deadline,
                          completion_deadline_ts=args.completion_deadline)
        elif args.cmd == "pickup":
            out = q.pickup(args.task, args.revision, by=args.by)
        elif args.cmd == "start":
            out = q.start(args.task, args.revision, by=args.by)
        elif args.cmd == "complete-claim":
            out = q.complete_claim(args.task, args.revision,
                                   attempt_id=args.attempt,
                                   artifact=args.artifact, by=args.by)
        elif args.cmd == "verify":
            out = q.verify(args.task, args.revision,
                           artifact_sha256=args.artifact_sha256,
                           criteria=args.criteria, verifier=args.verifier,
                           passed=not args.failed)
        elif args.cmd == "accept":
            out = q.accept(args.task, args.revision,
                           artifact_sha256=args.artifact_sha256,
                           criteria=args.criteria, by=args.by)
        elif args.cmd == "block":
            out = q.block(args.task, args.revision, reason=args.reason,
                          blocker_check_interval_s=args.blocker_check_interval)
        elif args.cmd == "hold":
            out = q.hold(args.task, args.revision, condition=args.condition,
                         release_authority=args.release_authority,
                         next_due=args.next_due)
        elif args.cmd == "release":
            out = q.release(args.task, args.revision, by=args.by)
        elif args.cmd == "cancel-request":
            out = q.cancel_request(args.task, args.revision, by=args.by)
        elif args.cmd == "cancel-confirm":
            out = q.cancel_confirm(args.task, args.revision, by=args.by)
        elif args.cmd == "escalate-check":
            out = q.escalate_check()
        elif args.cmd == "recover-notifications":
            out = q.recover_notifications()
        elif args.cmd == "show":
            out = q.get_item(args.task)
        else:  # pragma: no cover
            parser.error("unknown command")
    except CrewQueueError as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "message": str(exc)}))
        return 2
    print(json.dumps({"ok": True, "result": out}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
