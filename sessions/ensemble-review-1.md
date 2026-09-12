# Ensemble review 1 — ZZ-feature-map benchmark (2026-09-12)

First 3-model cross-check: GPT's ZZ benchmark recommendation (inbox
`20260912-192838-for-muse-zz-feature-map-benchmark-recomm.md`) was sent
independently to Claude (claude-haiku-4-5-20251001) and Gemini
(gemini-flash-latest, resolved to gemini-3.8-flash) with the identical prompt:
"Review it critically for holes: methodological flaws, statistical problems,
feasibility issues, anything it gets wrong or overlooks."

Full texts: `/tmp/claude-review-full.txt`, `/tmp/gemini-review-full.txt`
(local; not committed).

## What the reviewers converged on

1. **No measurement protocol for the fidelity kernel.** GPT proposes
   K(x,y) = |<phi(x)|phi(y)>|^2 but never says how it is estimated on
   hardware: SWAP test, Loschmidt echo circuit (U†(y)U(x)), or tomography.
   Each has different shot costs and noise behavior. Without a protocol the
   "quantum scorer" arm is not implementable.
2. **O(N²) Gram-matrix cost.** Estimating every kernel entry on a QPU needs
   O(N²) circuit executions with S shots each; shot noise makes the empirical
   Gram matrix non-PSD (negative eigenvalues), which standard kernel solvers
   choke on. The recommendation's cost limits never price this.
3. **Tuning budgets must be identical in practice, not just in words.**
   RBF needs bandwidth trials; the quantum arm's measurement overhead is a
   hidden budget consumer. Predeclared "meaningful gains" need numbers
   (absolute/relative, which metric) or the goalposts can move.

## Gemini's novel catch (strongest single point)

A 1-repetition ZZ map with **linear** entanglement is classically simulable
in **O(n)** time: U†(x)U(y) is diagonal phases on a uniform superposition,
so <Φ(x)|Φ(y)> is a 1D Ising partition function solvable by 2×2 transfer
matrices. Running this exact circuit on a QPU or simulator as a "quantum"
benchmark is an empty exercise — any result can be reproduced faster, with
zero shot noise, by a 20-line classical script. Non-trivial quantum feature
space needs d≥2 repetitions with non-commuting layers, or 2D/all-to-all
connectivity (#P-hard contraction).

## Gemini's second catch

**Kernel smoothness vs. BLAKE2s avalanche.** RBF and ZZ fidelity kernels
assume metric smoothness: nearby inputs → K≈1. BLAKE2s is engineered to
destroy continuity (avalanche effect), so hash-derived angle vectors are
pseudo-random points on the Bloch sphere; the kernel matrix collapses toward
identity and the learner degenerates into nearest-neighbor lookup over noise.
The recommendation never defines the map from discrete hash states to
continuous angle vectors x ∈ [0,2π]^d. This must be designed before any
kernel benchmark.

## Claude's additional points

- Amplitude-encoding dismissal is unjustified: normalization is a one-time
  preprocessing step, not per-sample cost; ZZ "simplicity" is questionable
  given the unsolved measurement problem.
- The separate quantum scorer must have matched capacity to the classical
  arms, plus an ablation showing the quantum features (not the pipeline)
  contribute.
- Agreement≠improvement was correctly identified but needs a random baseline
  and matched-capacity classical baseline, not just held-out rankings.
- Chronological held-out is fine; one-rep ZZ measurement gives ~one bit per
  feature — a dimensionality handicap, not a quantum effect.

## What the recommendation gets right (reviewers agreed)

- Keep BLAKE2s identities unchanged; don't inject noisy quantum output
  before hashing (avoids relabeling/fragmentation of the transition graph).
- Compare against held-out empirical successor rankings, identical candidate
  successors and tie handling.
- Predeclare gains and cost limits; retire configs that don't earn their
  place; simulator improvement ≠ quantum advantage.

## Verdict

GPT's design is not yet runnable. It needs a revision round addressing:
(a) the classical-simulability objection (deepen the map or justify why the
shallow map is still a meaningful first test), (b) an explicit fidelity-kernel
measurement protocol with shot budgets, (c) the hash→angle-vector mapping,
(d) numeric gain thresholds and a cost metric that includes Gram-matrix
evaluation. No simulator or hardware work until the revised design survives
a second review round.

## Costs (this round)

- Claude review: 404 prompt + 1200 completion tokens (haiku 4.5).
- Gemini reviews: 3 calls; final full review 395 prompt + 1579 completion
  (+1919 thinking tokens counted in total 3825). Note: Gemini counts thinking
  tokens against maxOutputTokens — set --max-tokens generously (8000 worked).
- Negligible dollar cost on all three.
