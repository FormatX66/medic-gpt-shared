# Assignment — Tally: GitHub usage audit (follow-on to the repo map)

From: Medic (producer)
To: Tally (Copilot), Git lead
Date: 2026-10-23
Authorization: Bruce, 2026-10-23 07:19 EDT in Medic's main chat: "Queue the GitHub audit to Tally." His framing: there is a lot of GitHub tooling and functionality the crew is not fully using.

## Scope

Audit, per repository in the repo map (BoxBrain, medic-gpt-shared, medic-model-hub, aurum-future-branch-quantum, factory-, and the private crew repos by name only — no private content in the deliverable), which GitHub capabilities exist, which are enabled, and which the crew actually uses. You are the only crew member seated natively inside GitHub; Medic works through a Contents API helper and is not gh-logged-in, so settings-level facts are yours to read.

Cover at minimum: Issues, Projects, pull requests and review mechanics (required reviewers, status checks), Actions (workflows present, schedules, artifacts), branch protection, environments and deployment approvals, releases/tags, secret scanning and push protection, Dependabot, webhooks, Discussions, wiki, and Copilot surfaces (code review, cloud-agent assignment).

## Rank adoption candidates against the crew's named frictions

1. Queue visibility — the crew queue lives in a VM-side JSON file; the VM rotates hourly. (Issues/Projects as the queue surface?)
2. Review lane — reviews travel as outbox packet files. (PRs with diffs, approvals, checks?)
3. Runner fragility — signals/watchlist publishers and hash verifications run as VM crons. (Scheduled Actions?)
4. Pickup gaps — Rivet polls; sends do not prove pickup. (Webhooks?)
5. LKG tracking — last-known-good is prose commit SHAs. (Releases/tags?)
6. Holds — WP6/Factory-style holds are discipline and prose. (Branch protection, environment approvals?)
7. Secret safety — the public repo has no automated guard; see the October 9 history warning on the public record. (Secret scanning, push protection?)
8. Your own friction — desktop-app approval clicks vs the Copilot cloud-agent assignment route (Bruce scoped your access to all his repos).

For each candidate: what it replaces, what it costs, what evidence would prove it works, and what could break. Name the three or four adoptions that pay for themselves first.

## Boundary

Audit and proposals only. No settings changes, no enabling features, no repository writes, no new access. Enabling anything is Bruce's decision, item by item. Keep private inventory and private content out of the deliverable, per the standing public/private route rule.

## Deliverable and ETA

One audit document in your clone; Medic verifies and publishes it byte-identically on the standing route. ETA: **Saturday 2026-10-24, 12:00 EDT**. If the settings read turns out shallower than expected, deliver what the evidence supports and mark the rest unverified — do not fill gaps from assumption.

— Medic
