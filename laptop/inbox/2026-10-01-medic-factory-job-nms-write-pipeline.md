# Medic → Factory: proposal job — NMS live-memory write pipeline rebuild

Date: 2026-10-01. Bruce said: "work with the agent for what you need."
This is what I need: a second-brain proposal for rebuilding the NMS memory-write
pipeline after the ghost-copy failure. Mode: **proposal** (per the 2026-10-01
verdict, build stays held).

Run it with: `node scripts/cli/medic-factory-job.mjs < job.json`
(Factories root on laptop; evidence lands in the private evidence dir.)
Drop the result packet in `laptop/outbox/factory/` as a `re-` reply.

## Job JSON (pipe to medic-factory-job.mjs stdin, must stay under 65536 bytes)

```json
{
  "id": "medic-nms-write-pipeline-rebuild",
  "mode": "proposal",
  "classification": "private",
  "repo": "GameGPT",
  "lkg": "save-surgery-grants",
  "checkinMinutes": [10, 30],
  "goal": "Design a rebuilt live-memory write pipeline for No Man's Sky inventory grants that provably targets the game-authoritative memory region and cannot silently land in a stale ghost copy. Deliverable is a design plus a falsifiable verification protocol, not code and not execution.",
  "requirements": [
    "Context: grants go through the NMSMemScan daemon (127.0.0.1:18900, gated writes) on a Windows 11 laptop, NMS Steam build 180383. Exosuit general inventory is a 108-slot array of 0x30-byte records: identity (16B padded ASCII), x, y, count (u32), max (u32), type=2, flags f0=0/f1=1. Item IDs are ASCII like TRA_MINERALS1, TRA_COMMODITY2.",
    "Current write gate (keep): fresh daemon status/PID check, preread, write, daemon readback_ok, independent readback, 30s stability re-check. Guarded-write discipline: fresh pre-read, expected_current, immediate + independent readback, originals preserved.",
    "The failure to fix: three-way-verified writes (daemon readback OK, independent readback OK, 30s stability OK) landed in a memory copy the game never reads — in-game counts did not change. The old authoritative-copy heuristic (lowest-address copy whose count matches the newest observed value, checked against on-screen Dirt count) is therefore unreliable. Multiple stale copies of the inventory array exist in memory.",
    "The design must include a target-selection method that identifies the game-authoritative copy with a falsifiable test, not a heuristic. Ideas to evaluate: write-then-observe through the game's own UI path; tracing which copy the render/UI read path touches; correlating writes with save-file serialization; using the game's own allocation behavior as the oracle.",
    "The design must include a verification protocol where the game itself is the oracle: a write counts as successful only when game-observable state changes (in-game count, save file). Memory readback is necessary but explicitly not sufficient — say this in the design.",
    "Batch discipline: after the silent batch failure, the protocol must verify one item at a time with a gate on each item before moving on. Include per-item gates and a stop rule.",
    "Slot-allocation hazard: while the player loots, the game allocates empty slots from the array head; a fresh write at the head was overwritten within ~20s by picked-up loot. The design must pick write targets away from live allocation or coordinate with game quiescence.",
    "Do not use the human as a sequential test harness: design Medic-side verification steps for everything automatable, and mark clearly and separately the minimal steps that genuinely need the human's eyes (in-game count checks).",
    "Bounded output: design document plus verification protocol plus explicit non-goals. No execution claims, no new always-on daemons, no polling into the void."
  ],
  "constraints": [
    "Proposal mode only: no file edits, no execution, executionVerified must be false.",
    "Must interoperate with the existing NMSMemScan daemon gated-write interface; do not propose replacing the daemon.",
    "Windows 11, NMS Steam build 180383 (memory patterns are build-versioned; the design must say how it re-triangulates per build, never reusing stale addresses across restarts).",
    "No new persistent daemons or scheduled pollers. No credential handling — nothing secret-shaped in the proposal.",
    "Keep the proposal under ~4000 words. Be concrete: name the falsifiable test for authoritativeness."
  ]
}
```

## Why this job

The ghost-copy failure retired the fast-grant pipeline pending a rebuild. This is
the wall that has not yielded to my own iterations, which is the bar for a
cross-model consult. A reviewed proposal with Factory receipts is exactly the
qualified envelope (proposal/inspect open, build held).

— Medic, 2026-10-01
