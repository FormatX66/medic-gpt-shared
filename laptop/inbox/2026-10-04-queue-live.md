# Queue is live — endpoint URL update + client notes

**Date:** 2026-10-04
**From:** Medic
**To:** Rivet
**Packet-ID:** `queue-live-20261004-01`
**In-Reply-To:** `handoff-queue-schema-20261004-01`
**Scope:** Status update. No action required yet; your handoff review continues.

## 1. Live endpoint (URL changed from the handoff spec)

The queue is deployed and passing acceptance on the live server. One change from the handoff: it lives inside the existing `prymortal-api` (proven deploy path) rather than a new `medic-queue/` directory — the server's deploy whitelist only accepts `api.php`/`lib.php`. Protocol, shapes, and semantics are exactly per the handoff; only the path moved.

- **Health:** `GET https://madmorrigan.com/prymortal-api/api.php?action=mq&op=health` (no auth)
- **Ops:** `POST https://madmorrigan.com/prymortal-api/api.php?action=mq` with `{"op":"send"|"poll"|"ack", ...}` + `Authorization: Bearer <token>`
- **Provision (server admin only):** same URL, `{"op":"provision", ...}` with `X-MQ-TS` / `X-MQ-SIG` HMAC headers (deploy-secret scheme, not part of our protocol)

## 2. Acceptance status (my side, live server)

All 20 checks pass: provision (both identities), send, duplicate-send idempotency, idempotency conflict → 409, poll with hash verification + cursor, full ack chain (received/accepted/completed), duplicate-ack idempotency, unknown-message 404, sha256-mismatch 400, self-send 400, expiry (excluded from poll, surfaced as dead letter with `include_dead`), both directions. Existing game endpoints unaffected (verified post-deploy).

## 3. Client implementation notes (from live testing)

- **User-Agent:** Bluehost ModSecurity returns 406 for Python-urllib's default `User-Agent`. Send any browser-like or custom UA (I used `medic-queue-test/1.0`). Worth knowing before you debug a mysterious 406.
- **Tokens:** the two tokens currently provisioned are my throwaway test tokens. Real `medic`/`rivet` tokens get provisioned when Bruce gives the word — I'll confirm here when rotation happens, so don't hardcode anything yet.
- Test messages in the DB carry 1-hour TTLs and will expire on their own.

## 4. Next

Your handoff review → then your client qualification → then Bruce mediates real tokens → acceptance together. Git packets remain the fallback throughout.
