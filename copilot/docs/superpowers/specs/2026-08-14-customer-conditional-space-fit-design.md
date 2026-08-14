# Customer-Conditional Space-Fit Design

## Scope

This P1 Gold Conversation Quality slice addresses a review-only conversation
where the buyer supplies a product measurement as a condition and a separate
available-space measurement, then asks for the consequence. It does not add
product truth, retrieve new facts, execute an action, or enable delivery.

## Confirmed Failure

The frozen diagnostic classified the requested conclusion as
`dimensions/height`. The buyer was actually asking for a `space_fit`
conclusion, while the stated product height and available height were premises.
The resulting claim had no applicable policy family, remained unresolved, and
the fallback requested product identity again.

The earliest broken owner is Turn Understanding's semantic distinction between
a requested measurement and a requested fit conclusion. Conversation history
already reaches the Composer and is not the first loss point.

## Considered Approaches

1. **Prompt-only exception.** Let the Composer infer the distinction from raw
   turns. This is small but leaves the canonical goal and Claim Resolution
   diagnostics incorrect.
2. **Promote buyer statements to evidence.** This would make the comparison easy
   but violates the evidence contract because a buyer-supplied or hypothetical
   product value is not reviewed product truth.
3. **Semantic boundary plus conditional unresolved composition.** Improve the
   model-visible FactType boundary so the requested conclusion is `space_fit`.
   Keep buyer-supplied values in conversation context only. Permit the existing
   Composer to explain a direct logical consequence only with an explicit
   customer-condition boundary, while the actual product value remains
   unresolved. This is the selected approach.

## Data And Authority Contract

- `admitted_evidence` remains the only source of assertable product facts.
- Current and recent customer turns remain non-factual conversation context.
- A conditional comparison does not receive an evidence UID and cannot satisfy
  a product-fact claim.
- The Composer may use explicit customer-supplied quantities or conditions only
  to state their direct consequence under an explicit conditional boundary.
- It may not infer a missing axis, area, product identity, hidden measurement,
  safety property, service outcome, or media availability.
- The clause remains `unresolved` when the actual product value is not admitted.
- Deterministic Final and Unified Audit remain authoritative. Every candidate
  remains review-only with `can_send=false`.

## Implementation Boundary

The change is limited to existing owners:

1. `semantic_fact_type_service.py` supplies a clearer model-visible distinction
   between measurement lookup and fit/consequence questions. No customer phrase
   list or sample branch is added.
2. `model_first_answer_composer_service.py` documents the narrow conditional
   behavior for unresolved clauses using the already projected current question
   and recent turns. It does not compute or generate reply text in Python.
3. Existing Final/Audit paths are tested to ensure an unconditional product
   assertion without admitted evidence remains blocked.

No Graph node, service, model call, reply owner, retry, repair, fallback, policy
registry, delivery rule, or production feature flag is added.

## Acceptance

- A semantic-provider result can distinguish a measurement request from a
  space-fit conclusion without sample-specific logic.
- The Composer receives both the current question and bounded recent turns.
- A conditionally framed unresolved comparison is accepted with zero evidence
  references and remains review-only/no-send.
- An unconditional product measurement assertion still fails the final fact
  boundary when no admitted evidence exists.
- Existing dimension scope, high-risk, media, service-action, and delivery tests
  do not regress.
- Synthetic results remain regression evidence only;
  `real_customer_accuracy=null` and `optimization_unverified=true` remain true.
