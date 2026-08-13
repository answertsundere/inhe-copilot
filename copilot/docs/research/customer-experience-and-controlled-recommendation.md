# Customer Experience and Controlled Recommendation Research

## Purpose

This note records external patterns and the resulting proposed contract for a
customer-service Agent that should sound natural, recognize when the customer
needs more help, and make commercially useful recommendations without turning
unverified inference into a product claim. It is research and design input; it
does not authorize a new production path, delivery authority, or marketing
automation.

## Mature-System Findings

Intercom documents a conversational support model that uses natural language,
preserves context, asks follow-up questions when needed, and offers or performs
human escalation for direct requests, frustration, and repeated unresolved
loops. Its escalation documentation distinguishes detection and escalation
rules from the workflow that routes the resulting handoff.

- https://www.intercom.com/help/en/articles/11433030-conversational-fin-experience
- https://www.intercom.com/help/en/articles/12396892-manage-fin-ai-agent-s-escalation-guidance-and-rules

Salesforce documents product upsell/cross-sell as a catalog-connected service
capability: the Agent clarifies the need, filters current catalog products, and
presents a curated, limited set rather than an unbounded list. Its documented
actions use current product and pricing data for eligible candidates.

- https://help.salesforce.com/s/articleView?id=xcloud.aslm_agentforce_for_product_upsell_and_cross_sell_in_service.htm&language=en_US&type=5
- https://help.salesforce.com/s/articleView?id=xcloud.aslm_included_agent_actions.htm&language=en_US&type=5

These products support two reusable design conclusions for this project:

1. Conversation signals can select a service or handoff strategy, but routing,
   task ownership, and completion remain explicit stateful workflows.
2. Commercial recommendations must start with current, filtered catalog
   candidates and a stated customer need. Generative language only explains a
   selected candidate; it does not create the candidate, price, promotion, or
   suitability claim.

## Proposed Agent Contract

### 1. Bounded Customer-Experience Signals

The formal Pipeline should eventually derive a versioned `ServiceStrategy`
from canonical conversation goals, deterministic risk state, and an attributed
interaction signal. Suggested stable fields are:

- `mode`: `resolve`, `clarify`, `offer_handoff`, `direct_handoff`, or
  `suppress_recommendation`;
- `emotion_signal`: `unknown`, `neutral`, `negative`, or `strong_negative`,
  with source turn IDs and confidence/abstention metadata;
- `loop_state`: canonical unresolved-goal repetition count, not a keyword or
  sentence-template match;
- `reasons`: typed goal, risk, policy, and rule identifiers; and
- `handoff_reason` and `recommendation_eligibility`: explicit outcome fields.

The signal must not diagnose a person, enrich a permanent customer profile, or
change identity, evidence admission, price, product suitability, or action
authority. A high-confidence-but-wrong emotion classification must degrade to
a polite clarification or human offer, not a stronger claim.

### 2. Human-Like Resolution and Handoff

The reply owner should first answer the evidence-supported portion, name the
specific remaining gap in plain language, and request only the information
needed to close that gap. It can acknowledge inconvenience and use the
configured brand tone, but must never promise that a live action occurred.

Direct requests for a person, high-risk cases, action requests that need a
human, or a configured severe-complaint rule require durable `HandoffTask`
creation/assignment once P4 exists. Repeated unresolved goals may offer a
handoff before direct escalation, subject to the configured policy and the
availability of a real routing target. A text-only transfer promise is not
acceptable.

### 3. Recommendation and Promotion Eligibility

A recommendation is an optional customer-service outcome, not a default reply
paragraph. It may be evaluated only after the primary goal is resolved or when
the buyer explicitly requests discovery/comparison. Eligibility requires all
of the following:

- direct customer need or voluntarily supplied preference linked to canonical
  goals;
- exact current identity where compatibility depends on an existing product;
- a typed, read-only live catalog result with allowed customer-facing fields,
  active status, timestamp, freshness, and provenance;
- a configured rule that maps the expressed need to the candidate and every
  buyer-visible benefit claim; and
- an explicit customer-visible price/promotion eligibility result if price,
  stock, discount, gift, urgency, or availability is mentioned.

The candidate selector, not the language model, enforces product status,
compatibility, eligibility, inventory policy, policy exclusions, and a small
configured display cap. The model may explain the selected recommendation in
natural language only from the supplied rationale. It must preserve an opt-out
and avoid pressure, fabricated scarcity, or unrelated alternatives.

The system must suppress recommendations for unresolved complaints, high-risk
or after-sales matters, human requests, identity ambiguity, live-source
failure, stale/partial evidence, customer opt-out, or any sensitive-attribute
inference. In particular, it may not claim that an item is right for a baby or
child from category labels, tone, or guessed age/health/development. Such a
statement needs explicit buyer-provided criteria and independently approved,
scoped product evidence.

### 4. Trace, Review, and Evaluation

Each strategy and candidate decision should record source IDs, current-data
timestamps, rule/policy version, reason codes, goal IDs, candidate IDs,
suppression reason, and the exact commercial claims rendered. Customer-visible
traces must redact internal cost, score, and unrelated customer data.

Before any operational rollout, E0 tests must mutate source freshness,
eligibility, complaint state, human request, loop count, opt-out, identity,
and candidate ordering. E3 real-Gold labels must separately score resolution,
tone, handoff correctness, recommendation relevance, inappropriate promotion,
unsupported claims, and latency. Until that happens,
`real_accuracy=null` and `optimization_unverified=true` remain mandatory.

## Delivery Sequence

1. Keep the active P1 scope on atomic multi-goal understanding and Claim
   Resolution; no recommendation or emotion-driven reply branch is added.
2. After P1 E2, complete P2's source-of-truth ADR and typed live reads with
   redaction and freshness admission.
3. Implement P4 durable handoff ownership and routing before enabling direct
   escalation outcomes.
4. Add the typed `ServiceStrategy`, candidate-selector contract, and offline
   mutation suite through the existing formal Pipeline; add an ADR before any
   production-flow ownership change.
5. Use Supervisor Assist and approved real-Gold review before considering any
   delivery expansion. Autonomous send remains governed by P7 only.