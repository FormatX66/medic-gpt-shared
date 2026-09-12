# Ensemble review 1, revision round — revised ZZ benchmark design (2026-09-12)

GPT's response to the Claude/Gemini red-team (`sessions/ensemble-review-1.md`),
produced over 3 loop turns in session `benchmark-revision-1` (gpt-4o-mini,
7,342 tokens, est. $0.00196). Medic drove; two corrections were required
mid-round (see Medic's notes at the end).

## Arms (re-anchored, kept distinct throughout)

- **Arm A** — unchanged Codelation seed (classical baseline; BLAKE2s identities,
  strongest-successor prediction, no kernel).
- **Arm B** — classical RBF-kernel scorer over the same features.
- **Arm C** — ZZ-feature-map fidelity-kernel scorer (revised below).

## GPT's verdicts on the six findings

1. No measurement protocol — **accepted**.
2. O(N^2) Gram-matrix cost / non-PSD noise — **accepted**.
3. Budgets must be identical in practice — **accepted**.
4. Classical simulability of 1-rep linear ZZ — **partially contested**: concedes
   the d=1 case, deepens the map instead (see below).
5. Hash avalanche vs kernel smoothness — **accepted**.
6. Claude's extras (amplitude encoding, matched capacity, ablations, baselines)
   — **accepted**.

## Revised Arm C

- **Circuit**: ZZ feature map, d=2 repetitions, linear nearest-neighbor CZ
  entanglement; n qubits = k features. Layer = single-qubit rotations from
  feature angles, then CZ on nearest neighbors; repeated once.
- **Measurement protocol**: Loschmidt echo U†(y)U(x); kernel estimate = all-zero
  outcome probability over S shots. No ancilla, depth ~2x the feature map.
  (GPT first proposed the SWAP test with an inverted depth claim; corrected in
  round — see notes.)
- **Observation→angle mapping**: angles come from RAW continuous features
  (transition counts, empirical successor probabilities, recency), normalized
  to [0,1], θ_i = 2π·f_i. The hash is identity only, never an angle source.
  (GPT's first attempt mapped the hash linearly to [0,2π], which preserves
  pseudo-randomness; corrected in round.)
- **Non-PSD fix**: nearest-PSD projection after Gram-matrix construction
  (negative eigenvalues → 0).

## Predeclared thresholds

- **Metric**: accuracy of predicted successor rankings vs held-out empirical
  rankings (identical candidate successors, identical tie handling).
- **Gain bar**: Arm C must beat Arm B by ≥5% absolute AND ≥10% relative.
- **Tuning budgets** (common unit: wall-clock seconds): 10 s each for Arms A, B,
  C. Arm C's 10 s includes all circuit evaluations AND the Gram-matrix build.
- **Ablation**: Arm C pipeline with quantum features replaced by the classical
  empirical-successor-probability estimator at matched dimension.
- **Random baseline**: uniform random angle vectors over [0,2π]^k through the
  same pipeline.

## Medic's notes (cross-check results)

1. **Caught and fixed in-round**: GPT's SWAP-test depth claim was inverted
   (echo needs no ancilla; CSWAPs are expensive on heavy-hex). It accepted the
   correction immediately. This is the ensemble loop working as designed.
2. **Caught and fixed in-round**: the first angle mapping still used the hash.
   The corrected version uses raw features — the actual fix for finding 5.
3. **Budget realism**: the 10-second common unit is coherent for the
   simulator phase, but it does NOT transfer to hardware — IBM queue times
   alone exceed it. The hardware phase needs a separate budget in QPU-seconds
   excluding queue. Flagged for Bruce's --confirm-qpu stage, not a blocker now.
4. **Simulability status**: d=2 linear ZZ is less trivially simulable than
   d=1, but still likely tensor-network tractable at small n. Treat this round
   as a pipeline/methodology shakedown, not an advantage claim. The reviewers'
   "simulator improvement ≠ quantum advantage" stands.
5. **Verdict**: the design is now *runnable* at simulator phase. All six
   findings are addressed with specifics. No hardware until the simulator
   phase clears the predeclared bars.

## Costs (this round)

- 3 turns, 7,342 tokens total, est. $0.00196 (gpt-4o-mini).
- Receipts: `~/workspace/chatgpt-bridge/server/gpt_sessions/benchmark-revision-1/receipt.jsonl`
