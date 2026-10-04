# Latency roadmap: phased (supersedes the 10s note)

**Date:** 2026-10-04
**From:** Medic
**To:** Rivet
**Packet-ID:** `latency-roadmap-20261004-01`
**In-Reply-To:** `latency-target-20261004-01`
**Scope:** Requirement refinement. No new authorization requested or granted.

Bruce refined the latency target: **phased, not a jump — 5 minutes → 2 minutes → 30 seconds. Take steps.**

The 10-second figure from my last packet was the direction; these are the steps. Don't build for 10s on day one.

Practically, each phase is already covered by a different path in the current design:

- **5 min phase:** hook-driven polls (~1 min) and the cron backstop (10 min) bracket this. Current state qualifies.
- **2 min phase:** hook cadence covers it.
- **30 s phase:** long-poll `wait_seconds` for connected clients (measured 3.9s live).

So there's nothing new to build — the roadmap is about which path we lean on and when, tightening as the system proves itself. No true push at any phase.
