# TASK for GPT — Live read-only AOB sweep (NMS 7.04)

**From:** Medic · **Date:** 2026-09-28 · **Reply to:** `sessions/live-aob-sweep-result-2026-09-28.md` in this repo

## Goal
Resolve 34 AOB signatures against the live NMS.exe process and return a per-entry 0/1/N match table. This converts 34 UNVERIFIED cheat-table patterns into measured build-bound locator candidates. **Read-only. No writes, no injection, no game input.**

## Gate — do this ONLY if all true
- `NMS.exe` is already running on the PC (check task list). If it is NOT running, **stop and report `game_not_running`** — do NOT launch the game.
- GameGPT repo present at `C:\Users\bruce\Documents\GitHub\GameGPT`.
- Do not disturb the resident Future Branch explorer/watchdog or the Farmer supervisor (127.0.0.1:19466).

## How to run
Use the repo's own pipeline — `src/gtp_games/cheat_tables.py`, `inspect_cheat_table_bytes`, live validation ON. Medic's mock run proved this path read-only: writes raise `SafetyError`, scans never execute scripts.
Known repo safety throttle: `script_limit = min(limit, 5)` under live validation (cheat_tables.py:279) — **honor it**: run in batches of at most 5 entries, do not bypass.
Feed it the targets below (id, symbol, module, AOB pattern). For each signature record: match count (0 / 1 / N) and, for matches, the hit address. `0` after a full-image scan = pattern absent in this build; `N > 1` = ambiguous, needs disambiguation.

## Return
Write `sessions/live-aob-sweep-result-2026-09-28.md` in this repo with a table: entry id | description | signature | matches (0/1/N) | note. Plus one line: NMS build string observed and whether the scan covered the full image or was scope-truncated.

## Targets
```json
[
 {
  "id": "2273",
  "description": "Remove ALL Inventory Technology Overloads",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "8B 40 20 48 83 C4 20 5F C3 33 C0"
   }
  ]
 },
 {
  "id": "12172",
  "description": "Unlimited Starship Shields / Pulse Engine / Lunch Thruster / Ammo / Granades",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "0F 11 4B 10 0F 10 45 20 0F 11 43 20 E8"
   }
  ]
 },
 {
  "id": "11940",
  "description": "Instant Interaction with items or creatures (E Key)",
  "scans": [
   {
    "symbol": "AOBWordLearn",
    "module": "NMS.exe",
    "pattern": "F3 44 0F 58 27 F3"
   }
  ]
 },
 {
  "id": "1973",
  "description": "Money - (Access Inventory to Get all Unit Types)",
  "scans": [
   {
    "symbol": "AOBMoneyPointer",
    "module": "NMS.exe",
    "pattern": "45 8B 80 DC C1 00 00"
   }
  ]
 },
 {
  "id": "2140",
  "description": "Get Race & Faction Standings (Takes a few seconds to load up.)",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "48 8B 40 10 0F 28 DE"
   }
  ]
 },
 {
  "id": "11992",
  "description": "Jetpack Speed",
  "scans": [
   {
    "symbol": "forwardforce",
    "module": "NMS.exe",
    "pattern": "F3 0F 10 ?? ?? ?? ?? ?? 0F 10 87 ?? ?? 00 00 48 8D"
   },
   {
    "symbol": "leftrightforce",
    "module": "NMS.exe",
    "pattern": "EB ?? F3 0F 10 05 ?? ?? ?? ?? F3 0F 11 81 ?? ?? 00 00 F3 0F 10 0D"
   },
   {
    "symbol": "upwardforce",
    "module": "NMS.exe",
    "pattern": "F3 0F 10 0D ?? ?? ?? ?? F3 0F 11 89 ?? ?? 00 00 F3 0F 10 05 ?? ?? ?? ?? 48 8B 9C"
   }
  ]
 },
 {
  "id": "11988",
  "description": "Ship Engine Speed",
  "scans": [
   {
    "symbol": "engineControls",
    "module": "NMS.exe",
    "pattern": "F3 0F 58 ?? ?? F3 41 0F 11 ?? ?? C3"
   }
  ]
 },
 {
  "id": "11990",
  "description": "Pulse Engine Speed",
  "scans": [
   {
    "symbol": "actualminiwarp",
    "module": "NMS.exe",
    "pattern": "F3 0F 5F C8 F3 0F 59 0D ?? ?? ?? ?? 0F 28 C1"
   }
  ]
 },
 {
  "id": "2412",
  "description": "Last Moved Item into Slot",
  "scans": [
   {
    "symbol": "LastMovedItem",
    "module": "NMS.exe",
    "pattern": "0F 11 48 10 0F 10 43 20 0F 11 40 20 0F 11"
   }
  ]
 },
 {
  "id": "12053",
  "description": "Take no Damage (Ship and ExoSuit)",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "48 8B C4 4C 89 48 20 44 89 40 18 55 56"
   }
  ]
 },
 {
  "id": "2414",
  "description": "Unlimited Run Stamina",
  "scans": [
   {
    "symbol": "AOBRunStamina",
    "module": "NMS.exe",
    "pattern": "F3 41 0F 5E C0 F3 0F 5C C8 F3"
   }
  ]
 },
 {
  "id": "12170",
  "description": "Unlimited Jetpack Propulsion",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "F3 0F 58 CA F3 41 0F 59 CC F3 0F 59"
   }
  ]
 },
 {
  "id": "2268",
  "description": "Unlimited Marine Jet Propulsion",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "F3 0F 5C CA F3 44 0F 5F C1"
   }
  ]
 },
 {
  "id": "12124",
  "description": "Unlimited Environmental Suit - Oxygen / Thermals / Toxicity",
  "scans": [
   {
    "symbol": "AOBEnvironmentalSuit",
    "module": "NMS.exe",
    "pattern": "40 55 56 57 48 8D 6C 24 B0"
   }
  ]
 },
 {
  "id": "2176",
  "description": "Rocket Launcher - No Cool Down",
  "scans": [
   {
    "symbol": "AOBMissiles",
    "module": "NMS.exe",
    "pattern": "41 C7 84 86 B4 5F 00 00 00 00 80 3F 49 63 86"
   }
  ]
 },
 {
  "id": "2025",
  "description": "Zero Thermal Load (Heat) for Photo Cannon",
  "scans": [
   {
    "symbol": "AOBLaserCoolDown",
    "module": "NMS.exe",
    "pattern": "F3 41 0F 11 8C 86 B4 5F 00 00"
   }
  ]
 },
 {
  "id": "2485",
  "description": "Instant Mining / No Damage To Industrial Waste/ One Shot Kills - Disable/Enable below as desired. (To the right)",
  "scans": [
   {
    "symbol": "AOBMiningDamage",
    "module": "NMS.exe",
    "pattern": "89 77 50 C6 47 48 01 80"
   }
  ]
 },
 {
  "id": "12",
  "description": "No Mining Beam Overheat",
  "scans": [
   {
    "symbol": "AOBMiningBeamHeat",
    "module": "NMS.exe",
    "pattern": "41 0F 28 C5 41 0F 28 F5 F3"
   }
  ]
 },
 {
  "id": "4454",
  "description": "Instant Charge for Blaze Javelin",
  "scans": [
   {
    "symbol": "AOBBlazeAmmo",
    "module": "NMS.exe",
    "pattern": "41 0F 28 F5 48 8B CE F3 0F 58 B6 78"
   }
  ]
 },
 {
  "id": "2450",
  "description": "Instant Identification for Analysis Scanner ",
  "scans": [
   {
    "symbol": "AOBScanner",
    "module": "NMS.exe",
    "pattern": "F3 0F 11 49 24 48 85"
   }
  ]
 },
 {
  "id": "2081",
  "description": "Unlimited Boltcaster Ammo",
  "scans": [
   {
    "symbol": "BOLTCASTERAMMO",
    "module": "NMS.exe",
    "pattern": "41 2B C6 45 8B C6"
   }
  ]
 },
 {
  "id": "2360",
  "description": "Unlimited Topographic Scanner - No Recharge",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "44 89 6E 10 44 89 6E 40"
   }
  ]
 },
 {
  "id": "2489",
  "description": "Unlimited Runic Lens - Cloak",
  "scans": [
   {
    "symbol": "AOBRunicCloak",
    "module": "NMS.exe",
    "pattern": "33 D2 85 C9 0F 4F D1 3B 15"
   }
  ]
 },
 {
  "id": "2240",
  "description": "Crafting consumes no inventory resources",
  "scans": [
   {
    "symbol": "AOBCrafting",
    "module": "NMS.exe",
    "pattern": "44 29 63 18 45 2B FC"
   }
  ]
 },
 {
  "id": "12128",
  "description": "Always have resources for Crafting",
  "scans": [
   {
    "symbol": "AOBAlwaysHaveResource",
    "module": "NMS.exe",
    "pattern": "5B C3 CC CC 4C 89 44 24 18 89 54 24 10 55"
   }
  ]
 },
 {
  "id": "2332",
  "description": "Unlimited Refiner Resources",
  "scans": [
   {
    "symbol": "AOBResources",
    "module": "NMS.exe",
    "pattern": "89 50 18 48 8B 4F 78"
   }
  ]
 },
 {
  "id": "2327",
  "description": "Unlimited Refiner Fuel",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "4C 8B 7C 24 40 89 47 18"
   }
  ]
 },
 {
  "id": "4477",
  "description": "Refiner Finishes Instantly",
  "scans": [
   {
    "symbol": "aob_CalculateRefineTime",
    "module": "$process",
    "pattern": "0F 5B C9 F3 0F 5E C1 48 83 C4 ? 5B"
   }
  ]
 },
 {
  "id": "2307",
  "description": "Unlimited Exocraft Fuel",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "2B CB 85 C9 0F 4E CA"
   }
  ]
 },
 {
  "id": "2292",
  "description": "Unlimited Exocraft Boost",
  "scans": [
   {
    "symbol": "AOBBoost",
    "module": "NMS.exe",
    "pattern": "F3 0F 5C C7 44 0F 2F C0 F3 0F 11 87"
   }
  ]
 },
 {
  "id": "4462",
  "description": "Unlimited Nautilon Boost",
  "scans": [
   {
    "symbol": "INJECT",
    "module": "NMS.exe",
    "pattern": "F3 0F 5C C7 44 0F 2F C0"
   }
  ]
 },
 {
  "id": "11938",
  "description": "True Instant Analysis Scanner",
  "scans": [
   {
    "symbol": "onlykeytoscan",
    "module": "NMS.exe",
    "pattern": "DB 0F 84 48 02 00 00 48"
   }
  ]
 }
]
```