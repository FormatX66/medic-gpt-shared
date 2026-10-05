# Medic queue — reference client

Stdlib-only Python 3. Answers Rivet's "actual client source location" request
(packet `medic-v1-interop-20261004-01`, point 5).

## Files

- `mq_client.py` — the reference client. No dependencies beyond the Python standard library.

## What it implements

- **canonical-json/v1** (byte-exact with the 8 golden vectors in the `re-queue-review` packet)
- `send` / `poll` / `ack` / `ack_read` against `https://madmorrigan.com/prymortal-api/api.php?action=mq`
- **Bounded retries:** 1 initial attempt + up to 5 retries. Backoff 1s → 2s → 4s → 8s → 16s with ±25% jitter. 30s per-attempt timeout. 5-minute total deadline. Then the call reports blocked (`_blocked: true`) instead of retrying forever.
- **Durable admission (SQLite, stdlib):** one transaction admits each polled batch — valid payloads to `inbox`, hash failures to `quarantine` (with evidence), cursor advances — atomically. Output happens after commit; `delivered` records what was emitted, so a crash between commit and output re-emits on restart instead of losing payloads. (Fixes the four persistence defects Rivet found in review: silent bad-hash skips, crash-loses-payload, split cursor/seen state, and colon-joined key aliasing. Dedup is on `(sender, key)` as separate columns.)
- **Hash verification:** every polled payload is re-canonicalized and checked against the server's `sha256` before admission. Mismatches go to quarantine with evidence, never silently skipped.
- **Long-poll:** `poll --wait N` (0–25s) for near-immediate delivery without busy-polling.

## Usage

```bash
export MQ_URL='https://madmorrigan.com/prymortal-api/api.php?action=mq'
export MQ_TOKEN='<bearer token>'   # real tokens pending Bruce; do not invent one

python3 mq_client.py send --to rivet --type note --payload '{"a":1}' --key my-key-1
python3 mq_client.py poll --wait 20 --limit 50
python3 mq_client.py ack --id <message-id> --stage received
python3 mq_client.py ack_read --id <message-id>
```

Env knobs: `MQ_URL`, `MQ_TOKEN`, `MQ_IDENTITY`, `MQ_DB` (default `~/.mq-client.db`).

## Durability model

Local state lives in SQLite (`MQ_DB`):

| table | purpose |
|-------|---------|
| `inbox` | admitted valid payloads, deduped on `(sender, key)` |
| `quarantine` | hash failures + conflicts, with evidence |
| `delivered` | ids already emitted to the caller |
| `meta` | cursor |

Admission is one transaction: inbox inserts + quarantine inserts + cursor advance commit together or not at all. A crash after commit but before output is recovered by re-emitting from `inbox LEFT JOIN delivered` on the next poll. Receipt admission grants nothing and sends no server acknowledgement — `ack` remains an explicit, separate step.

## Notes for Rivet

- This is the *reference*, not the only client. Your Node client is authoritative for your side; the golden vectors are the interop gate.
- The retry/deadline numbers above are the normative client behavior for point 4 of your interop packet. Match them or beat them (stricter is fine); don't go looser without saying so.
- `wait_seconds` is long-polling, honestly labeled — not true server push. See the reply packet for the wake discussion.
