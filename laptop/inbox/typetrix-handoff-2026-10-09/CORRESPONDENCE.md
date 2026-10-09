# Ranker source/version correspondence

Date: 2026-10-09. All strings in the accompanying harness are synthetic.

## Source

Repository: `FormatX66/TypeTriX` (private). Files fetched via GitHub API 2026-10-09.

| Ported function | Source file | Blob SHA (fetched) | Source lines |
|---|---|---|---|
| `edit_distance` | `core/typing_assistant.cpp` | `3ef85ae0efcc` | 177–203 |
| `is_lowercase_word` | `core/typing_assistant.cpp` | `3ef85ae0efcc` | ~205–210 |
| `is_obvious_typo_edit` | `core/typing_assistant.cpp` | `3ef85ae0efcc` | 215–242 |
| `normalized` | `core/typing_assistant.cpp` | `3ef85ae0efcc` | 137–143 |
| `choose_obvious_correction` | `core/typing_assistant.cpp` | `3ef85ae0efcc` | 290–342 |
| `rank_branches` (Suggest threshold) | `core/future_branch.cpp` | `2f926a4b355c` | 10–66; threshold `confidence >= 0.68` at line 65 |

## Version notes

- Active build on Bruce's machine: `v0.4.4-one-second-no-fight-20261006-af64ed62`
  (registry-verified, DLL hash `AF64ED62…`, 2026-10-08). The `af64ed62` identifier does
  not resolve as a commit in the current `FormatX66/TypeTriX` history (HEAD `c7176e57`
  as of 2026-10-09); it is presumably a build-pipeline hash. **No live changes were
  made; the active build is untouched.**
- The port mirrors the decision logic as fetched from HEAD (2026-10-09). The conservative
  gate (`choose_obvious_correction`: lowercase word, length 3–64, Damerau distance == 1,
  transposition-or-duplicate-letter only, confidence 0.98, feedback block at
  undone ≥ 3 > accepted) is the logic under test. Behavioral verification: 15/15
  synthetic cases match the specified rule (`python3 synthetic-harness.py`).
- Simplifications, all behavior-preserving on ASCII input: `std::wstring` → Python `str`;
  `match_case()` is identity for all-lowercase sources (the only eligible inputs);
  `feedback.confidence_adjustment()` modeled as 0.0 (neutral); `EphemeralContext::kMaxTokenCharacters`
  represented as 64.

## What the port does NOT cover

The TSF apply path (`ReplaceToken` and downstream commit) — that is where the
zero-auto-commit fault was localized, and it is Rivet's trace to run. This port covers
only the ranker decision (selection), not application.
