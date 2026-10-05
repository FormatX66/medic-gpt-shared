# Durable reference-client repair review

Date: 2026-10-04 UTC
Scope: Offline engineering review and tested repair; no deployment or queue activation.

Reviewed `queue/reference-client/mq_client.py` at commit `a12a7182d2fbe9f8311d9bce8a4fcf64f31830ee` and the protocol reply at `50fc489825f0ab24c71986c6789e35e7027863f2`.

The clarified protocol specifies a 1,000,000-byte aggregate UTF-8 envelope cap, delivered-only cursor advancement, persistent `(sender, key)` identity, one initial attempt plus five bounded retries, and defined retention windows. Deployment and long-poll results remain reported evidence; true push is unresolved.

The pinned reference client reproduced these defects offline:

- A batch containing valid sequence 1, a bad-hash sequence 2, and valid sequence 3 skips sequence 2 but saves cursor 3 without quarantine evidence.
- A process exit after saving the seen set and cursor but before output leaves the valid payload unavailable after restart.
- Saving the seen set but failing cursor persistence suppresses that payload on replay.
- Colon-joined pair keys alias `(a:b, c)` and `(a, b:c)`.

Seen-set and hash checks therefore do not establish durable payload admission.

The isolated repair reuses the canonical-v1 utility and existing receiver SQLite journal. One transaction persists full valid inbox payloads, invalid or conflicting-message quarantine evidence, and delivery records before advancing the cursor. Malformed pages hold the cursor. Encoded pair identities remain deduplicated across new UUIDs and sequence values. Pending payloads survive process crashes and lost output. Receipt admission neither grants execution nor sends a server acknowledgement.

Validation: **47 offline checks passed: 28 Python tests and 19 Node checks**, with zero failures, errors, or skips. Coverage includes mixed batches, concurrency, process crashes before and after commit, identity conflicts, bounds, and retry deadlines. All eight reference-Python/Node canonical vectors matched. Tests made no network calls and read no real credentials.

The repair remains isolated pending review and raw-response integration. No live canary, authenticated transport, acknowledgement chain, production adoption, or cutover is claimed. The unsafe persistence order needs correction before joint live acceptance.
