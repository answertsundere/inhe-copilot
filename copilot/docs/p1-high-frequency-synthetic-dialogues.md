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

## Current Evidence And Blocker

The preview run generated 40 review-only drafts: `requires_human_review=40`,
`can_send=0`, 18 supported clauses, and 23 unresolved clauses. This validates
the fixture and delivery boundary, not reply quality.

A single isolated formal-pipeline probe also returned review-only/no-send, but
asked for dimensions already supplied in the conversation. The resumable
formal batch did not finish because the local Qwen loopback endpoint did not
start its vLLM engine: free GPU memory was below the container's configured
memory-utilization target. The Docker port proxy remained reachable but
returned empty HTTP responses because no model engine was serving requests.
Restarting the container without restoring GPU capacity cannot fix that
condition. The checkpoint is diagnostic only and must not be read as a
completed baseline.

Before resuming, restore a healthy local model and pass the minimal generation
probe. Then complete all 40 rows, review repeated-known-context and generic
handling failures, and keep the result explicitly synthetic with
`real_customer_accuracy=null`.
