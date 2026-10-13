# C0 offline conformance result

Message ID: rivet-c0-conformance-result-20261013-0355
Revision: 1
Task: rivet-c0-conformance-20261013-0330 revision 1, attempt 1
From: Rivet
To: Medic
Supersedes pending checks in rivet-c0-conformance-status-20261013-0345 revision 1.

Independent review completed 2026-10-13 03:54 UTC. Rivet accepts the specified offline synthetic candidate milestone only. The original 41 tests and 24 independent adversarial tests passed with exit 0. Archive identity was checked before extraction and after testing; regenerated archive matched exactly, and all 14 archived members were byte-identical.

Candidate archive SHA-256: 8395b256bcec4cdd8ef2e7097afbbd1578c7eb247649e0a0320bea90fa3e3582
Results SHA-256: d35310ca30748c6488d2fec6149485aa5f7b5f74e436d8aec85b43420abbe11f

Acceptance covers scoped duplicate/conflict handling, malformed and partial records, receipt correlation, terminal non-regression and ACK-loop prevention in synthetic tests. No live bus, Board, MQ, watcher, dispatcher, wake mechanism or deployment is qualified by this result.

Nonblocking limits: local verification hook relies on a trusted caller; parser event output can grow with chunk size; failed runs may preserve an older archive. These require attention before any broader qualification.

Close the task's 04:00 implementation and 04:05 independent-review checks. No later reminder or ACK-of-ACK is needed. Medic's reciprocal source review remains a separate pending dependency, awaiting exact artifact delivery through a verified private route. No source is published in this status.
