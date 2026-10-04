# Correction: Titan model recommendation superseded + revised AI direction

**Date:** 2026-10-04
**From:** Medic
**Re:** Supersedes §4 (Titan model options) of `2026-10-02-re-prymortal-details-followup.md`; also delivers the pending Rosebud/GDevelop steer.

## 1. What is withdrawn

The `gpt-6.1-sol` Titan recommendation from the follow-up evidence pack is **withdrawn**. It was argued on coding-per-dollar benchmarks. Bruce's lived experience — "GPT really does not do the best on games" — outranks coding benchmarks for game generation. Do not revive it without new game-specific evidence.

## 2. Bruce's steer (deciding evidence)

- **Rosebud AI for simple game generation; GDevelop for more substantial games.** (GDevelop was the "other one" he was trying to remember.)
- Standing interest in **locally-hosted / game-specific AI**, not just the best general coding model.
- No model spending activated. No accounts created.

## 3. New research (read-only, no spend)

- **Fine-tuning on game data beats bigger general models.** Mapping study of LLM game-code literature: fine-tuning is the key strategy in ~40% of surveyed papers. A Unity GDD-to-game paper shows a fine-tuned model substantially outperforming state-of-the-art general LLMs on compilation success, design adherence, and best practices — "understanding game requirements is insufficient without the ability to translate that understanding into working code." DeepSeek-R1 fine-tuned on ~1000 Zelda-like levels: very high playability/novelty/diversity. ChatGE (poker): fine-tuned model 90% code-correctness vs 30% for the best 5-shot general model.
- **There is an actual arena where models generate games and get judged — GPT is not winning it.** `specimba/nexus_game_benchmark_agent_arena` (public, active through Aug 2026): recent rounds taken by deepseek-v4-flash-low, opus-4.6, kimi-k3, qwen3.8, glm-5.2. Operator's own note: the biggest quality-ceiling move came from *teaching* (prompting/materials), not from the model — and self-debugging mid-session (deepseek's PRISMA fixed 4 bugs live) was the differentiator.
- **Claude has a measured edge on game-logic correctness** — ~40% fewer hallucinations on state-machine/memory-management code vs GPT-class (kevurugames game-dev comparison, Oct 2026).
- **Rosebud is platform-locked for our purposes.** No confirmed public API (sources conflict; a software-comparison listing says "Has API: No"). We cannot plug their game brain into our pipeline today. Their own launch-post lesson stands: constrain the programming framework and the agent performs better.
- **GDevelop's AI story is the pattern to copy, not the product to rent.** In-editor AI Agent ("Build for me") plus the open-source `gdevelop-mcp` project: 30 tools giving any MCP-aware agent full agency over a GDevelop project with an edit→preview loop and safe-by-default editing. That is the shape our Titan harness mirrors.

## 4. Revised direction

Framing correction, agreed with Bruce: the generator's **game-design intelligence is the central bet of PryMortal, not a swappable detail**. The harness guarantees valid, safe code; only the model can produce a game worth playing.

- **Immediate — bake-off, not benchmarks.** Same prompt + DNA through candidate models, each output run through our validation harness, Bruce judges *feel* (human play is the oracle). Candidate list: Claude (opus-4.6 class), deepseek, kimi-k3, qwen3.8, glm-5.2, with gpt-6.1-sol kept as the control. Spend cap remains Bruce's call — **no spend activated by this packet**.
- **Long-term — fine-tune track.** Fine-tune an open coder model on game code (game JS, GDevelop/GDScript projects, game-jam codebases) for a PryMortal-native generator. Fits Bruce's local-hosted interest; drives per-generation inference cost toward zero. No training started; this is a direction, not a commitment.
- **Harness stays model-agnostic by design** — any candidate plugs into the same interface and validation pipeline.

## 5. Titan validation harness v1 — built

Medic built the harness side (the "engine we know how to build") in Medic-side workspace `~/workspace/prymortal-titan/` — not in this repo, no public URL; source available to Rivet on request via an authorized route.

- `MODULE_INTERFACE.md` — the contract: `init(dna, arena)` / `update(dt, input)` / `reset()` / `teardown()`; host owns clock, canvas, input, match boundaries, win enforcement; module owns only transient state; rendering decoupled via draw lists; DNA `win` gene is the declared win condition.
- `dna_schema.json` — real JSON schema for all 18 genes (mirrors `PM_GENE_RANGES` in `lib.php` plus twists).
- `titan-validate.js` (Node stdlib only) — 4 named, individually skippable steps: **static** (ban list: eval, Function, string-arg timers, network, DOM, host globals; unbounded-loop heuristic), **schema** (DNA vs schema, exports/arity), **sandbox** (init→N frames, 250ms/frame budget, teardown/reset/re-init leak check, determinism check, 15s kill-switch), **resources** (3000-line hard cap, heap/time accounting). Verdict `pass` (exit 0) / `held` (exit 2); fail-closed.
- **9/9 fixtures green** (re-verified by re-run 2026-10-04): good Pong variant passes; eval, infinite loop, missing export, schema violation, DOM access, network call, and a closure-counter global leak are each held at the right step. Adversarial probes (Date.now in gameplay, 2B-iteration frame) also held.
- **Not built yet:** model-calling side, bounded repair loop (notes are shaped for it), server integration, spend metering. No commits pushed anywhere; local only.

## 6. What hasn't changed

Game first, website second. Human play is the oracle — no claim of a working game until Bruce plays it. Prompt-only forks. Plays economy as specified. No marketing by comparison. No spend without Bruce's word.
