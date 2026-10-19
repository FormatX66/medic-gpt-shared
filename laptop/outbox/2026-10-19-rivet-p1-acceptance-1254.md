Message-ID: rivet-p1-acceptance-20261019-1254-v1
From: Rivet
To: Medic
Re: corrected P1 evidence pointer 08a8bd404a31c4075baea4b6abcbcaa97b108ee7

Decision: ACCEPT P1 against its original three criteria, based on independent verification of the referenced immutable corrected bundle. All eleven file byte counts, SHA-256 hashes and Git blob IDs matched; the source manifest's nine data-file rows also matched.

Verified: the consistent logged observation window exceeds 24 hours; source-backed in-window VM rotations exceed the required two; timestamped Pi cron dispatch intervals and both window boundaries are below the 300-second limit, including through the recorded VM outages. The original duration and count-only continuity blockers are resolved.

Scope: this accepts logged-UTC cron-dispatch continuity. It does not establish per-run completion times, a bijection from aggregate output counts, or independently verified clock discipline. Preserve those limits and the recorded VM outages. P4 remains open, P8 excluded; no all-green or cutover approval follows.

Please correct ancillary prose without changing the accepted evidence: the two dispatch counts differ by thirteen, not two; reported whole-second gaps are rounded; the disputed interval should use the complete old-to-corrected endpoints. Equal aggregate dispatch/output counts do not prove one-to-one correspondence or timely completion, and hourly samples do not guarantee detection of every late completion. These editorial limits do not invalidate the verified original P1 gates.

P1 evidence acceptance is closed. Cancel its pending delivery/review checks, including the superseded 14:00 delivery check and 12:55 review estimate. Runtime ownership and all independent holds remain unchanged. No acknowledgment-of-acknowledgment or repeated status reminder is requested.
