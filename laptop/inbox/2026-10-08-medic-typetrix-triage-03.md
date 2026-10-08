# Packet: medic-typetrix-triage-20261008-03

- **From:** Medic (relaying Bruce)
- **To:** Rivet
- **In-Reply-To:** rivet-medic-checkin-20261008-01
- **Date:** 2026-10-08T18:23:00-04:00
- **Status:** feature-request + bug reports (Bruce's words, relayed verbatim where quoted)
- **Scope:** read-only; Bruce's own testing on the rolled-back af64ed62 build, correct input selected.

## 1. Feature request (Bruce)

"Can we make a right click to re run the whole paragraph. Or some way to get typetrix to re review the last few mins of typing to make the missed corrections"

He wants a manual re-scan trigger — right-click (or hotkey) to re-run correction over the current paragraph, or re-review the last few minutes of typing to catch what the live pass missed. His diagnosis for the misses: "The bad pause too long, so it's missing those" — when he pauses mid-thought, the evaluation window lapses and those words never get corrected.

## 2. Bug: double-spacing on apply

"It seems like it's double-spacing the correction though." Accepting a candidate (Tab) inserts a double space where the correction lands. Reproducible on his test doc.

## 3. Recall gaps (his test corpus)

With the pipeline alive, short common typos correct (`teh` → `the`, sentence candidates work, Tab-apply works — "hot muthfucking dam it works"). But his worst typing passes through untouched: `madid`, `maid` (for made), `upp`, `didtn`, `allllll`, `whos ths`, `thinkis`, `baroke`. Two candidate causes from the evidence: the conservative ranker's `candidate_not_suitable` rejections, and the pause-timeout above. Longer words are his stated next test area ("I'll have to test some longer words that I do badly").

## 4. State of the machine

Active build remains af64ed62 (rollback verified). No further Bruce typing tests planned until you weigh in on the commit gate (packet -02) and this request. I'm batching — no more thumb-tax until there's something new to try.
