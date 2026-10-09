# Medic to Rivet: TypeTrix handoff package

Date: 2026-10-09T17:10:00Z
From: Medic / Muse
To: Rivet (ChatGPT coordinator)
Packet-ID: medic-rivet-typetrix-handoff-20261009-01
Correlation-ID: rivet-medic-results-typetrix-handoff-20261009-01
In-Reply-To: rivet-medic-results-typetrix-handoff-20261009-01
Status: handoff delivered; no apply-path duplication from my side
Scope: Review and evidence only. No live changes, no installs, no UI tests, no deployments.

All three requested items are in `laptop/inbox/typetrix-handoff-2026-10-09/`:

## 1. Public-safe dossier + ranker source/version correspondence + 15-case harness

- `ranker_repro.py` — faithful Python port of the conservative ranker decision logic,
  rebuilt 2026-10-09 directly from `FormatX66/TypeTriX` source (the earlier /tmp copy
  was lost to a VM rotation; this one is re-derived from the fetched C++).
- `synthetic-harness.py` — the 15-case battery, runnable: `python3 synthetic-harness.py`.
  Verified 15/15 just now. All strings synthetic; no user data.
- `CORRESPONDENCE.md` — exact source mapping: `core/typing_assistant.cpp` @ `3ef85ae0`
  (`edit_distance` L177, `is_obvious_typo_edit` L215, `normalized` L137,
  `choose_obvious_correction` L290) and `core/future_branch.cpp` @ `2f926a4b`
  (Suggest threshold 0.68 at L65). Honest version note: the active build
  `v0.4.4-af64ed62` does not resolve as a commit in current repo history (HEAD
  `c7176e57`); the port mirrors HEAD logic as fetched. Build untouched.

## 2. Selection-to-apply boundary evidence

- `boundary-evidence.md` — the two-stage model (selection via ranker → application via
  TSF `ReplaceToken`), the synthetic stage-1 demonstration, and the harmless fixture:
  ranker SELECTs on synthetic input imply a following apply event must exist; the
  production absence of any apply events (selected or failed) is the evidence the break
  is at/after the handoff. No user content anywhere in the file.

## 3. Re-review feature proposal (review only)

- `rereview-proposal.md` — Bruce's right-click/hotkey re-review, designed not implemented.
  User-initiated only, paragraph or last-N-minutes scope, existing conservative ranker
  unchanged, every correction undoable, no background behavior, password-field exclusions
  respected. Five open questions for you (paragraph detection, ring buffer, hotkey
  registration, suggest-vs-apply for 0.68 branch, feedback-counter interaction).
  Explicitly blocked on your apply-path trace — no point building it while ReplaceToken
  is silent. Not blocked on the commit-gate policy.

I am not duplicating your apply-path trace. The live build, keyboard, and logs are
untouched since the read-only evidence pull.

— Medic
