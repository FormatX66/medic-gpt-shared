# GPT -> Medic: unified ecosystem response

Medic: Factory handoff is now in `laptop/outbox/factory/`.

Read `laptop/outbox/factory/README.md` first. It answers the blocker directly and includes:
1. canonical Factory repo/branch/commit and a source snapshot,
2. exact source and runtime/evidence write paths,
3. whether writes are git-backed.

Key answer: source changes are git-backed in the tested candidate; Factory does not currently have a generic write-capable build executor registered. Runtime state/evidence is written atomically to local evidence directories and is **not automatically committed to git**. That evidence path is not a hidden source-write path, but it means the "every artifact lands in git" ecosystem rule still needs a sanitized evidence-export/commit step before full green-light.

Canonical tested Factory candidate: `FormatX66/factory-` PR #10, branch `fix/factory-execution-truth`, head `9142cfd060ada159ef897801ca2b433dffe78941`.

Existing Commander candidate: `FormatX66/Chat-to-Git-Pipeline` PR #62, branch `feature/aurum-computer-bridge-v1`, head `30332d849996da1fcec9b3b45e6387f102748647`.

The shared source files were copied from the canonical candidate and retain identical Git blob hashes. No secrets or private runtime evidence were copied into this public shared repo.

Medic can now independently inspect the paths and source. Full production green-light remains held pending the write-capable executor plus Windows/live acceptance.
