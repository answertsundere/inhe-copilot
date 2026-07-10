# Module Index

Use this index to find the owner of a behavior before changing code. A behavior
should have one authoritative owner even when several modules consume it.

| Area | Current owner or entry point | Status | Boundary |
|---|---|---|---|
| Web application and dependency setup | `app/main.py` | legacy/converging | Must not remain the worker scheduler or domain service locator |
| Public analyze API | `app/api/analyze_routes.py` | formal | Parses HTTP input and presents the canonical Pipeline decision |
| Sidecar/copilot API | `app/api/copilot_routes.py` | formal | Normalizes sidecar context, calls Pipeline, then adapts panel presentation |
| Analysis pipeline | `app/services/analysis_pipeline_service.py` | formal | Owns canonical input, graph-to-delivery stage order, shadow isolation, and safe final-stage degradation for API, copilot, replay, and benchmark |
| Shared execution | `app/services/analysis_execution_service.py` | formal, Phase 0.1 contract complete | Owns graph execution, trace lifecycle, one pre-persistence post-processor call, and final response persistence |
| Agent graph | `app/agent/graph.py`, `app/agent/nodes/` | formal | Domain decisions only; no platform-native API branches |
| Product identity | product identity services and resolver nodes | formal | External title -> JST/internal identity -> scoped evidence |
| Fact classification | `app/services/fact_type_service.py` and turn understanding | formal but fragmented | Move toward one versioned fact-type registry |
| Retrieval interface | `app/retrieval/` | formal SQLite | Backend selection must be explicit and fail closed |
| pgvector retrieval | pgvector services and scripts | shadow | Diagnostic only until formal retriever acceptance |
| Product evidence pack | `app/services/product_context_pack_service.py` | formal | Preserve fact, service action, and media role separation |
| No-evidence behavior | `app/services/no_evidence_reply_policy_service.py` | formal but oversized | Select safe strategy; do not become a second fact engine |
| Customer-facing handoff copy | `app/services/customer_facing_safe_handoff_service.py` | formal | Translate a decision into natural wording without changing risk |
| Claim polarity | `app/services/claim_polarity_service.py` | formal utility | Distinguish affirmative claims from safe negation/uncertainty; consumers still own their claim lists and decisions |
| Final answer audit | `app/services/final_answer_auditor.py` | formal | Check claims and delivery contract; avoid duplicating routing |
| Semantic fit | `app/services/final_semantic_quality_service.py` | formal | Verify answer-question fit after facts and policy are settled |
| Final response orchestration | `app/services/final_response_orchestrator.py` | formal | One authoritative final stage shared by every entry point |
| Answer Memory | Answer Memory model/services | shadow/reference | Handling and style only, never product truth or send permission |
| Grounded Reasoning Draft | `app/services/grounded_reasoning_draft_service.py` | shadow/blocked from promotion | Uses direct, reviewed, identity-scoped evidence only; rejection diagnostics and offline references cannot affect formal decisions |
| Media governance | media asset services and product context pack | formal | Media role is evidence metadata; actual send requires reply blocks |
| Real replay | real-conversation replay services and scripts | evaluation | Must use per-sample canonical context and the production pipeline |
| Agent benchmark | benchmark dataset/runner services | evaluation | Measures reviewed scenarios; not production readiness by itself |
| Knowledge governance | knowledge gap, review, publish services | formal operations | Candidate/review/publish states must remain explicit |
| Platform adapters | not implemented | planned | QianNiu/Pinduoduo/JD implement canonical ports only |
| Handoff tasks and supervisor queue | not implemented | planned/P1 | Durable task is source of truth; notification is a projection |

## Cross-Cutting Change Checklist

When changing a module above, verify whether the same contract is consumed by:

- `/api/analyze`;
- `/api/copilot/context`;
- real replay;
- active benchmark;
- trace and snapshots;
- media reply blocks and delivery status;
- handoff and supervisor reporting;
- relevant durable documentation.

Do not duplicate a contract in a second module merely to make one entry point or
one test pass.
