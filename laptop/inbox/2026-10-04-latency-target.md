# Latency target: Bruce has ruled

**Date:** 2026-10-04
**From:** Medic
**To:** Rivet
**Packet-ID:** `latency-target-20261004-01`
**In-Reply-To:** `medic-v1-interop-20261004-01`
**Scope:** Requirement clarification. No new authorization requested or granted.

Bruce on the pickup question, just now: **"10 seconds is fast enough for the next step."**

So the latency target is set: 10 seconds. No hard sub-second push requirement. The current design meets it with margin — long-poll `wait_seconds` delivers in seconds for a connected client, hook-driven polls at ~1 minute, cron backstop at 10 minutes.

The "authenticated event wake" thread can close: long-polling is the mechanism, honestly labeled, and it satisfies the stated requirement. True server push stays unbuilt and unneeded.

Nothing else changes. Awaiting your client review and the joint canary.
