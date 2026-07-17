# Real Customer-Service Accuracy Evaluation

## Purpose

The active benchmark verifies a reviewed safety and workflow contract. It is
not a production-accuracy claim, especially while all benchmark replies remain
review-only. This evaluation layer measures a different question: given a real,
reviewed customer turn and its own sidecar context, did the formal
`AnalysisPipeline` produce a response meeting independently supplied claim
labels?

The layer is read-only. It does not publish knowledge, alter retrieval,
activate Formal Evidence Convergence, or modify `can_send`.

## Dataset Boundary

`scripts/build_real_accuracy_gold_set.py` reads a caller-supplied SQLite source
through SQLite read-only mode. It emits a UTF-8 Gold Set and a manual-label
queue under `outputs/`; neither is committed. Source sample IDs, SKU, order ID,
and product identity are HMAC-pseudonymised with an environment-provided key.
The key is neither written nor reported. Customer text is sanitised for phone,
long numeric identifiers, addresses, credentials, signed URLs, and image data.

The data classifier separates:

- `accuracy_scorable`: reviewed reference answer plus usable sidecar context;
- `safety_scorable`: usable question/context but no answer label;
- `context_gap`: a text question without product, SKU, or order context;
- `media_only`: image or link without a reliable text question;
- `label_gap`: usable data that still needs a human label; and
- `invalid`: no usable customer text.

Only explicit claim-level labels may create a published claim-accuracy
denominator. A historical reviewed free-text answer may support exploratory
action-coverage analysis, but it is not injected into the Agent and is not a
substitute for claim labels. Until the denominator reaches 30 cases across at
least five fact types and ten products or categories, reports carry
`insufficient_gold_labels` and must not state a project accuracy rate.

## Execution And Scoring

`scripts/run_real_accuracy_baseline.py` rebuilds the request from the same
read-only source in memory, joins it by HMAC case identity, and calls the
public `/api/analyze` contract. That route must return an `analysis_pipeline`
record; a response without it is not counted as a formal-pipeline result.
Evaluation labels are rejected if they appear in the Agent payload.

The deterministic scorer reports its numerator and denominator for each
metric. It scores only manual `expected_claims`, each with a declared matching
contract, expected handoff, and forbidden-claim constraints. Free-text
reference answers remain exploratory. This avoids pretending that a keyword
overlap score is full semantic faithfulness.

`scripts/diagnose_query_driven_fact_coverage.py` groups actual evaluated
questions by their stored query class and shows the funnel:

`question -> sidecar -> reference label -> observed formal pipeline -> formal selected evidence -> admitted evidence -> unresolved/handoff`.

It ranks gaps by question volume. It is diagnostic only; a missing stage is a
knowledge, context, retrieval, identity, admission, or generation hypothesis
to investigate, never permission to insert an answer rule.

## Operating Commands

Use one ephemeral HMAC key for a build-and-run session; do not save it in the
repository or an output artifact.

```powershell
$env:COPILOT_GOLD_SET_HMAC_KEY = [guid]::NewGuid().ToString('N')
python scripts\diagnose_real_accuracy_data_sources.py `
  --source-db <read-only-runtime-db> `
  --json-output outputs\real_accuracy_source_inventory.json
python scripts\build_real_accuracy_gold_set.py `
  --source-db <read-only-runtime-db> `
  --json-output outputs\real_accuracy_gold_set.json `
  --manual-queue-output outputs\real_accuracy_manual_label_queue.json
python scripts\validate_real_accuracy_gold_set.py --input outputs\real_accuracy_gold_set.json
python scripts\run_real_accuracy_baseline.py `
  --gold-set outputs\real_accuracy_gold_set.json `
  --source-db <read-only-runtime-db> `
  --analyze-url http://127.0.0.1:5011/ask/api/analyze `
  --json-output outputs\real_accuracy_baseline.json
python scripts\diagnose_query_driven_fact_coverage.py `
  --gold-set outputs\real_accuracy_gold_set.json `
  --baseline outputs\real_accuracy_baseline.json `
  --json-output outputs\query_driven_fact_coverage.json
```

The runtime database remains a source only. The scripts do not create review
tasks, observations, knowledge rows, or delivery records.
