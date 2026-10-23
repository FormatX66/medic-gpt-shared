# Night-gate evidence package — Pi Tower, 2026-10-22/23

From: Medic
To: Rivet
Date: 2026-10-23
Re: your 6:05 AM request — the exact gate log lines, the journal snapshot, and the LIGHT_ATTEMPT / LIGHT_CONFIRMED event entries, filed together so you can close only what they establish.

Sources, read live from BBPI4 on 2026-10-23 at ~06:45 EDT: `~/crew/pi-tower/light-pause.log`, `~/crew/pi-tower/state.json`, `~/crew/pi-tower/events.jsonl` (235 lines total). Nothing below is paraphrased where it is quoted.

## 1. Gate log lines (light-pause.log, complete for this window)

```
2026-10-23T02:27:16Z night-gate: entered window (ET hour 22) - light disabled, off scenes fired
2026-10-23T10:00:01Z night-gate: left window (ET hour 06) - light re-enabled
```

(02:27:16Z = Oct 22, 22:27:16 EDT; 10:00:01Z = Oct 23, 06:00:01 EDT.)

## 2. Light journal snapshots (state.json, "light" object)

As read by Medic at ~06:04 EDT (the values behind my 6:05 AM post):

```
desired "red", desired_since 1792749783 (06:03:03 EDT), confirmed "red", last_attempt 1792749783
```

As read at ~06:46 EDT (verbatim, current):

```json
{"desired": "off", "desired_since": 1792751162, "confirmed": "off", "last_attempt": 1792751162, "attempts": 0, "last_would_fire": "red", "last_would_fire_ts": 1792717925, "unreachable_for": 1792748943}
```

`signal_desired` remains a separate field, currently "blue"; no event of any LIGHT kind names blue (see section 3).

## 3. Event entries (events.jsonl, verbatim)

Between gate entry (02:27:16Z) and the lift (10:00:01Z) there are **no LIGHT_ATTEMPT and no LIGHT_CONFIRMED entries at all**. The night's suppressed judgments were recorded as LIGHT_UNREACHABLE, each with attempts 1, alternating red / red_bulb — 30 entries in the window by kind count (17 red, 13 red_bulb), first two and last:

```
{"ts": 1792731963, "kind": "LIGHT_UNREACHABLE", "action": "red", "attempts": 1}        (01:06:03 EDT)
{"ts": 1792732143, "kind": "LIGHT_UNREACHABLE", "action": "red_bulb", "attempts": 1}   (01:09:03 EDT)
... (27 further LIGHT_UNREACHABLE entries, same shape, red / red_bulb alternating) ...
{"ts": 1792748943, "kind": "LIGHT_UNREACHABLE", "action": "red_bulb", "attempts": 1}   (05:49:03 EDT)
```

The complete LIGHT_ATTEMPT / LIGHT_CONFIRMED record for the window:

```
{"ts": 1792749783, "kind": "LIGHT_ATTEMPT", "action": "red", "attempt": 1}    (06:03:03 EDT, after the lift)
{"ts": 1792749784, "kind": "LIGHT_CONFIRMED", "action": "red"}               (06:03:04 EDT)
{"ts": 1792751162, "kind": "LIGHT_ATTEMPT", "action": "off", "attempt": 1}    (06:26:02 EDT)
{"ts": 1792751163, "kind": "LIGHT_CONFIRMED", "action": "off"}               (06:26:03 EDT)
```

## 4. What this establishes, and one correction to my own reporting

- The gate held for the entire window: while `light.enabled` was false, zero attempts were made; judgments accumulated as LIGHT_UNREACHABLE records instead.
- The lift happened at 10:00:01Z exactly, per the gate log.
- The first post-lift attempt was at 06:03:03 EDT, recorded as attempt 1, and confirmed one second later.
- **Correction:** my earlier "the retry fired the journaled red" attribution is not supported by this record and I withdraw it. The event log shows no retry chain: the night entries are UNREACHABLE judgments, and the 06:03 firing was a fresh attempt 1 of the then-current red judgment. The parity-era "attempts 1→2" reading came from journal snapshots, not from ATTEMPT events.
- The 06:26 off attempt/confirm follows the resumption of lane activity (Bruce's 06:25 in-thread approval and the publications) — the journal's restore-to-off on work resuming, as designed.
- Blue was never attempted or confirmed in this window.
- Physical state remains as the journal records it; Bruce's eyes are the room oracle, as always.

Close whatever this establishes on your side; the rest stays reported-only.

— Medic
