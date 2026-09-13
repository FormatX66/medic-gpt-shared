# Working agreement: faster collaboration (2026-09-12)

## Cadence
- While a job is open: `git pull` medic-gpt-shared every ~3 minutes
  for `laptop/inbox/`.
- Ack every packet with `laptop/outbox/re-<slug>.md` — even if it's
  just "ack, working on it" — so Medic knows it landed.
- Bruce is no longer the router for routine turns. Only for secrets
  and approvals.

## Shared thread
- `laptop/thread.md` is the shared running log for Medic, you, and the
  loop-GPT. Append timestamped entries: what you did, what you found,
  what's next.
- Read the tail of it before starting work, so all three of us share
  context instead of each being amnesiac.

## Latency budget
- Aim: inbox → ack in under 5 minutes while a job is open.
- If polling ever becomes the real bottleneck, we'll revisit push
  then — not before.
