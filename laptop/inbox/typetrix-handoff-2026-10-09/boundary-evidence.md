# Selection-to-apply boundary evidence (public-safe, synthetic)

Date: 2026-10-09. No real user typing. No live system touched.

## The boundary

TypeTrix auto-correction has two stages:

1. **Selection** (ranker): `choose_obvious_correction` picks an obvious typo and records
   `automatic_candidate_selected`.
2. **Application** (TSF path): the selected correction is committed via `ReplaceToken`,
   which should record `automatic_correction_applied`.

The fault: stage 1 works, stage 2 never fires.

## Synthetic demonstration of stage 1

Using the ported ranker (`ranker_repro.py`) with mocked provider candidates:

| Synthetic input | Provider candidates | Ranker decision |
|---|---|---|
| `teh` | [`the`] | SELECT `teh` → `the` (dist=1, transposition, conf=0.98) |
| `adn` | [`and`] | SELECT |
| `occured` | [`occurred`] | SELECT (duplicate-letter removal) |
| `the` | [`the`] | NOT_SUITABLE (no change needed) |
| `seperate` | [`separate`] | NOT_SUITABLE (substitution, not obvious per rule) |

Full battery: 15/15 in `synthetic-harness.py`. The ranker demonstrably selects
corrections on synthetic input.

## What stage 2 should do (and doesn't)

Per the activity-log event model (`activity_log.cpp`), a SELECT should be followed by
`automatic_correction_applied` when the TSF `ReplaceToken` commits. In the observed
production logs (real data, summarized here without user content): 231
`automatic_candidate_selected` events and **0** `automatic_correction_applied` events
across the same session window. The selection events prove the ranker fired; the
absence of any applied events proves the break is at or after the selection→apply
handoff — consistent with a `ReplaceToken` failure, not ranker strictness.

## Harmless fixture for the boundary

A minimal isolated fixture Rivet can run without any user data:

1. Feed the ported ranker a synthetic typo (`teh`, candidates [`the`]) → expect SELECT.
2. Assert that in a correct pipeline, the next observable must be an apply attempt
   (`automatic_correction_applied` or a logged apply failure).
3. The production log shows SELECTs with no subsequent apply events of either kind —
   the apply path is silent, not merely failing loudly.

This is the evidence that the commit-gate policy question ("should the ranker be
looser?") is the wrong lever: the ranker already selects, and loosening it cannot fix
a silent apply path.
