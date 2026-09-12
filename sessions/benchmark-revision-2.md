# ZZ-feature-map benchmark — final simulator-phase spec (2026-09-12)

Status: **RUNNABLE at simulator phase.** Survived two Claude/Gemini red-team
rounds and three GPT correction rounds (see `sessions/ensemble-review-2.md`).
Session `benchmark-revision-1`, 6 turns, ~$0.005 total.

## Arms

- **Arm A** — unchanged Codelation seed: BLAKE2s state identities,
  strongest-successor prediction, no kernel.
- **Arm B** — classical RBF-kernel scorer.
- **Arm C** — ZZ-feature-map fidelity-kernel scorer (below).

## Arm C specification

- **Circuit**: n = k = 12 qubits, d = 3 repetitions, all-to-all entanglement.
  Each layer: single-qubit rotations by feature angles θ_i, then parameterized
  R_ZZ(θ_{i,j}) = exp(-i·θ_{i,j}·Z_i·Z_j/2) with θ_{i,j} = θ_i·θ_j on all pairs.
- **Features → angles**: k = 12 raw continuous features (transition counts,
  empirical successor probabilities, recency, derived per-candidate
  statistics). Min-max normalization over the TRAINING SET ONLY, then
  θ_i = c·f̂_i with predeclared c = π/4. BLAKE2s hash is state identity only.
- **Measurement**: Loschmidt echo U†(y)U(x); kernel = all-zero outcome
  probability.
- **Simulator-phase estimation**: EXACT statevector overlaps (infinite-shot
  limit; 2^12 = 4096 amplitudes, microseconds per pair). Separate shot-noise
  ablation: overlaps resampled with S = 1024 shots.
- **PSD stabilization**: K_reg = (1-λ)·K̂ + λ·I with λ = 1/S_ablation
  (λ = 1/1024 for the ablation; λ → 0 for exact overlaps, kept as stabilizer).
- **Tuning**: hyperparameters (c, RBF γ, λ) PREDECLARED. Zero tuning allowance,
  zero Gram rebuilds this phase. (GPT's draft allowed "1 rebuild" while
  claiming "no tuning" — internally contradictory; resolved to 0 by Medic,
  keeping the budget arithmetic intact.)
- **Tie-breaking**: deterministic lexicographic on state identity, identical
  across arms.

## Scale and budgets (same units for all arms)

- N_train = 100, N_test = 50.
- Train Gram pairs: 100·99/2 = 4,950. Test pairs: 50·100 = 5,000.
- Arm C total: 9,950 kernel evaluations ≤ 10,000 ceiling.
- Arm A: 10,000 candidate-successor scoring evaluations.
- Arm B: 10,000 kernel evaluations (includes any γ search — none planned).
- Hyperparameter search, if ever run, must be priced inside these ceilings.

## Baselines

- **Ablation**: Arm C pipeline with quantum features replaced by the classical
  empirical-successor-probability estimator at matched dimension (k = 12).
- **Random baseline**: uniform random angle vectors over [0,2π]^12, seed 42,
  100 trials.

## Metric and verdict rule

- Metric: accuracy of predicted successor rankings vs held-out empirical
  successor rankings; identical candidate successors across arms.
- Arm C wins iff: absolute gain ≥ 5% AND relative gain ≥ 10% over Arm B,
  with 95% CI on the accuracy difference excluding zero and p < 0.05
  (paired permutation test).
- Thresholds from power analysis: Cohen's d = 0.5, N_test = 50 → power ≈ 0.80
  at α = 0.05.

## Explicit non-claims

- At n = 12 everything is exactly simulable via statevector. The d = 3
  all-to-all circuit is chosen to match the hardware-intended design so the
  simulator phase validates the real pipeline. **No quantum-advantage claim
  is made at simulator phase.** Simulator improvement ≠ quantum advantage.
- The 10,000-evaluation budget is simulator-phase only. A hardware phase
  needs a separate budget in QPU-seconds excluding queue time (flagged for
  Bruce's --confirm-qpu stage).

## Next step

Build the simulator phase: implement Arms A/B/C + ablation + random baseline
against Codelation successor data, run the verdict rule, report. No hardware
until the simulator phase clears the predeclared bars.
