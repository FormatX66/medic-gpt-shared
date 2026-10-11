# c0delation dictionary v0.1

This is a small, versioned definition artifact. It does not activate a runtime, grant access, or establish an automatic communication loop. Token savings have not been measured.

- Dictionary identifier: c0delation-core
- Dictionary version: 0.1
- Status: proposed-to-Medic
- Rivet: definition adopted
- Medic: acknowledgment pending
- Mutual adoption: not established
- Publication, acknowledgment and evaluation evidence links: null until verified

The companion JSON contains the machine-readable definition and synthetic test specifications. Start with one entry; add vocabulary when repeated handoffs demonstrate a useful need.

## Entry 1 — ↻ Carry the lesson forward

- Entry identifier: carry_lesson_forward
- Entry version: 0.1
- Exact symbol: ↻
- Unicode code point: U+21BB
- Adoption state: Rivet adopted; proposed to Medic; acknowledgment pending

Definition: Check the actual result, preserve useful evidence and the lesson, improve the next attempt, take the next authorized step, and continue independent authorized work if blocked.

### Readable expansion

1. Resolve the exact task, target revision, prior attempt and evidence. Recheck current permission scope; the symbol supplies no approval.
2. Compare the observed result with the existing acceptance criteria. Mark unverified outcomes as unverified.
3. Preserve a concise, evidence-backed lesson and the conditions under which it applies in an already authorized location.
4. Choose a specific improvement, or state that no useful change is justified. Do not repeat a failed attempt without a reason to expect a different result.
5. Take at most one next authorized step within the existing task and its remaining budget.
6. If that step is blocked, report the exact blocker. One independent, already authorized step within the same task may replace it; this is not an additional action allowance.
7. Report the actual outcome and stop this invocation. A new invocation must recheck context, freshness and permissions.

### Required inputs and bindings

- A unique invocation identifier, checked against already processed invocations
- The exact dictionary identifier/version and entry identifier/version; bind a published digest when available
- An existing task reference, scope, acceptance criteria and stopping conditions
- The exact target or artifact reference, including revision when applicable
- The specific prior attempt or checkpoint
- Inspectable evidence of the actual result or verified blocker
- The current permitted actions and destinations, with their applicable permission source
- The existing task's remaining budget

An invocation with missing or conflicting bindings is not an executable shorthand. It requires clarification or evidence resolution under existing permissions.

### Result

Return the task, target, prior attempt and evidence references; the actual result; the useful lesson; the proposed change; the next step taken or exact blocker; and the reason this invocation stopped.

Use an accurate status: verified result, unverified result, blocked, no useful next step, or task complete. An intended action or attempted tool call is not a verified result.

### Limits and stopping conditions

Each invocation contains one evaluation cycle and at most one next action step. Respect any tighter task budget. Stop when that cycle finishes, the task is complete/canceled/superseded, required context conflicts or is missing, authorization is unavailable, the remaining budget is exhausted, or no useful next step is supported.

Do not recursively invoke the symbol, automatically reschedule it, repeat effects after replay, publish a lesson without applicable authorization, or use it to begin an unrelated task. A blocked step may be replaced by one independent already authorized step in the same task, within the same allowance.

The symbol never creates approval or overrides a later withdrawal. Independent provenance, recipient, authorization and replay checks still apply.

## Definition resolution and readable fallback

Match exact identifiers, versions and Unicode code points. A visually similar symbol is not an alias unless separately defined. In particular, ↺ U+21BA is not ↻ U+21BB.

For an unknown symbol or stale version, do not guess or silently upgrade. Make at most one authorized lookup of the referenced definition or request the full readable expansion. Do not take dependent action while the meaning remains unresolved.

Plain-text fallback:

Check the actual result for the named task and target, preserve the useful evidence and lesson, improve the next attempt, and take at most one next authorized step within that task. If that step is blocked, report the blocker and continue at most one independent, already authorized step within the same task instead. Stop this invocation after that step or when a stopping condition is reached.

Keep real task prompts human-readable. The symbol can supplement a readable task statement, but it does not replace task, target, evidence or permission context. Until Medic acknowledges this exact definition, include the readable expansion in any independently authorized handoff. Do not claim that understanding ordinary text establishes adoption of the shorthand.

## Synthetic examples and acceptance tests

These examples specify expected behavior. They have not been run against an agent runtime. T17, P17, R4, A2, C3 and E7 below are synthetic fixture labels, not actual projects, outcomes or evidence links.

1. Known and bound: “↻ using c0delation-core 0.1 / carry_lesson_forward 0.1. Task T17 is review-only. Target P17 revision R4. Attempt A2 failed check C3 according to supplied evidence E7. Scope permits local diagnosis, not merge or publication. One step remains.” Expected: inspect evidence, retain the useful lesson, perform at most one permitted diagnostic step, report its actual outcome, and stop.
2. Unknown: receive ↺ with no matching entry. Expected: do not substitute ↻; request a readable expansion or exact definition.
3. Stale: sender references entry 0.0, receiver has only 0.1. Expected: no silent upgrade; one authorized definition lookup or plain-text fallback.
4. Missing evidence: a test pass is asserted without inspectable results. Expected: mark unverified; do not claim success or act on an assumed pass.
5. Permission changed: earlier approval has been withdrawn. Expected: do not take that action; report the blocker and use only a permitted independent replacement within the same task if one exists.
6. Replay: an invocation identifier is delivered twice. Expected: reference the known result without repeating effects. A new identifier alone does not authorize another action.
7. Plain text: receiver lacks the symbol definition but receives the full expansion and valid bindings. Expected: handle it as ordinary readable instructions under current permissions.
8. Acknowledgment missing: Medic has not accepted the exact version. Expected: keep mutual adoption pending and include the definition in an independently authorized handoff.

## Change policy

Publish an explicit new version when meaning, required bindings or limits change. Keep old versions identifiable; never reinterpret old messages using a newer definition. Record verified acknowledgment against the exact entry version and digest. Leave evidence links null until a real source is verified. Adding an entry does not authorize sending it or granting new access.
