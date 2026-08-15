# P1 High-Frequency Synthetic Dialogues

## Purpose

This P1 fixture turns the privacy-safe aggregate buyer-demand map into a
repeatable set of fictional multi-turn contexts. It is used to expose context
continuity, factual restraint, review/no-send safety, and reply usability
before any real-dataset quality claim is considered.

It is not customer data, product knowledge, an approved reply set, or an
authorization to change delivery behavior.

## Fixture Contract

- Dataset: `p1-high-frequency-synthetic-dialogues` version `1.0.0`.
- Size: 40 fictional scenarios, each with five turns and a final buyer turn.
- Scope: installation, size fit, promotion/price, logistics, returns, damage,
  missing parts, storage, configurations, accessory purchase, delivery
  changes, ordinary material/durability questions, and high-risk boundaries.
- Every identity uses a `SYN-` prefix. The generator declares no real buyer,
  product, order, or runtime input.
- The validation rejects non-synthetic identities, incomplete multi-turn
  context, mismatched final buyer messages, invalid delivery flags, and
  sensitive-content findings.

## Runners

Generate the fixture and the deterministic Supervisor Assist preview report:

```powershell
python scripts\build_p1_high_frequency_synthetic_dialogue_set.py --json-output <external>\synthetic-dialogues.json
python scripts\run_p1_high_frequency_synthetic_preview.py --input <external>\synthetic-dialogues.json --json-output <external>\preview-report.json --markdown-output <external>\preview-report.md
```

The formal runner requires an explicitly supplied loopback-only endpoint and
can checkpoint after each scenario:

```powershell
python scripts\run_p1_high_frequency_synthetic_preview.py --mode formal --input <external>\synthetic-dialogues.json --analyze-url http://127.0.0.1:<port>/api/analyze --checkpoint <external>\formal-pipeline-checkpoint.json --resume --max-new-cases 8 --json-output <external>\formal-pipeline-report.json --markdown-output <external>\formal-pipeline-report.md
```

The runner refuses a non-loopback URL and stops if an answer becomes sendable
or loses the human-review requirement.

Formal report schema `v3` derives one immutable stability observation from the
same API response used by the checkpoint and summary. It verifies the exact
ordered history projection, authoritative Turn Understanding, Composer entry,
and Deterministic Final result. An accepted Composer result is now explicitly
classified as `owned` or `not_applicable`; a media/service-only no-op remains
scorable but cannot be counted as a Composer-owned reply. The first failure is classified as
`turn_understanding_not_authoritative`,
`conversation_history_projection_mismatch`, `composer_entry_blocked`, or
`final_audit_failed`; later stages cannot hide an earlier boundary failure.

The formal request uses the same public `/api/analyze` contract as the
customer-facing path. It sends the current message, canonical prior turns, and
the fixture's synthetic `product_title`, `sku_code`, `i_id`, and `order_id` as
top-level structured identity fields. It must not send review expectations,
requested-claim labels, reference answers, or scoring metadata. The API route,
not the evaluator, owns conversion into `copilot_context`.

## Current Evidence And Blocker

The preview run generated 40 review-only drafts: `requires_human_review=40`,
`can_send=0`, 18 supported clauses, and 23 unresolved clauses. This validates
the fixture and delivery boundary, not reply quality.

A later isolated GLM attempt completed 14 rows before Deterministic Final
stopped on an internal-process phrase. That attempt is superseded as a quality
baseline: its evaluator omitted all four structured synthetic identity fields,
so identity-dependent requests did not exercise the formal input contract.
The snapshot remained query-only, formal-knowledge DML was zero, every row was
review-only, and `can_send` stayed false; those safety observations remain
valid, but its reply-quality observations do not.

After the evaluator was corrected, the previously failing logistics case ran
once through the same isolated formal Pipeline with all four prior turns and
synthetic identity present. It passed Deterministic Final, retained
`can_send=false`, required human review, leaked no transport turn UID, wrote no
formal knowledge, and left the snapshot hash unchanged. This one-case result
qualifies the input-contract repair only. The remaining 39 cases have not been
completed, and `real_customer_accuracy` remains `null`.

The corrected identity-sensitive gate then completed four fixed scenarios
(`001`, `009`, `010`, and `014`) once each. All four retained history `4/4`,
passed Deterministic Final, kept `can_send=false`, required human review, wrote
no formal knowledge, and preserved the snapshot hash. The subsequent fixed
40-case attempt stopped at row 18 with
`conversation_history_projection_mismatch`: that row returned a safe
review-only logistics fallback but exposed history `0/4` and did not use the
Composer. A diagnosis-only replay of the same row later retained `4/4` and
used the Composer. The replay does not overwrite the first failure or permit
rows 19-40 to run. The earliest gate is now Turn Understanding / Composer-entry
stability under the same canonical input, not reply wording.

The bounded stability qualification then stopped on its first permitted call;
the second and third calls were not made. The row exposed an invalid
`turn_understanding_boundary` with earliest reason
`canonical_claim_type_not_allowed`, followed by correctly blocked media and
Composer stages, history `0/4`, a safe review-only fallback, `can_send=false`,
and formal-knowledge DML `0`. The earlier runtime-only gate had reported this
as a history mismatch because it checked history before the authoritative
understanding boundary. The corrected evaluator classifies the earliest owner
as `turn_understanding_not_authoritative`. This is a reproducible stability
failure, not permission to change reply wording or continue rows 19-40.

Across the stopped 18-row attempt, Deterministic Final passed `18/18`,
`can_send=true` was `0`, human review was `18/18`, formal-knowledge DML was
`0`, and Pipeline latency p50/p95 was `8.913s/23.209s`. Composer output was
used in `14/18` rows. Every row had zero selected formal evidence because the
fictional `SYN-` identities do not exist in the query-only knowledge snapshot;
therefore this attempt evaluates unresolved/context handling only and cannot
measure product-fact accuracy. A simple text heuristic flagged many generic
or handoff-like replies, but that heuristic is diagnostic and is not an
acceptance score.

The historical fixed 26-case real-derived development asset referenced by the
legacy runner is not present in the recovered workspace. It must not be
recreated from the 40 synthetic fixture or represented as recovered customer
data. Until that asset or an approved replacement is restored, the 40-case set
is limited to synthetic regression, context-continuity, and safety diagnosis.

The current follow-up corrected two generic contract gaps. A safe media request
whose provider output improperly assigns a fact type is retained only as an
`unmapped` non-factual goal; it cannot create evidence, an action, or send
authority. A provenance-valid current-turn `customer_goal` now enters the
existing evidence path when legacy intent routing remains `general`, while
invalid, public, media, and service goals remain in the clarification path. A
single price-validation scenario then retained history `4/4`, traversed the
existing Evidence Builder, produced one unresolved claim and one Composer
clause, passed Deterministic Final, required human review, and kept
`can_send=false` with zero formal-knowledge DML.

The subsequent fresh fixed-40 run stopped at row 1. GLM-4.5-Air returned an
invalid `claim_type_status`; strict Turn Understanding validation rejected it
before Composer use. The run was not retried. The official provider interface
offers JSON-object mode rather than server-enforced JSON Schema, so the current
Turn Understanding provider is not stable enough for this fixed-40 gate. This
is a provider qualification blocker, not permission to normalize an invalid
enum, loosen the schema, or claim reply-quality progress.

A later GLM-4.7-Flash candidate passed the existing Composer-role gate `5/5`
without retry, repair, fallback, knowledge DML, or send authority. The first
fixed-40 attempt reached row 10, where the Composer rejected the customer-safe
boundary phrase `不能承诺` as internal language. The shared redline contract
was inconsistent with its own reviewed benchmark and generic service rules,
which require a clear refusal of unsupported guarantees. The contract now
allows negative promise boundaries while continuing to reject evidence,
review, knowledge-base, RAG, and Final-Gate process language. The frozen row 10
then passed once with Final accepted, human review required, `can_send=false`,
and DML `0`.

The new-source fixed-40 run stopped at row 3 on the unchanged 180-second HTTP
timeout. GLM-4.7-Flash therefore remains latency-unqualified despite its schema
and Composer-role results. GLM-4.6 stopped at its first qualification call with
a rate-limit error. Neither result is a conversation-quality score, and
`real_customer_accuracy` remains `null`.

The associated versioned safety benchmark passed smoke `5/5` and full
`22/22` with `can_send=0` and mandatory human review for all scenarios. Those
runs used an explicit isolated knowledge snapshot whose runtime readiness was
verified before execution. A preliminary run against an empty snapshot
produced `3/5`; it was classified as `input/context gap` because the Pipeline
correctly stopped at runtime readiness, not as an Agent quality regression.
