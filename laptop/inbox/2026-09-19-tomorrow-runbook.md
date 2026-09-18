# Tomorrow runbook — Saturday 2026-09-19 (Bruce at the laptop)

Four jobs, in order. Everything is pre-staged; each step is small. Report
results back to the `laptop/outbox/` as usual (`re-YYYY-MM-DD-<job>.md`).

## 1. NMS Blind Distortion table — manual extraction (replaces the timed-out watch)

The 12-hour extraction watch timed out with no result. Do this by hand:

1. The RAR is in this repo at `laptop/inbox/nms-bd-table/`
   (`tablica-dlja-cheat-engine-upd-07-11-2024_1731065431_411585.rar`).
2. Extract with 7-Zip or WinRAR. **Never open the result in Cheat Engine.**
3. Take the `.CT` file (and any README) and upload to
   `laptop/outbox/nms-bd-table/` in this repo (GitHub web upload is fine).
4. Ping Medic — he runs the inert parse + GameGPT intake from there.

## 2. QPU connectivity check (read-only, zero QPU seconds)

Packet: `laptop/inbox/2026-09-17-qpu-connectivity-check.py`

1. Set a fresh IBM API key **locally on the laptop only** (new key, never
   committed anywhere).
2. Run the script as documented in its header. It exchanges the key for an
   IAM token, lists backends, reads usage. **Submits no job, spends nothing.**
3. Report backends list + usage/quota numbers to
   `laptop/outbox/re-2026-09-19-qpu-connectivity.md`.
4. If `browser_signature_banned` recurs, note it — do not retry in a loop.

## 3. Hub v1.2.4 upgrade — verify or complete

Packet: `laptop/inbox/2026-09-14-hub-v124-upgrade.md` (curl-transport fix for
the IBM 1010 ban). v1.2.0 was verified healthy on 2026-09-13; v1.2.4 status
is unknown.

1. If not yet upgraded, follow the packet steps (back up `.env` first,
   never overwrite it, add `QPU_HTTP_CLIENT=curl`, rebuild).
2. Verify: `GET http://localhost:8090/health` → 200, version 1.2.4.
3. Then: `GET http://localhost:8090/v1/qpu/backends` → expect 200
   (this is the fix proving itself). Same for `/v1/qpu/usage`.
4. Report to `laptop/outbox/re-2026-09-19-hub-v124.md`. No hardware jobs.

## 4. Medic Bridge v1.2.0 — confirm Stage 2

If the extension install / relay rebuild from the v1.2.0 packet was never
finished: re-extract `bridge/medic-bridge.zip` + `bridge/medic-bridge-docker.tar.gz`
from this repo, `docker compose up -d --build` in `C:\Users\bruce\MedicBridge\relay`,
reload the extension in `chrome://extensions`. Send a test drop and confirm
Medic's watcher picks it up.

## Standing rules

- Secrets never enter the repo. The human carries keys.
- Read-only unless a packet authorizes a write.
- Never submit a QPU hardware job to "prove" anything.
- Report exact outputs, not summaries.
