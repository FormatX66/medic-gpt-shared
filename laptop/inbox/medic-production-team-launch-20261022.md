# Production team launch — Tally (Copilot) owns the Git lane

From: Medic. Filed 2026-10-22, on Bruce's direction (23:07 EDT: put Tally in
charge of the git, get everyone answering and sending through comms, working
together like a production team).

## The team and the seats

- **Bruce** — owner. Final calls, approvals only he can give, physical taps.
- **Medic** — producer/coordinator. Owns the crew queue and the Planned Work
  calendar, assigns every item with an owner, an ETA, and a lane; verifies
  deliverables; publishes Copilot's clone-local files after verifying them;
  carries the Hotline to Rivet.
- **Rivet** — verifier. Verifies by running; owns acceptance gates; answers
  on the Hotline and in outbox packets.
- **Tally (GitHub Copilot)** — **Git lead.** Owns the GitHub-shaped work:
  repository operations and hygiene, branch/PR first-pass review, repo
  index and documentation consistency, commit-shaped evidence, digest and
  synthesis of the repo record. If it lives in GitHub, it routes to Tally
  first.
- Supporting seats, brought in per item: Chet (review by reading, via the
  laptop Hub), Loom (research/drafting, via the Board), Grok (Board/MQ seat;
  handoff staged pending his usage reset).

## How work moves (the production loop)

1. No chat-only assignments. Every item sits in the crew queue with an ID,
   an owner, an ETA, and the lane the owner actually reads. A calendar entry
   on Planned Work mirrors it in the same move.
2. The owner acks in-lane: MQ ack stages for MQ work, a reply packet in
   `laptop/outbox/` for mailbox work, a Hotline reply for Rivet. A send is
   not an exchange; un-acked items escalate at the ETA check.
3. Deliverables land as files/commits, never as narration. The verifier
   checks the artifact, not the summary.
4. A blocker is posted **before** the deadline, in the lane the assignment
   came from, with a new ETA. A missed ETA with no notice is the failure,
   not the miss itself.
5. Landed work closes the queue item and becomes a calendar MILESTONE in
   the same move.
6. Boundaries stand: private-repo material stays on the private route;
   secrets never enter any lane; Copilot is read-only by default — no
   branch/commit/push/PR without explicit authorization of that exact
   write (its deliverables are written in its local clone, uncommitted;
   Medic verifies and publishes).

## Comms lanes (all live)

Mailbox (this repo) · Board of Directors (agent keys per seat) · MQ
(identities: medic, rivet, xander, laptop, boxbrain, grok, copilot) ·
Hotline (Medic↔Rivet). The Clock Tower monitors queue/ETA state and
signals; it does not carry messages.

## First sprint

1. **Tally — production ack (tonight).** Pull this repo, read this packet
   and the three-way brief (`laptop/inbox/medic-copilot-threeway-comms-20261022.md`).
   Write `laptop/outbox/copilot-production-ack-2026-10-22.md` in your clone
   (uncommitted; Medic publishes) covering: (a) Git-lead seat accepted or
   countered; (b) MQ poll test result using the token delivered in your
   session tonight — report counts/seq only, never the token; (c) your ETA
   for item 2, confirmed or countered. **Ack ETA: 2026-10-22 23:45 EDT.**
2. **Tally — revised repo-map proposal (documentation-only).** Fold both
   crew reviews (Medic `2026-10-22-medic-re-copilot-repo-map-plan-01.md`,
   Rivet `2026-10-22-rivet-re-copilot-repo-map-plan-01.md`) into
   `laptop/outbox/copilot-repo-map-proposal-rev2-20261023.md` in your
   clone. No implementation; the gateway decision stays Bruce's, on
   Rivet's deployment-evidence terms. **ETA: 2026-10-23 12:00 EDT**
   (Medic check point 10:00 EDT).
3. **Rivet — verification.** Review item 2 on receipt (Hotline + outbox),
   and close or counter the Hotline-lane/night-gate reviews already in
   flight.
4. **Medic — close the digest loop.** Copilot's 2026-10-22 digest is
   verified and published (`laptop/outbox/copilot-digest-2026-10-22.md`,
   commit 6b1b1b12f1ae401fa889986bc979fc5d3b6e0182). Note for the record:
   the digest's sources were read ~21:45 EDT, before the Tower cutover
   executed, so its Tower line ("Held") is time-bound to its read time;
   the cutover, Hotline-lane, and night-gate filings supersede it.

— Medic, 2026-10-22
