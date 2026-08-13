# P1 Multi-Goal Completion Boundary

## Status

`P1-MULTIGOAL-001F` is a scope decision record, not a customer-facing feature.
It records the outcome of the reconstructed E1 review after the dimension
subject-scope repair. It does not approve a new reply owner, action executor,
or send authority.

## Verified Finding

The reviewed compound after-sales case reached the formal Pipeline with three
distinct atomic `customer_goal` records: condition confirmation, outcome
selection, and compensation assessment. All three remained unresolved, all
three received an individual review-only clause, and no refund, replacement,
compensation, or other external action was selected or executed.

This distinguishes the current gap from an atomic-goal loss defect. The
existing Turn Understanding and Claim Resolution owners preserve the customer's
separate needs and fail closed when there is no admitted fact, policy result,
or live service result.

## Current Boundary

The active P1 contract freezes Composer wording, delivery, live evidence, and
durable handoff ownership. Its existing Composer contract requires an
unresolved clause without unsupported cause, probability, performance,
eligibility, policy outcome, or promised follow-up. Therefore P1 cannot safely
turn an unresolved after-sales, installation, or high-risk question into a
customer-visible evidence checklist, refund/replacement decision, compensation
statement, or human-task promise.

In particular, the following are prohibited until their owners and evidence
contracts are approved:

- claiming that an outcome is unsupported, denied, approved, or scheduled;
- requesting a fixed set of documents as though it is a current platform
  requirement;
- promising a human reply, escalation SLA, refund, replacement, compensation,
  attachment, or media delivery;
- deriving a product, policy, order, or eligibility fact from a semantic key;
- changing `can_send`, `requires_human_review`, or Delivery authority.

## Permitted P1 Work

P1 may still repair a demonstrated deterministic defect in its existing owners
when a current-turn request is lost, merged, misclassified, given invalid
provenance, associated with the wrong identity, or resolved against incompatible
evidence. Such a repair must preserve the current response-owner and no-send
boundary, add a general regression, and repeat the isolated E0/E1 checks.

## Required Reauthorization for Customer-Visible Completion

The reviewed quality gap needs a separately authorized P3/P4 contract before
implementation. That contract must define:

1. a typed, read-only source for current after-sales/policy/action eligibility;
2. a durable handoff-task state model, acknowledgement and audit receipt for
   any promised human follow-up;
3. the exact non-factual action guidance that is allowed in the Composer input;
4. failure behavior for missing identity, unavailable sources, conflicting
   policy, expired evidence, and human opt-out; and
5. independent regression and human-review gates while `can_send=false`.

This keeps the project on the path to a capable customer-service Agent: it does
not confuse fluent wording with a completed service action, and it leaves
volatile product and policy facts to their approved answer-time sources.
