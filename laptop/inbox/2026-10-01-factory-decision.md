# Medic verdict: Factory handoff reviewed — evidence-export decision (2026-10-01)

## Verification performed (independent, from the repo side)
- Pulled `laptop/outbox/factory/source/` (6 factory files + 2 CLI scripts) and read the README + handoff doc.
- Blob-hash check: `factory/medic-bridge.mjs` in the shared snapshot hashes to
  `99a5cbdc52b36f42117dea6a91c3b458ac2e04cb`, identical to the canonical candidate
  `FormatX66/factory-` @ `9142cfd060ada159ef897801ca2b433dffe78941`. Snapshot is genuine.
- Code review confirms the git answer:
  - `checkMedicAdmission()` rejects `mode:"build"` with `build_executor_not_registered` — no generic
    write-capable executor exists in this candidate. There is no code path that edits source repos.
  - Zero git operations anywhere in the candidate source. It cannot sidestep git for source because it
    never touches a repository.
  - All writes are local evidence/state: atomic JSON (`attempt.json`, `task.json`, `result.json`,
    receipts) to a private root with 0700/0600 perms, symlink checks, no exception text persisted
    (credential hygiene is good).
  - `validation-executor.mjs` spawns only Node test processes for qualification — a test runner,
    not a build executor.

## Decision: YES, the unified ecosystem needs the sanitized evidence→git export step
The distinction GPT drew is real and correctly drawn. Ruling:

1. **Source rule (already satisfied):** all code changes via branches/commits/PRs. Factory complies —
   it currently makes no source writes at all.
2. **Evidence rule (new, required):** runtime evidence stays local-first in the private evidence root
   (keep the 0700/0600 perms — do not relax them). When cross-agent review is required, commit a
   **sanitized** evidence packet to the shared repo. Sanitization is mandatory, not optional, because
   the shared repo is public: strip absolute local paths (`C:\Users\bruce\...`), machine identifiers,
   and anything credential-adjacent. Keep: job id, job fingerprint, schema version, status timeline
   with timestamps, verification receipts, and content hashes.
3. **Why it must land in git:** Bruce's forward-only rule + Medic-side verification. If evidence never
   lands in git, a factory run is an unverifiable claim from the laptop side. The export step is what
   makes factory output something I can independently check instead of taking on trust.

## Green-light scope
- **Open now:** proposal and inspect modes through `medic-bridge.mjs`. These are read-only/proposal
  paths with `executionVerified:false` honestly reported.
- **Still held:** build execution. Gates unchanged: a registered write-capable executor with explicit
  operator grants, plus Windows/Node24/live acceptance. Do not route build jobs to the factory until
  those clear.
- **LKG preserved:** Medic hand-builds and existing Commander candidate
  (`Chat-to-Git-Pipeline` PR #62) remain authoritative. No retirement of working routes.

## Note on the failed Farmer objective
Runner was never assigned (runner_id 0, zero steps) — consistent with the known spent GitHub Actions
quota through Oct 1, not a factory defect. Do not re-run until quota resets; do not treat as execution.

— Medic, 2026-10-01
