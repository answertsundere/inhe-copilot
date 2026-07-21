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

Phase 0.8C real-derived evidence probes remain outside the customer-accuracy
denominator. They reuse real reviewed product fields with pseudonymous identity,
but their customer questions are synthetic capability probes. The 15/15 offline
result demonstrates Pack-to-selected-to-admitted plumbing only. The isolated API
1x1 delivery gate did not pass and the 5-product tier was not run; Tier A and
real-customer accuracy therefore remain `null` until independently approved Gold
claims satisfy the published denominator.

## Dataset Boundary

`scripts/build_real_accuracy_gold_set.py` reads a caller-supplied SQLite source
through SQLite read-only mode. It emits a UTF-8 Gold Set and a manual-label
queue under `outputs/`; neither is committed. Source sample IDs, SKU, order ID,
and product identity are HMAC-pseudonymised with an environment-provided key.
The key is neither written nor reported. Customer text is sanitised for phone,
long numeric identifiers, addresses, credentials, signed URLs, and image data.

The data classifier separates:

- `reference_available`: a reviewed free-text answer exists but is not a claim label;
- `claim_label_pending`: a privacy-clean case is ready for human claim annotation;
- `claim_accuracy_scorable`: at least one human-approved claim with its matching
  contract and necessary context exists;
- `safety_scorable`: usable question/context but no answer label;
- `context_gap`: a text question without product, SKU, or order context;
- `media_only`: image or link without a reliable text question;
- `role_unresolved`: a conversation whose source DOM and explicit speaker
  prefix do not establish a buyer, agent, or system role; it is excluded from
  the manual claim queue;
- `label_gap`: usable data that still needs a human label; and
- `invalid`: no usable customer text.

Only explicit, human-approved claim-level labels may create a published claim-accuracy
denominator. A historical reviewed free-text answer may support exploratory
action-coverage analysis, but it is not injected into the Agent and is not a
substitute for claim labels. Until the denominator reaches 30 cases across at
least five fact types and ten products or categories, reports carry
`insufficient_gold_labels` and must not state a project accuracy rate.

## Execution And Scoring

`scripts/run_real_accuracy_baseline.py` rebuilds the request from the same
read-only source in memory, joins it by HMAC case identity, and calls the
public `/api/analyze` contract. A scorable case must also carry one or more
human-selected `target_turn_uids`. The Agent message is built only from those
buyer turns, and conversation history stops at the last selected turn. Later
buyer or agent messages cannot leak into the evaluated request. That route
must return an `analysis_pipeline` record; a response without it is not counted
as a formal-pipeline result. Evaluation labels and reference answers are
rejected if they appear in the Agent payload.

The deterministic scorer reports its numerator and denominator for each
metric. It scores only manual `expected_claims`, each with a declared matching
contract, expected handoff, and forbidden-claim constraints. Free-text
reference answers remain exploratory. This avoids pretending that a keyword
overlap score is full semantic faithfulness.

## Mandatory Before/After Change Gate

Any implementation that can change customer-visible Agent behaviour must be
evaluated against a pinned real dataset both before and after the change. The
comparison must use the same dataset content hash, formal HTTP entry point,
sidecar mode, feature flags, provider/model, scorer version, and timeout
contract. A recent parent-commit baseline may be reused only when all of those
fields match; otherwise the baseline must be rerun.

The report keeps independent numerators and denominators for supported claims,
required actions, evidence selection, partial-answer progression, handoff,
unsafe auto-send, unsupported media promises, empty/error responses, timeouts,
and p50/p95 latency. Excluded, media-only, role-unresolved, and context-gap cases
remain visible and cannot disappear from the denominator silently.

An implementation may be described as an optimisation only when its declared
target metric improves or its target defect count decreases, no safety metric
regresses, and latency/error changes are disclosed. Tier C synthetic results are
mandatory regression evidence but cannot prove real accuracy. When Tier A has
insufficient approved labels, real accuracy remains `null`; Tier B and Tier D
may diagnose evidence capability and conversation progression, but the final
status is `optimization_unverified`, not “accuracy improved.”

## Phase 0.7C.1 Business Accuracy Matrix

The project reports three deliberately non-combinable evaluation tiers. This
uses the separation of answer faithfulness, answer relevance, and retrieval
context quality described by [Ragas](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/),
and the claim-versus-context distinction in [DeepEval faithfulness](https://deepeval.com/docs/metrics-faithfulness).
It also follows the [OpenAI Evals dataset/solver separation](https://github.com/openai/evals/blob/main/docs/build-eval.md):
expected outcomes remain scorer data and never enter the Agent request.

- **Tier A, Real Gold** contains a real buyer turn, its own sidecar context,
  and supervisor-approved claim labels.  It is the only tier permitted to
  report a customer-service accuracy rate.  Fewer than 30 approved labelled
  cases remains `insufficient_gold_labels`; the rate is `null`, never 0% or
  100%.
- **Tier B, Real-Derived Capability** reads published, direct, identity-scoped
  product fields query-only and asks a generic fact-type question through the
  same API pipeline.  It reports evidence selection, admission, identity, and
  delivery behaviour, but is not a real-customer accuracy rate.
- **Tier C, Synthetic Safety** runs the versioned benchmark fixture.  It
  validates handoff, media, and delivery contracts only, and is likewise not a
  real-customer accuracy rate.
- **Tier D, Simulated Multi-turn** starts from a privacy-checked real
  conversation prefix and target buyer turn, then lets an independently
  configured buyer model continue against the formal HTTP AnalysisPipeline.
  It measures execution reliability, deterministic safety contracts, required
  action coverage, buyer-model outcome acceptance, response repetition, and
  trial stability. It never scores an unapproved product claim as truth and
  never contributes to the Tier A customer-accuracy numerator or denominator.

The Tier D shape follows the task/trial/transcript/outcome separation described
in [Anthropic's agent evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
and the thread-level outcome and trajectory distinction in
[LangSmith multi-turn evaluations](https://docs.langchain.com/langsmith/online-evaluations-multi-turn).
As with [OpenAI HealthBench](https://openai.com/index/healthbench/), detailed
criteria and multi-turn transcripts are useful, but model grading does not
replace expert-approved truth labels. Tier D therefore reports an exploratory
pass rate and keeps real-customer accuracy `null`.

## Tier D Long-Conversation Simulation

`scripts/build_long_conversation_simulation_set.py` joins the privacy-checked
Gold artifact to the minimum supervisor queue. It selects only conversations
with resolved roles, a readable buyer target, at least 20 source turns, and a
bounded pre-target history. Selection round-robins structured business domains
and does not use product names, raw IDs, or buyer-message keyword rules. A
media-labelled review item without target media or declared media evidence is
excluded instead of being presented as a high-quality media scenario.

The artifact stores HMAC case identities and a non-reversible transcript
fingerprint. `scripts/run_long_conversation_simulation.py` resolves the source
sidecar in process. If the original Gold HMAC key is unavailable, only a unique
exact transcript fingerprint may establish the linkage; ambiguous records are
excluded and reported. Raw source identifiers never enter the dataset or
report. The generated dataset is scanned again after controlled hashes, HMAC
identities, and manifest fields are removed from the privacy projection; any
remaining phone, address, URL, account, credential, or long-identifier finding
fails the artifact before execution.

The buyer simulator uses separate `COPILOT_CUSTOMER_SIMULATOR_*` configuration.
It sees the hidden buyer goal and transcript, while the Agent receives only the
current buyer message, bounded history, and source sidecar. Evaluation labels,
required actions, and review metadata are rejected from the Agent payload. The
buyer may not invent product facts or claim to have supplied a new image,
video, order number, or attachment. The runner validates one exact JSON shape
and does not repair free text into a decision.

The deterministic thread scorer reports independent metrics:

- formal HTTP and AnalysisPipeline execution;
- review-only and auto-send safety when handoff is required;
- attached-media promise consistency;
- buyer-model outcome acceptance;
- required-action coverage from at most one qualified transcript-semantic
  grader call per trial;
- repeated consecutive replies and per-turn latency;
- all-trials and any-trial scenario stability.

The buyer outcome and semantic action coverage remain model observations, not
Gold truth. Simulator self-reported actions cannot credit coverage. Without a
qualified grader, action coverage and overall pass are `null`; deterministic
safety diagnostics remain available. A same-provider-family diagnostic records
`same_provider_family_risk=true` and cannot be treated as independent-model
acceptance.

### 2026-07-18 Exploratory Baseline

The first strict calibrated run selected nine long scenarios across six structured
domains. Seven had a unique source-sidecar linkage; two duplicate transcripts
with different sidecars were excluded. The seven scenarios ran twice for 14
trials and 41 formal Agent turns:

- exploratory overall pass: `1/14` (`7.14%`);
- deterministic contract pass: `5/14` (`35.71%`);
- buyer outcome acceptance: `2/14` (`14.29%`);
- mean required-action coverage: `41.67%`;
- stable scenario pass across both trials: `0/7`;
- formal selected-evidence turns: `0/41`;
- consecutive identical reply rate: `17/27` (`62.96%`);
- Agent latency p50/p95: about `15.3s / 35.5s`.

The strict scorer treats failed final-answer or semantic-fit audits as contract
failures; the run contained six and eight such failed trials respectively. One
installation trial became auto-sendable while the review contract required
handoff. Across the wider set, the dominant failure was non-progression: order,
logistics, product-size, suitability, news/safety, and aftersales follow-ups
often repeated a generic verification response while selected evidence stayed
empty. This baseline is evidence for the next diagnostic priority, not a
production accuracy claim. The buyer simulator and formal Agent both used the
same configured provider in this first run, so provider-correlated behaviour is
an additional limitation.

```powershell
python scripts\build_long_conversation_simulation_set.py `
  --gold-set outputs\real_accuracy_gold_set.json `
  --review-queue outputs\real_accuracy_minimum_supervisor_queue.json `
  --json-output outputs\long_conversation_simulation_set.json

$env:COPILOT_CUSTOMER_SIMULATOR_API_KEY = "<separate-evaluation-provider-key>"
$env:COPILOT_CUSTOMER_SIMULATOR_API_BASE = "<openai-compatible-base>"
$env:COPILOT_CUSTOMER_SIMULATOR_MODEL = "<model>"
python scripts\run_long_conversation_simulation.py `
  --dataset outputs\long_conversation_simulation_set.json `
  --source-db <read-only-runtime-db> `
  --analyze-url http://127.0.0.1:5011/api/analyze `
  --trials 2 --max-generated-turns 2 `
  --json-output outputs\long_conversation_simulation_report.json
```

`scripts/run_real_derived_business_matrix.py` creates a pseudonymised Tier B
manifest and result report without exporting product identity, field values, or
reply text.  `scripts/build_business_accuracy_matrix.py` combines summaries
only: it never copies buyer text, label content, or raw sidecar identifiers
into the matrix.  It classifies the nine business domains only from structured
`query_fact_type` or reviewed `question_type`, never from buyer-message
keywords.

The matrix keeps numerator and denominator for each available metric.  Claim
precision/recall and free-text relevance remain `null` when no human-approved
claim label exists.  Tier B instead exposes direct evidence citation/admission
rates, while Tier C exposes its own safety-contract result.  Empty replies,
timeouts, media promises without blocks, service-action-as-fact, identity,
handoff, and partial-answer observations use independent fields rather than a
single `passed` flag.

## Phase 0.7C.2 Claim Review Workflow

`real_accuracy_claim_review_service` creates a review plan from the Gold
artifact's structured query class, risk level, sidecar availability, reviewed
reference availability, and explicit formal-evidence provenance.  It never
uses buyer-message keywords to choose a strategy and never turns a historical
customer-service reply into product evidence.

The workbench groups review candidates into product facts, high-risk residual
claims, order/logistics, aftersales, promotion/gift/invoice,
installation/accessory, media, missing-context, and not-scorable policies.
Each proposal is atomic and records its source category, evidence UID summary,
identity scope, delivery boundary, and required action.  Product facts are
proposed as `supported` only when the Gold record already has direct,
reviewed, identity-matched formal evidence; otherwise they remain
`unresolved`.

The workflow states are deliberately separate:

- `ai_proposed` is a machine suggestion with no reviewed source.
- `source_reviewed_candidate` has a reviewed historical reference, not proof
  of a product fact.
- `policy_validated` passed deterministic privacy, provenance, conflict, and
  high-risk checks, but is still not Gold.
- `supervisor_approved` is the only state eligible for the Tier A denominator.
- `rejected` remains audit data and is never evaluated as a supported claim.

Batch operation may create **drafts** and submit explicit selected drafts for
review.  It cannot batch-approve claims.  A supervisor must still select a
buyer target turn and explicitly approve each case.  The workbench returns a
bounded turn window around that target rather than exposing a full long
conversation.  `scripts/build_approved_real_accuracy_gold_manifest.py`
creates a privacy-checked, content-free approval manifest; it reports
`awaiting_supervisor_approval` until an actual approved denominator exists.

## Minimum Supervisor Queue And Tier A Gate

`scripts/build_minimum_supervisor_review_queue.py` selects atomic claims from
the existing privacy-checked review plan only.  The selection is deterministic,
requires a readable buyer target and a bounded buyer/agent context window, and
round-robins domains while capping any one domain at 30 percent of the target.
An explicit missing-context claim may be included only as a
`context_follow_up_only` review item; it is not product evidence.  The script
does not save drafts, approve claims, call the Agent, or write knowledge.

Approval remains a per-case supervisor/admin action.  The label store records
one `claim_approved` audit event for every approved atomic claim, including the
pseudonymous actor role and optimistic-lock version.  The approval manifest
rejects missing claim events, non-supervisor roles, and broken state-version
history.  Tier A remains `null` until at least 30 independently approved claims
cover at least five business domains; that first result is a limited baseline,
not a project-wide accuracy rate.

### Operating Commands

Run the real-derived portion only against a temporary local API process and a
read-only runtime database.  The HMAC key is ephemeral and must not be saved.

```powershell
$env:COPILOT_REAL_DERIVED_MATRIX_HMAC_KEY = [guid]::NewGuid().ToString('N')
python scripts\run_real_derived_business_matrix.py `
  --source-db <runtime-db> --api-url http://127.0.0.1:5012/api/analyze `
  --manifest-output outputs\real_derived_business_manifest.json `
  --json-output outputs\real_derived_business_report.json

python scripts\run_real_accuracy_baseline.py `
  --gold-set outputs\real_accuracy_gold_set.json --source-db <runtime-db> `
  --label-db <ignored-label-db> --approved-only `
  --analyze-url http://127.0.0.1:5012/api/analyze `
  --json-output outputs\real_accuracy_approved_baseline.json

python scripts\build_business_accuracy_matrix.py `
  --gold-set outputs\real_accuracy_gold_set.json `
  --tier-a-baseline outputs\real_accuracy_approved_baseline.json `
  --tier-b-report outputs\real_derived_business_report.json `
  --tier-c-smoke outputs\benchmark_smoke.json `
  --tier-c-full outputs\benchmark_full.json `
  --json-output outputs\business_accuracy_matrix.json
```

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
python scripts\diagnose_real_accuracy_conversation_structure.py `
  --source-db <read-only-runtime-db> `
  --json-output outputs\real_accuracy_conversation_structure.json
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

## Privacy And Human Labeling

Gold build no longer stores raw `full_context` as a flattened string. It first
uses stable message-container metadata from the reviewed chat DOM, including
`imui-msg-l` / `imui-msg-r` direction classes, and then uses an explicit
speaker prefix only when DOM direction is unavailable. It emits only
`BUYER`, `AGENT`, or `SYSTEM` roles; an unproven role is represented as a
`role_unresolved` turn state rather than being disguised as `SYSTEM`.
Fragments inside one message body are merged before a turn is emitted. Every
turn receives a deterministic, conversation-scoped `turn_uid`; its controlled
format is validated independently from customer-content privacy scanning.
The parser caps a source case at 500 merged turns and classifies an over-limit
case as `conversation_truncated`, excluding it from the manual claim queue
rather than silently scoring incomplete context.
Controlled link tokens, image markers, HMAC actor IDs, and sanitised text are
retained, while raw nicknames and source attributes are discarded.

The independent output scanner checks for PII, URLs, HTML/CSS, credentials,
source identifiers, and unbounded media data. Content scanning intentionally
excludes generated HMAC and manifest fields; their formats are separately
validated. Build, validation CLI, baseline runner, and the workbench all call
the same `validate_gold_dataset()` contract. A failed scan, manifest, schema,
or controlled-identifier validation sets
`privacy_validation_failed`, exits with code 2, and blocks both the label
workbench and baseline runner.

Human labels live in `COPILOT_REAL_ACCURACY_LABEL_DB`, an ignored evaluation
SQLite database separate from `knowledge_base.db`. It stores only pseudonymous
case IDs, selected target buyer-turn UIDs, structured claim JSON, a
pseudonymous reviewer actor, versions, and append-only audit events. A draft may
omit a target while it is being prepared. Submission for review and approval
require at least one target that exists in the same case and belongs to the
buyer; unknown, agent, and system turns are rejected. Reviewers may draft or
submit labels; only supervisors or administrators may approve them.
Product-fact claims need formal evidence UIDs before approval. The
`/ask/real-accuracy-labels` management view reads the
sanitised Gold artifact and never receives raw source rows. Its list and detail
API are reviewer-or-higher only; operators and unauthenticated callers cannot
read reference answers or de-identified conversation turns.

The baseline records attempted, success, error, timeout, p50/p95 latency, and
exclusion counts independently. A timeout is an execution error, not a human
handoff. It separately reports draft, reviewed, approved, and rejected label
records. Only an approved case with approved claims enters the accuracy
denominator. With no approved claims, the denominator and rate are `0` and
`null`; that is an intentionally incomplete baseline, not a score.
