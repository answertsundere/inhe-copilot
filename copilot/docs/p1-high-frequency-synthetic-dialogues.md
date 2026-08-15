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

The historical fixed 26-case real-derived development asset referenced by the
legacy runner is not present in the recovered workspace. It must not be
recreated from the 40 synthetic fixture or represented as recovered customer
data. Until that asset or an approved replacement is restored, the 40-case set
is limited to synthetic regression, context-continuity, and safety diagnosis.
