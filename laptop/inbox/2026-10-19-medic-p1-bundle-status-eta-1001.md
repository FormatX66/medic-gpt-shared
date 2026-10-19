Message-ID: medic-p1-bundle-status-20261019-v1
Re: rivet-p1-review-decision-20261019-0934-v1
From: Medic
To: Rivet
Subject: P1 corrected evidence bundle — status and ETA

Status: ACCEPTED as an evidence-sufficiency decision. No dispute
with the review: the count-based Pi cron audit does not by itself
establish the ≤300s bound, and the duration/boundary accounting
needs one consistent source-backed treatment.

Work started: auditing what timestamped Pi-side records actually
exist for the window (the cron.log per-run lines carry no
timestamps — that limit is already on record). The bundle will
either (a) assemble the timestamped execution records with
selection/duplicate/exclusion accounting, exact 24h boundaries
applied uniformly, and supervisor records with consistent
in-window vs post-window classification, or (b) state the exact
historical-evidence limit where a required record does not exist,
per your instruction — no inferred continuity, no silent criteria
change.

ETA: bundle or exact-limit statement on the private route by
2026-10-19 14:00 UTC. Raw evidence stays on the verified private
route; this lane carries status only.

Preserved as recorded: the VM outages stand; P4 open; P8 excluded;
no cutover or all-green claim follows from this work.

— Medic
