#!/usr/bin/env python3
"""One-shot importer: crew-queue v1 store -> crew-queue v2 store (gate G1).

Activation gate artifact for the crew-queue v2 cutover (spec rev 3,
sha256 c8b85a96dd22179460b8be5dd23a0b5400a085173bf2434dadcbd5155ef4c9b3;
module of record: crew_queue_v2.py commit 8ddee483...). NON-LIVE: this
tool never touches the running Tower and refuses to write the live v1
store path. It is run by an operator, once, at G3 preparation time.

Design notes
------------
Construction: revisions are built with the v2 module's OWN constructors
(CrewQueue._new_rev, CrewQueue._record, _attempt_id) and the store is
written through the module's own locked, fsynced transaction
(CrewQueue._txn / _save_locked), then validated by reopening it through
the public API (get_item, unresolved_revisions). The module's live
transition API (admit/start/verify/accept) is deliberately NOT replayed:
those transitions mint evidence (admission deadlines, completion claims,
section-11 verification/acceptance records) that a historical import
cannot truthfully fabricate. Instead every imported revision carries an
"import" record binding it to its v1 source item, and imported terminal
states are marked import-asserted, with v2-form evidence explicitly
absent (verification/acceptance stay None).

Payload: the payload of an imported revision is the v1 item dict,
verbatim. Its sha256 (module canonical form) is the revision's
payload_sha256, and the verbatim item is preserved inside the import
record (the record's v1_item field) so the hash can be recomputed
from the store alone. Revisions carry no payload field of their
own — payload_sha256 plus the import record are the whole story.

Operational history (correction fix 2): history is NOT carried as
metadata only — the v2 watcher consumes records and escalation keys,
so imports write the operational forms, import-marked: an item whose
v1 history shows pickup (a pickup_evidence string, or a picked-up /
done state) gets a "pickup" record (imported=True, the v1 evidence
attached), which is exactly what the watcher's pickup check reads;
an item v1 marked missed gets import-marked entries in the
revision's escalations list keyed exactly as the watcher computes
them for the imported deadlines, because the v1 escalation for
those deadlines already fired pre-migration. Deadlines set after
import carry new keys and escalate normally.

Claim-less continuation (correction fix 3): imported revisions in
assigned / reported-complete carry no section-11 completion claim,
and the live API rightly rejects start / complete_claim / verify on
revision 1 — that rejection is the safety property. The importer
flags them CLAIM-LESS, marks them with an import_continuation
record-field, and prints the continuation path in the mapping
report: admit revision 2 through the public API with the preserved
v1 payload and fresh deadlines, then run the normal lifecycle on
revision 2. No claim is ever fabricated on revision 1.

Reconciliation / supersession (residual R2): a claim-less revision 1
left in assigned / reported-complete stays in the watcher's
unresolved view after revision 2 completes — the continuation
marker alone is not operational retirement. Retirement is a
separate, bounded administrative step, run by an operator through
reconcile_import_continuations() (or --reconcile-continuations):
ONLY when the item's current successor revision carries the same
payload and is verified-accepted — i.e. its completion was claimed,
verified, and accepted with real section-11 evidence on the
successor — is revision 1 retired, via the module's public
cancel_request / cancel_confirm, with an import-marked
import-reconciliation record on revision 1 linking predecessor and
successor and citing the successor's acceptance artifact. Revision
1's historical records are never rewritten and it gains no
completion claim, verification, or acceptance: for an already-done
import the successor's lifecycle is the verification/reconciliation
vehicle for the historical completion, not a replay of the old
work. Until the successor is verified-accepted, revision 1 stays
unresolved and visible — reported as awaiting-continuation, never
hidden and never retired early.

Target classification (correction fix 1): whether a pre-existing
apply target is empty / this exact import / foreign is decided
UNDER the destination lock, on the store as loaded inside the
module's transaction — never from a pre-check outside the lock,
whose result could go stale before the write and whose loaded
contents the old code then cleared sight unseen.

Empty is not absent (residual R1): the module's loader returns a
synthesized empty store for a path that does not exist, and that
dict is indistinguishable from a saved, still-empty v2 ledger — so
existence is decided as part of the classification, read inside
the same transaction (the destination lock is held, and the loaded
store came from that same path under that lock). New
initialization is allowed ONLY for a genuinely absent destination.
A pre-existing target that already holds this exact import is a
byte-preserving no-op; EVERY other pre-existing target refuses —
including an empty ledger of the wrong spec and a valid empty
ledger carrying operator provenance, both of which the cleared
transaction previously destroyed.

State mapping (v1 effective state = "status" when present and non-empty,
else "state"; the status field is the later overlay in every dual-field
item in the v1 store of record, and dual-field items are flagged in the
mapping report):
    done              -> reported-complete (no section-11 claim migrated)
    verified-accepted -> verified-accepted (import-asserted; v2-form
                         verification/acceptance records absent)
    picked-up         -> admitted (pickup evidence rides in the v1 item)
    open              -> assigned
    blocked           -> blocked (blocked_from_state from the item's
                         underlying mapped state, default admitted)
    cancelled/canceled-> canceled (import-asserted cancellation record)
    missed            -> the item's underlying mapped state (status if
                         present, else assigned), flagged MISSED-CARRIED:
                         the v1 escalation already fired pre-migration;
                         the item is carried NON-terminal and visible,
                         never silently closed
    already-v2 values (assigned/admitted/started/reported-complete/
    cancellation-requested/captured/eligible/admission-uncertain)
                      -> passed through unchanged
    missing or unrecognized -> UNRESOLVED: state "assigned" (the
                         least-committal non-terminal state) plus an
                         "import_unresolved" marker on the revision,
                         an import record, and a line in the mapping
                         report's UNRESOLVED section. Never terminal,
                         never hidden.

Deadlines: v1 eta_ts -> completion deadline, v1 escalate_ts -> pickup
deadline (it was the v1 pickup-watch/escalation bound), each recorded
with its v1 origin as the reason. Items with neither keep empty
deadline lists and are flagged NO-DEADLINE in the report.

Duplicates: a repeated id with the SAME canonical payload is a dedup
note. A repeated id with a DIFFERENT payload is a rejected conflict
(section 4 semantics): the whole import aborts and nothing is written.

Idempotency: feeding the importer's own output (a v2 store) back as
input is a clean rejection. Applying to a target that already holds the
identical imported store is a no-op; applying to any other pre-existing
target is refused rather than overwriting it — a pre-existing EMPTY
v2 ledger included (residual R1: empty is not absent, and an empty
ledger's provenance is not the importer's to destroy). "This exact
import" also binds the store-level import provenance (importer +
source sha256), so a competing import that merely produces the same
item set — including two different EMPTY sources — is refused, not
mistaken for a no-op.

Exit codes: 0 ok (dry-run printed, apply written, or no-op);
2 refusal (target is the live store, or target == source);
3 input invalid / corrupt / conflict / foreign pre-existing target.
"""

import argparse
import copy
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crew_queue_v2 import (  # noqa: E402
    CrewQueue, InvalidTransition, QUEUE_LANE_CADENCE_S, SPEC_SHA256,
    StoreCorrupt, _attempt_id, canonical_bytes, payload_sha256,
)

LIVE_STORE_PATH = os.path.expanduser(
    "~/workspace/goals/medic-gpt-automated-loop/hidden_files/"
    "crew-queue.json")

IMPORTER_ID = "crew_queue_import_v1"
IMPORT_REVISION = 1

CONTINUATION_DETAIL = (
    "claim-less import: revision 1 carries no section-11 completion "
    "claim, and the live API rightly rejects start / complete_claim "
    "/ verify on it. Continuation path: admit revision 2 through "
    "the public API (CrewQueue.admit) with the preserved v1 payload "
    "and fresh deadlines, then pickup -> start -> complete_claim "
    "-> verify -> accept on revision 2. Once revision 2 is "
    "verified-accepted, an operator retires revision 1 with the "
    "importer's reconcile_import_continuations step "
    "(--reconcile-continuations): an import-reconciliation record "
    "links revision 1 to its successor and cites the successor's "
    "acceptance, and revision 1 is canceled through the public "
    "cancel_request / cancel_confirm operations. Until then "
    "revision 1 remains unresolved and visible. Revision 1's "
    "historical record is never rewritten and no claim is ever "
    "fabricated on it.")


class ImportFailure(Exception):
    """Input is invalid, corrupt, or in conflict. Nothing is written."""


class ImportRefusal(Exception):
    """The requested write target is forbidden. Nothing is written."""


class _NoOpImport(Exception):
    """Internal control flow: raised INSIDE the destination
    transaction when the target already holds this exact import, so
    the transaction aborts and the file stays byte-unchanged."""


# ------------------------------------------------------------------ input

def _sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load_v1(path):
    """Read and shape-check a v1 store. Fail closed: any read, parse,
    or shape problem raises ImportFailure; nothing is substituted."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError) as exc:
        raise ImportFailure(
            "v1 source %s is unreadable (%s); failing closed"
            % (path, type(exc).__name__))
    if not isinstance(data, dict):
        raise ImportFailure("v1 source %s is not a JSON object" % path)
    if data.get("version") == 2 or (
            isinstance(data.get("items"), dict)
            and "spec_sha256" in data):
        raise ImportFailure(
            "v1 source %s is already a v2 store; re-import is a clean "
            "rejection (the importer is one-shot)" % path)
    if not isinstance(data.get("items"), list):
        raise ImportFailure(
            "v1 source %s has no items list; unrecognized shape" % path)
    for i, item in enumerate(data["items"]):
        if not isinstance(item, dict):
            raise ImportFailure(
                "v1 item #%d in %s is not an object; failing closed"
                % (i, path))
        iid = item.get("id")
        if not isinstance(iid, str) or not iid.strip():
            # Correction fix 6: ids are validated HERE, before
            # anything is built or written. A numeric id previously
            # passed a truthiness check, the target store was
            # written, and only the post-write lookup failed (JSON
            # object keys are strings); list/dict ids raised
            # unhandled errors downstream.
            raise ImportFailure(
                "v1 item #%d in %s has an unusable id (%r); ids must "
                "be non-empty strings — it cannot be keyed and will "
                "not be silently dropped" % (i, path, iid))
    return data


# ---------------------------------------------------------------- mapping

_V2_PASSTHROUGH = (
    "captured", "eligible", "assigned", "admission-uncertain", "admitted",
    "started", "reported-complete", "cancellation-requested",
)


def _effective(item):
    """(value, field): status (the later overlay) precedes state."""
    status = item.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip(), "status"
    state = item.get("state")
    if isinstance(state, str) and state.strip():
        return state.strip(), "state"
    return None, None


def _underlying(item):
    """The non-status field's mapped value, used for blocked/missed
    underlays. Returns a v2 state or None."""
    state = item.get("state")
    if not (isinstance(state, str) and state.strip()):
        return None
    state = state.strip()
    if state == "picked-up":
        return "admitted"
    if state == "open":
        return "assigned"
    if state == "done":
        return "reported-complete"
    if state in _V2_PASSTHROUGH:
        return state
    return None


def map_state(item):
    """Map one v1 item to (v2_state, unresolved, flags, detail)."""
    eff, field = _effective(item)
    flags = []
    if item.get("state") and item.get("status"):
        flags.append("DUAL-FIELD(status-over-state)")
    if eff is None:
        return ("assigned", True, flags + ["UNRESOLVED"],
                "no state or status in v1 item")
    if eff == "done":
        return ("reported-complete", False, flags,
                "v1 done -> reported-complete; no section-11 completion "
                "claim migrated (v1 predates claims)")
    if eff == "verified-accepted":
        return ("verified-accepted", False, flags,
                "v1 verified-accepted carried as terminal; import-"
                "asserted (v2-form verification/acceptance records "
                "absent)")
    if eff == "picked-up":
        return ("admitted", False, flags,
                "v1 picked-up -> admitted; pickup evidence rides in "
                "the preserved v1 item")
    if eff == "open":
        return ("assigned", False, flags, "v1 open -> assigned")
    if eff == "blocked":
        return ("blocked", False, flags,
                "v1 blocked -> blocked (section 9 overlay preserved)")
    if eff in ("cancelled", "canceled"):
        return ("canceled", False, flags,
                "v1 cancelled -> canceled (import-asserted)")
    if eff == "missed":
        under = _underlying(item) if field == "status" else None
        base = under or "assigned"
        return (base, False, flags + ["MISSED-CARRIED"],
                "v1 missed: ETA escalation already fired pre-migration; "
                "carried non-terminal as %s, never silently closed"
                % base)
    if eff in _V2_PASSTHROUGH:
        return (eff, False, flags, "already a v2 state value; passed "
                "through")
    return ("assigned", True, flags + ["UNRESOLVED"],
            "unrecognized v1 state %r" % eff)


def _as_ts(value):
    if isinstance(value, bool):
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return ts if ts > 0 else None


def analyze(v1):
    """Per-item mapping analysis. Raises ImportFailure on a duplicate
    id with a differing payload (rejected conflict, section 4)."""
    entries = []
    seen = {}
    conflicts = []
    for item in v1["items"]:
        task_id = item["id"]
        sha = payload_sha256(item)
        if task_id in seen:
            if seen[task_id] == sha:
                entries.append({
                    "id": task_id, "duplicate": True, "sha256": sha,
                    "detail": "duplicate id with identical payload; "
                              "deduped (one revision kept)"})
                continue
            conflicts.append({
                "id": task_id, "existing_sha256": seen[task_id],
                "rejected_sha256": sha})
            continue
        seen[task_id] = sha
        state, unresolved, flags, detail = map_state(item)
        if _as_ts(item.get("eta_ts")) is None and \
                _as_ts(item.get("escalate_ts")) is None:
            flags.append("NO-DEADLINE")
        eff_value, _eff_field = _effective(item)
        pickup_happened = bool(
            isinstance(item.get("pickup_evidence"), str)
            and item["pickup_evidence"].strip()) or \
            eff_value in ("picked-up", "done") or \
            item.get("state") == "picked-up"
        continuation = None
        if state in ("assigned", "reported-complete") \
                and not unresolved:
            flags.append("CLAIM-LESS")
            continuation = CONTINUATION_DETAIL
        entries.append({
            "id": task_id, "duplicate": False, "item": item,
            "v1_state": item.get("state"), "v1_status": item.get(
                "status"),
            "v2_state": state, "unresolved": unresolved,
            "flags": flags, "detail": detail, "sha256": sha,
            "pickup_happened": pickup_happened,
            "continuation": continuation})
    if conflicts:
        raise ImportFailure(
            "duplicate id(s) with differing payloads are rejected "
            "conflicts, never overwrites: %s"
            % ", ".join(sorted(c["id"] for c in conflicts)))
    return entries


# ------------------------------------------------------------------ build

def build_store(v1, entries, source_path, source_sha256, import_ts):
    """Construct the v2 store dict for the analyzed v1 items, using the
    module's own revision/record constructors."""
    store = {"version": 2, "spec_sha256": SPEC_SHA256,
             "created_ts": import_ts, "updated_ts": import_ts,
             "items": {}, "notifications": {}, "outbox": {},
             "deliveries": []}
    unresolved_ids = []
    for entry in entries:
        if entry["duplicate"]:
            continue
        item = entry["item"]
        task_id = entry["id"]
        sha = entry["sha256"]
        owner = item.get("owner") or "unknown"
        created = _as_ts(item.get("created_ts")) or _as_ts(
            v1.get("updated_ts")) or import_ts
        rev = CrewQueue._new_rev(task_id, IMPORT_REVISION, sha, owner,
                                 owner, None, created)
        rev["state"] = entry["v2_state"]
        attempt_state = "admitted"
        if entry["v2_state"] in ("started", "reported-complete",
                                 "verified-accepted"):
            attempt_state = "started"
        attempt_id = _attempt_id(task_id, IMPORT_REVISION, 1)
        rev["attempts"].append({"attempt_id": attempt_id, "n": 1,
                                "state": attempt_state,
                                "started_ts": None})
        rev["current_attempt_id"] = attempt_id
        eta = _as_ts(item.get("eta_ts"))
        if eta is not None:
            rev["deadlines"]["completion"].append(
                {"ts": eta, "reason": "imported from v1 eta_ts",
                 "original": True})
        esc = _as_ts(item.get("escalate_ts"))
        if esc is not None:
            rev["deadlines"]["pickup"].append(
                {"ts": esc,
                 "reason": "imported from v1 escalate_ts (v1 "
                           "pickup-watch/escalation bound)",
                 "original": True})
        if entry["v2_state"] == "blocked":
            under = _underlying(item)
            blocked_from = under if under in ("admitted", "started") \
                else "admitted"
            rev["blocked_from_state"] = blocked_from
            rev["blocked"] = {
                "reason": "imported from v1 blocked state",
                "since_ts": created,
                "interval_s": QUEUE_LANE_CADENCE_S,
                "next_check_ts": created + QUEUE_LANE_CADENCE_S,
                "checks": []}
            if blocked_from == "started":
                rev["attempts"][-1]["state"] = "started"
        if entry["v2_state"] == "canceled":
            rev["cancellation"] = {
                "requested_ts": created, "by": IMPORTER_ID,
                "confirmed_ts": created, "confirmed_by": IMPORTER_ID,
                "pre_request_state": "admitted", "import_asserted": True}
        if entry["v2_state"] == "cancellation-requested":
            rev["cancellation"] = {
                "requested_ts": created, "by": IMPORTER_ID,
                "confirmed_ts": None, "pre_request_state": "admitted",
                "import_asserted": True}
        if entry.get("pickup_happened"):
            # Correction fix 2: the watcher consumes pickup RECORDS,
            # so the import writes one — import-marked, carrying the
            # v1 evidence, never disguised as a live pickup call.
            CrewQueue._record(
                rev, "pickup", import_ts, by=owner,
                attempt_id=attempt_id, payload_sha256=sha,
                imported=True,
                v1_evidence=item.get("pickup_evidence"),
                detail="pickup occurred pre-migration per the v1 "
                       "record (state / pickup evidence); import-"
                       "marked operational history so the watcher "
                       "consumes it — the v1 pickup time is not "
                       "recorded in v1 and is not invented here")
        if "MISSED-CARRIED" in entry["flags"]:
            # Correction fix 2: mark the escalation keys the watcher
            # computes for the imported deadlines as already fired
            # (they fired in v1 — that is what 'missed' means), so
            # nothing re-fires. New post-import deadlines carry new
            # keys and escalate normally.
            for kind in ("pickup", "completion"):
                for dl in rev["deadlines"][kind]:
                    rev["escalations"].append({
                        "key": [task_id, IMPORT_REVISION, kind,
                                dl["ts"], rev["material_epoch"]],
                        "notification_id": None, "ts": import_ts,
                        "imported": True,
                        "detail": "the v1 ETA escalation for this "
                                  "deadline already fired pre-"
                                  "migration (v1 state 'missed'); "
                                  "marked so the watcher does not "
                                  "re-fire it"})
        if entry.get("continuation"):
            rev["import_continuation"] = {
                "path": "new-revision",
                "detail": entry["continuation"]}
        if entry["unresolved"]:
            rev["import_unresolved"] = {
                "v1_state": entry["v1_state"],
                "v1_status": entry["v1_status"],
                "reason": entry["detail"]}
            unresolved_ids.append(task_id)
        CrewQueue._record(
            rev, "import", import_ts, source="crew-queue-v1",
            v1_state=entry["v1_state"], v1_status=entry["v1_status"],
            mapped_state=entry["v2_state"],
            unresolved=entry["unresolved"], detail=entry["detail"],
            payload_sha256=sha, v1_item=copy.deepcopy(item))
        store["items"][task_id] = {
            "task_id": task_id, "created_ts": created,
            "current_revision": IMPORT_REVISION,
            "revisions": {str(IMPORT_REVISION): rev}}
    store["import"] = {
        "importer": IMPORTER_ID, "imported_ts": import_ts,
        "source_path": source_path, "source_sha256": source_sha256,
        "source_version": v1.get("version"),
        "precedence": "status-over-state (status is the later overlay)",
        "items_imported": len(store["items"]),
        "unresolved": unresolved_ids,
        "v1_evidence_baseline": v1.get("evidence_baseline"),
    }
    return store


# ------------------------------------------------------------------ report

def format_report(source_path, source_sha256, entries, mode,
                  target=None):
    lines = []
    lines.append("crew-queue v1 -> v2 import (%s)" % mode)
    lines.append("source: %s" % source_path)
    lines.append("source sha256: %s" % source_sha256)
    if target:
        lines.append("target: %s" % target)
    lines.append("items: %d" % len(entries))
    for e in entries:
        if e["duplicate"]:
            lines.append("  %s  DUPLICATE deduped  sha256:%s  %s"
                         % (e["id"], e["sha256"][:12], e["detail"]))
            continue
        lines.append(
            "  %s  v1[state=%r status=%r] -> v2 %s  sha256:%s  %s"
            % (e["id"], e["v1_state"], e["v1_status"], e["v2_state"],
               e["sha256"][:12],
               ("flags=" + ",".join(e["flags"]) + "  ") if e["flags"]
               else ""))
        lines.append("      %s" % e["detail"])
        if e.get("continuation"):
            lines.append("      CONTINUATION: %s" % e["continuation"])
    unresolved = [e for e in entries if e.get("unresolved")]
    if unresolved:
        lines.append("UNRESOLVED (carried visibly, non-terminal):")
        for e in unresolved:
            lines.append("  %s: %s" % (e["id"], e["detail"]))
    imported = len([e for e in entries if not e["duplicate"]])
    lines.append("summary: %d imported, %d duplicates deduped, "
                 "%d unresolved"
                 % (imported,
                    len([e for e in entries if e["duplicate"]]),
                    len(unresolved)))
    return "\n".join(lines)


# -------------------------------------------------------------------- run

def _refuse_live_or_source(source, target):
    live = os.path.realpath(LIVE_STORE_PATH)
    tgt = os.path.realpath(target)
    if tgt == live:
        raise ImportRefusal(
            "target %s resolves to the LIVE v1 store path; the "
            "importer never writes the live store" % target)
    if tgt == os.path.realpath(source):
        raise ImportRefusal(
            "target %s is the source itself; refusing to overwrite "
            "the input" % target)


def _classify_loaded_store(st):
    """Classify a store dict AS LOADED INSIDE the destination
    transaction (correction fix 1): 'empty' — a fresh store with
    nothing in it, safe to fill; 'v2' — a populated v2 store;
    'foreign' — anything else (a v1-shaped dict, an unrecognized
    shape). The classification is only ever applied to the dict the
    transaction itself loaded under the destination lock, so the
    decision and the write are atomic with respect to other
    writers: content inserted by anyone else is seen, classified,
    and refused — never cleared sight unseen."""
    if not isinstance(st, dict) or st.get("version") != 2 or \
            not isinstance(st.get("items"), dict):
        return "foreign"
    if not st["items"] and not st.get("notifications") and \
            not st.get("outbox") and not st.get("deliveries") and \
            "import" not in st:
        return "empty"
    return "v2"


def _same_import(existing, built):
    """True when an existing v2 store already holds THIS import: same
    item set, and for every item the same payload hash, the same
    mapped state, and the same preserved v1 item. (Record timestamps
    legitimately differ between runs and are not compared.) The
    store-level import provenance must also match (residual R1):
    without it, a competing import that produces the same item set —
    in the limit, ANY other empty source, where the item comparison
    is vacuous — would be mistaken for this import and silently
    treated as a no-op."""
    ex_meta = existing.get("import") or {}
    built_meta = built.get("import") or {}
    if ex_meta.get("importer") != built_meta.get("importer") or \
            ex_meta.get("source_sha256") != \
            built_meta.get("source_sha256"):
        return False
    ex_items = existing.get("items", {})
    if set(ex_items) != set(built["items"]):
        return False
    for task_id, built_item in built["items"].items():
        ex_rev = ex_items[task_id].get("revisions", {}).get(
            str(IMPORT_REVISION), {})
        built_rev = built_item["revisions"][str(IMPORT_REVISION)]
        if ex_rev.get("payload_sha256") != \
                built_rev["payload_sha256"]:
            return False
        if ex_rev.get("state") != built_rev["state"]:
            return False
        def _preserved(rev):
            for rec in rev.get("records", []):
                if rec.get("kind") == "import":
                    return rec.get("v1_item")
            return None
        if canonical_bytes(_preserved(ex_rev)) != \
                canonical_bytes(_preserved(built_rev)):
            return False
    return True


def import_v1(source, target=None, apply=False, now=None):
    """Run the import. Returns (exit_code, report_text). Writes only
    in apply mode, only to target, never to the live store."""
    import_ts = int(time.time()) if now is None else int(now)
    source_sha = _sha256_file(source)
    v1 = load_v1(source)
    entries = analyze(v1)
    if not apply:
        return 0, format_report(source, source_sha, entries, "dry-run")
    if not target:
        raise ImportFailure("--apply requires an explicit --target")
    _refuse_live_or_source(source, target)
    built = build_store(v1, entries, source, source_sha, import_ts)
    queue = CrewQueue(target)
    try:
        with queue._txn() as st:
            # Correction fix 1: classify the target HERE, on the
            # store as loaded under the destination lock. Only an
            # empty store is filled; a populated store is either
            # this exact import (no-op — abort the transaction so
            # the file stays byte-unchanged) or a refusal. Nothing
            # the transaction loaded is ever cleared before this
            # decision.
            kind = _classify_loaded_store(st)
            if kind == "v2":
                if st.get("spec_sha256") == SPEC_SHA256 and \
                        _same_import(st, built):
                    raise _NoOpImport
                raise ImportFailure(
                    "target %s already exists (v2) and does not "
                    "hold this exact import; refusing to overwrite "
                    "it" % target)
            if kind == "foreign":
                raise ImportFailure(
                    "target %s already exists (foreign content) "
                    "and does not hold this exact import; refusing "
                    "to overwrite it" % target)
            # Residual R1: kind == "empty" means the loaded store
            # has no content — but the loader synthesizes exactly
            # this dict for a path that does not exist, so content
            # alone cannot distinguish a genuinely absent
            # destination from a saved, still-empty v2 ledger.
            # Existence is therefore read HERE, inside the
            # transaction: the destination lock is held and the
            # store above was loaded from this same path under it,
            # so the existence answer and the write are atomic
            # with respect to every cooperating writer. Empty is
            # not absent: initialization is allowed ONLY for a
            # genuinely absent destination; an existing empty
            # ledger — wrong spec, or valid but carrying operator
            # provenance — refuses, byte-preserved. (An exact
            # import can never classify 'empty': a built import
            # store always carries its "import" block, so the
            # no-op case is fully handled by the 'v2' branch.)
            if os.path.exists(queue.path):
                raise ImportFailure(
                    "target %s already exists as an empty v2 "
                    "ledger; empty is not absent — refusing to "
                    "initialize over an existing store (its "
                    "provenance would be destroyed). Initialize "
                    "only a genuinely absent destination, or "
                    "remove the existing ledger through the "
                    "operator's own decision first" % target)
            st.clear()
            st.update(built)
    except _NoOpImport:
        return 0, format_report(source, source_sha, entries,
                                "apply (no-op: target already "
                                "holds this import)", target)
    except StoreCorrupt as exc:
        raise ImportFailure(
            "target %s is corrupt or unreadable (%s); refusing to "
            "overwrite it" % (target, type(exc).__name__))
    # Validate the written store through the module's public read API.
    check = CrewQueue(target)
    for e in entries:
        if e["duplicate"]:
            continue
        item = check.get_item(e["id"])
        if item is None:
            raise ImportFailure(
                "post-write validation failed: %s missing" % e["id"])
        rev = item["revisions"][str(IMPORT_REVISION)]
        if rev["payload_sha256"] != e["sha256"]:
            raise ImportFailure(
                "post-write validation failed: payload hash mismatch "
                "for %s" % e["id"])
    check.unresolved_revisions()
    return 0, format_report(source, source_sha, entries, "apply", target)


# ------------------------------------------------- residual R2: retire

def reconcile_import_continuations(queue, by=None, now=None):
    """Administrative reconciliation / supersession of claim-less
    imported revisions (residual R2).

    The fix-3 continuation (admit revision 2, run its lifecycle)
    completes the WORK, but revision 1 — claim-less, in assigned or
    reported-complete — is not a terminal state, so the watcher's
    unresolved_revisions() keeps surfacing it next to its completed
    successor: the marker alone is not operational retirement, and
    leaving it means a permanent orphan that can still escalate.

    This step retires such a revision 1, and ONLY when retirement
    is authorized by evidence:

      * revision 1 carries the importer's import_continuation
        marker (this step touches nothing else — a live revision 1
        is never eligible);
      * the item's current revision is a successor (> 1) carrying
        the SAME payload hash as revision 1 (the continuation of
        THIS import, not some other work);
      * the successor is verified-accepted, with a recorded
        acceptance — its section-11 evidence (claim -> verify ->
        accept, all on the successor) is what authorizes retiring
        the predecessor. For an already-done import, the
        successor's verified lifecycle is the verification /
        reconciliation of the historical completion, not a replay
        of it.

    Retirement itself uses only authorized public operations and
    preserves history:

      * an import-marked "import-reconciliation" record is
        appended to revision 1 (the module's own record mechanism,
        as at import time) linking predecessor and successor and
        citing the successor's acceptance artifact sha256;
      * revision 1 is then canceled through the module's public
        cancel_request / cancel_confirm — the cancellation record
        keeps pre_request_state, so the historical fact (assigned /
        reported-complete, claim-less) stays readable, and revision
        1 gains NO completion claim, verification, or acceptance.

    Anything not yet authorized is reported as
    "awaiting-continuation" and left exactly as it is: still
    unresolved, still visible, still able to escalate — never
    hidden, never retired early. The step is idempotent: a retired
    revision 1 is terminal and is not visited again.

    Returns a list of per-item outcome dicts."""
    by = by or IMPORTER_ID
    ts = int(time.time()) if now is None else int(now)
    outcomes = []
    candidates = [e for e in queue.unresolved_revisions()
                  if e["revision"] == IMPORT_REVISION]
    for entry in candidates:
        task_id = entry["task_id"]
        item = queue.get_item(task_id)
        if item is None:
            continue
        rev1 = item["revisions"].get(str(IMPORT_REVISION))
        if rev1 is None or "import_continuation" not in rev1:
            continue  # not a claim-less import continuation
        current = item["current_revision"]
        succ = item["revisions"].get(str(current)) \
            if current > IMPORT_REVISION else None
        if succ is None:
            outcomes.append({
                "task_id": task_id, "revision": IMPORT_REVISION,
                "status": "awaiting-continuation",
                "detail": "no successor revision admitted yet"})
            continue
        acceptance = succ.get("acceptance") or {}
        if succ["state"] != "verified-accepted" or \
                not acceptance.get("artifact_sha256"):
            outcomes.append({
                "task_id": task_id, "revision": IMPORT_REVISION,
                "status": "awaiting-continuation",
                "successor_revision": current,
                "detail": "successor revision %d is %s, not "
                          "verified-accepted; revision 1 stays "
                          "unresolved" % (current, succ["state"])})
            continue
        if succ["payload_sha256"] != rev1["payload_sha256"]:
            outcomes.append({
                "task_id": task_id, "revision": IMPORT_REVISION,
                "status": "awaiting-continuation",
                "successor_revision": current,
                "detail": "successor payload hash differs from "
                          "revision 1; not the continuation of "
                          "this import"})
            continue
        # Authorized. Link predecessor -> successor on revision 1
        # itself (append-only; no historical record is rewritten),
        # skipping the link record if a prior interrupted run
        # already wrote it for this successor.
        with queue._txn() as st:
            _, r1 = CrewQueue._get_rev(st, task_id, IMPORT_REVISION)
            linked = any(
                rec.get("kind") == "import-reconciliation"
                and rec.get("successor_revision") == current
                for rec in r1["records"])
            if not linked:
                CrewQueue._record(
                    r1, "import-reconciliation", ts, by=by,
                    predecessor_revision=IMPORT_REVISION,
                    successor_revision=current,
                    successor_state=succ["state"],
                    successor_acceptance_artifact_sha256=
                    acceptance["artifact_sha256"],
                    predecessor_state=rev1["state"],
                    detail="claim-less imported revision retired "
                           "by administrative reconciliation: "
                           "superseded by revision %d, whose "
                           "recorded verification + acceptance is "
                           "the reconciliation evidence. Revision 1 "
                           "keeps its full historical record and "
                           "gains no completion claim, verification, "
                           "or acceptance." % current)
        # Retire through the module's public cancellation
        # operations — the authorized administrative path. The
        # cancellation record preserves pre_request_state.
        if rev1.get("cancellation") is None:
            queue.cancel_request(task_id, revision=IMPORT_REVISION,
                                 by=by, now=ts)
        queue.cancel_confirm(task_id, revision=IMPORT_REVISION,
                             by=by, now=ts)
        outcomes.append({
            "task_id": task_id, "revision": IMPORT_REVISION,
            "status": "retired",
            "successor_revision": current,
            "successor_acceptance_artifact_sha256":
                acceptance["artifact_sha256"],
            "detail": "revision 1 canceled (pre-request state %s "
                      "preserved in its cancellation record) after "
                      "successor revision %d reached "
                      "verified-accepted" % (rev1["state"], current)})
    return outcomes


def format_reconcile_report(outcomes):
    lines = ["import continuation reconciliation:"]
    if not outcomes:
        lines.append("  (no claim-less imported revisions "
                     "unresolved)")
    for o in outcomes:
        lines.append("  %s rev %d: %s — %s"
                     % (o["task_id"], o["revision"], o["status"],
                        o["detail"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="One-shot crew-queue v1 -> v2 importer (gate G1). "
                    "Dry-run is the default and writes nothing.")
    parser.add_argument("--source", default=LIVE_STORE_PATH,
                        help="v1 store to read (default: the live v1 "
                             "store, read-only)")
    parser.add_argument("--target", default=None,
                        help="v2 store to write in --apply mode; must "
                             "not be the live store path")
    parser.add_argument("--apply", action="store_true",
                        help="write the v2 store to --target "
                             "(default is dry-run)")
    parser.add_argument("--reconcile-continuations",
                        action="store_true",
                        help="residual R2: retire claim-less "
                             "imported revisions whose successor "
                             "revision is verified-accepted "
                             "(administrative reconciliation / "
                             "supersession) on the --target store; "
                             "no import is run")
    parser.add_argument("--by", default=None,
                        help="operator identity recorded for "
                             "--reconcile-continuations "
                             "(default: the importer id)")
    args = parser.parse_args(argv)
    if args.reconcile_continuations:
        if not args.target:
            print("IMPORT FAILED: --reconcile-continuations "
                  "requires an explicit --target", file=sys.stderr)
            return 3
        if os.path.realpath(args.target) == os.path.realpath(
                LIVE_STORE_PATH):
            print("REFUSED: target %s resolves to the LIVE v1 "
                  "store path; reconciliation never writes the "
                  "live v1 store" % args.target, file=sys.stderr)
            return 2
        try:
            outcomes = reconcile_import_continuations(
                CrewQueue(args.target), by=args.by)
        except InvalidTransition as exc:
            print("IMPORT FAILED: reconciliation could not "
                  "complete: %s" % exc, file=sys.stderr)
            return 3
        print(format_reconcile_report(outcomes))
        return 0
    try:
        code, report = import_v1(args.source, target=args.target,
                                 apply=args.apply)
    except ImportRefusal as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    except ImportFailure as exc:
        print("IMPORT FAILED: %s" % exc, file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print("IMPORT FAILED: %s" % exc, file=sys.stderr)
        return 3
    print(report)
    return code


if __name__ == "__main__":
    sys.exit(main())
