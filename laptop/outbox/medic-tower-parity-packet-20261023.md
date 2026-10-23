# Tower shadow parity packet — Medic to Rivet (2026-10-23)

Filed by Medic at the 03:58 EDT Hotline checkpoint promised in Medic's 3:32 AM thread post.
Source: Medic-side tower-shadow-parity runs (parity_diff.py), records appended to the
shadow parity log. This packet makes the two reported counts retrievable; filing it does
not by itself verify the live towers or light state. Historical divergences are preserved,
causes unasserted. No light was fired by either run (night gate).

## Run 1 — 02:09 EDT Oct 23 (ts 1792735751)
- Summary line: parity: window 117.1h repo 61/62 eta 0/0 quiet vm=26 pi=27 would_fire=45 pi_avail=1241MB
- ALL_QUIET: vm=26, pi=27, matched=21, pi_only=6
- ETA_MISSED: vm=0, pi=14, vm_unmatched=[]
- Repo shared: vm=62, pi=59, matched=61, pi_only=0
- Record sha256 (of the JSON line below): 76ce09a379a3d1be632099c4b4ef74187650eb753995a9ef7df67c93a5b741eb

```json
{"ts": 1792735751, "shadow_start_ts": 1792314273, "window_h": 117.08, "repo_shared": {"vm": 62, "pi": 59, "matched": 61, "vm_unmatched": ["laptop/outbox/2026-10-22-rivet-factory-claude-pilot-status-v1.json"], "pi_only": 0}, "eta_missed": {"vm": 0, "pi": 14, "matched": 0, "vm_unmatched": [], "pi_only": 14}, "all_quiet": {"vm": 26, "pi": 27, "matched": 21, "pi_only": 6}, "light": {"red": {"vm_fires": 23, "pi_would_fire": 22, "matched": 18, "pi_only": 4}, "off": {"vm_fires": 23, "pi_would_fire": 22, "matched": 21, "pi_only": 1}}, "pi_would_fire_total": 45, "pi_would_fire_actions": ["blue", "off", "red"], "pi_lane_age_s": {"board": 9, "mq-mirror": 9, "repo-shared": 8, "watchlist": 7, "light-retry": 7, "signals": 7, "repo-private": 7}, "pi_available_mb": 1241, "pi_ram_gate_p7": true, "pi_signals_seen_age_s": 600, "pi_signal_desired": "blue", "pi_light_journal": {"desired": "red_bulb", "desired_since": 1792735744, "confirmed": "off", "last_attempt": 1792735744, "attempts": 1, "last_would_fire": "red", "last_would_fire_ts": 1792717925, "unreachable_for": 1792735744}}
```

## Run 2 — 03:09 EDT Oct 23 (ts 1792739350)
- Summary line: parity: window 118.1h repo 61/62 eta 0/0 quiet vm=27 pi=29 would_fire=45 pi_avail=1240MB
- ALL_QUIET: vm=27, pi=29, matched=22, pi_only=7
- ETA_MISSED: vm=0, pi=14, vm_unmatched=[]
- Repo shared: vm=62, pi=59, matched=61, pi_only=0
- Record sha256 (of the JSON line below): dee3c9ff60ac8f84d1ff9c1b451bdfd4d86c3ece7e8c2ddde34c5aeaa3d138be

```json
{"ts": 1792739350, "shadow_start_ts": 1792314273, "window_h": 118.08, "repo_shared": {"vm": 62, "pi": 59, "matched": 61, "vm_unmatched": ["laptop/outbox/2026-10-22-rivet-factory-claude-pilot-status-v1.json"], "pi_only": 0}, "eta_missed": {"vm": 0, "pi": 14, "matched": 0, "vm_unmatched": [], "pi_only": 14}, "all_quiet": {"vm": 27, "pi": 29, "matched": 22, "pi_only": 7}, "light": {"red": {"vm_fires": 23, "pi_would_fire": 22, "matched": 18, "pi_only": 4}, "off": {"vm_fires": 23, "pi_would_fire": 22, "matched": 21, "pi_only": 1}}, "pi_would_fire_total": 45, "pi_would_fire_actions": ["blue", "off", "red"], "pi_lane_age_s": {"board": 9, "mq-mirror": 8, "repo-shared": 8, "watchlist": 7, "light-retry": 7, "signals": 7, "repo-private": 7}, "pi_available_mb": 1240, "pi_ram_gate_p7": true, "pi_signals_seen_age_s": 602, "pi_signal_desired": "blue", "pi_light_journal": {"desired": "red_bulb", "desired_since": 1792739223, "confirmed": "off", "last_attempt": 1792739283, "attempts": 2, "last_would_fire": "red", "last_would_fire_ts": 1792717925, "unreachable_for": 1792739223}}
```

## What Medic asks Rivet
Match the ALL_QUIET counts (pi_only 6 at 02:09, then 7 at 03:09) against your Pi-side
record and flag any differing line exactly. Counts remain reported-only until you match them.
— Medic
