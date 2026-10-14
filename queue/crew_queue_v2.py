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

Fix pass 2026-10-14 (Rivet implementation review
rivet-crewqueue-impl-review-20261014-1732-v1, six blocking fixes):
  1. Dispatch/start reject held, blocked, and admission-uncertain items
     (section 8 hold semantics enforced at the dispatch gate, not only
     in the watcher).
  2. Cancellation confirmation reconciles pending AND dispatched effects
     (not only uncertain ones); terminal states are preserved against
     late cancellation callbacks; recover_cancellations() completes
     crash-left pending cancellations once their effects resolve.
  3. Repeat notify() reconciles against the destination (query by
     notification_id) BEFORE any re-send, exactly like crash recovery;
     escalate_check passes its destination view through.
  4. A corrupt or unreadable store FAILS CLOSED (StoreCorrupt); it is
     never silently replaced with an empty ledger.
  5. The watcher view (escalate_check, unresolved_revisions) covers ALL
     unresolved revisions of an item, not only the current revision.
  6. Admission requires at least one deadline (pickup or completion);
     the blocker-check cadence is validated positive and defaults to the
     queue's configured cadence, not an unqualified literal.

Round-2 fix pass 2026-10-14 (Rivet re-review
rivet-crew-rereview-verdict-20261014-2002-v1; round-1 fixes 1 and 4
were accepted as addressed and are NOT disturbed here):
  2. A clean admission-effect callback no longer overwrites a
     cancellation that was requested while the effect was in flight;
     recover_cancellations keys off the cancellation record, not only
     the state string; reconcile_effect authoritatively reconciles ALL
     unresolved effect states (pending, dispatched, uncertain) — the
     states cancellation confirmation waits on.
  3. An unresolved EXTERNAL notification fails closed without the
     matching destination query, in repeat notify() and in
     recover_notifications alike; the local outbox view/sender is valid
     only for notifications actually delivered via the local outbox.
  5. Cross-revision ownership fencing: while any revision of a task
     owns unresolved execution (started, admission-uncertain, or
     blocked-from-started), no other revision may be admitted, take an
     effect, or start (OwnershipFenced).
  6. The blocker-check default is the target lane cadence (60 s),
     replacing the unqualified 300 s literal. This corrects the module
     default only; it changes no platform observation schedule.
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


class OwnershipFenced(CrewQueueError):
    """A second admission, admission-with-effect, or execution start was
    attempted for a task while another revision's ownership is
    unresolved (started or admission-uncertain). Cross-revision
    fencing, round-2 fix 5."""


class ReplayForbidden(CrewQueueError):
    """Replay of an uncertain (or already resolved) effect was attempted."""


class AuthorityError(CrewQueueError):
    """The actor is not the named authority for this act."""


class MissingVerification(CrewQueueError):
    """Acceptance was attempted without prior passed verification evidence."""


class StoreCorrupt(CrewQueueError):
    """The on-disk store exists but cannot be read or parsed. Raised
    instead of ever substituting an empty ledger (fail closed)."""


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

# Section 9 blocker-check cadence: the target lane cadence — blocker
# checks ride the crew queue's normal watch cycle, 60 seconds.
# DEFAULT_BLOCKER_CHECK_INTERVAL_S is that cadence, used only when
# neither the CrewQueue instance nor the block() call configures one.
# (Round-2 fix 6: the previous unqualified 300 s default did not match
# the target lane.)
QUEUE_LANE_CADENCE_S = 60
DEFAULT_BLOCKER_CHECK_INTERVAL_S = QUEUE_LANE_CADENCE_S


class CrewQueue:
    """File-backed crew queue v2 store. All public methods reload state
    from disk inside the lock, so multiple CrewQueue instances (watchers)
    over the same path stay consistent."""

    def __init__(self, path, blocker_check_interval_s=None):
        self.path = os.path.abspath(path)
        self.lock_path = self.path + ".lock"
        # The queue's configured blocker-check cadence (fix 6): block()
        # calls without an explicit interval honor this, and it in turn
        # defaults to DEFAULT_BLOCKER_CHECK_INTERVAL_S.
        if blocker_check_interval_s is None:
            blocker_check_interval_s = DEFAULT_BLOCKER_CHECK_INTERVAL_S
        self.blocker_check_interval_s = self._validate_interval(
            blocker_check_interval_s, "queue blocker_check_interval_s")

    @staticmethod
    def _validate_interval(value, what):
        if isinstance(value, bool):
            raise CrewQueueError(
                "%s must be a positive integer number of seconds, got %r"
                % (what, value))
        try:
            interval = int(value)
        except (TypeError, ValueError):
            raise CrewQueueError(
                "%s must be a positive integer number of seconds, got %r"
                % (what, value))
        if interval <= 0:
            raise CrewQueueError(
                "%s must be positive, got %r" % (what, value))
        return interval

    # ---- persistence plumbing

    def _empty(self):
        return {"version": 2, "spec_sha256": SPEC_SHA256,
                "created_ts": int(time.time()), "updated_ts": int(time.time()),
                "items": {}, "notifications": {}, "outbox": {},
                "deliveries": []}

    def _load_locked(self):
        if not os.path.exists(self.path):
            return self._empty()
        # FAIL CLOSED (fix 4): a store that exists but cannot be read,
        # parsed, or recognized is a hard error. Returning an empty
        # ledger here would silently erase every admission, escalation,
        # and reconciliation record the queue is the evidence for.
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError) as exc:
            raise StoreCorrupt(
                "crew queue store at %s is unreadable (%s); refusing to "
                "substitute an empty ledger" % (self.path,
                                                 type(exc).__name__))
        if not isinstance(data, dict) or "items" not in data:
            raise StoreCorrupt(
                "crew queue store at %s has an unrecognized shape; "
                "refusing to substitute an empty ledger" % self.path)
        return data

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
            try:
                self.st = q._load_locked()
            except Exception:
                # Fail closed WITHOUT leaking the lock: a corrupt store
                # must not wedge every later caller behind a dead flock.
                fcntl.flock(self.lock_fh.fileno(), fcntl.LOCK_UN)
                self.lock_fh.close()
                self.lock_fh = None
                raise
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

    @staticmethod
    def _require_deadline(task_id, revision, pickup_deadline_ts,
                          completion_deadline_ts):
        # Fix 6 / section 3: ADMISSION evidence is a queue record naming
        # task_id, revision, owner, AND a deadline. An admission with no
        # deadline of either kind has no ETA clock and can never be
        # checked, so it is refused at creation.
        if pickup_deadline_ts is None and completion_deadline_ts is None:
            raise CrewQueueError(
                "admission of %s revision %s requires at least one "
                "deadline (pickup_deadline_ts or completion_deadline_ts)"
                % (task_id, revision))

    # Round-2 fix 5 (cross-revision ownership fencing): a revision OWNS
    # unresolved execution while it is started, admission-uncertain, or
    # blocked from started (started work that is paused still owns its
    # execution). While any revision of a task owns execution, no OTHER
    # revision may be admitted, take an effect, or start: exactly one
    # executing ownership per task, until that ownership is safely
    # resolved (a terminal state). Round-3 (verdict 2022, residual 1)
    # extends the fence in _ownership_fence: open effects and an
    # unconfirmed cancellation also retain ownership, covering the
    # cancellation interval the state strings alone miss.
    @staticmethod
    def _owning_state(rev):
        if rev["state"] in ("started", "admission-uncertain"):
            return rev["state"]
        if rev["state"] == "blocked" and \
                rev["blocked_from_state"] == "started":
            return "blocked-from-started"
        return None

    def _ownership_fence(self, item, revision):
        """Why `revision` of this item is fenced by another revision's
        unresolved ownership, or None when every other revision is
        safely resolved."""
        for key in sorted(item["revisions"], key=int):
            other = item["revisions"][key]
            if other["revision"] == revision:
                continue
            owning = self._owning_state(other)
            if owning is None:
                # Round-3 (verdict 2022, residual 1): ownership also
                # persists through the CANCELLATION INTERVAL. The
                # state-based check above goes blind there:
                # cancel_request rewrites the state string to
                # cancellation-requested WITHOUT resolving the
                # revision's effects, so a timed-out admission effect
                # stopped fencing at exactly the moment the earlier
                # work was least resolved, and a later revision could
                # invoke a second effect. Fencing is retained while
                # another revision holds open (pending/dispatched/
                # uncertain) effects, or while a cancellation of that
                # work remains unconfirmed.
                if self._open_effects(other):
                    owning = "open-effects"
                elif other["cancellation"] is not None and \
                        other["cancellation"].get("confirmed_ts") \
                        is None:
                    owning = "cancellation-unresolved"
            if owning is not None:
                return ("task %s revision %d is %s; revision %d may "
                        "not be admitted, take an effect, or start "
                        "until that ownership is safely resolved"
                        % (item["task_id"], other["revision"], owning,
                           revision))
        return None

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
        self._require_deadline(task_id, revision, pickup_deadline_ts,
                               completion_deadline_ts)
        fence = self._ownership_fence(item, revision)
        if fence is not None:
            raise OwnershipFenced(fence)
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

    @staticmethod
    def _preserved_callback_status(rev):
        """The status of record after a late admission callback whose
        effect was authoritatively resolved during the callback window
        (round-3 residual 2): a terminal state stands exactly as it is;
        a still-unconfirmed cancellation reports
        cancellation-requested; otherwise the revision's current state
        is the truth (reconciliation already promoted it, e.g. to
        admitted). The callback's own outcome never rewrites it."""
        if rev["state"] in TERMINAL_STATES:
            return rev["state"]
        if rev["cancellation"] is not None:
            return "cancellation-requested"
        return rev["state"]

    def admit_with_effect(self, task_id, revision, payload, route, owner,
                          attempter, effect_fn, effect_id=None, now=None,
                          pickup_deadline_ts=None,
                          completion_deadline_ts=None):
        """Admission whose externally visible effect may time out after it
        has taken effect (section 4). Intent is persisted FIRST with the
        item in admission-uncertain and the effect owned by the attempter;
        only a clean effect_fn return finalizes the admission. A timeout
        leaves ownership with the attempter and never permits replay.
        If the effect is authoritatively resolved while the callback is
        still outstanding (round-3 residual 2), the late callback —
        clean or failed — preserves that resolution and any terminal
        state the item has since reached."""
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
            self._require_deadline(task_id, int(revision),
                                   pickup_deadline_ts,
                                   completion_deadline_ts)
            fence = self._ownership_fence(item, int(revision))
            if fence is not None:
                raise OwnershipFenced(fence)
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
                if eff["state"] == "resolved":
                    # Round-3 (verdict 2022, residual 2): while this
                    # callback was outstanding, the effect was
                    # AUTHORITATIVELY resolved against destination
                    # evidence — and any cancellation on the item may
                    # since have been confirmed to its terminal state.
                    # The late failure must not reopen the ledger by
                    # overwriting resolved with uncertain, nor disturb
                    # that terminal state. The callback outcome is
                    # recorded as evidence only; the state of record
                    # stands, and is also the returned status.
                    self._record(rev, "effect-callback", ts,
                                 outcome="error-after-resolution",
                                 error=type(exc).__name__,
                                 effect_id=effect_id,
                                 attempt_id=rev["current_attempt_id"],
                                 payload_sha256=rev["payload_sha256"],
                                 owner=attempter)
                    status = self._preserved_callback_status(rev)
                else:
                    eff["state"] = "uncertain"
                    eff["error"] = type(exc).__name__
                    self._record(rev, "effect-uncertain", ts,
                                 effect_id=effect_id, attempt_id=rev[
                                     "current_attempt_id"],
                                 payload_sha256=rev["payload_sha256"],
                                 owner=attempter)
                    status = "admission-uncertain"
            return {"status": status, "task_id": task_id,
                    "revision": int(revision), "effect_id": effect_id,
                    "attempt_id": rev["current_attempt_id"]}
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            eff = self._find_effect(rev, effect_id)
            attempt_id = rev["current_attempt_id"]
            if eff["state"] == "resolved":
                # Round-3 (verdict 2022, residual 2): the clean
                # callback lands AFTER an authoritative resolution of
                # its effect (and possibly a confirmed cancellation).
                # It finalizes NOTHING: overwriting resolved with
                # dispatched would reopen the ledger under a terminal
                # item, where cancellation recovery no longer looks.
                # Preserve the resolution and the revision's state —
                # terminal states included — record the callback as
                # evidence, and report the state of record.
                self._record(rev, "effect-callback", ts,
                             outcome="success-after-resolution",
                             effect_id=effect_id, attempt_id=attempt_id,
                             payload_sha256=rev["payload_sha256"],
                             owner=owner, route=route)
                status = self._preserved_callback_status(rev)
            elif rev["cancellation"] is not None:
                eff["state"] = "dispatched"
                # Round-2 fix 2: a cancellation requested while the
                # effect was in flight (the callback runs outside the
                # store lock, so a cancel_request can land in that
                # window) is AUTHORITATIVE. The clean callback
                # finalizes the EFFECT evidence (dispatched) only —
                # it must not overwrite cancellation-requested with
                # admitted. The round-1 overwrite left the cancellation
                # recorded but in state "admitted", where
                # recover_cancellations never looked. The cancellation
                # now waits on this dispatched effect until it is
                # reconciled, exactly like any in-flight effect
                # (section 10).
                self._record(rev, "admission", ts, route=route,
                             owner=owner, attempt_id=attempt_id,
                             effect_id=effect_id,
                             payload_sha256=rev["payload_sha256"],
                             cancellation_pending=True)
                status = "cancellation-requested"
            else:
                eff["state"] = "dispatched"
                rev["state"] = "admitted"
                rev["attempts"][-1]["state"] = "admitted"
                self._record(rev, "admission", ts, route=route,
                             owner=owner, attempt_id=attempt_id,
                             effect_id=effect_id,
                             payload_sha256=rev["payload_sha256"])
                status = "admitted"
        return {"status": status, "task_id": task_id,
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
        """Reconcile an unresolved effect against its own record (server
        table / journal / destination query). found=True resolves it.
        found=False (receiver absence) is recorded but changes nothing:
        absence NEVER permits replay and ownership is retained (A7/A15).
        Round-2 fix 2: ALL unresolved effect states are reconcilable
        (pending, dispatched, uncertain) — cancellation confirmation
        waits on pending and dispatched effects too, so restricting
        reconciliation to uncertain effects deadlocked it."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            eff = self._find_effect(rev, effect_id)
            if eff["state"] == "resolved":
                raise InvalidTransition(
                    "effect %s is already resolved; reconciliation "
                    "applies to unresolved effects (pending, dispatched, "
                    "uncertain)" % effect_id)
            if found:
                eff["state"] = "resolved"
                eff["resolved_ts"] = ts
                self._record(rev, "reconciliation", ts, effect_id=effect_id,
                             outcome="found", detail=detail,
                             attempt_id=eff["attempt_id"],
                             payload_sha256=rev["payload_sha256"])
                if rev["state"] == "admission-uncertain" and \
                        rev["cancellation"] is None and not any(
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

    @staticmethod
    def _dispatch_blocker(rev):
        """Why this revision may not be dispatched/started right now, or
        None if dispatch is allowed. Fix 1 (A14 hold semantics): a hold
        suppresses dispatch just as it suppresses alerts — release is an
        explicit act by the named authority, never a side effect of
        time or of a runner deciding to proceed. Blocked and
        admission-uncertain items are likewise undispatchable, and a
        cancellation request stops all new dispatch at once (section
        10)."""
        if rev["cancellation"] is not None or \
                rev["state"] == "cancellation-requested":
            return "cancellation requested: all new dispatch is stopped"
        if rev["state"] in TERMINAL_STATES:
            return "item is terminal (%s)" % rev["state"]
        if rev["hold"] is not None:
            return ("item is held (%s); only %s may release it"
                    % (rev["hold"]["condition"],
                       rev["hold"]["release_authority"]))
        if rev["state"] == "blocked":
            return "item is blocked (%s)" % (
                rev["blocked"]["reason"] if rev["blocked"] else "blocked")
        if rev["state"] == "admission-uncertain":
            return ("admission is uncertain; the uncertain effect must "
                    "be reconciled before any dispatch")
        return None

    def can_dispatch(self, task_id, revision=None):
        with self._txn() as st:
            item, rev = self._get_rev(st, task_id, revision)
            return rev["state"] in ("admitted", "started") and \
                self._dispatch_blocker(rev) is None and \
                self._ownership_fence(item, rev["revision"]) is None

    def start(self, task_id, revision=None, by=None, evidence=None, now=None):
        """EXECUTION-START evidence, bound to the attempt. The only record
        class that moves an item to started (section 3). Blocked by a
        cancellation request (section 10), by an approval hold (section
        8), by a blocker (section 9), by admission uncertainty
        (section 4), and by cross-revision ownership fencing (round-2
        fix 5): no second execution while another revision owns
        unresolved execution."""
        ts = _now(now)
        with self._txn() as st:
            item, rev = self._get_rev(st, task_id, revision)
            blocker = self._dispatch_blocker(rev)
            if blocker is not None:
                raise InvalidTransition(blocker)
            if rev["state"] != "admitted":
                raise InvalidTransition(
                    "start requires state admitted, not %s" % rev["state"])
            fence = self._ownership_fence(item, rev["revision"])
            if fence is not None:
                raise OwnershipFenced(fence)
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

    @staticmethod
    def _notif_delivery(st, notif):
        """Delivery route of a notification record: "local-outbox" when
        it is delivered through the store's own outbox, "external" when
        an injected sender carries it to a real destination. Records
        written before the field existed are inferred from the outbox
        itself: an id present there was delivered locally (round-2
        fix 3)."""
        delivery = notif.get("delivery")
        if delivery:
            return delivery
        if notif["notification_id"] in st.get("outbox", {}):
            return "local-outbox"
        return "external"

    def _notify_locked(self, st, destination, payload, sender, hooks, ts,
                       kind, task_id, revision, deadline_kind, deadline_ts,
                       material_epoch, destination_view=None):
        nid = _notification_id(destination, kind, task_id, revision,
                               deadline_kind, deadline_ts, material_epoch)
        existing = st["notifications"].get(nid)
        if existing is not None and existing["state"] in (
                "sent", "sent-confirmed"):
            return copy.deepcopy(existing)
        if existing is not None:
            # Fix 3 (section 7): a REPEAT notify of an intent/uncertain
            # notification reconciles against the destination BEFORE any
            # re-send — the same query recover_notifications performs.
            # Seen at the destination -> confirmed, never duplicated
            # (A12). Unseen -> fall through and send exactly once under
            # the persisted notification_id (A11).
            # Round-2 fix 3: without a destination_view, an unresolved
            # EXTERNAL notification FAILS CLOSED — it is never re-sent
            # on hope. The local outbox view may be substituted only
            # for a notification actually delivered via the local
            # outbox; it is not a view of any external destination.
            view = destination_view
            if view is None:
                if self._notif_delivery(st, existing) == "local-outbox":
                    view = _OutboxView(st)
                else:
                    raise CrewQueueError(
                        "notification %s is unresolved (%s) and "
                        "targets an external destination; refusing to "
                        "re-send without a destination_view query of "
                        "that destination (fail closed, section 7)"
                        % (nid, existing["state"]))
            if view.has_seen(nid):
                existing["state"] = "sent-confirmed"
                existing["updated_ts"] = ts
                existing["reconciled"] = "destination-has-seen"
                self._save_locked(st)
                return copy.deepcopy(existing)
        if existing is None:
            existing = {"notification_id": nid, "destination": destination,
                        "kind": kind, "task_id": task_id,
                        "revision": revision, "deadline_kind": deadline_kind,
                        "deadline_ts": deadline_ts,
                        "material_epoch": material_epoch,
                        "delivery": "local-outbox" if sender is None
                        else "external",
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
        if sender is None and \
                self._notif_delivery(st, existing) == "external":
            # Unresolved external notification, destination queried and
            # unseen, but this call supplied no sender for that
            # destination: sending via the local outbox would deliver
            # to the WRONG destination. Fail closed (round-2 fix 3).
            raise CrewQueueError(
                "notification %s targets an external destination; no "
                "external sender was supplied to re-send it (fail "
                "closed, section 7)" % nid)
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
               deadline_ts=None, material_epoch=0, destination_view=None):
        """Send a notification under section 7 semantics. If this exact
        notification already exists in intent/uncertain state and a
        destination_view is supplied, the destination is queried by
        notification_id BEFORE any re-send (fix 3). Round-2 fix 3:
        without a destination_view, an unresolved EXTERNAL notification
        fails closed (CrewQueueError) instead of being re-sent; only a
        local-outbox notification may reconcile against the local
        outbox view."""
        ts = _now(now)
        with self._txn() as st:
            return self._notify_locked(st, destination, payload, sender,
                                       hooks, ts, kind, task_id, revision,
                                       deadline_kind, deadline_ts,
                                       material_epoch,
                                       destination_view=destination_view)

    def recover_notifications(self, sender=None, destination_view=None,
                              now=None):
        """Crash recovery for notifications in intent/uncertain state.
        The destination is queried by notification_id BEFORE any re-send:
        seen -> sent-confirmed, no duplicate (A12); unseen -> send exactly
        once under the persisted notification_id (A11).
        Round-2 fix 3: the query must be of the notification's OWN
        destination. With no destination_view supplied, an unresolved
        EXTERNAL notification fails closed (reported, state untouched,
        never re-sent): the local outbox view is valid only for
        notifications actually delivered via the local outbox, and the
        local outbox sender never substitutes for an external one."""
        ts = _now(now)
        actions = []
        with self._txn() as st:
            for nid, notif in sorted(st["notifications"].items()):
                if notif["state"] not in ("intent", "uncertain"):
                    continue
                delivery = self._notif_delivery(st, notif)
                view = destination_view
                if view is None:
                    if delivery == "local-outbox":
                        view = _OutboxView(st)
                    else:
                        actions.append(
                            {"notification_id": nid,
                             "action": "fail-closed-no-destination-view",
                             "resent": False})
                        continue
                if view.has_seen(nid):
                    notif["state"] = "sent-confirmed"
                    notif["updated_ts"] = ts
                    actions.append({"notification_id": nid,
                                    "action": "confirmed-at-destination",
                                    "resent": False})
                    continue
                if delivery == "external":
                    if sender is None:
                        actions.append(
                            {"notification_id": nid,
                             "action": "fail-closed-no-external-sender",
                             "resent": False})
                        continue
                    snd = sender
                else:
                    snd = sender or _outbox_sender(st)
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
        """Evaluate pickup/completion CHECK events for every UNRESOLVED
        revision of every item (fix 5: the watcher view is not limited
        to the current revision -- an older revision whose deadline was
        missed still escalates). Checks are check-only: evaluating them
        never mints attempts or executes work (A4). A missed check
        escalates exactly once per (task_id, revision, deadline,
        material epoch) via the section 7 machinery. Holds suppress
        alerts (section 8). Blocked items get blocker-check events on
        their own cadence and NO ETA escalation (section 9)."""
        ts = _now(now)
        actions = []
        with self._txn() as st:
            for task_id in sorted(st["items"]):
                item = st["items"][task_id]
                for rev_key in sorted(item["revisions"], key=int):
                    self._escalate_rev_locked(
                        st, item["revisions"][rev_key], ts, sender,
                        destination_view, actions)
        return actions

    def _escalate_rev_locked(self, st, rev, ts, sender, destination_view,
                             actions):
        task_id = rev["task_id"]
        state = rev["state"]
        if state in TERMINAL_STATES or \
                state == "cancellation-requested":
            return
        if state == "blocked":
            blk = rev["blocked"]
            while blk and ts >= blk["next_check_ts"]:
                blk["checks"].append(blk["next_check_ts"])
                blk["next_check_ts"] += blk["interval_s"]
                self._record(rev, "blocker-check", ts,
                             payload_sha256=rev["payload_sha256"])
                actions.append({"task_id": task_id,
                                "revision": rev["revision"],
                                "action": "blocker-check"})
            return
        if rev["hold"] is not None:
            return  # alerts suppressed; time alone changes nothing
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
                due, rev["material_epoch"],
                destination_view=destination_view)
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
                            "revision": rev["revision"],
                            "action": "escalated", "check": kind,
                            "notification_id":
                                notif["notification_id"]})

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
              blocker_check_interval_s=None):
        """Block an item (section 9). The blocker-check cadence comes
        from the explicit argument when given, else the queue's
        configured cadence (constructor), else the section 9 default —
        never an unqualified literal — and must be positive (fix 6)."""
        if blocker_check_interval_s is None:
            interval = self.blocker_check_interval_s
        else:
            interval = self._validate_interval(
                blocker_check_interval_s, "blocker_check_interval_s")
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
                              "interval_s": interval,
                              "next_check_ts": ts + interval,
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

    # Effect states that still owe the world an answer. Fix 2:
    # cancellation reconciliation covers pending (intent persisted,
    # effect never confirmed) and dispatched (in-flight) effects, not
    # only uncertain ones.
    OPEN_EFFECT_STATES = ("pending", "dispatched", "uncertain")

    @classmethod
    def _open_effects(cls, rev):
        return [e for e in rev["effects"]
                if e["state"] in cls.OPEN_EFFECT_STATES]

    def _confirm_cancellation_locked(self, rev, by, ts):
        rev["cancellation"]["confirmed_ts"] = ts
        rev["cancellation"]["confirmed_by"] = by
        rev["state"] = "canceled"
        self._record(rev, "cancel-confirmed", ts, by=by,
                     attempt_id=rev["current_attempt_id"],
                     payload_sha256=rev["payload_sha256"])

    def cancel_confirm(self, task_id, revision=None, by=None, now=None):
        """Phase two: confirm cancellation ONLY when no in-flight,
        pending, or uncertain effects remain. While any effect is open
        the request stays open as a reconciliation item and ownership
        is retained in full (A6/A15). A late confirmation callback
        against an item already in a terminal state changes nothing:
        terminal states are preserved."""
        ts = _now(now)
        with self._txn() as st:
            _, rev = self._get_rev(st, task_id, revision)
            if rev["state"] in TERMINAL_STATES:
                raise InvalidTransition(
                    "item is already terminal (%s); late cancellation "
                    "callback changes nothing" % rev["state"])
            if rev["cancellation"] is None:
                raise InvalidTransition("no cancellation was requested")
            open_effects = self._open_effects(rev)
            if open_effects:
                self._record(rev, "reconciliation", ts,
                             outcome="cancel-confirm-blocked",
                             detail="open effects unresolved: %s"
                                    % [(e["effect_id"], e["state"])
                                       for e in open_effects],
                             payload_sha256=rev["payload_sha256"])
                raise InvalidTransition(
                    "cannot confirm cancellation: %d open effect(s) "
                    "unresolved (pending/dispatched/uncertain); "
                    "reconciliation and ownership retained"
                    % len(open_effects))
            self._confirm_cancellation_locked(rev, by, ts)
            return copy.deepcopy(rev)

    def recover_cancellations(self, now=None):
        """Crash recovery for cancellations (fix 2). A cancellation can
        be left pending by a crash anywhere between the request and the
        confirm (or between the last effect resolving and the confirm).
        On recovery, every revision carrying an UNCONFIRMED cancellation
        record is re-examined — keyed off the cancellation record
        itself, not only the state string (round-2 fix 2), so a record
        whose state was disturbed stays visible to recovery. If no
        pending/dispatched/uncertain effects remain, the cancellation
        is confirmed under the retained request; if effects are still
        open, the request stays pending and is reported, with
        reconciliation and ownership untouched."""
        ts = _now(now)
        actions = []
        with self._txn() as st:
            for task_id in sorted(st["items"]):
                item = st["items"][task_id]
                for rev_key in sorted(item["revisions"], key=int):
                    rev = item["revisions"][rev_key]
                    if rev["cancellation"] is None or \
                            rev["cancellation"].get("confirmed_ts") \
                            is not None or \
                            rev["state"] in TERMINAL_STATES:
                        continue
                    open_effects = self._open_effects(rev)
                    if open_effects:
                        actions.append(
                            {"task_id": task_id,
                             "revision": rev["revision"],
                             "action": "cancellation-still-pending",
                             "open_effects":
                                 [e["effect_id"] for e in open_effects]})
                        continue
                    self._confirm_cancellation_locked(rev, "recovery", ts)
                    actions.append(
                        {"task_id": task_id, "revision": rev["revision"],
                         "action": "cancellation-confirmed"})
        return actions

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

    def unresolved_revisions(self):
        """The watcher view (fix 5): EVERY unresolved revision of every
        item — a revision is unresolved until it reaches a terminal
        state (verified-accepted or canceled). Watchers must evaluate
        this whole list, not only each item's current revision: an
        older revision can still carry a missed deadline, an open
        effect, or a pending cancellation after a newer revision is
        admitted."""
        view = []
        with self._txn() as st:
            for task_id in sorted(st["items"]):
                item = st["items"][task_id]
                for rev_key in sorted(item["revisions"], key=int):
                    rev = item["revisions"][rev_key]
                    if rev["state"] in TERMINAL_STATES:
                        continue
                    view.append({
                        "task_id": task_id,
                        "revision": rev["revision"],
                        "is_current": rev["revision"] ==
                        item["current_revision"],
                        "state": rev["state"],
                        "owner": rev["owner"],
                        "attempt_id": rev["current_attempt_id"],
                        "pickup_deadline_ts":
                            rev["deadlines"]["pickup"][-1]["ts"]
                            if rev["deadlines"]["pickup"] else None,
                        "completion_deadline_ts":
                            rev["deadlines"]["completion"][-1]["ts"]
                            if rev["deadlines"]["completion"] else None,
                        "held": rev["hold"] is not None,
                        "blocked": rev["state"] == "blocked",
                        "cancellation_requested":
                            rev["cancellation"] is not None,
                        "open_effects":
                            [e["effect_id"]
                             for e in self._open_effects(rev)],
                        "material_epoch": rev["material_epoch"],
                    })
        return view

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
    parser.add_argument(
        "--queue-blocker-check-interval", type=int, default=None,
        help="the queue's configured blocker-check cadence in seconds "
             "(fix 6); block() calls without their own interval use it")
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
    p.add_argument("--blocker-check-interval", type=int, default=None,
                   help="per-call blocker-check cadence; defaults to the "
                        "queue's configured cadence")

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
    sub.add_parser("recover-cancellations")
    sub.add_parser("unresolved")

    p = sub.add_parser("show")
    p.add_argument("--task", required=True)

    args = parser.parse_args(argv)
    q = CrewQueue(args.store,
                  blocker_check_interval_s=args.queue_blocker_check_interval)
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
        elif args.cmd == "recover-cancellations":
            out = q.recover_cancellations()
        elif args.cmd == "unresolved":
            out = q.unresolved_revisions()
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
