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
