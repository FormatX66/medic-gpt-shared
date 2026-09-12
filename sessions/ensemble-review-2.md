# Ensemble review 2 — revision verification rounds (2026-09-12)

Two further red-team rounds on the revised ZZ benchmark (following
`sessions/ensemble-review-1.md` and `sessions/benchmark-revision-1.md`).
Same method: identical prompt to Claude (claude-haiku-4-5-20251001) and
Gemini (gemini-flash-latest → gemini-3.8-flash), independent, adversarial.

## Review round 2 (against revision 1)

| Finding | Claude | Gemini |
|---|---|---|
| 1. Measurement protocol | Fixed | Fixed |
| 2. Gram cost / non-PSD | Partially (clipping is a band-aid) | Partially (scaling unaddressed) |
| 3. Budgets identical | Fixed | Partially (wall-clock is hardware-dependent) |
| 4. Simulability | **Not fixed** — d=2 linear still MPS-tractable (χ≤4) | **Not fixed** — barely increases treewidth |
| 5. Hash avalanche | Fixed | Fixed |
| 6. Baselines/ablation | Fixed | Partially (amplitude encoding dropped; fixed CZ wastes capacity) |

New holes found in round 2:
- **Gemini**: the "revised" circuit wasn't a ZZ map at all — fixed CZ gates
  instead of parameterized R_ZZ(θ_i·θ_j). No data-dependent entanglement.
- **Gemini**: exponential kernel concentration — off-diagonal fidelities fall
  to 1e-4..1e-2 at n≥10; shot discretization collapses the Gram matrix to
  identity. Needs angle-scaling calibration.
- **Claude**: k/n unpinned; feature→angle mapping underspecified; no
  tie-breaking rule; no noise model; tuning-scope ambiguity; random-baseline
  seeds unspecified; no significance test; thresholds unjustified.
- Verdicts: Claude "runnable with changes", Gemini "not yet".

## Review round 3 (against revision 2 + corrections)

- **Claude**: RUNNABLE WITH CHANGES. One blocking item: classical budget
  10,000 — each arm or pooled? Non-blocking risk: S=10 marginal for 5% effect.
- **Gemini**: NOT YET. Blocking: (1) **S=10 shot collapse** — P(zero-count) >
  0.98 on 12 qubits, Gram matrix → identity, ΔK=0.10 resolution obliterates
  the signal; (2) **tuning allowance illusion** — 10 pair-evals can't tune
  anything, one Gram rebuild = 4,950 pairs; (3) power-analysis mismatch.
  Also: n=12 is exactly simulable (4096 amplitudes) — "not a toy" is false.

## Resolution (GPT correction round 3, driven by Medic)

1. Exact statevector overlaps for the Gram matrix (infinite-shot limit) +
   separate S=1024 shot-noise ablation. S=10 dropped entirely.
2. Hyperparameters predeclared, zero tuning allowance, zero Gram rebuilds.
3. Classical budgets: 10,000 each; Arm A's unit defined as
   candidate-successor scoring evaluations. Arm C: 9,950 ≤ 10,000.
4. Explicit non-claim: n=12 is exactly simulable; d=3 all-to-all matches the
   hardware-intended circuit so the simulator phase validates the real
   pipeline; no advantage claim at simulator phase.

## Final standing

All blocking issues from both reviewers are addressed. Spec is **runnable at
simulator phase** (`sessions/benchmark-revision-2.md`). Residual risks, both
non-blocking and predeclared: shot-noise ablation may show the S=1024 regime
is underpowered (that's what the ablation is for); hardware phase needs its
own QPU-seconds budget.

## Costs (rounds 2–3)

- Review round 2: Claude 3,321 tokens; Gemini 3,289 tokens.
- Review round 3: Claude 1,616 tokens; Gemini 2,884 tokens.
- GPT correction rounds: session `benchmark-revision-1`, 6 turns total,
  ≈ $0.0053. All negligible.
