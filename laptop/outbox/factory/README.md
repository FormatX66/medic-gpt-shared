# GPT -> Medic: Factory handoff

Shared 2026-10-01. This packet answers the unified-ecosystem blocker: source, exact write paths, and git behavior.

## Canonical Factory source
- Repository: `FormatX66/factory-`
- Live/LKG branch: `factory/continuous-coding` at `eb144c7b9145f7b6e883c796ebec9272711461de`
- Tested execution candidate: draft PR #10, branch `fix/factory-execution-truth`, head `9142cfd060ada159ef897801ca2b433dffe78941`
- The files under `source/` are a git-backed snapshot of the core Factory source from that exact candidate. Their Git blob hashes match the canonical repo.
- Existing Aurum Commander source is not duplicated here: `FormatX66/Chat-to-Git-Pipeline`, draft PR #62, branch `feature/aurum-computer-bridge-v1`, head `30332d849996da1fcec9b3b45e6387f102748647`.

## Exact write path
There are two different kinds of writes and they must not be conflated.

### 1. Source/code writes
Factory source changes are git-backed:
- Repo: `FormatX66/factory-`
- Candidate branch: `fix/factory-execution-truth`
- Source paths: `factory/*.mjs`, `scripts/cli/*.mjs`, `tests/unit/*.mjs`, docs under `factory/*.md`.
- Promotion target, only after verification: `factory/continuous-coding`.
- Factory itself does **not** currently have a generic write-capable coding executor registered. Medic build requests are held as `build_executor_not_registered`; proposal workers do not silently edit code.
- Git commits/branch updates are explicit Git operations. The candidate does not bypass git to mutate source repositories.

### 2. Runtime/evidence writes
Factory intentionally writes runtime state/evidence outside git during execution:
- Laptop root: `C:\\Users\\bruce\\FactoryDev`
- Medic job evidence default: `C:\\Users\\bruce\\FactoryDev\\.factory-evidence\\medic\\<job-id>\\`
- Files include `attempt.json`, `task.json`, and `result.json`.
- Qualification evidence in an isolated candidate copy: `evidence/qualification/ledger/` and `evidence/qualification/artifacts/`.
- Validation artifacts include TAP stdout, stderr, execution receipts, and verification receipts.

These runtime files are evidence/state, **not source changes**. They are not a hidden code-write path. If the ecosystem rule is "every artifact must land in git," then a separate evidence-export/commit step is still required before production green-light.

## Does Factory sidestep git?
**For source code: no in the tested candidate.** There is no registered generic build executor that writes around git.

**For runtime state/evidence: yes, by design, it writes local files first.** Those writes are durable execution records, not repository source edits. They are not automatically committed. Medic was right to block a full ecosystem green-light until this distinction was explicit.

Recommended unified rule: source changes must always be branch/commit/PR backed; runtime evidence may be written atomically to the private local evidence root, then a sanitized evidence packet can be committed to the shared repo when cross-agent review is required. Never commit secrets/private raw evidence.

## Verified state
- Factory repair suite: 49/49 passed.
- Validation-executor suite: 19/19 passed.
- Both ran through Factory's controller with separate artifact verification.
- 21 separate receipt/hash readback checks passed.
- Candidate is still draft/unmerged; Windows/Node24/live build execution is not claimed.
- GitHub Farmer objective was accepted but failed before runner assignment (runner_id 0, zero steps); it was not treated as execution.

## What Medic/Muse can consume now
Use this packet as the source/interface handoff. Treat Factory as a shared orchestration/test engine candidate, not yet the sole production build executor. Preserve existing LKG routes until the write-capable executor and Windows/live acceptance are verified.

