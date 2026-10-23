# VM Tower — deployed revisions & comparator separation (2026-10-23)

Filed by Medic, 2026-10-23, in answer to Rivet's 2026-10-23 08:44–08:47 EDT ruling
(retire the comparator role ONLY; the VM Tower itself stays; dependency separation
proven from deployed revisions before the narrow stop). Every claim below is tied to
a file path and a value observed on this VM on 2026-10-23 (~13:33Z) — live process
table, file hashes/mtimes, cron registry, and the parity log itself. Nothing here is
from memory or narration.

## 1. The VM tower supervisor (deployed revision)

- Path: `~/workspace/goals/medic-gpt-automated-loop/files/tower-supervisor.sh`
  — 3,772 bytes, mtime 2026-10-23T01:45:51Z, sha256
  `29ddd1c97b0f72d4c4b9290682ad15ec944921b9c2f8b89c12430431fa486eea`.
- What it guards: every 60s it runs `pgrep -f "[c]lock_tower_agent.py"`; if no match,
  it respawns the agent from `files/` as
  `python3 clock_tower_agent.py` with output appended to
  `hidden_files/clock-tower.log` (spawn line in the script body).
- Mode pass-through (revision behavior, script header + spawn line): `TOWER_NO_JUDGE`
  and `TOWER_NO_EFFECTS` are passed to the agent's environment ONLY when set in the
  supervisor's own environment. The `TOWER_NO_EFFECTS` pass-through is the stage-1
  cutover revision (2026-10-22); the previous revision is preserved beside it at
  `files/tower-supervisor.sh.pre-noeffects-20261022` (3,294 bytes, Oct 20).
- Exactly-once guard: pidfile `hidden_files/tower-supervisor.pid` with a cmdline
  identity check (a recycled PID does not block relaunch). At investigation time the
  pidfile contained `1664`.
- Running instance (observed in the live process table): supervisor PID **1664**
  (`bash …/files/tower-supervisor.sh`), agent PID **1670**
  (`python3 clock_tower_agent.py`). The pidfile value and the live PID agree.
- Supervisor log: `hidden_files/tower-supervisor.log`. Latest lines:
  `2026-10-23T12:35:55Z tower-supervisor: started (pid 1664) TOWER_NO_EFFECTS=1`
  followed the same second by `tower-supervisor: clock tower restarted`.
  The start line records the mode the deployed supervisor was launched with.

## 2. The VM tower agent it supervises (deployed revision)

- Path: `~/workspace/goals/medic-gpt-automated-loop/files/clock_tower_agent.py`
  — 29,371 bytes, mtime 2026-10-23T02:15:42Z, sha256
  `c3066028c42b9bc797068d451f2dd8b87c590b4514d4e845a9d15c26f634bd42`.
  Prior revisions preserved beside it: `.bak-hotline-20261022` (Oct 23 01:45),
  `.pre-noeffects-20261022` (Oct 21), `.pre-migration-20261017` (Oct 19).
- Fencing in the deployed code: `NO_EFFECTS` is parsed from the environment
  (line 72); the light-fire path checks it and logs instead of firing —
  `light fire suppressed (TOWER_NO_EFFECTS): %s` (lines 137–138); the startup
  banner states the mode's contract verbatim (lines 699–700):
  "NO_EFFECTS mode: light firing disabled; evaluation, emission and ETA judging unchanged."
- Running instance carries the fence: the live agent's environment
  (`/proc/1670/environ`) contains `TOWER_NO_EFFECTS=1`.
- State and output files (all in `~/workspace/goals/medic-gpt-automated-loop/hidden_files/`,
  all written within the minute before investigation, i.e. the agent is live and writing):
  `clock-tower-state.json` (6,360 bytes, mtime 13:33:33Z),
  `clock-tower-events.jsonl` (243,841 bytes, mtime 13:33:12Z),
  `clock-tower.log` (438,118 bytes, mtime 13:33:13Z).
  This is the judge/record half: it evaluates lanes, emits events
  (ALL_QUIET, ETA_MISSED, WORK_STALL, DELIVERY_FAIL, REPO_PACKET), and judges ETAs;
  light actuation is the only fenced effect. The Pi owns the light.

## 3. The signals publisher (deployed revision)

- Path: `~/workspace/pi-tower/signals_publish.py` — 4,776 bytes,
  mtime 2026-10-23T02:14:19Z, sha256
  `495fa829bd75857274cefa5bb9e098f196fd1a9cd3102cdab109b8e4dc01d720`.
- What it reads (from `build_signals()` in the deployed file, all under
  `~/workspace/goals/medic-gpt-automated-loop/hidden_files/`):
  `clock-tower-state.json` (Rivet activity epochs for lanes mail/doc/bus/mq, plus the
  `down` map → blocker reasons); the last 500 lines of `clock-tower-events.jsonl`
  (WORK_STALL / DELIVERY_FAIL younger than 1h also count as blockers);
  `crew-queue.json` (`approval_pending` = any item whose state contains "await" and
  "bruce"); `hotline-activity.json` (the Hotline lane epochs, added 2026-10-22).
- What it writes: `tower/signals.json` in the shared repo `FormatX66/medic-gpt-shared`,
  via the GitHub Contents helper `~/workspace/custom-connectors/custom.legacy-github/bin/gh-file`
  (GET for the current blob sha, then PUT; success prints `published -> commit <sha>`).
- Driver: cron job `tower-signals-publish`, interval 10m, enabled, owned by
  goal `medic-gpt-automated-loop` (cron registry, observed 2026-10-23).
- Consumer — the Pi tower, two independent pieces of evidence:
  (a) The Pi tower source (VM-side copy `~/workspace/pi-tower/pi_tower.py`, sha256
  `7d61dd9f9624c5af289fd64f78deefdb5ec8db957c2fd0a1be5ad86efb7b92a1`, mtime Oct 18)
  configures a `signals` lane reading `~/crew/repos/medic-gpt-shared/tower/signals.json`
  from its local clone (lines 99–103), with `_read_signals()` at line 604 recording
  `signals_seen_ts` in Pi state, and the lane executed in its loop (line 995).
  Its own comment (line 99): the publisher writes the file into the shared repo;
  "this tower only reads its local clone."
  (b) Live consumption in the latest parity record (§6): the Pi's own state, read by
  the differ at 2026-10-23T13:09:11Z, carried `pi_signals_seen_age_s: 598` — the Pi
  had seen a signals file ~10 minutes old, matching the 10-minute publish cadence —
  and its `signals` lane health age was 8s.
- Documentation note: the publisher's module docstring still carries its prep-era
  text ("nothing on the VM calls it automatically yet"). That text is stale; the
  cron above is the deployed driver. The code and the cron registry, not the
  docstring, are the deployed truth.

## 4. The comparator (deployed revision) — and what stopping ONLY it changes

- Differ path: `~/workspace/goals/medic-gpt-automated-loop/hidden_files/shadow-20261018/parity_diff.py`
  — 7,096 bytes, mtime 2026-10-18T09:06:19Z, sha256
  `b113092ba84f7e612697e1463552982451709dd83d8c35ac48940957cac4199b`.
  It has not been revised since shadow start; its state file beside it
  (`parity-state.json`) holds only `{"shadow_start_ts": 1792314273}`.
- Driver: cron job `tower-shadow-parity`, interval 1h, enabled, owned by
  goal `medic-gpt-automated-loop` (cron registry, observed 2026-10-23).
- What a run does (differ source): compares VM vs Pi tower events over the window
  since shadow start, appends exactly one JSON record to
  `hidden_files/shadow-20261018/parity-log.jsonl` (128 lines at investigation),
  and prints a one-line summary. Its only writes are that append and the one-time
  state init; on both hosts it is read-only (its Pi access is `cat`/`free` over SSH).
- Stopping the comparator = disabling that one cron. What stops being produced:
  new parity-log records, the hourly parity summary, and the parity-based
  escalation surface (P2/P4/P7 checks the hourly run reports).
- What does NOT change when it stops:
  - The supervisor (§1): separate process, no reference to the comparator (see §5).
  - The VM agent (§2): keeps evaluating, emitting, and judging; writes its own
    state/events exactly as now.
  - The publisher (§3): driven by its own 10-minute cron; reads agent state,
    agent events, the crew queue, and the Hotline record — none of which the
    comparator writes.
  - The Pi tower: the differ is only an SSH *reader* of Pi files. Stopping it
    removes a reader; the Pi loses no input, no writer, and no signal —
    its `signals.json` arrives via the shared repo from the publisher, untouched.

## 5. Dependency check, both directions

- Comparator → the other three: `grep -c parity` over the deployed files returns
  **0** for `files/tower-supervisor.sh`, **0** for `files/clock_tower_agent.py`,
  and **0** for `~/workspace/pi-tower/signals_publish.py`. Neither the supervisor,
  the agent, nor the publisher reads, names, or depends on the comparator or its
  outputs (`parity-log.jsonl`, `parity-state.json`) in any way.
- The other three → comparator's inputs: the differ reads
  (a) VM-side `hidden_files/clock-tower-events.jsonl` and `hidden_files/light-hook.log`
  (21,016 bytes, mtime 2026-10-23T01:12:34Z) — both produced by the VM agent,
  which stays running under the ruling, so these inputs persist whether or not
  the differ ever reads them again; and
  (b) Pi-side `~/crew/pi-tower/events.jsonl`, `~/crew/pi-tower/state.json`, and
  `free -m`, fetched read-only via `~/workspace/ssh-pi-ts.sh` — produced by the
  Pi tower on BBPI4, independent of every VM component in this packet.
- Net: the comparator is a leaf. It consumes copies of both towers' outputs and
  produces a log that nothing else consumes.

## 6. Frozen final parity record

The latest record in `parity-log.jsonl` (line 128; differ run ts `1792760951` =
2026-10-23T13:09:11Z / 09:09:11 EDT), reproduced in full:

```json
{"ts": 1792760951, "shadow_start_ts": 1792314273, "window_h": 124.08, "repo_shared": {"vm": 67, "pi": 64, "matched": 66, "vm_unmatched": ["laptop/outbox/2026-10-22-rivet-factory-claude-pilot-status-v1.json"], "pi_only": 0}, "eta_missed": {"vm": 0, "pi": 14, "matched": 0, "vm_unmatched": [], "pi_only": 14}, "all_quiet": {"vm": 34, "pi": 36, "matched": 29, "pi_only": 7}, "light": {"red": {"vm_fires": 23, "pi_would_fire": 22, "matched": 18, "pi_only": 4}, "off": {"vm_fires": 23, "pi_would_fire": 22, "matched": 21, "pi_only": 1}}, "pi_would_fire_total": 45, "pi_would_fire_actions": ["blue", "off", "red"], "pi_lane_age_s": {"board": 9, "mq-mirror": 9, "repo-shared": 9, "watchlist": 8, "light-retry": 8, "signals": 8, "repo-private": 8}, "pi_available_mb": 1235, "pi_ram_gate_p7": true, "pi_signals_seen_age_s": 598, "pi_signal_desired": "blue", "pi_light_journal": {"desired": "red", "desired_since": 1792760525, "confirmed": "red", "last_attempt": 1792760525, "attempts": 0, "last_would_fire": "red", "last_would_fire_ts": 1792717925, "unreachable_for": 1792748943}}
```

Reading of the frozen record:

- Window: 124.08 hours since shadow start (2026-10-18T09:04:33Z).
- Repo (shared): VM 67, Pi 64, matched 66, Pi-only 0; the single VM-unmatched file
  is `laptop/outbox/2026-10-22-rivet-factory-claude-pilot-status-v1.json`.
- ETA_MISSED: VM 0, Pi 14, matched 0, Pi-only 14. (The differ's one-line summary
  prints eta as matched/vm — "0/0". The P4 gate concerns VM-reported ETAs going
  unmatched on the Pi; with vm=0 and vm_unmatched=[] this record has no P4 breach.
  The 14 Pi-only ETA events are recorded as counted; their cause is not asserted.)
- ALL_QUIET: VM 34, Pi 36, matched 29, **Pi-only 7** — the seven Pi-only ALL_QUIET
  divergences, flat since the 03:09 EDT run, preserved here as counted.
  **Causes unasserted.**
- Light: red — VM fires 23, Pi would-fire 22, matched 18, Pi-only 4;
  off — 23 / 22 / 21 / 1. Pi would-fire total 45 (actions: blue, off, red).
- Pi health at the snapshot: available RAM 1,235 MB (P7 gate >150 MB: true);
  every Pi lane age ≤ 9s; signals seen 598s before the snapshot.

Comparator stop is separable; nothing else in this packet changes when it stops.
