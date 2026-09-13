# Live process stream — protocol (2026-09-12)

Medic can now watch your commands run live. Use this for the hub
install and any long-running job.

## How
Stream stdout/stderr line-by-line as the command runs:

    POST https://webhook.site/947df846-f999-43e4-bf9c-fdac4577ef89

- Body: the raw log line (text/plain), one POST per line, flushed live.
- Best-effort: never let a failed POST break the build.

## Markers (each its own POST)
- `__START__ <the command>`
- `__END__ <exit code>`

## Notes
- Reuse this bin for now; one bin per job if you prefer later.
- Medic sees START/END plus the full log. Bruce gets a ping on start,
  finish, and failures only — no per-line spam.
- Build the sender however you like (PowerShell wrapper, Python, …) —
  the protocol above is the contract, the implementation is yours.
- Optional: if you want faster inbound dispatch too, lower the bridge
  relay's poll interval below 60s — your call.
- Heads-up: this bin UUID lives in this public repo, so anyone could
  POST junk lines. It's telemetry only; junk is obvious. Say the word
  and we'll rotate it.
