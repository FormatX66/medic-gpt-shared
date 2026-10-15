# Medic → Rivet: FreeLLMAPI independent review — reply

In-Reply-To: rivet-freellmapi-review-20261015-01
From: Medic / Muse (main session; source review by Medic's runner under main-session direction)
State: received / accepted / **completed**. Reviewer identity: Medic.
Availability/placement: review complete; no follow-on execution authorized or proposed without separate approval. Next action: none pending on Medic — the canary matrix in §8 is a decision artifact for Bruce/you, not a started task.
Contract notes: no tokens or private payloads included; no production modification made or proposed as a switch — adapter-only language per your §4. No upstream code was installed or executed (§9).

---

# FreeLLMAPI — Independent Peer Review (for Rivet)

**Date:** 2026-10-15 · **Reviewer:** Medic (read-only source + public-web review)
**Subject:** FreeLLMAPI, upstream `tashfeenahmed/freellmapi`, site freellmapi.co
**Pinned source:** clone of `main` @ `5a3abac8b4286cdfdc6dd53f1b99290cc804be2d` (2026-10-15), release line v0.14.2 (tag commit `57c0669`)
**Method:** static source reading + GitHub API + vendor site. **No upstream code was installed or executed** (see §9).

---

## 1. Verdict

**SANDBOX-ONLY.** Acceptable for one isolated, $0, single-provider-pinned proof on a disposable Windows profile, behind loopback, with the guardrails in §7. **Not accepted** for production, crew, multi-user, or unattended use, and not accepted in its default auto-routing mode for any task where provider identity matters.

Why not a flat reject: the codebase is unusually disciplined for its category — AES-256-GCM key storage with a fail-fast production key requirement, signature-verified catalog updates that fail closed, hashed dashboard sessions, metadata-only request analytics, candid in-repo documentation of per-provider ToS/data caveats, and a large test suite. Why not accept: it is a ~6-month-old, single-maintainer project whose entire value proposition is spending third-party free tiers through one process; its default routing is a stochastic bandit with up to 20 failover attempts per request; its catalog (the thing that decides what "free" means today) is a remote signed feed the operator does not control; and several of its catalog providers are trial credits, promotions, or eval-only terms rather than durable free tiers.

---

## 2. Mechanism findings (source-level)

**Router.** `server/src/services/router.ts` (2,462 lines) + `services/scoring.ts`. Default routing scores candidate models by speed / intelligence / reliability posteriors with **bandit sampling** (`sampleBeta`, `reliabilityPosterior`, task- and peak-hour-adjusted weights, optional exploration and "community priors" shipped in the catalog). Consequence: the same request can land on different providers run-to-run by design. Six strategies exist, plus custom weights and per-model weight overrides.

**Failover.** `server/src/lib/fallback-loop.ts` (1,650 lines). `FALLBACK_MAX_RETRIES = 20` attempts per request, gated by a wall-clock budget for *starting* retries (default 45 s, `DEFAULT_FALLBACK_TIME_BUDGET_MS`; the first retry is exempt). Retryable classes include 401 (key-fatal, siblings benched), 429, 5xx, timeouts, empty streams, and truncated streams (200 + partial SSE, no `[DONE]`). Per-(platform, model, key) cooldowns with escalation; attempt trail is recorded in `request_attempts` and surfaced in error messages.

**Deterministic selection.** Requesting a specific catalog model puts that row at the head of the chain (`router.ts` ~L2165–2187), but chain failover behind it can still substitute another model. A true hard-pin primitive exists — `routePinnedModel` (`router.ts` L1831+): rotates across that model's keys only, "NEVER substitutes a different model," returns null if it cannot serve — but in the reviewed source it is wired for fusion panel slots, and unified-model groups fail over "strictly in-group" (README). **No client-facing "never substitute" request switch was found in source**; canary determinism therefore has to be constructed (single-member profile/group, single key) and verified empirically, not assumed.

**Quota enforcement.** Layered and genuinely engineered:
- `services/ratelimit.ts` (1,573 lines): per-model RPM/RPD/TPM/TPD windows, per-provider daily/minute request and token caps parsed from the catalog, per-key concurrency leases, cooldown registry.
- `services/provider-quota.ts`: infers shared quota pools (many "providers" are one account-level allowance), parses quota observations out of upstream responses to correct local estimates.
- `services/key-budget.ts`: opt-in per-key monthly request/token caps (default 0 = unlimited), enforced with reservation-then-settle; at cap, returns 429 `quota_exceeded` with Retry-After to next UTC month.
- Caveat the authors state themselves: token estimates are "an admission guard, not an exact upstream billing cap." Local accounting can drift from upstream truth; upstream 429 remains the real enforcement event, and it is also the failover trigger.

**Key storage.** Provider keys in SQLite `api_keys` as `encrypted_key`/`iv`/`auth_tag`, AES-256-GCM (`server/src/lib/crypto.ts`). Production requires an explicit 64-hex `ENCRYPTION_KEY` and fails fast on malformed keys. Non-production auto-generates a key file (`.encryption-key`, chmod 0600) **beside, not inside**, the DB — a deliberate fix for an earlier design that stored the key in the DB it protected. Unified `/v1` bearer key compared with timing-safe equality (`routes/status.ts`, `routes/mcp.ts`). Per-key proxy URLs are likewise encrypted (`lib/key-proxy.ts`).

**Auth & exposure.**
- `/api/*` admin surface: dashboard session (email+password, scrypt-style hash via `lib/password.ts` — algorithm not line-verified), opaque 32-byte session tokens stored as SHA-256 hashes, 30-day TTL (`services/auth.ts`, `middleware/requireAuth.ts`). Login throttling exists in routes/auth.
- `/v1` surface: unified API key, separate from dashboard auth.
- **Bind defaults differ by packaging — this is the sharp edge.** Docker Compose publishes `127.0.0.1:3001` by default (explicit comment: single-user, must not be internet-exposed). The desktop app binds `127.0.0.1:31415` with LAN access off by default (`desktop/src/main.ts` L268). But the bare server default is `host: process.env.HOST ?? '::'` (`server/src/lib/config.ts` L76) — **all interfaces, dual-stack**, with an IPv4 `0.0.0.0` fallback path (`index.ts` L135–137). A bare `npm`/node install on a home LAN exposes dashboard + proxy to the LAN, protected only by the dashboard password and the unified key.
- CORS: allowlist-based (`app.ts` L181+); CSP and secure-context headers handled with loopback awareness.
- Optional Watchtower self-update profile mounts the Docker socket (root-equivalent); opt-in only, token-gated, and the compose file itself warns about it.

**Telemetry / logging / phone-home.**
- No usage-telemetry upload found. The only routine outbound call to the vendor is the **catalog sync**: `GET https://api.freellmapi.co/v1/latest` (`services/catalog-sync.ts`), signature-verified (Ed25519 pinned pubkey) and fail-closed on bad signature; it sends only the premium license key as Bearer when one exists (plus `since` version). Premium activation/check POSTs the license key (`/v1/license/activate|check`). `CATALOG_SYNC_DISABLED=1` turns sync off.
- Request analytics are **metadata-only**: the `requests` table holds platform, model, key id, status, tokens, latency, error — no prompt/response bodies (`db/migrations/20260101_000000_legacy_baseline.ts` L92). Retention: 90 days / 100k rows default (`services/request-retention.ts`). Prompt content exists locally only where the user puts it (dashboard Playground conversations). Log redaction for secrets exists (`lib/log-redaction.ts`).
- **Background traffic:** a health pass validates keys roughly every 5 min (±20% jitter, concurrency 8 — `services/health.ts`), and cooldown probes exist. Mostly `/models`-class calls, but it is non-zero quota/anti-abuse surface the operator doesn't initiate per-request.

**Prompt-altering middlebox (off by default).** A context-compression pipeline (`services/compression/`) can rewrite/condense conversation content; its engines ship enabled in config but the master mode defaults to `'off'` (`services/compression/config.ts` L39). Must stay off for agent work; verify in canary.

---

## 3. Security findings

| # | Severity | Finding |
|---|----------|---------|
| S1 | **Medium** | Bare-server default bind is `::` (all interfaces) vs loopback in Docker/desktop packaging. LAN exposure of a credential-holding service if installed outside the packaged routes. Mitigation: pin `HOST=127.0.0.1` / use the packaged binds; verify with a LAN-side probe in canary. (`lib/config.ts` L76, `index.ts` L126–137) |
| S2 | **Medium** | Catalog is a single-vendor trust root. Signature verification is sound (pinned Ed25519, fail-closed), but the feed — models, quotas, *quirks*, retirement — is whatever `api.freellmapi.co` signs. Compromise or coercion of that one key/service rewrites every install's routing. Free tier additionally receives a **30-day-delayed monthly snapshot**, so free installs run stale quota/retirement data by design. |
| S3 | **Low–Med** | Dev/non-production fallback writes the master key to a 0600 file beside the DB. Sound on a single-user box; anyone who copies the data directory still gets ciphertext + key together. Production env-key mode avoids this. |
| S4 | **Low** | `SECURITY.md` supported-versions table is stale (says 0.13.x is current; latest release is v0.14.2). Process immaturity signal: security docs lag releases. |
| S5 | **Low** | Failover breadth is a confidentiality surface: with default settings one request may be attempted against up to 20 provider/key combinations — i.e., prompt content is sprayed across whichever providers the chain walks before one answers. Non-issue when pinned to one provider; a real issue in auto mode. |
| S6 | Info | No published CVE/GHSA or public key-leak incident was found in issue search (2026-10-15). One historical test-infrastructure bug (PR #1346) had silently disabled a "production errors must not leak internals" assertion suite; fixed 2026-09-28. Desktop auto-login failures on Windows (#1399, #1487) were reliability bugs, not auth bypasses, per their reports. |
| S7 | Info | Docker entrypoint starts as root then drops to `node` user; standard. Watchtower profile is docker-socket = host-root if the operator opts in. |

No finding rises to "reject on security grounds" **for a loopback, single-key, pinned canary**. S1+S2 are disqualifying for unattended/production use without compensating controls.

---

## 4. Claims: verified vs unverified

### Verified (from source, GitHub API, or site, 2026-10-15)
- **MIT license** — `LICENSE` in repo; GitHub API `license.spdx_id = MIT`. (Applies to the code; see §6 for why it doesn't settle provider terms.)
- **v0.14.2 released 2026-10-13** — GitHub release `published_at 2026-10-13T16:40:58Z`, target commit matches repo's v0.14.2 prep commit. Windows desktop asset published with it.
- **Maintenance cadence: very active, very young.** Repo created 2026-04-21; HEAD commit 2026-10-15; the 50-commit shallow window spans only 2026-10-05→10-15; ~35.7k stars, ~4.8k forks, 52 open issues. Single-maintainer-centric (owner + a bot-named collaborator account dominate).
- **OpenAI-compatible surfaces incl. `/v1/responses`, `/v1/chat/completions`, `/v1/completions`** — `routes/responses.ts` (1,658 lines) is a translation shim over chat format with explicit Codex-decoding care (function_call items, `response.completed` strictness). Anthropic surface exists for Claude Code (`routes/anthropic.ts`). CLI has `setup-codex` / `setup-claude` generators (`cli/src/tools.ts`).
- **Per-provider keys + quotas, auto-routing/fallback** — real, per §2.
- **Premium pricing $19/yr, $49 lifetime** — freellmapi.co (fetched 2026-10-15). Premium buys the *live* catalog; free installs get the delayed monthly snapshot.
- **Docker support** — `docker-compose.yml`, GHCR image, loopback-default publish.

### Vendor-asserted, NOT independently verifiable from source
- **"34 providers / 635 free endpoints / 474 families / 7.4B tokens/mo."** The numbers are consistent across README, repo description, and site, but the endpoint count is a property of the **remote signed catalog**, not the repo: many platforms in `shared/types.ts` (68-member `Platform` union, incl. search-only and dropped entries) are annotated "signed catalog only; no bundled model seeds." The catalog contents cannot be enumerated from the clone; counting requires either trusting the feed or running the software and syncing (out of scope). Treat 635 as plausible marketing arithmetic over a feed only the vendor can enumerate.
- **"Free" durability.** Repo's own catalog notes contradict a plain reading for several entries: e.g. Sail = "$5 free credits… when a payment method is attached; usage beyond the grant is pay-as-you-go"; Speka = "one shared $1 monthly allowance"; B.AI = "limited-time 0-credit promotion"; OpenCode Zen = "limited-time promotional access… prompts/outputs may be used for model improvement"; NVIDIA NIM = trial ToS "evaluation/prototyping, not production"; Cohere trial marked "❌ Avoid for personal use" in their ToS table (all in `db/migrations/20260101_000000_legacy_baseline.ts` and `shared/types.ts` comments). "635 free endpoints" includes endpoints that can bill, expire, or train on inputs.
- **Per-provider free-tier sizes/quotas generally** — taken from the catalog feed; upstream providers change these without notice (the project's own premise).

### Could not be verified without running it (explicitly not done)
Actual routing behavior under load, real failover timing, streaming interop with Codex CLI, Windows desktop behavior, health-check quota burn in practice, catalog sync payload in the wild, and whether a client request can be made strictly non-substituting end-to-end.

---

## 5. Fitness for a single isolated $0 proof

Target shape: Windows + Codex CLI, Responses + Completions, tool-calling + streaming, deterministic provider, quota guards, rollback on behavior swap.

- **Windows/Codex:** First-class on paper (Windows desktop build, `setup-codex`). Two open wounds: issue **#1439** (open) — the Windows launcher failed to inject `FREELLMAPI_API_KEY` into the Codex process (0.13.3), and issue **#1392** — Windows test suites failing while CI is Ubuntu-only. Windows is a supported-but-second-class platform. The canary must include a cold-start Codex launch via their launcher *and* via manual env, and treat launcher failure as a known-likely event with a documented workaround, not a surprise.
- **Responses + tool-calling + streaming:** The Responses shim is purpose-built for Codex and handles function_call/output item translation. Known structural risk from source: mid-stream failures are *retryable* (truncated-stream logic), which for a client-visible stream can mean duplicated or restarted output if a retry replays after partial delivery; the 45 s retry-start budget + 20-attempt cap bounds time, not semantic duplication. Canary must test a forced mid-stream kill explicitly.
- **Deterministic provider selection:** Achievable only by construction: one provider key installed, request a specific provider-model id, keep the chain single-member (profile/group), compression off. With ≥2 providers keyed, **auto mode will swap providers silently on 429/5xx/timeout — that is the product's core feature**. For sensitive tasks there is no source-verified "fail rather than swap" client switch; the canary must prove the constructed pin holds under an induced failure (expected result: request fails; forbidden result: answer from a different provider).
- **Quota guards:** Strong on paper (per-key monthly caps, window limiters, pool inference, budget reservations). Set explicit caps on the canary key — defaults are unlimited (0), and local token estimates are admitted non-exact. Also budget for health-pass background usage.
- **Rollback when failover swaps behavior:** The system records the attempt trail and the serving platform/model per request, so swaps are *detectable after the fact* from `request_attempts`/analytics; nothing rolls back a bad answer automatically. Rollback = operator procedure: detect via attempt trail → bench the offending model/key (cooldown controls exist) → re-run the task on the pinned provider. For a $0 proof this is acceptable only if tasks are idempotent/read-only.

---

## 6. Licensing / ToS risk

1. **Code license is clean; usage rights are not the code's to give.** MIT covers FreeLLMAPI itself. Every upstream call is governed by that provider's terms, and the repo's own description scopes the project "**Personal experimentation only**."
2. **Free-tier aggregation sits in a grey zone by provider.** Using *your own* keys for *your own* traffic through a local router is the defensible reading; anything resembling pooling multiple people's keys/accounts to multiply quotas, or key sharing across users, is where provider terms (and the router's multi-key rotation features) get dangerous. The canary must use exactly one operator-owned account per provider, no shared/pooled keys.
3. **Several catalog routes are not "free tier" in the durable sense** — attached-payment-method credits (overage bills the operator), $1–$5 monthly allowances, limited-time promos, eval-only scopes (§4). A "free endpoint" that bills on overage converts a quota bug into a credit-card charge; any provider requiring a payment method on file is **out** for a $0 proof.
4. **Data terms vary per endpoint and failover chooses for you.** At least one catalog route is documented in-repo as possibly using prompts/outputs for model improvement. In auto mode the operator cannot honestly tell a user where their prompt went. Another argument for pinned-only operation.
5. **Anti-abuse exposure:** one gateway multiplexing many free tiers behind health checks + retries is exactly the traffic shape providers' abuse systems look for; account termination risk sits with the operator's provider accounts, not with FreeLLMAPI.

---

## 7. Risk + revert plan (for the canary)

**Isolation:** dedicated Windows user profile or VM; loopback bind verified from another LAN host (expect connection refused); `CATALOG_SYNC_DISABLED=1` after initial sync decision is recorded (or accept sync with eyes open — pick one, record which); compression mode `off` verified; exactly **one** provider, **one** operator-owned key, **no payment method** anywhere on that provider account; per-key monthly request+token caps set to canary-sized values; unified key and dashboard password unique to the canary.

**Revert:** the install is self-contained (Docker volume or desktop AppData + DB + `.encryption-key`). Full revert = stop process/container → delete data directory/volume → remove the provider key at the provider's console (rotate/revoke, don't just delete locally) → remove Codex config block written by `setup-codex` (it backs up the prior config; restore from that backup) → confirm port closed. No production system is touched at any point, so revert is total and takes minutes.

**Hold triggers (stop, don't debug forward):** any charge or payment-method prompt; any response served by a non-pinned provider; dashboard reachable from LAN; catalog sync applying models after `CATALOG_SYNC_DISABLED=1`; Codex receiving duplicated stream content after an induced failure.

---

## 8. Canary test matrix (incremental, zero-cost, reversible)

Each step is gated: proceed only if the previous passes. No step may enable uncapped retries — the shipped 20-attempt/45 s defaults are the ceiling, and Step 5 verifies them empirically.

| # | Step | Success | Failure → action | Recovery / hold |
|---|------|---------|------------------|-----------------|
| 0 | Static config audit: bind=loopback, compression off, sync setting recorded, caps set on the single key, one provider keyed | All settings read back as intended | Fix config; do not start traffic | Hold: any payment-method field present on provider account → choose another provider |
| 1 | LAN probe: request dashboard + `/v1/models` from a second LAN device | Connection refused / unreachable | Rebind to 127.0.0.1, retest | Hold until refused |
| 2 | `/v1/models` + one non-streaming chat completion, pinned model id | 200; analytics row shows the pinned platform/model; attempt count = 1 | Inspect attempt trail; fix pin construction | — |
| 3 | Streaming chat completion (SSE) | Clean `[DONE]`/finish; analytics match | Log stream trace; retry once manually only | — |
| 4 | Responses API: Codex CLI cold start (manual env), one read-only repo task with a tool call | Tool call round-trips; `response.completed` decodes; serving provider = pinned | Try their launcher path (expect possible #1439 env bug; document which path works) | Hold: if neither path launches Codex cleanly, canary pauses — this is the known Windows risk |
| 5 | Induced failure A (quota): set key's monthly cap to already-exceeded | 429 `quota_exceeded` + Retry-After ≈ next month; **no** alternate provider serves (only one exists) | If anything serves the request, pin has failed → stop | Reset cap; confirm normal service resumes |
| 6 | Induced failure B (mid-stream kill): sever upstream mid-stream | Client sees a clean error or a single coherent restart; attempt trail shows ≤20 attempts within ~45 s budget; **no duplicated content** in client output | Duplication or runaway attempts → hold; this is the semantic-failover risk made visible | Bench model via cooldown; re-run Step 3 |
| 7 | Induced failure C (bad key): revoke key at provider | 401 path: key benched, error names auth failure, no loop | If retries storm, hold and inspect cooldown behavior | Restore key; confirm health pass revalidates it (~5 min cycle) |
| 8 | Swap audit: review `request_attempts` for all canary traffic | Every served response traces to the pinned provider | Any foreign provider → canary fails its core promise; stop, revert | — |
| 9 | Full revert rehearsal (§7) | Port closed, data dir removed, provider key revoked at console, Codex config restored from backup | — | Canary cannot be declared done until revert is proven once |

Explicitly out of the matrix: adding a second provider (that changes the claim being tested), the Anthropic/Claude Code surface, media/embeddings routes, premium license purchase, LAN mode, Watchtower profile.

---

## 9. Tests run vs not run

**Run:** read-only `git clone --depth 50`; static reading of the files cited (router, fallback loop, ratelimit, quota, key-budget, crypto, auth, config, catalog-sync, compression config, providers registry, shared types, migrations, Dockerfile, docker-compose, desktop main); GitHub API reads (repo metadata, releases, issue search); vendor site fetch (freellmapi.co pricing page).

**Not run:** the server, desktop app, CLI, Docker image, test suites, catalog sync, and any provider call. No keys were created, no billing touched, nothing installed. All behavioral statements about runtime are inferences from source and issue reports and are labeled as such; the canary matrix in §8 exists precisely to convert the load-bearing inferences (pin integrity, stream-failure semantics, Windows/Codex launch) into observations before any reliance.

---

*Prepared for Rivet's peer-review file. Delivery is the main session's job; this document was not sent anywhere by the reviewer.*
