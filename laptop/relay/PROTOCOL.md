# Medic Relay Plugin — Protocol v1.0

A structured task relay between Medic (VM) and the laptop agent (ChatGPT desktop app).
Medic writes **tasks**, the laptop agent executes them and writes **results**.
No raw shell crosses the wire. No human in the loop.

## Why this exists

Medic cannot directly execute commands on the laptop (safety). The desktop app
can, but has no API Medic can call. This plugin is the bridge: a durable,
auditable task queue they both share.

## The queue

**Location:** GitHub repo `FormatX66/medic-gpt-shared`, directory `laptop/relay/`

- `laptop/relay/inbox/` — Medic writes `task-<id>.json` here.
- `laptop/relay/outbox/` — Laptop agent writes `result-<id>.json` here.
- `laptop/relay/archive/` — Completed pairs moved here (by Medic).

**Poll cadence:** Laptop agent checks inbox every 30 seconds. Medic checks outbox
every 1 minute. (Tightened 2026-09-19 per ensemble review — zero-complexity speedup.)

## Task format

`laptop/relay/inbox/task-<YYYYMMDD>-<NNN>.json`:

```json
{
  "id": "task-20260919-001",
  "created": "2026-09-19T14:55:00Z",
  "from": "medic",
  "title": "Fix sleep settings (P0)",
  "description": "Prevent the laptop from sleeping or locking during long runs.",
  "objectives": [
    "Set AC standby timeout to never",
    "Set AC hibernate timeout to never",
    "Set AC monitor timeout to never",
    "Verify with powercfg /query"
  ],
  "constraints": [
    "Do NOT enable Windows auto-login",
    "Reversible changes only"
  ],
  "priority": "P0",
  "timeout_minutes": 30,
  "status": "pending"
}
```

**Timeout:** `timeout_minutes` is the max time the laptop agent may spend. If it
expires with no result, Medic marks the task `timeout` and re-queues or escalates.
The agent should also write a `heartbeat` (see below) so Medic can detect a hang
before the timeout.

**Rules:**
- `objectives` are WHAT, not HOW. No shell commands. No PowerShell. The laptop
  agent decides the implementation.
- `constraints` are hard boundaries. The agent must respect them or refuse the task.
- `status`: `pending` → `claimed` → `done` | `failed` | `refused`.

## Result format

`laptop/relay/outbox/result-<id>.json`:

```json
{
  "task_id": "task-20260919-001",
  "completed": "2026-09-19T15:05:00Z",
  "status": "done",
  "summary": "All three AC timeouts set to 0 (never), verified via powercfg /query.",
  "evidence": [
    "Standby (AC): 0",
    "Hibernate (AC): 0",
    "Monitor (AC): 0"
  ],
  "notes": "Lock screen left enabled (requires admin policy change; flagged for Bruce)."
}
```

**Rules:**
- `status`: `done` (all objectives met), `partial` (some met, notes explain),
  `failed` (could not complete, notes explain why), `refused` (constraint violation
  or safety refusal, notes explain).
- `evidence` is concrete output, not claims. Command output excerpts, file paths,
  screenshots described — something Medic can verify.
- Never claim success from "command ran." Show the verification.

## Heartbeat (reliability)

The laptop agent writes `laptop/relay/heartbeat.json` every 30 seconds:

```json
{
  "at": "2026-09-19T19:20:00Z",
  "status": "working",
  "current_task": "task-20260919-002"
}
```

`status`: `idle` | `working` | `stuck`. If Medic sees a heartbeat older than
2 minutes, it marks any `claimed` tasks as `timeout` and re-queues them.
This solves the hang-forever problem (laptop sleeps mid-task, network drops).

## Safety

1. **No raw commands.** If a task contains shell/PowerShell, the laptop agent must
   refuse it. Tasks describe outcomes.
2. **Constraints are absolute.** If a task asks to violate a constraint, refuse.
3. **Destructive actions** (delete, format, registry writes outside the task scope)
   require explicit `destructive: true` in the task AND Bruce's approval. The agent
   must not infer it.
4. **Secrets** never go in tasks or results. If a task needs a credential, it says
   `needs_credential: "description"` and waits for Bruce.
5. **Audit.** Every task and result is a git commit. Full history, blame, rollback.

## Lifecycle

1. Medic writes `task-<id>.json` with `status: pending`, commits, pushes.
2. Laptop agent polls, finds pending task, updates to `status: claimed` (commit).
3. Agent executes using its own judgment within objectives + constraints.
4. Agent writes `result-<id>.json`, updates task to `done`/`failed`, commits, pushes.
5. Medic polls, reads result, archives the pair, proceeds.

## Bootstrap (one-time, Bruce)

Tell the desktop app:

> "Poll the GitHub repo FormatX66/medic-gpt-shared, folder laptop/relay/inbox/,
>  every 2 minutes. When you find a task-<id>.json with status pending, do the task
>  following the protocol in laptop/relay/PROTOCOL.md, and write the result to
>  laptop/relay/outbox/. You have my standing approval for P0/P1 tasks that follow
>  the protocol. Ask me only for destructive actions, credentials, or costs."

After that, Bruce is out of the loop.
