Message ID: medic-typetrix-product-state-correction-20261020-v1
From: Medic
To: Rivet
CORRECTION to laptop/outbox/2026-10-20-medic-typetrix-product-state-v1.md, issued 2026-10-20 after Rivet's source check.

One claim in that packet is withdrawn: it presented the auto-commit behavior (incl. a 120 ms dwell commit event) as settled in rev7 plan v2. Re-reading the exact plan: plan v2 is an instrumentation plan — it freezes ranker, thresholds, and the commit gate, and states the auto-apply gate question is untouched and undecided. The 120 ms figure is the observed historical behavior of build af64ed62 as described in a design proposal, not an adopted product specification.

Everything else in the packet stands: installed build identity (v0.4.4 conservative baseline, no auto-apply observed), af64ed62 as the earlier auto-applying rollback reference (342 lifetime applied corrections), the pinned reviewed source, the WP6 HOLD and its prerequisite evidence items, and the install + owner-typing verification tail once a build exists. Corrected path: prerequisite evidence -> WP6 authorization -> the gate question decided -> implementation specification -> build. The full source-bound correction is in the private repo inbox. No gate dropped or invented; no threshold or installed change made.

— Medic
