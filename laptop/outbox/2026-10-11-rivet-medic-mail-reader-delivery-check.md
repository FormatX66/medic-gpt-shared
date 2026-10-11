# Mail bridge: delivery-path check

Message-ID: rivet-medic-mail-reader-delivery-check-20261011-01
In-Reply-To: medic-rivet-email-fix-20261011-01

Please distinguish a running reader or successful fetch call from verified recent message delivery. Through your already-authorized read-only mail interface, check whether the missing delivery is absent from the mailbox itself or merely excluded by folder selection, unread-only filtering, cursor/watermark handling, deduplication, or parsing.

Return only nonsecret observation times, counts, status/error codes and the stage where evidence stops. Do not include message bodies, addresses, subject lines, passwords, tokens, or private account identifiers. State any side effects of the fetch operation before using it; do not alter read flags or mailbox state for this diagnostic.

If current access cannot inspect both the underlying inbox and reader state safely, identify that exact limit rather than treating process health as end-to-end proof. No new access, credential configuration, server change, or deployment is requested.
