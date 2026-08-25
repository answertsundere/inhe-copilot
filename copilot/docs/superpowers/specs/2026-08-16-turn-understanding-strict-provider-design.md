# Turn Understanding Strict Provider Qualification Design

## Goal

Qualify and optionally route Turn Understanding through the existing strict
Provider transport so elliptical follow-ups can use bounded role-aware history
without copying historical text into current-message provenance.

## Active Priority And Boundary

This work serves P1 Gold Conversation Quality. The earliest failing owner is
Turn Understanding transport/provenance, observed after the fixed `3x1` gate
rejected a historical source span for an elliptical logistics follow-up.

The existing Pipeline remains:

```text
canonical input
-> existing graph
-> Evidence Admission
-> Claim Resolution
-> Model-first Composer
-> Deterministic Final
-> Unified Audit
-> Delivery Gate
```

No Graph node, service, reply owner, evidence role, retry, repair, fallback, or
send condition is added. Formal knowledge remains query-only and every
candidate remains review-only with `can_send=false`.

## Chosen Approach

Add a role-scoped, default-disabled strict transport configuration to the
existing `SemanticFactTypeService`. It reuses
`StrictDecisionProviderService`, `MINIMAL_PROVIDER_OUTPUT_SCHEMA`, the existing
Turn Understanding prompt, payload projection, and the existing deterministic
normalizer/provenance validator.

Two rejected alternatives are:

1. Replacing the formal Agent model globally. This changes unrelated Composer,
   tool, audit, and reply behavior and cannot isolate the failing owner.
2. Handling ellipsis with customer-text keywords. This cannot generalize and
   would create a second semantic owner in Python.

Official Provider documentation is capability evidence only. A model is usable
for this role only after the repository qualification matrix passes.

## Configuration Contract

The existing config module owns these role-scoped settings:

- `COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED`, default `false`
- `COPILOT_TURN_UNDERSTANDING_PROVIDER`
- `COPILOT_TURN_UNDERSTANDING_API_BASE`
- `COPILOT_TURN_UNDERSTANDING_API_KEY`
- `COPILOT_TURN_UNDERSTANDING_MODEL`
- `COPILOT_TURN_UNDERSTANDING_CAPABILITY`
- `COPILOT_TURN_UNDERSTANDING_TIMEOUT_SECONDS`
- `COPILOT_TURN_UNDERSTANDING_DISABLE_THINKING`
- `COPILOT_TURN_UNDERSTANDING_QUALIFIED`
- `COPILOT_TURN_UNDERSTANDING_QUALIFICATION_FINGERPRINT`

The role never inherits formal Agent, Composer, decision-shadow, or Unified
Audit credentials. Incomplete, unqualified, or fingerprint-mismatched config
fails closed before a Provider call. With the feature disabled, the current
formal `json_object` behavior remains unchanged.

## Data Flow

```text
current customer message + bounded role-aware recent turns
-> existing field-aware privacy projection
-> strict Provider request using the existing schema
-> existing local normalization
-> current-message exact-span validation
-> canonical goal identities and diagnostics
```

The strict Provider returns only the existing minimal `goals` object. Server
code derives span offsets, digests, goal references, owner metadata, and
diagnostics. History remains context and never becomes evidence.

### Canonical Stability Boundary

Provider repeatability is measured only over fields that are authoritative for
the goal kind. `semantic_key` remains exactly authoritative for a
`contextual_constraint` and for an unmapped `customer_goal` bound to a trusted
`policy_intent_ref`. An unbound unmapped customer goal requires stable
presence, but its free wording is non-authoritative. The field is also
diagnostic-only for non-renderable `service_action`, `media_request`, and
`evidence_dependency` goals. Those non-renderable goals reach the Composer as
opaque goal references and statuses; their free semantic labels cannot change
evidence admission, action execution, reply delivery, or `can_send`.

Exact current-turn source validation remains fail-closed. After a Provider
substring is proven to occur exactly once in the current message, the existing
Turn Understanding owner may normalize it to its deterministic punctuation
bounded clause. If multiple distinct atomic source spans occupy the same
clause, each exact span is retained so normalization cannot merge goals. Text
from history, missing text, repeated ambiguous text, and paraphrased text are
still rejected. This is a provenance normalization rule, not a semantic parser:
it never invents text and never crosses a current-message clause boundary.

## Qualification Matrix

The read-only qualifier uses fictional conversations only and repeats every
case three times. It covers:

- standalone acknowledgement and conversation closure;
- explicit current-turn product and promotion requests;
- logistics and after-sales elliptical follow-ups;
- identical short text occurring in both history and the current message;
- an agent statement that must not become buyer truth;
- a current correction that supersedes, but does not copy, history;
- multiple atomic goals in one current message;
- factual/media requests that coexist with an explicit customer-service speech
  boundary;
- separately scoped product and packaging aggregate-dimension requests,
  including colloquial wording;
- malformed schema, historical-source, timeout, truncation, and free-text
  counterexamples through deterministic tests.

Qualification requires 100% execution, schema, current-source provenance,
semantic expectation, and repeat stability, with zero timeout, truncation,
free-text fallback, historical-source admission, knowledge writes, or send
changes. Authoritative semantic stability and source-provenance stability are
reported separately and both must reach 100%. Reports contain only safe
Provider identity, model, hashes, metrics, latency, and reason codes.

## Runtime Gates

1. Run the synthetic Provider matrix.
2. If qualified, run one fictional long follow-up through the strict role.
3. Start an isolated current-source 5013 with the exact qualification
   fingerprint and run the fixed `1x1` gate.
4. Run fixed `3x1` once.
5. Only after `3/3`, run the 20 authorized internal conversations once.

Any infrastructure, schema, provenance, timeout, empty-reply, knowledge-write,
or send-boundary failure stops the next stage. No retries are used to wait for
an accidental pass.

## Acceptance And Rollback

The role is an engineering candidate, not an accuracy claim. Even a complete
20-case run keeps `real_customer_accuracy=null`, mandatory human review, and
Autonomous Send blocked.

Rollback is the single strict-role feature flag. Disabling it restores the
existing formal Turn Understanding transport without changing schemas or
downstream owners.
