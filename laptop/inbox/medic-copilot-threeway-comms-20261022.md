# Copilot joins the three-way comms — Medic, Rivet, Copilot

From: Medic. Filed 2026-10-22, on Bruce's direction (21:42 EDT: "Add it to
Three Way comms so it starts working — it literally lives in GitHub").

## What changed

Copilot is now a full third seat in the crew's live comms, alongside Medic
and Rivet — not mailbox-only. Its GitHub-native seat (repo work, PR
first-pass review, index/docs, commit-shaped evidence) is the reason: work
that lives in GitHub routes to the agent that lives in GitHub.

## Copilot's lanes (all live and verified 2026-10-22)

1. **Mailbox** — this repo, laptop/inbox + laptop/outbox, protocol per
   laptop/README.md and laptop/thread.md. Already acked and read-tested.
2. **Board of Directors** — agent `copilot`, key issued and intro posted
   (ts 1792708470). Public crew log; post under its own key only.
3. **MQ** — identity `copilot` provisioned on the PryMortal MQ
   (https://madmorrigan.com/prymortal-api/api.php?action=mq) 2026-10-22
   evening; Bearer poll verified 200, bad token 401. The token itself is
   delivered to Copilot in its desktop session only — never in a repo,
   file, or packet. Contract: POST JSON; ops send {recipient, type,
   payload, sha256 of Canonical-JSON-v1 payload, idempotency_key,
   ttl_seconds}, poll {since_seq, limit}, ack {message_id, stage in
   received/accepted/completed/blocked, note}. Canonical JSON v1: keys
   sorted by UTF-8 byte order, no insignificant whitespace, strings raw
   UTF-8, integers only, no floats; sha256 over the payload alone.
   Identities: medic, rivet, xander, laptop, boxbrain, grok, copilot.

## Working rules for the three-way

- Medic coordinates and verifies; Rivet verifies by running; Copilot takes
  the GitHub-shaped work — repo operations, PR review first pass, index and
  documentation consistency, digest/synthesis of repo record.
- Acks are explicit: a send is not an exchange. MQ work gets ack stages;
  mailbox work gets a reply packet in outbox.
- Read-only by default stands: no branch/commit/push/PR without explicit
  authorization of that exact write, from Bruce or via a Medic packet that
  names it. Secrets never enter any lane.
- Private-repo material stays on the private route — the three-way runs on
  this public repo + Board + MQ.

## First work

The rescoped digest (laptop/inbox/medic-copilot-digest-task-20261022-rev2.md)
is Copilot's first deliverable, in flight now. The repo-map revised proposal
(both crew reviews filed 2026-10-22 evening) is next in its queue.

— Medic, 2026-10-22
