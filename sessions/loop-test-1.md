# Session loop-test-1 — automated Medic↔GPT loop test (2026-09-12)

First live test of the API loop. No Bruce in the middle, no browser.

## Result: PASS (with one note)

- Turn 1: Medic sent the ZZ-benchmark context; GPT confirmed it and named the
  open question (hyperparameter selection criteria, ZZ vs RBF scorer). DONE.
- Turn 2: memory check + tuning-budget proposal. GPT agreed to a fixed,
  predeclared tuning budget (same configs, same held-out split, both scorers).
- NOTE: GPT's restatement of the three arms drifted slightly — it merged
  "unchanged seed" and "classical RBF scorer" into one arm and listed the
  fidelity kernel as the third. All components were recalled; the structure
  drifted. Anchor: the three arms are (1) unchanged seed, (2) classical
  RBF-kernel scorer, (3) ZZ-kernel scorer. Future sessions re-state the arms
  explicitly in the seed message to prevent drift.

## Cost receipt
- 2 turns, 768 tokens total, est. $0.000181.
- Guardrails enforced in `server/gpt_loop.py`: 10-turn cap, 1200 tokens/call,
  30k session budget, per-exchange receipts.

## Files
- Thread: `~/workspace/chatgpt-bridge/server/gpt_sessions/loop-test-1/thread.json`
- Receipts: `~/workspace/chatgpt-bridge/server/gpt_sessions/loop-test-1/receipt.jsonl`
- Loop: `~/workspace/chatgpt-bridge/server/gpt_loop.py`
- API CLI: `~/workspace/skills/openai/bin/gpt-chat` (vault-backed credential)
