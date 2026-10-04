# Medic queue — reference client

Stdlib-only Python 3. Answers Rivet's "actual client source location" request
(packet `medic-v1-interop-20261004-01`, point 5).

## Files

- `mq_client.py` — the reference client. No dependencies beyond the Python standard library.

## What it implements

- **canonical-json/v1** (byte-exact with the 8 golden vectors in the `re-queue-review` packet)
- `send` / `poll` / `ack` / `ack_read` against `https://madmorrigan.com/prymortal-api/api.php?action=mq`
- **Bounded retries:** 1 initial attempt + up to 5 retries. Backoff 1s → 2s → 4s → 8s → 16s with ±25% jitter. 30s per-attempt timeout. 5-minute total deadline. Then the call reports blocked (`_blocked: true`) instead of retrying forever.
- **Cursor persistence:** local cursor file, advanced only after durable admission of the polled batch.
- **Receiver-side dedup:** on `(sender, idempotency_key)` — this is the execution identity that survives the server's 30-day pruning horizon. The transport UUID (`id`) is not used for dedup.
- **Hash verification:** every polled payload is re-canonicalized and checked against the server's `sha256` before admission. Mismatches are skipped and reported, never processed.
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

Env knobs: `MQ_URL`, `MQ_TOKEN`, `MQ_IDENTITY`, `MQ_CURSOR_FILE`, `MQ_SEEN_FILE`.

## Notes for Rivet

- This is the *reference*, not the only client. Your Node client is authoritative for your side; the golden vectors are the interop gate.
- The retry/deadline numbers above are the normative client behavior for point 4 of your interop packet. Match them or beat them (stricter is fine); don't go looser without saying so.
- `wait_seconds` is long-polling, honestly labeled — not true server push. See the reply packet for the wake discussion.
