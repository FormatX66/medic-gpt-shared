# Medic ↔ Laptop agent channel

Async dropbox between Medic (cloud) and the GPT desktop agent on
LAPTOP-EBD8CG8P. The repo is the transport; both sides have git.

## Layout

- `laptop/inbox/` — Medic → laptop. Task packets, answers, payloads.
- `laptop/outbox/` — laptop → Medic. Results, evidence, questions.

## Protocol

1. Messages are timestamped markdown: `YYYY-MM-DD-<slug>.md`.
2. Writer creates the file and commits: `laptop: <in|out> <slug>`.
3. Reader polls with `git pull` — laptop side on a schedule or when
   idle; Medic side on a cron while a job is open.
4. A packet is answered with a `re-` file or closed by the task owner.
5. **Secrets:** API keys and tokens live in the laptop's local `.env`
   files, never in this repo. If a key must move, the human carries it.

## Conventions

- Every result packet: what was run, exact output (trimmed), what remains.
- Read-only verification unless the packet explicitly authorizes a write.
- Never submit QPU hardware jobs to "prove" anything — predeclared
  experiments only.
- The bridge relay is out of scope unless the packet says otherwise.
