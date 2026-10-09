# Re-review feature: design proposal (review only, no implementation)

Date: 2026-10-09. Origin: Bruce's 2026-10-08 feature request. Status: proposal for Rivet's review.

## Problem (Bruce's diagnosis)

Longer or mangled words pass through untouched. His diagnosis: "bad pause too long" —
the evaluation window lapses before he finishes the word, so the ranker never evaluates
it. Short words and sentence candidates work; the misses are words that outlast the
pause window.

## Proposed feature

A user-initiated **re-review**: re-run the correction pipeline over already-committed
text, on demand.

### Triggers (either; Bruce asked for right-click or hotkey)

1. **Right-click** on a text field → context-menu item "Re-review text" (or similar).
2. **Hotkey** (suggest `Ctrl+Shift+R`; must not collide with existing TypeTrix or
   application shortcuts — collision audit required before settling).

### Scope of re-review

- **Unit**: the current paragraph (caret's paragraph), or — if invoked with a modifier —
  the last N minutes of committed text in the current field. Default N = 5.
- **Pipeline**: tokenize the scope into words, run each through the *existing*
  conservative ranker (`choose_obvious_correction`, unchanged thresholds). No new
  ranker, no loosened policy.
- **Application**: apply selected corrections through the *existing* apply path
  (which Rivet is tracing — this feature depends on that path working).
- **Feedback**: show a small transient summary ("3 corrections applied", click to undo).
  Every application must be individually undoable via the existing undo mechanism,
  plus one "undo all from this re-review" action.

### Safety and bounds

- Strictly user-initiated: no background re-scanning, no timers, no ambient behavior change.
- Operates only on committed text the user can already see and edit; never on password
  fields (respect the existing privacy exclusions — verify against the privacy audit).
- Reversible: per-correction undo + batch undo. No correction is ever un-undoable.
- No new network, no new credentials, no settings changes without the user.
- Must not fight the live pipeline: if live typing is in progress in the same field,
  the re-review either waits for idle or scopes to text before the caret — never
  interleaves with active composition.

### Open questions for Rivet

1. Paragraph detection across applications (rich text vs plain text vs web fields) —
   what defines the scope unit in each?
2. "Last N minutes" needs a committed-text ring buffer; does one already exist, or is
   this new state? Retention and privacy implications?
3. Hotkey registration: global vs per-application? Collision audit?
4. Should re-review use the obvious-correction gate only, or also surface popup-style
   suggestions (0.68 branch) for user choice? Bruce's ask is auto-apply; the proposal
   keeps auto-apply for obvious typos and suggests (not auto-applies) the rest.
5. Interaction with the feedback model: do re-review applications count toward
   accepted/undone counters? (Proposal: yes — the user can undo them, so they should.)

## Dependencies

- Blocked on the apply-path trace: re-review is pointless if `ReplaceToken` stays silent.
- Not blocked on the commit-gate policy: uses the existing conservative ranker as-is.

## What is NOT proposed

No automatic re-scanning, no loosened ranker, no new correction policy, no background
agents, no cloud, no settings migration. One user gesture, one bounded scope, fully
undoable.
