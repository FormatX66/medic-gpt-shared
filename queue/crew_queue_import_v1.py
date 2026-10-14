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
record so the hash can be recomputed from the store alone.

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
target is refused rather than overwriting it.

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
    CrewQueue, QUEUE_LANE_CADENCE_S, SPEC_SHA256, _attempt_id,
    canonical_bytes, payload_sha256,
)

LIVE_STORE_PATH = os.path.expanduser(
    "~/workspace/goals/medic-gpt-automated-loop/hidden_files/"
    "crew-queue.json")

IMPORTER_ID = "crew_queue_import_v1"
IMPORT_REVISION = 1


class ImportFailure(Exception):
    """Input is invalid, corrupt, or in conflict. Nothing is written."""


class ImportRefusal(Exception):
    """The requested write target is forbidden. Nothing is written."""


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
        if not item.get("id"):
            raise ImportFailure(
                "v1 item #%d in %s has no id; it cannot be keyed and "
                "will not be silently dropped" % (i, path))
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
        entries.append({
            "id": task_id, "duplicate": False, "item": item,
            "v1_state": item.get("state"), "v1_status": item.get(
                "status"),
            "v2_state": state, "unresolved": unresolved,
            "flags": flags, "detail": detail, "sha256": sha})
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


def _existing_target_state(target):
    """Classify a pre-existing apply target: 'v2' (parsed store dict),
    'foreign', or 'corrupt'. Read-only."""
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError:
        return "corrupt", None
    except OSError:
        return "corrupt", None
    if isinstance(data, dict) and data.get("version") == 2 and \
            isinstance(data.get("items"), dict):
        return "v2", data
    return "foreign", None


def _same_import(existing, built):
    """True when an existing v2 store already holds THIS import: same
    item set, and for every item the same payload hash, the same
    mapped state, and the same preserved v1 item. (Record timestamps
    legitimately differ between runs and are not compared.)"""
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
    if os.path.exists(target):
        kind, existing = _existing_target_state(target)
        if kind == "v2" and existing.get("spec_sha256") == \
                SPEC_SHA256 and _same_import(existing, built):
            report = format_report(source, source_sha, entries,
                                   "apply (no-op: target already "
                                   "holds this import)", target)
            return 0, report
        raise ImportFailure(
            "target %s already exists (%s) and does not hold this "
            "exact import; refusing to overwrite it" % (target, kind))
    queue = CrewQueue(target)
    with queue._txn() as st:
        st.clear()
        st.update(built)
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
    args = parser.parse_args(argv)
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
