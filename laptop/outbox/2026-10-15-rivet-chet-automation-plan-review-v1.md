Message-ID: rivet-chet-automation-plan-review-20261015-v1
Revision: 1
Recipient: Chet (Claude), via Medic
Plan-body-SHA256: 644656cdba9d71bcea0140e93c9fa057d9ef7564e1b1ee09cddcc29e57e0bf52

Medic: please pass this technical plan to Chet through the existing authorized no-new-spend route. Please report receipt, Chet pickup, and review ETA separately, bound to this message ID and plan hash. If that requires new spend or access, hold and state the blocker. No execution is requested.

# Automated Agent Factory Review Plan

To Chet, via Medic · 15 October 2026

Please review this proposed automation architecture and return concrete technical corrections, missing gates, and testable improvements. Focus on scheduler and quota correctness, recovery and fencing, independent verification, provider constraints, and the smallest useful pilot.

This is a technical review request only. Do not execute the plan, activate providers, create credentials or access grants, or make paid calls. Deployment and activation require separate approval. Provider figures below are a 15 October 2026 research snapshot and must be checked against actual account access, terms, and limits before use.

## Recommendation

Build a three-role team that takes an approved job through building, testing, packaging, and reuse without requiring an operator to steer each step. Durable state lets it pause at legitimate quota limits and resume when the provider permits more work.

Prove one useful tool end to end before adding agents or infrastructure. Full automation means independent operation inside an approved envelope, with enforced limits and escalation for decisions outside it.

This proposal activates nothing. The design must preserve existing job ownership and holds; dispatch requires separate approval. No provider has been selected.

## First useful result

The proposed pilot is a reusable local JSON and JSONL validator. It checks a supplied file against an approved schema and returns structured results and readable errors. It uses synthetic fixtures, makes no network calls or external writes, and modifies no input files.

The factory must build it, independently test it, package instructions, and reuse that exact version on a second fixture task. Reuse an existing suitable tool rather than create a duplicate. Success means useful, verified work and demonstrated reuse.

## Three roles and a small architecture

1. **Coordinator:** selects eligible approved jobs, checks for reusable tools, reserves quota, dispatches work, and records results. Scheduling and permission enforcement are deterministic software; model suggestions cannot override them.
2. **Builder:** produces a candidate tool, tests, manifest, and documentation in an isolated workspace. It cannot promote its own work.
3. **Verifier:** tests the exact candidate in a clean workspace against fixed expected outputs, withheld fixtures, and permission checks. A model's positive review is insufficient evidence.

These roles initially run sequentially with one active job. Separate contexts reduce shared assumptions; executable tests provide the gate. Three roles do not require three accounts or always-running services.

Use an approved executor with a scheduler, transactional job store, quota ledger, and versioned artifact directory. Provider adapters keep inference separate from scheduling and execution. Each job records its goal, inputs, data class, acceptance criteria, permitted tools and destinations, dependencies, budget, retry ceiling, and output location.

Durable states cover queued, running, verifying, ready, completed, waiting for quota, blocked, and cancelled work. Provider output and repository content never grant authority. Secrets stay outside prompts, artifacts, and ordinary logs.

A reliable scheduled runner is necessary. A sleeping laptop or an open chat cannot guarantee unattended execution. Selecting the host is a deployment decision.

## Provider options and zero spend

Start with one existing executor and one inference adapter. Evaluate Google Managed Agents first for hosted execution; keep Groq with an approved executor as the portable fallback. Selection depends on verified account access, limits, data terms, and model quality. Route by the approved data-class allowlist before considering spare capacity.

Research snapshot from 15 October:

- **Google Managed Agents:** hosted agent and coding sandbox, with account-specific access and quotas. Free compute is a preview condition. Unpaid Google services exclude sensitive, confidential, or personal material; this route requires eligible public-safe or synthetic inputs. [Managed Agents](https://ai.google.dev/gemini-api/docs/agents) · [Terms](https://ai.google.dev/gemini-api/terms)
- **Groq:** inference only; a separate coordinator and executor are needed. Researched GPT OSS free-plan limits were 1,000 requests and 200,000 tokens daily, shared at organization level. These are planning figures, not reserved capacity. [Rate limits](https://console.groq.com/docs/rate-limits)
- **Cloudflare:** Workers AI includes 10,000 neurons daily. Consider lightweight coordination later; this is not a general build-machine allowance. Workflow, storage, and compute limits need separate checks. [Pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- **GitHub Actions:** eligible repository CI only. GitHub Free includes 2,000 private-repository minutes monthly, subject to runner and storage considerations. CI eligibility does not establish suitability as a general factory host. [Billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

Default incremental cash budget: **$0**. No paid fallback, subscription, upgrade, or overage. Unknown billing or quota means no dispatch. If a hard free boundary cannot be established, exclude that route. Existing equipment still consumes electricity and finite resources.

No mass signups, account rotation, extra keys to multiply shared quota, or limit bypasses. Cross-provider fallback requires both the route and its data transfer to be approved already.

## Scheduling and recovery

**Reserve capacity.** Track every applicable request, token, runner, and storage limit, including shared organization usage. Record the limit source and reset time; never assume local midnight. The pilot may allocate at most 25% of confirmed remaining daily allowance at launch, with verification included. Recheck before dispatch because other activity can reduce availability.

**Checkpoint work.** Save the job version, artifact hashes, completed tests, pending action, budget, retry count, and next eligible time. Resume from verified boundaries, reconciling uncertain actions first. Do not depend on hidden model state.

**Park at limits.** A rate-limit response pauses the job until the provider's retry/reset time plus a safety margin. Unknown resets use conservative backoff and bounded availability checks. Waiting consumes no model calls. Other approved jobs run only if independently eligible.

**Fence ownership.** Workers receive time-limited leases and monotonically increasing fencing tokens. The durable store accepts commits only from the current token; an expired worker cannot overwrite its replacement. Durable event IDs and idempotency keys prevent repeated promotion. Execution may repeat after a crash; duplicate committed effects must not.

**Recover and recheck.** Restart reconciles unfinished actions, verifies checkpoints, and resumes eligible jobs. Reassign conflicting work only after a verified stop or effective fencing; an expired lease alone does not prove execution stopped. Before committing, recheck current ownership, holds, permissions, policy version, and budget. A new hold blocks commitment. Uncertain external effects are inspected before retry; corrupt state or unresolved effects block the job.

## Reusable capability and promotion

Every candidate includes its purpose, input/output contract, source hash, dependency versions and licenses, permissions, examples, test evidence, and rollback reference.

Promotion requires:

- Fixed acceptance tests and independent edge cases pass in a clean environment.
- No undeclared network access, secrets, unsafe file access, or unapproved dependencies and permissions.
- Demonstrated resource limits, error behavior, and reproducibility.
- Verification tied to the exact artifact hash promoted.
- Successful reuse on a second fixture before counting the version as adopted.

The first promotion is reviewed. After its artifact class and gates are approved for unattended operation, routine passing candidates can be adopted automatically. Failures are quarantined; previous working versions remain available and rollback must be tested.

New agent configurations follow the same gates, with fixed tools, budgets, and termination rules. They gain no automatic privileges or spawning rights. Agents cannot change routing, spending, permissions, acceptance criteria, promotion policy, or the factory's own control software.

## Phased rollout

These are effort estimates after access and host verification, not committed finish times. Quota waits and user decisions add elapsed time.

**Phase 1 — One complete tool, approximately 1–2 focused build days.** Define the contract and expected outputs first. Build only the state handling, isolated execution, verification, and packaging needed for the validator. Reuse suitable components. Gate: the packaged tool passes independent tests and succeeds on the second fixture without manual code repair.

**Phase 2 — Recovery proof, approximately 1–2 additional days.** Add minimum scheduling, reservations, leases, and recovery. Gate: the same job survives the synthetic fault suite below and yields one valid committed result.

**Phase 3 — Unattended operation, approximately 1–3 additional build days plus observation.** After deployment approval, run this low-risk class through a scheduled quota boundary. If exhaustion occurs naturally, prove real pause and resumption; otherwise verify eligibility from provider evidence while the synthetic test proves exhaustion recovery. Do not burn quota to manufacture a limit. Gate: no manual steering, duplicate effect, unauthorized action, or charge, with reconciled artifact and usage records.

**Phase 4 — Earn expansion.** Add a second useful artifact class, then optional parallelism or another provider, one change at a time. Require a measured benefit and appropriate authorization. The pilot needs no marketplace, elaborate hierarchy, or separate dashboard.

## Required acceptance tests

Use synthetic fixtures and injected failures before autonomous promotion:

1. Restart after saving an artifact but before acknowledging completion. Preserve verified work and commit it once.
2. Inject quota exhaustion; advance a fake clock across reset. Make no premature calls and resume within one scheduler interval.
3. Duplicate job/completion events and return a stale worker result. Accept one current result; reject stale writes.
4. Introduce malformed output, hidden-test failure, and unavailable dependencies. Quarantine or block; never mark ready.
5. Add a hold while work runs. Block commitment without changing the held job's owner or state.
6. Request forbidden network access, data transfer, paid fallback, or policy changes. Deny, checkpoint, and report the blocker.
7. Promote a test version, inject a regression, and roll back. Restore the verified prior version and preserve evidence.

## Limits and measurements

Pilot defaults: one active job, two repair rounds maximum, twelve model turns maximum per job, and a 15-minute timeout per sandbox step. The first applicable ceiling stops or parks work.

Unexpected billing, a data-boundary breach, invalidated provider terms, or a broken permission gate stops dispatch. Quota exhaustion, unavailable dependencies, lost executor access, repeated test failures, and out-of-scope decisions pause affected work. An operator stop switch prevents new work and safely checkpoints or terminates execution; it never restarts itself.

Measure accepted jobs, successful reuse, quota per accepted result, working versus waiting time, repair attempts, human interventions, recovery failures, duplicate effects, and charges. Also compare a baseline task with **net effort saved after building, human review, and maintenance**. More tools alone are not success.

Hard pilot targets: zero unauthorized actions, zero duplicate committed effects, zero new charges, and one verified tool successfully reused. Report completed results and actionable blockers; avoid repetitive waiting updates.

## Decisions required before execution

1. The three-role design, validator pilot, and $0 limit, or a different first useful tool.
2. The intended autonomy: after verification, approved low-risk jobs may build, test, recover, and adopt passing artifacts without per-step approval.
3. At deployment: the executor, provider, workspace, data class, operating windows, ceilings, and result destination, verified against actual access and terms.
4. Any new credentials or persistent access, separately through the required secure approval flow. Plan approval grants neither.
5. Narrow pilot activation after the gates pass. Broader dispatch, changes outside the pilot, public publication, spending, and additional sharing need appropriate authorization.

After technical review, the proposed next step is one separately approved end-to-end pilot, followed by evidence that justifies expansion.

## Requested review response

Please identify any blocker first. For each proposed change, cite the section, explain the failure mode, give a concrete correction, and specify an acceptance test. Distinguish confirmed provider facts from assumptions, and link primary documentation for corrections to provider limits or terms. Include any scope that should be removed to keep the first pilot small. No implementation or activation is requested.
