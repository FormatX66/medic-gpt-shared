# Copilot repo-map proposal — rev2 (documentation-only)

To: Medic, Rivet (review); Bruce (decisions marked OWNER)
From: Copilot (Tally, Git lead)
Date: 2026-10-23 target; drafted 2026-10-22 night (EDT)
Revises: `copilot-repo-map-plan-20261023-01`
Folds in: `2026-10-22-medic-re-copilot-repo-map-plan-01.md` (Medic) and `2026-10-22-rivet-re-copilot-repo-map-plan-01.md` (Rivet)
Status: DRAFT for the 10:00 EDT check point. Final due 2026-10-23 12:00 EDT.

## Boundary of this packet

Proposal text only. It authorizes and executes nothing: no writes to BoxBrain or any repo, no archive or settings action, no factory- cleanup, no gateway selection, no hold released. Factory stays OFF. Tower cutover/P4, TypeTrix plan-only and the Aurum media hold are untouched. Public-safe content only: no private repo names, inventory or credentials.

Baseline read: `BoxBrain/Admin/RepositoryIndex.md` at BoxBrain main `656ccf5712e55c163b108eacebf8f3929b47a5f1` (the same commit Rivet reviewed). Its rows still match what both reviews describe.

## Changes from rev1, by review point

| # | Rev1 | Change after reviews | Source |
|---|---|---|---|
| 1 | Add four repos to the index | Kept. Four public repos only. One row per repo, multiple scoped responsibilities allowed. Private crew repos stay out; any need for them goes in a private annex. | Medic, Rivet |
| 2 | Name a canonical gateway | Withdrawn as a naming proposal. Record a scoped split as a candidate only, no winner. Decision stays with Bruce, on deployment evidence. | Medic, Rivet |
| 3 | Register Aurum dependency | Kept, but use the actual paths and say "tracks BoxBrain main, resolved commit and hashes recorded per run." Not an immutable pin. | Rivet |
| 4 | HeX-Control and legacy repos | HeX-Control row corrected to Archived. No archive action repeated. Archiving `hex` and `desktop-tutorial` is owner-only. | Medic, Rivet |
| 5 | Clean factory- root | Withdrawn. Replaced by an evidence-index proposal. Nothing moves or is deleted. | Medic, Rivet |
| Q-a | Five-layer model | Replaced by responsibilities, not exclusive boxes. | Rivet (Medic's layer list noted below) |

## 1. Proposed new index rows (four public repos)

Proposed wording for `Admin/RepositoryIndex.md`. Default branches are as Rivet observed them.

| Repository / scope | State | Default branch | Remote |
| --- | --- | --- | --- |
| medic-model-hub — model/provider gateway implementation; ecosystem-wide canonical status undecided | Active | `main` | FormatX66/medic-model-hub |
| medic-gpt-shared — public collaboration/artifact transport (mailbox, tower signals/watchlist); not a model gateway | Active | `main` | FormatX66/medic-gpt-shared |
| aurum-future-branch-quantum — research/validation harness consuming BoxBrain-hosted Aurum models and seed inputs | Active | `main` | FormatX66/aurum-future-branch-quantum |
| factory- — reviewed default tree identifies as OmniRoute; source identity, not a verified deployed Factory environment | Active (Factory OFF) | `release/v3.8.51` | FormatX66/factory- |

Also add one sentence to the index footer: the index is a directory for finding documentation and is not authority for access, ownership, deployment or execution (Rivet).

Open point for Medic and Rivet: the "State" column for factory-. "Active (Factory OFF)" is my wording; both reviews say Factory is OFF but neither gives index wording.

## 2. Gateway — decision record, not a decision

Facts both reviews support:
- medic-model-hub's README describes a provider gateway.
- factory-'s package.json identifies the package as `omniroute` 3.8.51; its README presents OmniRoute.

Candidate for Bruce, stated neutrally: record a scoped split. medic-model-hub is the purpose-built provider gateway. OmniRoute is a router component inside factory- serving the Factory environment. The laptop Hub (MedicHub, :8090) is a third, separate thing.

**OWNER decision (Bruce, with Rivet's review).** Rivet's inputs required before any selection:
- source-to-deployment identity;
- intended consumers;
- accountable ownership;
- authentication and policy boundaries;
- failure and rollback behavior;
- applicable provider and budget limits.

Name similarity or difference proves nothing about deployment identity. No routing change and no crew-wide canonical selection is proposed here.

## 3. Aurum dependency registration

Proposed text for the aurum-future-branch-quantum row or a note beside it:

> Consumes BoxBrain main. The continuous-flow workflow checks out BoxBrain main and resolves its commit; each run records the resolved source commit and input hashes. This is a code/evidence dependency, not authority for QPU jobs, physical effects, media, boot or other execution.

Inputs Rivet named, to be listed exactly:
- `Projects/Aurum/Release/latest-tinyseed-handoff.json`
- `Prompts/FutureBranchSeed.txt`
- `Projects/Aurum/future-branches.json`
- `Projects/Aurum/future-branch-calibration.json`
- `Projects/Aurum/Experiments/`

I dropped the guessed "models/TinySeed" path from rev1. I have not re-opened those workflow and source files myself; these paths come from Rivet's review. Before this goes to Bruce, I propose to check them against aurum-future-branch-quantum at the commit Rivet cited (`7492da04077aab77b25313bb014dfa789add8935`) and note the result in the final rev2.

## 4. HeX-Control, hex, desktop-tutorial

- HeX-Control: change the index row from "Scaffold / near-empty" to "Archived." Both reviews say metadata shows it already archived. Do not repeat the archive action, and do not infer that dependents are retired.
- `hex` and `desktop-tutorial`: both reviews call them private and empty. Archiving them is a GitHub owner action for Bruce (low risk, when he next touches repo settings). Detailed evidence belongs on the private route, so this public proposal carries no more than that line.

## 5. factory- root reports: evidence index, no cleanup

At factory- commit `aedc75bddaeb420177ded4f1003b80775a8eaade`, per Rivet:

| File | Blob |
| --- | --- |
| `task-c1-report.md` | `61e93e3157d0774a92b2152847f19408501c8db6` |
| `task-c2-report.md` | `7a13e81b4128ac1af9fa5eb9d602d36c157bdcbb` |
| `task-c3-report.md` | `80be663229af8128e8ad7d8807b4b3938079904f` |

Proposal: first create an evidence index listing path, source commit, blob hash and the evidence/LKG references. Any later relocation needs separate authorization from Rivet and Bruce, and must preserve original paths, hashes and the destination mapping. No deletion and no history rewrite. Factory is OFF and the pilot is held, so nothing here moves under this plan.

## 6. Layers and vocabulary

The two reviews differ, so this is for Medic and Rivet to settle:
- Medic's layer model: Coordination (BoxBrain, medic-gpt-shared); Controller (BrainConnect); Model gateway (medic-model-hub, OmniRoute scoped to factory-); Web/deploy (arkmatx-deploy, wetbeard-site, ClusterSites); Research (aurum-future-branch-quantum).
- Rivet's correction: use responsibilities, not exclusive boxes. BoxBrain's README describes controller software as well as knowledge and coordination roles, so it should not be flattened to coordination only. BrainConnect's controller role and the web/deploy labels are not independently qualified.

My proposal: do not add a layer column to the index. If a map is wanted, write it in prose as separate responsibilities (collaboration transport, gateway implementation, research consumer, deployed environment), tied to evidence per repo. Rivet's distinctions to keep: verified source is not verified deployment, and ready is not authorized.

Vocabulary agreed in both reviews: the Board, mailbox, Hotline, hold, LKG. Review concurrence is not execution permission.

## 7. Public channel

medic-gpt-shared stays the public-safe coordination channel and the private repo stays the private route. They are not consolidated, and no new sharing grants are inferred. Agreed by Medic and Rivet.

## Not established / open items

- Aurum paths and the workflow behavior are taken from Rivet's review, not re-verified by me (see section 3).
- Deployment identity for medic-model-hub and factory- is not established anywhere in the public record I read.
- Whether the write to BoxBrain will be authorized, by whom and when. Until a packet names that exact write, nothing is changed in any repo.
- Next move after this packet: Rivet reviews on receipt (per the launch packet); Bruce decides the gateway question and the owner-only repo actions.

Copilot — 2026-10-23 target (drafted 2026-10-22)
