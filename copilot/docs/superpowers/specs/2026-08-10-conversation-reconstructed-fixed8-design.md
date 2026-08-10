# Conversation-Reconstructed Fixed-8 Design

## Status

- Date: 2026-08-10
- Branch: `codex/recovery-conversation-eval-v1`
- Evidence class: `conversation_reconstructed`
- Intended use: P1 engineering-quality baseline for Supervisor Assist
- Explicit non-use: real-customer accuracy, Gold approval, Autonomous Send, or production promotion

## Problem

The recovered repository preserves the formal Pipeline, safety contracts, P1
architecture, and prior engineering checkpoints. The exact Fixed-8 dataset,
dataset manifest, query-only formal-knowledge snapshot, and runtime binding were
not recovered. Their original hashes cannot be reproduced safely from prose.

The project still needs a stable conversation-quality gate. Reusing unrelated
legacy simulator artifacts would mix evaluation contracts, while inventing the
old hashes would destroy provenance. The replacement therefore needs a new,
explicit identity and a lower evidence grade.

## Decision

Create a new versioned eight-case dataset named
`p1-conversation-reconstructed-v1`. Its source class is
`conversation_reconstructed`, and its manifest states that cases were rebuilt
from durable project documentation, previously discussed failure families, and
existing formal contracts. It is not the missing Fixed-8 and cannot replace a
future restored real dataset.

The dataset will run through the existing canonical input and formal Pipeline:

```text
versioned reconstructed case
-> canonical conversation input
-> existing AnalysisPipeline
-> Evidence Admission
-> Claim Resolution
-> Model-first Composer candidate
-> Deterministic Final
-> advisory Unified Audit
-> forced human review / can_send=false
-> post-run evaluator
```

No new Graph node, reply owner, production service, retry, repair, fallback, or
send condition is introduced.

## Alternatives Considered

### Recreate the missing Fixed-8 identity

Rejected. The original content and hashes are unavailable. Reusing the name or
expected hash would make an unverifiable reconstruction appear authoritative.

### Reuse old simulator candidates as the baseline

Rejected. Those files were produced under different model, scoring, context,
and contract versions. They remain useful historical diagnostics but cannot
define the recovered P1 gate.

### Create a new traceable reconstruction

Accepted. It provides a fast, repeatable engineering baseline while preserving
the distinction between reconstructed evaluation, synthetic regression, and
real approved Gold accuracy.

## Fixed Coverage Matrix

The first version contains exactly eight cases. Cases use generic products and
anonymous identities; they do not branch on a production SKU, order number,
customer phrase, or historical run ID.

| Alias | Conversation capability | Required contract |
|---|---|---|
| `rc-01` | Order reference resolves product before installation follow-up | Preserve structured identity, avoid asking again for known context, keep installation review-only |
| `rc-02` | Material fact plus safety and moisture questions | Answer admitted material; do not convert missing safety/moisture evidence into positive or negative facts |
| `rc-03` | Width and height requested together | Preserve both requested claims; cite each admitted evidence UID; no unrelated material inclusion |
| `rc-04` | Packaging dimensions versus product dimensions | Keep packaging and product scopes separate; no packaging-to-product inference |
| `rc-05` | Installation request with a media candidate but no delivered block | No unsupported promise that an image or video was sent; preserve the useful supported portion |
| `rc-06` | After-sales request mixing visible damage and refund/replacement outcome | Describe admitted observation only; keep refund, replacement, compensation, and responsibility unresolved or action-scoped |
| `rc-07` | Long-context follow-up carrying an unresolved product goal | Preserve the open goal without duplicating or deleting the current goal; do not repeat already known questions |
| `rc-08` | Absolute guarantee plus bounded practical explanation | Reject the guarantee while allowing only a policy-bound, premise-attributed, review-only alternative |

## Dataset Contract

The dataset JSON uses UTF-8 and stable canonical ordering. Top-level fields are:

- `schema_version`
- `dataset_id`
- `dataset_version`
- `source_class`
- `source_summary`
- `privacy_classification`
- `cases`
- `manifest`

Each case contains:

- `case_alias`: opaque `rc-NN` identifier
- `category`: stable capability family
- `conversation_turns`: ordered canonical `CUSTOMER` and `AGENT` turns
- `current_customer_message`: the single current buyer turn
- `identity_context`: anonymous product/order references only
- `evidence_candidates`: explicit role, review, identity, FactType, attribute,
  value, provenance, and eligibility metadata
- `service_actions` and `media_candidates`: always marked non-factual
- `expected_contract`: post-run scoring constraints, never Agent input
- `prohibited_outcomes`: safety and scope violations, never Agent input

The Agent payload is built from conversation, identity, and candidate context
only. `expected_contract`, `prohibited_outcomes`, case aliases, dataset hashes,
and evaluator labels are removed before the formal Pipeline call.

## Manifest And Provenance

The companion manifest records:

- dataset ID, version, and schema version
- exact case count and category distribution
- canonical dataset SHA-256
- each case SHA-256
- source class `conversation_reconstructed`
- source limitations
- privacy scan result
- explicit statements that `real_customer_accuracy=null` and
  `original_fixed8_restored=false`

Hash validation, duplicate alias detection, category-count validation, and
schema validation fail closed before any Agent or Provider call.

## Knowledge And Evidence Boundary

The reconstruction does not copy or mutate a production database. Evidence is
carried in versioned case sidecars and passed through the existing admission
contract. The runner must verify:

- formal knowledge is query-only when a database is configured;
- no formal knowledge DML occurs;
- rejected, conflicting, reference-only, service-action, media-reference, and
  identity-mismatched candidates do not become selected evidence;
- evidence values are not inferred from expected answers.

The sidecar evidence is an evaluation fixture and cannot prove live knowledge
coverage.

## Scoring

Scoring is claim- and contract-based, not fixed-sentence matching. The report
records:

- execution success and non-empty candidate reply
- authoritative goal preservation
- supported-claim coverage and evidence attribution
- unresolved/prohibited boundary preservation
- partial-answer success
- query/reply fit and context continuity
- unsupported high-risk claims
- unsupported media promises
- unsupported service-action claims
- repeated known-information requests
- unnecessary generic handoff
- `can_send` and `requires_human_review`
- Pipeline, Composer, and Audit latency
- Provider calls, retries, repairs, fallbacks, timeouts, and errors

The dataset may establish `reconstructed_baseline_status`, but must always emit
`real_customer_accuracy=null` and `optimization_unverified=true` until an
approved real dataset is restored and evaluated.

## Fail-Closed Rules

The run is invalid and returns a non-zero exit code when:

- the dataset or manifest hash does not match;
- the dataset contains other than eight cases;
- aliases are duplicated or unstable;
- an expected or prohibited field reaches the Agent payload;
- a case has invalid turn ordering or an unresolved role;
- identity or evidence schema is incomplete;
- formal knowledge is writable or DML changes;
- `can_send=true` appears;
- the report claims real accuracy or original Fixed-8 equivalence;
- runtime or evaluator source identity drifts during execution.

Provider failure is reported as a valid infrastructure failure only when the
dataset and runtime integrity checks passed. It is never converted into a
quality score.

## Implementation Boundary

The implementation should extend the existing P1 baseline/evaluation ownership
instead of creating another evaluator subsystem. Expected durable changes are:

- one versioned dataset fixture;
- one companion manifest;
- validation and reconstructed-mode support in the existing P1 runner or a
  narrowly shared loader used by that runner;
- direct integrity and leakage tests;
- documentation updates to the existing P1 architecture and module index.

Production Agent behavior remains unchanged.

## Verification Order

1. Dataset/manifest schema and privacy tests.
2. Manifest tamper, duplicate alias, label-leakage, and zero-case negative tests.
3. Payload projection equivalence and expected-field exclusion tests.
4. One-case dry run without a Provider call.
5. Eight-case deterministic preflight.
6. One native Fixed-8 reconstructed run through the existing formal Pipeline.
7. Synthetic benchmark smoke `5/5` and full `22/22` as safety regression only.
8. `py_compile`, Python JSON parse, PowerShell JSON parse, and `git diff --check`.

No production flag is enabled by any successful result.

## Recovery And Promotion

If the original Fixed-8 assets are recovered later, they are added under their
original independent identity and verified hashes. Results from the
reconstructed dataset remain historical engineering evidence and are not
merged into the restored real dataset score.
