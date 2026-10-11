# c0delation: Improving System Handoffs

A practical proposal for developers and agent builders

c0delation is a working name for improving the handoffs between existing tools, agents and protocols. Its central question is: what useful meaning can travel directly between systems, and what work are they unnecessarily repeating?

Start with one real workflow. Preserve its intent, evidence and permissions while adapting its representation to each receiving system. Reuse available capabilities, share stable definitions, prepare likely next steps, and measure the complete exchange. This guide proposes an approach to test; it makes no claim of deployment, novelty or measured performance.

## 1. Work at the boundary

Trace a task across its boundaries: conversation to task record, task record to tool call, tool result to decision, and decision to the next system.

For each crossing, identify:
- What the receiver must know
- What it already knows
- What changes during translation
- Which explanation, lookup or confirmation is repeated
- What evidence establishes successful completion

Evaluate tools by their actual capabilities as well as their names. A versioned document can hold a shared vocabulary. An artifact manifest can connect a review request to exact files. A test runner can supply evidence for a checkpoint.

Reuse remains subject to documented behavior and granted access. A convenient transport does not become a trusted instruction source merely because it carries useful information.

## 2. Preserve meaning while adapting format

Maintain a small, explicit task record: objective, acceptance criteria, current state, artifact references and revisions, evidence, unresolved questions, and the next requested action.

Each adapter translates this record into the receiving system’s supported format. It must preserve material distinctions such as “proposed,” “authorized,” “attempted,” and “verified.” A tool reporting success does not prove that the intended downstream result exists.

Use immutable references where possible. If a destination cannot represent an important field, report that limitation or carry a clearly defined extension. Do not silently discard it.

The aim is to remove repeated explanation while leaving enough information to reconstruct the task and check the result.

## 3. Share definitions and use context carefully

Repeated exchanges can reference a small dictionary of agreed meanings. Give the dictionary an identifier, version and content digest. Define it once when establishing context; send definitions again when the receiver lacks them or the version changes.

Symbols, short names and ordinary words are all candidates. For example, a compact token might mean “checkpoint complete; evaluate the referenced next action.” Its usefulness depends on reliable interpretation and actual token cost.

Keep action targets, permission references and material constraints explicit. Context may resolve a harmless abbreviation. It must not invent approval, select an ambiguous recipient or widen access.

Missing definitions trigger a targeted lookup or clarification. Stale definitions trigger a version check. Conflicting context blocks consequential action.

For signed JSON, use an established representation rather than an improvised serialization. [JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html) describes deterministic serialization and preserves Unicode string data; visually similar symbols therefore need explicit testing.

## 4. Prepare a small Future Branch

A Future Branch records the likely next step after success and the most relevant recovery step after failure.

Specify the observable condition, required evidence, permitted action and stopping point. Keep the branch small enough to inspect and useful enough to avoid another explanation round trip.

For example:
- If the exact patch passes the named checks, prepare its review summary.
- If a check fails, return the failure evidence and a proposed diagnosis.
- If approval is missing, preserve the result and request the specific decision.

Preparing a branch does not authorize its execution. Uncertainty may justify a question or another observation rather than an expanding tree of speculative work.

## 5. A worked handoff

Consider a synthetic patch-review workflow.

The initial handoff states: “Patch P17, revision R4, is ready for review. Tests T3 passed on R4. Review only; do not merge. If the review finds a defect, return a minimal reproduction.”

A warmed-up receiver already has the project context and dictionary. A later handoff can carry typed references to P17/R4, T3, the review-only action, its permission scope, and the relevant Future Branch. The adapter produces the native review request without repeating the whole project history.

If R5 replaces R4, the receiver does not assume that T3 covers it. If the dictionary is missing, it retrieves the definition. If “review” becomes “merge,” the permission check runs again.

Compare the complete exchanges to find out whether this actually saves work.

## 6. Keep useful failures

Save a short record of an unsuccessful candidate: what was tested, under which conditions, what evidence failed, and when reconsideration might make sense.

A rejected shorthand may still work in another context. A failed adapter may reveal a reusable constraint. Preserve useful test fixtures and conclusions without accumulating private transcripts, secrets or irrelevant data.

Revisit conclusions when dependencies or context change. Repeated improvement is measurable; compounding improvement should remain a hypothesis until evidence supports it.

## 7. Measure the whole exchange

Compare three variants: a clear prose baseline, structured dictionary references, and contextual inference.

A bounded first experiment uses six practical handoffs under nine conditions: cold context, warm context, missing definition, stale definition, ambiguous intent, changed permission, replay, wrong recipient, and confusable symbols. That produces 162 trials across three variants; allow one complete repeat, capped at 324.

Use synthetic data and inert tools. Keep models, task facts and permission checks consistent. Score against expected outcomes written before testing.

Count actual input, output and cached tokens, including setup, lookups, clarifications, retries and corrections. Report cold-start and repeated-use costs. Measure end-to-end latency, round trips, task accuracy, recovery effort and unsafe acceptance.

Advance an approach only when observed savings survive these costs without accuracy loss or security failures. A small passing test set supports further testing, not a guarantee.

## 8. Reusable checklist

- Is the intended result explicit?
- Are evidence and exact artifact revisions preserved?
- Can the receiver resolve every reference?
- Are provenance and permissions checked independently of wording?
- Are retry and replay effects controlled?
- Is the next success or failure step bounded?
- Are unsuccessful candidates recorded usefully?
- Does the measured complete exchange improve?

Where message authentication is needed, use established mechanisms such as [HTTP Message Signatures](https://www.rfc-editor.org/rfc/rfc9421.html). Optimize the work between systems while preserving their security boundaries.

## Paste-ready reusable prompt

c0delation: Work in the gaps between systems. Preserve intent across handoffs. Use existing tools for what they can actually do, beyond their intended labels. Reuse shared context instead of repeatedly explaining it. Agree on compact definitions, combine them, and update them as understanding improves. Infer harmless meaning when context is clear; clarify when ambiguity could change the outcome. Shorthand never creates permission. Before acting, prepare the most useful likely success and failure paths, including what could fail after success. Run independent, authorized tests in parallel. Keep useful lessons from failed attempts so the next attempt starts further ahead. After each result, update the shared map: what worked, what failed, under which conditions, and what should change next. Measure total time, compute, errors and recovery effort. Keep improvements that hold up, retire stale assumptions, and feed the evidence into the next cycle. Make each cycle improve the next. Keep the meaning; remove avoidable work.

Operational note: Run bounded tests with synthetic data and inert tools before deployment. Keep task prompts human-readable. This prompt grants no new authorization; existing permissions and required approvals remain in force.
