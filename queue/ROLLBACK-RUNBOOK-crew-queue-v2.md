# Rollback Runbook — Crew Queue v2 Activation (Gate G2)

Scope: undo a G3 activation of crew-queue v2 (Clock Tower queue lane
reading the v2 store via `crew_queue_v2.py`, commit `8ddee483`) and
return the crew queue to the v1 store + pinned Clock Tower v1.1.
Owner: Medic. Verifier: Rivet. This runbook is written BEFORE G3 runs;
every path and command below is exact. The governing rule, from Rivet's
gate criteria: **reconcile first — no restore may proceed past an
unreconciled unresolved effect or notification, and missing
destination evidence fails closed.**

Drill proof: `test_crew_queue_import_v1.py::TestRollbackDrill` plus
`TestRollbackGateConditions` and `TestRollbackPreflight` execute
step 2 (including the 2.0 preflight) against synthetic stores and
prove unresolved effects/notifications are surfaced, reconciled
without loss or replay, that EACH of the four gate conditions in 2e
aborts before any restore write when it is the one violated, and
that a missing ledger or a tampered baseline manifest aborts in
preflight before anything is reconciled.
`TestRollbackManifestCompleteness` additionally proves the 2.0
manifest rules (residual R3): the manifest is verified as the
COMPLETE three-member restore set, cross-pinned against
MANIFEST.json — a subset manifest (the v1 queue baseline alone),
an empty manifest, a missing pin, a pin conflict, an extra listed
member, and a duplicate entry each abort in preflight, while the
complete pinned set proceeds.

## Fixed paths

| Artifact | Path |
|---|---|
| Live v1 store (rollback target state) | `/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue.json` |
| v2 store (created at G3) | `/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue-v2.json` |
| Tower state | `/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/clock-tower-state.json` |
| Tower source (pinned v1.1) | `/home/hatch/workspace/goals/medic-gpt-automated-loop/files/clock_tower_agent.py` |
| Tower log | `/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/clock-tower.log` |
| Baseline dir | `/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/activation-baseline-20261014/` |
| Baseline manifest | `.../activation-baseline-20261014/MANIFEST.sha256` (and `MANIFEST.json`) |
| v2 module | `/home/hatch/workspace/shared/medic-gpt-shared/queue/crew_queue_v2.py` |
| Importer | `/home/hatch/workspace/shared/medic-gpt-shared/queue/crew_queue_import_v1.py` |

Baseline contents (sha256 in `MANIFEST.sha256`):
`crew-queue-v1-baseline.json` = `b2a0185d…`, `clock-tower-state-baseline.json`
= `24a7508b…`, `clock_tower_agent-v1.1-baseline.py` = `a5ac32ce…`
(full hashes in the manifest; verify, never trust this summary).

At rollback start, create the evidence directory and record everything
in it:

```
EVID=/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/rollback-evidence-$(date +%Y%m%d-%H%M%S)
mkdir -p "$EVID"
```

## Step 1 — Freeze new admissions

Stop the Tower (it is the only writer of the queue lane). The Tower is
a main-session `nohup` process, not a service:

```
pkill -f "[c]lock_tower_agent.py"
python3 - << 'EOF'
import os
hits = []
for pid in os.listdir('/proc'):
    if not pid.isdigit():
        continue
    try:
        cmd = open('/proc/%s/cmdline' % pid, 'rb').read().decode('utf-8', 'replace')
    except Exception:
        continue
    if 'clock' + '_tower_agent.py' in cmd:
        hits.append(pid)
print("tower processes:", hits)
EOF
```

The scan must print an empty list before proceeding. Then post a
COMMS LOG entry titled "Rollback freeze in effect" (doc
`1gHVGrWSbuWGPNca8-lO8K9hAWv6gBesRmapOCoi-fP8`) so the 2-minute drain's
DAEMON_DOWN report during the freeze is expected and nobody restarts
the Tower mid-rollback. The laptop supervisor does not manage the
Tower and needs no action. Record the freeze time and the rollback
reason in `$EVID/freeze.txt`.

## Step 2 — Reconcile v2 effects and notifications FIRST

No file is restored in this step. All commands run against the v2
store:

```
Q=/home/hatch/workspace/shared/medic-gpt-shared/queue/crew_queue_v2.py
V2=/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue-v2.json
B=/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/activation-baseline-20261014
```

2.0 **Preflight (read-only — before ANY reconcile or restore
write).** A missing v2 ledger must never be "reconciled" as an
empty store: opening a missing path through the module yields an
empty ledger against which every recovery trivially succeeds,
which would manufacture a passed gate out of a lost store. And the
baseline manifest's integrity is verified HERE — before any restore
write — not only after one (step 4 re-verifies after restore).

The manifest is verified as a SET (residual R3 — the drill's
`_verify_baseline_manifest` enforces exactly these rules): it must
list the COMPLETE expected restore set — `crew-queue-v1-baseline.json`,
`clock-tower-state-baseline.json`, `clock_tower_agent-v1.1-baseline.py`
— no more, no fewer. `sha256sum -c` alone is NOT sufficient: it
returns 0 for a manifest that lists only one member perfectly, so
a subset manifest would wave a partial rollback through a
"passed" gate. (`-c` does reject an empty manifest on its own —
no properly formatted checksum lines found, exit 1; the subset is
the case it cannot see, and the set verification above is what
rejects both.) An empty, incomplete, or
conflicting (duplicate-entry) manifest fails closed, as does any
missing or tampered member. The manifest's own integrity is pinned
by MANIFEST.json, written when the baseline was snapshotted: it
must pin the same complete set and agree with MANIFEST.sha256 on
every member's hash.

```
test -f "$V2" || { echo "PREFLIGHT FAIL: v2 ledger $V2 is missing — STOP"; exit 1; }
python3 - << 'EOF'
import json, sys
sys.path.insert(0, "/home/hatch/workspace/shared/medic-gpt-shared/queue")
from crew_queue_v2 import SPEC_SHA256
with open("/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue-v2.json") as fh:
    data = json.load(fh)
ok = isinstance(data, dict) and data.get("version") == 2 \
    and isinstance(data.get("items"), dict) \
    and data.get("spec_sha256") == SPEC_SHA256
print("ledger recognized:", ok)
sys.exit(0 if ok else 1)
EOF
python3 - << 'EOF'
import hashlib, json, os, sys
B = "/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/activation-baseline-20261014"
EXPECTED = ("crew-queue-v1-baseline.json", "clock-tower-state-baseline.json",
            "clock_tower_agent-v1.1-baseline.py")
def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()
problems = []
entries = {}
with open(os.path.join(B, "MANIFEST.sha256")) as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            problems.append("malformed manifest line %r" % line)
            continue
        name = parts[1].lstrip("*").strip()
        if name in entries:
            problems.append("conflicting manifest: duplicate entry for %s" % name)
            continue
        entries[name] = parts[0]
if not entries:
    problems.append("manifest is empty; an empty manifest verifies nothing")
missing = [m for m in EXPECTED if m not in entries]
if missing:
    problems.append("manifest is incomplete: missing restore member(s) %s" % (missing,))
extra = [n for n in entries if n not in EXPECTED]
if extra:
    problems.append("manifest lists member(s) outside the restore set: %s" % (extra,))
for name, want in entries.items():
    p = os.path.join(B, name)
    if not os.path.exists(p):
        problems.append("restore member %s is missing on disk" % name)
    elif sha(p) != want:
        problems.append("restore member %s fails its manifest hash" % name)
pin_path = os.path.join(B, "MANIFEST.json")
if not os.path.exists(pin_path):
    problems.append("MANIFEST.json is missing; the manifest's integrity is unpinned")
else:
    with open(pin_path) as fh:
        pin = json.load(fh)
    pin_entries = {f["copy"]: f["sha256"] for f in pin.get("files") or []
                   if isinstance(f, dict) and f.get("copy")}
    if set(pin_entries) != set(EXPECTED):
        problems.append("MANIFEST.json does not pin the complete restore set")
    else:
        for name, want in entries.items():
            if pin_entries.get(name) != want:
                problems.append("manifest pin conflict for %s" % name)
print("manifest problems:", problems)
sys.exit(1 if problems else 0)
EOF
cd "$B" && sha256sum -c MANIFEST.sha256
```

The `sha256sum -c` at the end is the per-member hash confirmation;
the completeness and pin checks above it are the gate. All three
must pass.

Any preflight failure: **STOP.** Nothing is reconciled, nothing is
restored; escalate per the gate-failure path in 2e.

2a. Surface everything unresolved, and save the output:

```
python3 $Q --store $V2 unresolved > "$EVID/unresolved-before.txt"
cat "$EVID/unresolved-before.txt"
```

2b. Recover cancellations whose effects are already resolved:

```
python3 $Q --store $V2 recover-cancellations > "$EVID/recover-cancellations.txt"
```

Any `cancellation-still-pending` line names open effects that must be
reconciled in 2c before this command is re-run.

2c. Reconcile each open effect against ITS OWN destination evidence
(spec section 4: server table, journal, or a destination query by
effect_id — never a re-send, never receiver absence). For each
effect_id printed in `$EVID/unresolved-before.txt`, query the
destination, then record the outcome (`FOUND=1` only when the
destination evidence shows the effect landed; `FOUND=0` records the
absence and changes nothing):

Run once per open effect, with `TASK_ID` / `EFFECT_ID` set to the ids
printed in `$EVID/unresolved-before.txt` and `FOUND=1` only when the
destination evidence shows the effect landed (`FOUND=0` records the
observed absence and changes nothing):

```
TASK_ID=<task id> EFFECT_ID=<effect id> FOUND=1 python3 - << 'EOF'
import os, sys
sys.path.insert(0, "/home/hatch/workspace/shared/medic-gpt-shared/queue")
from crew_queue_v2 import CrewQueue
q = CrewQueue("/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue-v2.json")
out = q.reconcile_effect(os.environ["TASK_ID"], os.environ["EFFECT_ID"],
                         found=os.environ["FOUND"] == "1",
                         detail="rollback reconciliation: destination query by effect_id")
print(out)
EOF
```

An effect reconciled with `FOUND=0` is STILL OPEN. Re-run 2b after 2c;
repeat 2b–2c until no `cancellation-still-pending` lines remain and
`unresolved` shows no `open_effects`.

2d. Reconcile notifications. First run the built-in recovery; it
confirms local-outbox notifications against the store outbox and
reports every unresolved EXTERNAL notification as
`fail-closed-no-destination-view`:

```
python3 $Q --store $V2 recover-notifications > "$EVID/recover-notifications.txt"
```

For each external notification still unresolved: query its
destination for the notification_id, write each id the destination
HAS seen (one per line) to `$EVID/seen-notifications.txt`, then run
recovery with that destination view:

```
SEEN_FILE="$EVID/seen-notifications.txt" python3 - << 'EOF'
import os, sys
sys.path.insert(0, "/home/hatch/workspace/shared/medic-gpt-shared/queue")
from crew_queue_v2 import CrewQueue
with open(os.environ["SEEN_FILE"]) as fh:
    seen = {ln.strip() for ln in fh if ln.strip()}
class DestinationView:
    def has_seen(self, notification_id):
        return notification_id in seen
q = CrewQueue("/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue-v2.json")
for action in q.recover_notifications(destination_view=DestinationView()):
    print(action)
EOF
```
What recovery can do with an unseen EXTERNAL notification depends
on a sender being supplied, and **this runbook deliberately wires
no sender**: the commands above call `recover_notifications` with a
destination view only, so an unseen external notification is
reported `fail-closed-no-external-sender` and stays unresolved —
**the gate fails**. (The module CAN send an unseen notification
exactly once under its persisted notification_id when an operator
explicitly supplies the destination's sender — `sent-on-recovery`,
completion of the original intent rather than a replay — but that
is an operator decision outside this runbook's documented commands,
never a silent default.) A notification whose destination cannot
be queried at all likewise stays unresolved: **the gate fails**.

2e. **GATE — all four must hold, else STOP:**
- `$EVID/unresolved-before.txt` re-run (`python3 $Q --store $V2 unresolved`) shows no `open_effects` and no `cancellation_requested` entries;
- the last `recover-cancellations` output contains no `cancellation-still-pending`;
- the last notification recovery output contains no `fail-closed-*` and no `still-uncertain` actions;
- every effect and notification that was unresolved at 2a appears in the step-2 outputs with a reconciled outcome (resolved / confirmed-at-destination / sent-on-recovery / cancellation-confirmed), AND a final read of the store shows no notification left in a non-terminal (`intent` / `uncertain`) state — including any minted after 2a by a writer that was not frozen.

If the gate fails: **do not restore anything.** The v2 store stays
exactly as it is, the Tower stays frozen, and the operator posts a
COMMS LOG entry + Board post naming the unreconciled ids and the
missing evidence, and hands the rollback to Medic/Rivet as an open
reconciliation item. A rollback is never forced past an unreconciled
unresolved effect or notification.

## Step 3 — Restore the v1 baseline (only after the gate passes)

```
H=/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files
B=$H/activation-baseline-20261014

# Quarantine the v2 store for forensics — never delete it.
mv $H/crew-queue-v2.json $H/crew-queue-v2.json.rolled-back-$(date +%Y%m%d-%H%M%S)
mv $H/crew-queue-v2.json.lock $H/crew-queue-v2.json.lock.rolled-back-$(date +%Y%m%d-%H%M%S) 2>/dev/null || true

# Restore the v1 queue store and the Tower state.
cp -p $B/crew-queue-v1-baseline.json $H/crew-queue.json
cp -p $B/clock-tower-state-baseline.json $H/clock-tower-state.json

# Restore the Tower source ONLY if G3 modified it.
sha256sum /home/hatch/workspace/goals/medic-gpt-automated-loop/files/clock_tower_agent.py
# Expected (pinned v1.1): a5ac32ce2a738e731b51fcf176e9e03396a8cb266a04b48368bea960b5cbfc1f
# If different:
cp -p $B/clock_tower_agent-v1.1-baseline.py /home/hatch/workspace/goals/medic-gpt-automated-loop/files/clock_tower_agent.py
```

## Step 4 — Post-rollback verification reads

```
cd $B && sha256sum -c MANIFEST.sha256
sha256sum $H/crew-queue.json $H/clock-tower-state.json /home/hatch/workspace/goals/medic-gpt-automated-loop/files/clock_tower_agent.py
```

(This step's `-c` is a post-restore hash re-verification only; the
manifest's completeness and MANIFEST.json pin were already enforced
as the gate at step 2.0 — a subset manifest passing `-c` here proves
nothing on its own.)

The three live hashes must equal the manifest values
(`crew-queue.json` ↔ `crew-queue-v1-baseline.json`,
`clock-tower-state.json` ↔ `clock-tower-state-baseline.json`,
`clock_tower_agent.py` ↔ `clock_tower_agent-v1.1-baseline.py`).
Also confirm the restored queue parses as the v1 store:

```
python3 -c "import json; d = json.load(open('/home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/crew-queue.json')); print(d['version'], len(d['items']))"
```

Expected: version `1` and the baseline item count.

## Step 5 — Restart the Tower and watch one full cycle

```
nohup python3 /home/hatch/workspace/goals/medic-gpt-automated-loop/files/clock_tower_agent.py >> /home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/clock-tower.log 2>&1 < /dev/null &
sleep 70
tail -20 /home/hatch/workspace/goals/medic-gpt-automated-loop/hidden_files/clock-tower.log
```

Verify: the start line is present, one full queue cycle (60 s) ran
with no `lane queue error` line, and the 2-minute comms-log drain
returns to normal decisions (no DAEMON_DOWN). Note: the Tower state
was restored from the baseline, so the first cycle re-evaluates from
the baseline watermarks — a burst of already-seen lane events on the
first drain is expected and is not a rollback failure.

## Step 6 — Evidence to record

In `$EVID/` and summarized in a COMMS LOG entry (doc
`1gHVGrWSbuWGPNca8-lO8K9hAWv6gBesRmapOCoi-fP8`) titled "Rollback
complete" (or "Rollback aborted at reconcile gate"):

- `freeze.txt`: freeze time, who ordered the rollback, the reason.
- `unresolved-before.txt`: the unresolved surface at freeze time.
- `recover-cancellations.txt` (every run), `recover-notifications.txt`, and the per-effect reconciliation outputs from 2c: every effect_id / notification_id with its destination evidence and outcome.
- The gate decision from 2e (pass, or abort with the unreconciled ids).
- Post-restore hashes (step 4 output) next to the manifest values.
- The Tower restart log lines and the first clean queue cycle.
- The quarantined v2 store's exact filename.

— Medic, 2026-10-14. Gate G2 artifact for Rivet verification.
Activation (G3) is NOT authorized by this runbook; it documents the
way back, and G3 runs only under its own approval.
