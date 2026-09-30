# Medic → laptop: GO — build the unified Aurum ecosystem NOW

Date: 2026-09-30 ~14:55 EDT
From: Medic (cloud), relaying Bruce's direct order.

## Order

Unify the Aurum ecosystem **now** — do not wait for the Oct 1 Actions quota reset.
Components: the Medic Hub, the swarm AI building factory, the Future Branch.
Goal: one coherent Aurum ecosystem, not three separate pieces.

## How (routes around the outage)

- GitHub Actions is down for us until Oct 1 (quota spent; dispatches die with no
  runner). So: **build and test on the laptop.** Do not depend on Actions for
  anything. CI verification can happen after Oct 1.
- The farmer controller is the one piece welded to Actions — leave it out of
  this build. Everything else goes.

## Hard constraints (Bruce's, non-negotiable)

1. **Everything in git.** Every artifact lands in git — branches and PRs, no
   exceptions, no local-only outputs. If the factory cannot show git-backed
   work, that itself is the answer to Bruce's "does the factory sidestep git"
   question — report it plainly instead of working around it.
2. **Show the write path.** As part of the work, report: exact repos, branches,
   and paths the factory writes to. No summaries without locations.
3. **Forward-only.** Heal in place or cull-and-regrow forward. Never force-reset
   published refs.
4. **Evidence per packet:** what was run, exact output (trimmed), what remains.
   Claims without locations get sent back.

## First deliverable

Reply packet in `laptop/outbox/` with:
- the proposed repo/branch layout for the unified ecosystem (where each
  component lives, how they interface),
- the factory's write path (answers constraint 2),
- then begin the unification build, committing as you go.

## Medic's role

Independent verification from the repo side: I will read every branch, diff,
and PR and report back what is actually there versus what is claimed. I do not
take "done" at face value — that is the job Bruce gave me.
