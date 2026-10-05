# GameGPT research drop — weekly sweep 2026-10-05

From Bruce: "send the research to rivet for game gpt."

## What's here

- `NMS-BD-CT-V3.6.3.2026-09-30.CT` (109 KB) — Blind Distortion's No Man's Sky cheat table v3.6.3, pulled from the GamePressure mirror (no login needed). Matches game patch 7.05 (released 2026-09-30).
- `NMS-BD-CT-V3.6.3.2026-09-30.json` (19 KB) — safe parse (XML + regex only, no Lua/AA executed): 41 entries, 32 Auto Assembler scripts, 33 AOB scans. **UNVERIFIED** — every address/pattern must be confirmed against the running game before GameGPT profile use.

## Sweep highlights (full notes in FormatX66/GameGPT, branch recovery/consolidated-20260912)

**NMS — busy week:**
- Patch 7.05 (Sep 30): beacon milestone fix, new in-game "reset space station base" option, alliance-scoring rebalance, corvette/derelict-freighter fixes, multiplayer networking exploits resolved. Tempo is fast: 7.0 → 7.05 in 21 days.
- Table v3.6.3 fixes: exocraft-creation crash (v3.6.2), terrain-manipulator crash + unlimited health/ship shields rework (v3.6.3). Same 41-entry set as v3.6.1 — crash fixes, not new cheats.
- NomNom 7.00.2: new "make Space Station claimable" button.
- Cheat Happens is tracking Cosmos builds (correction: earlier "stale" notes were wrong).
- 7.05 closed multiplayer networking exploits — cheat work stays single-player/offline.

**Small games — unchanged:** Joe Danger (build 166135), JD2 (169155), Last Campfire (7473523). No new tables.

**Light No Fire — still unreleased.** No date. Game Awards Dec 10 is the next plausible news window (speculation).

## For the factory / write-pipeline work

The parsed JSON is the machine-readable piece: entry descriptions, types, AOB patterns, script counts. Treat everything as UNVERIFIED until it's confirmed against a live game instance — the parse is structural, not behavioral.

Outstanding: BigJit901's force-allow-craft-items script (no standalone file found), one Last Campfire table behind a forum login.
