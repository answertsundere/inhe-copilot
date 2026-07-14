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
| Final answer audit | `app/services/final_answer_auditor.py` | formal | Check claims, exact attached-media wording, and direct evidence for high-risk installation prescriptions; avoid duplicating routing |
| Semantic fit | `app/services/final_semantic_quality_service.py` | formal | Verify answer-question fit after facts and policy are settled |
| Final response orchestration | `app/services/final_response_orchestrator.py` | formal | One authoritative final stage shared by every entry point |
| Answer Memory | Answer Memory model/services | shadow/reference | Handling and style only, never product truth or send permission |
| Grounded Reasoning Draft | `app/services/grounded_reasoning_draft_service.py`, `scripts/*grounded_reasoning_positive_eval*` | shadow/blocked from promotion | Owns admitted-fact planning from structured requested attributes and deterministic segmented-draft evaluation; every factual clause retains evidence UID provenance and cannot affect formal decisions |
| Admitted answer context | `app/services/admitted_answer_context_service.py` | formal utility / read-only | Owns identity-, review-, role-, claim-, placeholder-, and conflict-aware evidence admission; separates direct product facts, policy facts, handoff actions, media candidates, rejected evidence, and unresolved claims |
| LLM decision proposal | `app/services/agent_decision_proposal_service.py`, `app/services/claim_resolution_service.py`, `app/services/strict_decision_provider_service.py`, `scripts/qualify_strict_decision_provider.py` | shadow-only / qualification-gated | Uses a separately configured, strict-schema provider after the formal graph. Claim Resolution keeps supported, unresolved, and conflicting claims independent; a valid proposal must cite admitted evidence for each confirmed clause and retain a pending clause for every unresolved claim. It stays disabled unless the exact provider passes transport and semantic qualification; application-owned read-only lookups remain bounded, order/media actions stay deferred, and formal decisions stay immutable |
| Media governance | media asset services and product context pack | formal | Media role and scoped identity are evidence metadata; actual send and customer wording require matching reply blocks |
| Product media observations | `app/services/product_media_observation_service.py`, `app/services/product_media_panel_proposal_service.py`, `app/services/product_media_observation_v3_service.py`, `app/services/composable_vision_grounding_service.py`, `app/services/composable_vision_ocr_provider_service.py`, `app/services/composable_vision_object_provider_service.py`, `app/services/semantic_object_grounding_provider_service.py`, `app/services/product_media_annotation_schema_service.py`, `scripts/diagnose_semantic_object_runtime.py`, `scripts/probe_semantic_object_runtime.py`, `scripts/export_product_media_annotation_tasks.py`, `scripts/validate_product_media_annotations.py`, `scripts/diagnose_product_media_annotation_feasibility.py`, `app/services/product_media_observation_review_service.py`, `app/services/vision_grounding_provider_qualification_service.py` | shadow-only / external annotation pilot / v2 legacy staging / v3 planned review | V3 resolves original media bytes before validated cache/URL fallback, records observed SHA-256 provenance, and uses deterministic panel proposals plus verified panel, object, label, and object-label binding for a product, packaging, component, accessory, included item, or display prop. The composable PoC separates OCR, object proposals, same-panel geometry binding, and verification without treating panels as objects. Its Windows OCR adapter produces normalized text-box label candidates only. Its OpenCV object adapter proposes only primary visual geometry: explicit packaging text may scope a carton, but all other regions remain unknown and cannot enter geometry binding. The semantic adapter can use a configured local Transformers Grounding DINO or Florence-2 runtime, generic class queries, and contract-checked boxes; unavailable runtime or conflicting scope remains fail-closed. The readiness and one-image probe scripts must succeed before semantic ten-image qualification can begin, and every failed qualification stops before Geometry Binding. Neither current local semantic candidate is eligible for the next stage. New annotation tasks use packaging-dimension, mode-dimension, product-specification, or compliance-document palettes selected only from durable task/media metadata; the broad visual-layout palette is historical-only. Completed regions and controlled fields compile into a SHA-256/bbox-provenanced visual-description report. Neither annotations, predictions, nor compiled descriptions create observations, formal evidence, Product Evidence Pack or Grounded input, delivery changes, or `can_send` changes. |
| Claim plan and bounded derivation | Grounded Reasoning is the current shadow precursor; no formal owner yet | planned/shadow-first | Separate direct observations, declared low-risk derivations, general guidance, and high-risk facts/actions; every factual clause needs evidence or derivation provenance |
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
