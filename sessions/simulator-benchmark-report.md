# Codelation simulator-phase benchmark — results

**Date:** 2026-09-12 · **Spec:** benchmark-revision-2 (3-arm, simulator phase)
**Code:** `simulator/` in this goal workspace · **Raw output:** `hidden_files/bench-full/benchmark_results.json`

## Verdict: NO WIN for the quantum kernel

Arm C (ZZ fidelity kernel) did **not** beat Arm B (RBF kernel) under the
predeclared rule (Δ_abs ≥ 5%, Δ_rel ≥ 10%, 95% CI excludes 0, p < 0.05):

| arm | pairwise acc | top-1 | Kendall τ | MRR |
|---|---|---|---|---|
| A — unchanged Codelation seed | 0.913 | 0.917 | 0.709 | 0.958 |
| B — RBF kernel scorer | 0.913 | 0.917 | 0.637 | 0.958 |
| C — ZZ fidelity kernel | 0.880 | 0.833 | 0.582 | 0.896 |
| ablation (classical prob.) | 0.913 | 0.917 | 0.709 | 0.958 |
| C + S=1024 shot noise | 0.863 | 0.750 | 0.595 | 0.833 |
| random angles (100 trials) | 0.487 ± 0.099 | — | — | — |

C vs B: Δ_abs = **−0.033**, Δ_rel = **−3.6%**, 95% CI **(−0.094, 0.0)**,
paired permutation **p = 0.50**. The quantum kernel underperforms the
classical RBF kernel slightly and matches neither it nor the plain seed rule.

Per the spec's explicit non-claim: this is a 12-qubit exact simulation —
**no quantum-advantage claim is permitted or made**, in either direction.

## What the numbers mean

1. **The seed's own rule is already near-optimal here.** Arm A (rank by
   train transition counts, the exact rule in `codelation_seed.py`) hits
   0.913 pairwise accuracy. The synthetic task has strong Zipf structure
   (a=1.25), so train counts predict held-out counts well. Little headroom
   remains for any smoother.
2. **RBF adds nothing over counts; the quantum kernel adds noise.**
   Arm B reproduces Arm A's pairwise ordering exactly (0.913). Arm C's
   fidelity kernel is healthy (off-diagonal mean 0.26 ± 0.25, PSD,
   well-conditioned) but its similarity geometry does not align with
   successor probability better than counts do.
3. **Shot noise degrades gracefully.** S=1024 resampling costs ~1.7 points
   of pairwise accuracy (0.880 → 0.863) — the pipeline is not brittle to
   finite shots, it just isn't better.
4. **The ablation collapses to Arm A — as predicted.** Ranking by
   empirical probability is a monotone transform of ranking by counts for
   a fixed state, so the spec'd ablation carries no independent information.
   Kept in the pipeline for fidelity to the spec; reported as identical.
5. **Random angles sit at chance (0.487 ± 0.099).** The ZZ pipeline with
   random features carries no signal — so Arm C's 0.880 reflects the real
   feature geometry, not an architectural free lunch.

## Secondary track: real Future Branch data

Leave-one-run-out over the three recorded `future-branch-qpu.json` runs
(8 ranked paths each, 7 numeric features, Kendall τ vs recorded ordering):

| held-out run | RBF τ | quantum τ |
|---|---|---|
| full-field-learning | 0.714 | 0.500 |
| 20260824T202253Z | 0.929 | 0.571 |
| processing-race | 0.786 | 0.500 |

Small-N and descriptive only — but directionally consistent with track 1:
the classical kernel reproduces the recorded rankings better.

## Limitations (read before reusing)

- **Synthetic task, strong signal.** The Zipf generator makes counts highly
  predictive by construction. Real Codelation data (noisier, with recency
  effects the seed format doesn't even store) may behave differently.
  This benchmark falsifies "quantum kernel helps" *on this task structure*,
  not universally.
- **Primary metric choice.** Spec's power sketch assumed N_test=50
  independent observations; top-1 over ~14 test states would have ~7%
  granularity — coarser than the 5% win threshold. Primary metric is
  **pairwise ranking accuracy** (100 candidate-pair decisions); top-1 and
  Kendall reported as secondary.
- **Random baseline budget.** 100 trials × 9,950 evals ≈ 1M kernel evals —
  treated as a diagnostic outside the three-arm verdict, per the spec's
  open accounting question.
- **Real `seed.bin` has no timestamps.** The 12-feature schema (incl.
  recency) cannot be built from the actual seed format; `seedbin.py`
  parses the real binary format and flags synthetic timestamps. Re-run on
  Bruce's real `seed.bin` when available — the loader is ready.

## Budgets (all under ceiling)

A: 50/10,000 · B: 9,950/10,000 · C: 9,950/10,000 · ablation: 50/10,000.
Zero tuning, zero Gram rebuilds. Hyperparameters predeclared:
c=π/4, γ=1.0, λ_ridge=1e-3, λ_psd=1e-6 (1/1024 shot ablation).

## Recommendation

Do **not** advance the ZZ-kernel successor scorer toward QPU on the
strength of this benchmark — it loses to the classical baseline on both
synthetic and (small-N) real ranking data. The more promising QPU
directions remain the ones already sequenced: (1) verify live IBM
connectivity/quota, (2) run Codelation successor-distribution sampling
through the Future Branch pipeline, (3) test feature-space preprocessing
*before* hashing. If the kernel idea is revisited, first find a task
regime where Arm A is *not* already at 0.91 — e.g. real seed data where
counts are sparse and recency matters.
