# Factory runtime evidence for Medic

This is a sanitized export of the preserved **2026-09-29 real source-qualification run**, prepared on 2026-10-01. No executor was launched during this export. Factory PR [#10](https://github.com/FormatX66/factory-/pull/10) remains draft and unmerged at `9142cfd060ada159ef897801ca2b433dffe78941`.

Both recorded jobs passed on **Linux / Node22.16.0**:

| Job | Passed | Failed / skipped | Attempts |
| --- | ---: | ---: | ---: |
| factory-repair-qualification | 49 | 0 / 0 | 1 |
| validation-adapter-qualification | 19 | 0 / 0 | 1 |

The process intervals overlapped by **217 ms**. Separate verification callbacks checked saved output and hashes. The preserved archive matches the SHA-256 published in [the original verification comment](https://github.com/FormatX66/factory-/pull/10#issuecomment-5898101687): `1147d35a927376e3956b63b799268e3748e8359212dc39f0753a3431bf75e948`.

Read `packet.json`, then each job's `record.json` and `verification.json`. They preserve the job ID, recomputable fingerprint, original schema versions, timestamped lifecycle, test totals, and original content hashes. The initial queued entry is derived from `acceptedAt` and the reviewed controller's initial-state definition; subsequent events are recorded verbatim. The repair recipe's revision is `986bd7a…`; the adapter recipe's revision is its implementation SHA-256. These are manifest recipe revisions, while `9142cfd…` identifies the containing candidate.

Sanitization uses selected fields. Absolute paths, process identifiers, executable identity, invocation arguments and test labels are omitted. No source code, worker responses, environment values, private user content, or raw original archive is included. The original job classification remains `private` because changing it would change the fingerprint; the exported job fields describe fixed source-qualification recipes only.

`stdout.sanitized.tap` preserves numeric results and timing while omitting all test labels. Its hash intentionally differs from the original stdout hash in the verification receipt. `exportedArtifacts` records both hashes. `original-content-hashes.json` identifies original archive members; `SHA256SUMS` seals exported bytes. Original receipts are hash evidence, not signatures or tamper-resistant attestation.

Fresh export checks: **64 passed**, including original archive integrity, 12 canonical source blob/content comparisons, pinned source copies, job fingerprints, lifecycle order, receipt correlation, TAP totals and overlap. The historical 21-check readback and no-relaunch claim remain historical evidence; no replay was attempted. Run `python verify_packet.py` here for independent offline packet checks.

Windows process-tree termination, Windows/Node24 acceptance, live provider failover and Commander parity remain **unrun**. A generic write-capable build executor remains **held/unregistered**. The historical Farmer controller attempt failed before runner assignment and ran zero steps; it is separate from these passing local qualification jobs. No LKG promotion or full-repository qualification is claimed.

Prepared destination: `FormatX66/medic-gpt-shared`, `laptop/outbox/factory/runtime/2026-10-01/`. That repository is **public**. Publication awaits Bruce's confirmation of the exact file set. Nothing was published or delivered to Medic, and publication would not establish Medic acceptance. The current decision matches [Medic's pinned acceptance source](https://github.com/FormatX66/medic-gpt-shared/blob/0b91485daf51b398bd92450f40f9d86e0ba28607/laptop/inbox/2026-10-01-factory-decision.md).
