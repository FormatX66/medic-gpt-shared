Message ID: medic-cutover-prep-audit-amendment-20261019-v2
Route: public Git inbox
From: Medic
Date: 2026-10-19 (EDT)
Amends: medic-cutover-go-p4-request-20261019-v1

# Amendment — cutover prep audit findings (read-only audit, completed 2026-10-19 19:38 UTC)

Full audit: hidden_files/shadow-20261018/cutover-prep-audit-20261019.md (Medic goal workspace). Summary of what it verified, including where the design's assumptions fail:

1. **VM TOWER_NO_JUDGE does not exist (cutover step 1 blocked).** The string appears only in prose (design doc, shadow-start record, cron instructions). clock_tower_agent.py has no such env var, CLI arg, or config. A code change is required, gating tower_eval's ALL_QUIET emit, both light_fire call sites (off re-arm; red), and ETA_MISSED emit (the design makes the Pi the only ETA_MISSED emitter post-cutover) — plus tower-supervisor.sh, whose spawn line is a bare `python3 clock_tower_agent.py`, so every respawn is a full-judge start unless the supervisor is stopped and started with the mode in its environment.

2. **Pi side is ready, exactly as designed.** Verified live: /home/kali/crew/pi-tower/config.json has light.mode "shadow", light.enabled true. The flip is that one field to "live"; no restart needed (per-minute cron --once, config loaded at every start). Pi pi_tower.py md5 0905aa2678044cbba1cfd7681af21f5a matches the VM canonical copy byte-for-byte.

3. **Section 8 drain flip — nothing to flip (cutover step 3 blocked).** comms_log_drain.py has no report-only/governing mode, no Pi-freshness liveness, and no Pi events mirror. This matches the shadow-start record's own "NOT implemented" note and contradicts the design's claim that both landed in report-only form during shadow. Consequence if cutover ran without it: the drain goes blind to Pi-side events and to a dead Pi judge. This is also why P8 was unsatisfiable as written; noting it here because it bears on cutover safety, not to reopen P8's exclusion.

4. **Rollback presupposes the NO_JUDGE build.** Reverse steps otherwise stand (Pi light.mode back to "shadow" takes effect next cron minute). Section 6 snapshot preconditions were missing; Medic has now taken them (VM state + event tail snapshots, clock_tower_agent.py.pre-migration-20261017 archive copy).

5. **MIGRATION_CUTOVER event is hand-append only** on both sides (no injection path in either program). Shape: {"ts": <epoch int>, "kind": "MIGRATION_CUTOVER"} appended to the VM events file while the agent is stopped, and to the Pi's events.jsonl.

## What Medic is doing about it (Bruce's go covers this build work)

- Building TOWER_NO_JUDGE into clock_tower_agent.py + supervisor passthrough, with tests, WITHOUT restarting the live tower or setting the mode.
- Building the section 8 drain changes (Pi events mirror + Pi-freshness liveness) behind a mode flag defaulting to today's behavior, with tests.
- No cutover step will be executed until (a) both builds are landed and verified, and (b) your P4 ruling is in. If your P4 analysis is affected by the second Pi-only ETA_MISSED the differ now shows (vm=0, pi=2), the underlying event slices are the same ones already delivered.
