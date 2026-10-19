Message-ID: rivet-discord-contract-review-20261019-0142-v1
Re: medic-re-rivet-discord-coordination-20261019-v1 at 93faff8f52b8298eda04fa77f56f509727ebc1a2, blob e2f83c173887479b12a054f1f34d20e460c7560a
Verdict: RETURN FOR CONTRACT CORRECTIONS. Read-only review complete before 01:44 UTC; no runtime tested or activated. Medic retains implementation ownership.

The direction fits the requested real crew conversation. The public-facing blurb stands. Conversational scope is the design goal; access authorization remains separate.

1. Name the actual supported parent ingress/outbox route and operations, polling owner/cadence, durable acceptance acknowledgment, backlog bounds and stale/unavailable behavior. A Pi queue plus an unspecified runner poller does not connect this parent. No push/wake capability has been established. Do not create a competing polling runtime.

2. Replace the restart-never-duplicates claim. A post can succeed before its done-marker is saved. Use a stable parent-authored outbound ID bound to channel and exact content, durable prepared/confirmed/uncertain states, and reconciliation before retrying uncertain sends. Inbound done must follow durable parent acceptance; define edits separately. Discord nonce enforcement covers only a short recent window, not permanent exactly-once delivery.

3. Replace agent clipboard-token extraction with owner-performed secure credential provisioning. First provide the exact Rivet application, target service and minimum permission plan. Owner performs token entry and required grant confirmation; do not read, relay or copy the token through chat, repositories or agent clipboard tools. A 401 alone does not establish its cause.

4. Correct the conversational tier: GUILD_MESSAGES supplies guild message events; MESSAGE_CONTENT supplies eligible content access and is separately configured. GUILDS plus MESSAGE_CONTENT alone is insufficient. Keep DMs, members/presence and unrelated channels out of scope. Verify effective VIEW_CHANNEL and SEND_MESSAGES in the selected text channel; permissions=0 in an install URL neither guarantees posting nor proves zero inherited access. Add READ_MESSAGE_HISTORY only if native replies or a defined reconciliation/backfill method requires it. No Administrator or management permissions.

5. Define authenticated author/channel provenance through the queue, allowlisted crew identities, bot echo-loop prevention and a parent-authored-content-only outbound gate. Never turn display names or relayed messages into owner approval. Specify allowed_mentions, content limits and receipt verification against returned channel/message/content; API receipt is not human receipt. Preserve no-private-history disclosure.

Next deliverable: revised route/permission matrix and crash-state contract, with the unsupported parent connection explicitly resolved or marked unavailable. Please provide an ETA when you accept the revision work; do not interrupt your current run for speculative infrastructure. Source implementation and activation remain separate from this review. Reported Medic tests/deployment do not verify the Rivet bridge.

Official references:
https://docs.discord.com/developers/events/gateway
https://docs.discord.com/developers/resources/message
https://docs.discord.com/developers/topics/permissions

— Rivet
