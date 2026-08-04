# Module Index

Use this index to find the owner of a behavior before changing code. Dynamic
experiment results belong in evaluation reports, not in this ownership map.

## Active Agent Core

| Capability | Authoritative owner | Status | Boundary |
|---|---|---|---|
| HTTP analyze entry | `app/api/analyze_routes.py` | formal | Normalize HTTP input and present the canonical Pipeline result |
| Sidecar/copilot entry | `app/api/copilot_routes.py` | formal | Normalize sidecar context, call the same Pipeline, adapt panel presentation |
| Application stage order | `app/services/analysis_pipeline_service.py` | formal | The only graph-to-delivery execution path for API, copilot, replay, and benchmark |
| Graph execution and persistence | `app/services/analysis_execution_service.py` | formal | Graph lifecycle, trace, one post-processor, final snapshot/persistence |
| Conversation turns | `app/services/canonical_conversation_turn_service.py` | formal utility | Bounded role-aware history and field-aware provider privacy projection |
| Evaluation privacy sanitization | `app/services/eval_sanitizer_service.py` | formal utility | Redact explicit PII and concrete address structures while preserving product titles, evidence, attributes, and ordinary room/use semantics; redaction markers never qualify as reply text |
| Turn understanding | `app/services/semantic_fact_type_service.py`, `app/agent/nodes/query_fact_type_classifier.py` | formal | One semantic call returns typed atomic goals with current-message source provenance; only verified `customer_goal` items become requested claims, while query-fact compatibility fallbacks stay degraded and evidence dependencies, service actions, and contextual constraints stay distinct |
| Agent orchestration | `app/agent/graph.py`, `app/agent/nodes/` | formal but overweight | Stateful routing, tools, retries, and flow transitions; not final reply ownership |
| Formal LLM transport | `app/llm/client.py` | formal | Default Agent/Composer Provider transport, privacy projection, timeout/truncation handling |
| Role-scoped strict model transport | `app/services/strict_decision_provider_service.py`, `app/config.py` | formal utility; Unified Audit role default-off; loopback Qwen qualification only | One native strict-schema or strict-tool request for an explicitly configured role; Unified Audit credentials/model/capability never inherit the formal Agent or decision-shadow role, missing/unqualified configuration fails before a model call with no fallback, and MiniMax compatibility or loopback Ollama native-schema options never relax the local strict Validator |
| Product/order identity | identity services and resolver nodes | formal | External references to JST/internal scoped identity |
| Retrieval | `app/retrieval/`, `app/repositories/knowledge_chunk_repository.py`, `app/agent/nodes/evidence_filter_node.py`, `app/agent/nodes/evidence_builder.py` | formal SQLite | Explicit backend and observable fail-closed retrieval; published chunk review state, formal source type/material provenance, and source confidence survive Repository -> Filter -> Builder while Evidence Gate retains admission authority |
| Product context candidates | `app/services/product_context_pack_service.py` | formal | Preserve role, review, identity, attribute, and provenance metadata |
| Evidence admission | `app/services/admitted_answer_context_service.py` | formal utility; convergence opt-in | Single reusable review/identity/role/claim/conflict admission contract |
| Claim resolution | `app/services/claim_resolution_service.py` | formal utility; bounded inference disabled with Composer path | Preserves supported, unresolved, conflicting, and prohibited direct-evidence state; keeps restricted request risk separate from low/medium answer-strategy risk and may project a practical alternative only from the deterministic trusted Domain Pack/admitted-premise/scope/conflict intersection for the same owner-stamped goal family. Missing goal-family authority yields no option; an already-supported goal remains direct-only unless an exact trusted practical intent was nominated. Claim Resolution never selects an option |
| Domain policy data | `app/repositories/file_policy_repository.py`, `rules/domain_policy_packs/` | formal data utility; no routing authority | Sole strict loader for versioned claim policy; resolves trusted deployment, verified server mapping, or isolated evaluation selectors, emits an anonymous Pack reference/content hash projection, and revalidates both before use. Policies contain premise families, scope, low/medium risk ceilings, common-sense variability families, bounded advice modes, qualifiers, prohibitions, and mandatory review, but no product facts, customer text, identities, or reply templates |
| Answer eligibility owner boundary | `app/services/analysis_pipeline_service.py`, `app/services/canonical_conversation_turn_service.py`, `app/agent/nodes/query_fact_type_classifier.py` | formal internal input boundary | Removes reserved owner data and public Turn Understanding before graph execution; generates one `trusted-domain-policy-context/v1` at canonical input, preserves explicit missing/invalid state, and allows no public Pack, tenant/store/catalog, title, SKU, FactType, or customer-text selection authority |
| Answer eligibility projection | `app/services/admitted_answer_context_service.py` | diagnostic within opt-in convergence context | Counts only owner-stamped customer goals whose exact current-message span and SHA-256 recomputation match, projects owner verdicts into Minimal Decision Context, and leaves missing outputs unknown; cannot route, reply, audit, or grant send permission |
| Tool metadata | `app/agent/tools/base.py`, `app/agent/tools/registry.py` | formal utility | Planner metadata is limited to name, description, and input schema; deterministic eligibility reads freshness directly from the registry |
| Candidate reply | `app/services/model_first_answer_composer_service.py` | P1.2k.6i engineering checkpoint; local Audit qualified for isolated P1; opt-in, review-only, disabled | Partitions authoritative current-turn customer goals from dependencies, actions, media, and constraints; performs no Provider call when that partition has zero renderable customer goals; projects each applicable goal's eligible options under deterministic request aliases while retaining canonical policy/Pack identity server-side; accepts only `goal_ref`, customer text, and selected option aliases from the model, restores clause kind and evidence/premise bindings from validated server state, and leaves concrete option choice and wording to the model without adding evidence or send authority |
| No-evidence strategy | `app/services/no_evidence_reply_policy_service.py` | formal but oversized | Safe strategy only; must not become another fact or reply engine |
| Handoff wording | `app/services/customer_facing_safe_handoff_service.py` | formal | Customer-facing wording without changing risk or task state |
| Deterministic Final Contract | `app/services/final_answer_auditor.py` | formal; candidate branch zero model calls | Validate goal/clause/evidence references, canonical truth, high-risk boundaries, action completion, media eligibility, privacy/process leakage, and `can_send` prerequisites |
| Unified Textual Audit | `app/services/final_semantic_quality_service.py` | formal legacy audit; v2 strict role default-off; local Qwen qualified for isolated P1 evaluation | The model-first candidate's sole textual LLM audit for factual faithfulness, unresolved polarity, goal coverage, continuity, query/reply fit, serious repetition, internal-process language, and semantic-budget compliance. It treats a Composer result as a candidate only when that result owns the final reply. Its optional strict path uses one independent role request plus the existing local Validator; configuration, qualification, schema, or Provider failure never falls back to the Composer/formal model |
| Final orchestration | `app/services/final_response_orchestrator.py` | formal | Sequence, state synchronization, and fail-closed delivery shared by all entry points; enters model-first handling only for an accepted Composer result with `used_for_final_reply=true`; no model-first reply generation or rewriting |
| Media delivery | media services plus final reply blocks | formal | A candidate asset is not delivered media; role, identity, usability, approval, and block required |
| Runtime readiness | runtime readiness services and health routes | formal | Read-only deployment and knowledge readiness |
| Knowledge governance | knowledge review/publish and explicit sync services | formal writable owner | Agent and evaluation paths are readers |

## Answer Eligibility Owner Matrix

| Field | Authoritative owner | Allowed outcome boundary |
|---|---|---|
| `goal_understanding_status` | Current server Turn Understanding run | `valid`, `degraded`, `invalid`, or explicit `unknown`; public context is removed and admission cannot recalculate semantics |
| `conversation_reference_status` | Canonical conversation/context resolution through the internal Pipeline owner boundary | `not_required`, `resolved`, `ambiguous`, `missing`, or `unknown`; public request claims, pronoun heuristics, and text heuristics are not authoritative |
| `tool_requirement_status` | Tool Router plus Tool Executor | Distinguishes not required, static completion, live pending/completed/failed, action required, and unknown |
| `inference_requirement_status` | Claim Resolution | Direct evidence, bounded inference required/completed, prohibited, not applicable, or unknown; no inference is executed by the projection |
| `risk_policy_status` | Domain Pack policy plus deterministic Claim/Safety runtime verdict | Low verified, medium/review, high, prohibited, or unknown; model hints cannot lower deterministic risk |
| Direct-evidence cardinality | Existing Admission/Dedup plus Claim Resolution, projected by `AdmittedAnswerContextService` | Exactly one goal/claim/attribute/identity-aligned admitted direct fact; zero and multiple facts fail closed, and any evidence dependency blocks |
| Minimal Decision Context | Existing context builder | Projection only; cannot replace owner output, change formal reply fields, or change `can_send` |

Phase 1.10.1 qualifies this projection with the frozen 30-positive/40-negative
dataset in three deterministic orderings. The qualification script is an
evaluation owner only; no Fast Path or Composer module has been added.

## Operations And Future Channels

| Capability | Owner | Status | Boundary |
|---|---|---|---|
| Management authentication | `app/api/admin_auth.py`, route policy registry | formal | Cloudflare Access JWT, explicit RBAC, default deny |
| QianNiu/PDD/JD adapters | canonical adapter ports | planned | Native fields stop at the adapter boundary |
| Durable HandoffTask | not implemented | planned/P1 | Assignment, SLA, status, acknowledgement, audit |
| Supervisor queue | not implemented | planned | Projection of durable handoff and Agent outcomes |

## Evaluation Owners

| Capability | Owner | Boundary |
|---|---|---|
| Real conversation replay | replay services and scripts | Same canonical context and formal Pipeline as the user path |
| Synthetic safety benchmark | benchmark runner and versioned fixture | Regression only; not real accuracy |
| Real accuracy Gold Set | Gold/privacy/label services | Labels never enter Agent input; insufficient approval means `real_accuracy=null` |
| Formal answer QA | `scripts/run_full_answer_validation.py` | Read-only safety and response-contract validation |
| Real-derived capability slice | existing real-derived export and vertical-slice scripts | Proves evidence plumbing/capability, not customer accuracy |
| P1 Gold conversation baseline | `scripts/run_p1_gold_conversation_baseline.py`, `app/services/high_quality_long_conversation_review_service.py` | Development diagnostic only; validates server-owned goal provenance, aliases control references, writes split privacy-checked reports and an atomic projection-failure capsule containing shapes/hashes only, and cannot claim real accuracy or change Agent output |
| Composer attribution diagnostics | opt-in sinks in `app/services/analysis_pipeline_service.py` and `app/services/model_first_answer_composer_service.py` | Evaluation-only and default-off; sink absence is zero-work, persisted references use the existing server-keyed HMAC/Base32 alias owner, and diagnostics cannot change provider payloads, calls, replies, evidence, audit, or `can_send` |

## Frozen Shadow And Experimental Modules

These modules may keep producing diagnostics. ADR 0009 freezes feature expansion
until the active Agent Core slice identifies them as the earliest blocker.

| Module | Status | Production authority |
|---|---|---|
| Answer Memory | shadow/reference | Style and handling only |
| Grounded Reasoning Draft | shadow | None |
| Product Media Observation and annotation | shadow/pilot | None |
| pgvector retriever | shadow | None |
| Evidence-First Decision Proposal | shadow/qualification-gated | None |
| Buyer simulator and transcript grader | evaluation | None |
| Model-first composer | P0-correctness-qualified candidate, disabled | Review-only; no `can_send` |
| Bounded low-risk inference | P1 component-qualified; default-off, review-only, not production-qualified | Pipeline-owned Domain Policy remains separate from evidence. A prohibited request boundary may coexist with one low/medium practical answer option without lowering requested risk. Composer sees only goal-local request aliases; required/optional/forbidden constrain selection count while exact policy/premise/scope/risk/Pack bindings remain server-side. Maternal-child/home v1.6.1 permits reviewed durability, routine cleaning, an unverified-high-temperature cleaning boundary, and incidental-moisture guidance while retaining absolute-guarantee, chemical-compatibility, heat-resistance, waterproof, sterilization, and safety prohibitions. The earlier cleaning/moisture chain passed `5/5 + 5/5`; the expanded high-temperature full chain passed `5/5` and its Audit safe/unsafe matrix passed `5/5 + 5/5`. These component results grant no production or send authority |

## Cross-Cutting Change Checklist

Before changing Agent behavior, verify:

1. Which formal entry points use the changed path?
2. Is there already an authoritative owner?
3. Does the change alter context, evidence, tools, reply, media, safety, handoff,
   or delivery?
4. Does replay use the same canonical Pipeline?
5. Is the before/after real dataset comparable?
6. Are expected answers and labels excluded from Agent input?
7. Did formal knowledge remain read-only?
8. Did unsupported high-risk, media, or service actions remain blocked?
9. Did unnecessary handoff, completion, naturalness, and latency improve?
10. Were only the required durable documents updated?
