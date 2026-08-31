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
| Turn understanding | `app/services/semantic_fact_type_service.py`, `app/agent/nodes/query_fact_type_classifier.py` | formal | One semantic call returns typed atomic goals with current-message source provenance. Every explicit buyer fact, property, suitability, comparison, guarantee, practical request, or request to determine which service outcome applies remains a `customer_goal`; attributes narrow the requested property rather than identify the product. A request to execute an external side effect now remains a `service_action`; neither kind authorizes the outcome or executes it. Canonical `customer_goals` own goal identity; `requested_claims` are derived and must be rebuilt from them before Claim Resolution, never accepted as a divergent customer-goal source. Canonical dimension goals may additionally declare one closed `subject_scope` (`product`, `packaging`, `component`, `accessory`, or `included_item`); an absent scope never becomes an explicit `product` scope, may select only direct product-overall or legacy-unscoped evidence, never becomes a fact, and cannot replace the requested attribute. Policy candidates are projected only from the trusted Domain Pack with their family, scope, conclusion boundary, qualifiers, prohibited claim families, and optional unmapped semantic boundary. A canonical goal may nominate only an exact family. An unmapped goal can retain a nominated policy only when its non-authoritative semantic key is explicitly listed by that policy's trusted Pack boundary; a missing or nonmatching key clears the nomination. This is a fail-closed restriction only: it never creates a fact, derives a goal family, selects an option, or authorizes an answer. When a canonical goal omits policy intent, only an exact family from trusted Domain Pack candidates may be projected; its intent kind is projected only when every candidate in that exact family agrees on one non-empty kind. Neither path selects a policy. With an explicit runtime HMAC, the same call may receive an opaque open-goal alias and typed identity metadata, then nominate a same-identity continuation from the current span; historical text, server goal IDs, conversation IDs, and provenance never leave the server. Query-fact compatibility fallbacks stay degraded, while supporting dependencies, service actions, and contextual constraints remain distinct |
| Agent orchestration | `app/agent/graph.py`, `app/agent/nodes/` | formal but overweight | Stateful routing, tools, retries, and flow transitions; not final reply ownership |
| Formal LLM transport | `app/llm/client.py` | formal | Default Agent/Composer Provider transport, privacy projection, timeout/truncation handling |
| Role-scoped strict model transport | `app/services/strict_decision_provider_service.py`, `app/config.py`, `scripts/qualify_unified_audit_role.py` | formal utility; Unified Audit role default-off; provider-neutral qualification available | One native strict-schema or strict-tool request for an explicitly configured role; Unified Audit credentials/model/capability never inherit the formal Agent or decision-shadow role, missing/unqualified configuration fails before a model call with no fallback, and MiniMax compatibility or loopback Ollama native-schema options never relax the local strict Validator. The read-only role qualifier uses the v4 Audit schema and frozen no-test boundary, including an independent prohibited-extension decision, but never changes qualification state, feature flags, evidence, replies, or send authority |
| Product/order identity | identity services and resolver nodes | formal | External references resolve to JST/internal scoped identity. Structured sidebar order values preserve adapter type; an untyped value is a bounded `unknown_identifier` lookup rather than a length-based platform-ID guess. A verified single order item is projected through the existing selection policy as internal product name/SKU/`i_id`; ambiguity remains unresolved and cannot scope facts. |
| Retrieval | `app/retrieval/`, `app/repositories/knowledge_chunk_repository.py`, `app/agent/nodes/evidence_filter_node.py`, `app/agent/nodes/evidence_builder.py` | formal SQLite | Explicit backend and observable fail-closed retrieval; published chunk review state, fact type, attribute key, evidence UID, identity/subject scopes, source type/material provenance, and source confidence survive Repository -> Filter -> Builder through a narrow protocol allowlist while Evidence Gate retains admission authority |
| Product context candidates | `app/services/product_context_pack_service.py`, `app/integrations/product_hub/reviewed_facts_client.py` | formal; Product Hub reader default-off | Preserve role, review, identity, attribute, and provenance metadata. For a JST-derived identity, the optional Hub reader verifies the exact resolved SKU through the Hub SKU endpoint before using its returned Hub product code for facts; JST `i_id` never crosses namespaces as a Hub product code. It is never a title search, catalog snapshot, media source, or independent evidence registry |
| Evidence admission | `app/services/admitted_answer_context_service.py` | formal utility; convergence opt-in | Single reusable review/identity/role/claim/conflict admission contract |
| Claim resolution | `app/services/claim_resolution_service.py` | formal utility; bounded inference disabled with Composer path | Preserves supported, unresolved, conflicting, and prohibited direct-evidence state; for a scoped dimension goal, direct evidence must match both canonical attribute and canonical object scope. Aggregate `overall_dimensions` is a separate attribute and is never decomposed into width, height, depth, or any other axis. It keeps restricted request risk separate from low/medium answer-strategy risk and may project a practical alternative only from the deterministic trusted Domain Pack/admitted-premise/scope/conflict intersection for the same owner-stamped goal family. Missing goal-family authority yields no option; an already-supported goal remains direct-only unless an exact trusted practical intent was nominated. Claim Resolution never selects an option |
| Domain policy data | `app/repositories/file_policy_repository.py`, `rules/domain_policy_packs/`, reviewed `KBProduct.domain_policy_id` | formal data utility; no routing authority | Sole strict loader for versioned claim policy; resolves trusted deployment, a Pipeline-verified mapping from one exact SKU/`i_id` to one published product, or an isolated evaluation selector, emits an anonymous Pack reference/content hash projection, and revalidates both before use. The product field is non-factual control metadata and changing it returns a published product to review. Query-only legacy catalogs that lack the optional column remain readable and are treated as unbound until a normal writable migration. Policies contain premise families, scope, low/medium risk ceilings, common-sense variability families, bounded advice modes, qualifiers, prohibitions, and mandatory review, but no product facts, customer text, identities, or reply templates |
| Answer eligibility owner boundary | `app/services/analysis_pipeline_service.py`, `app/services/canonical_conversation_turn_service.py`, `app/agent/nodes/query_fact_type_classifier.py`, `app/tracing/repository.py` | formal internal input boundary; lifecycle default-disabled | Removes reserved owner data and public Turn Understanding before graph execution; generates one `trusted-domain-policy-context/v1` at canonical input and preserves explicit missing/invalid state. Public Pack, tenant/store/catalog, title, FactType, customer-text, and lifecycle-state claims have no authority. A public SKU/`i_id` is only an identity signal: the Pipeline must match one published product exactly and load its reviewed control metadata; ambiguity, an unpublished product, or no binding fail closed. If configured with a runtime HMAC, it loads and records only HMAC-addressed open-goal metadata in Trace; only a trusted delivery receipt may close it, and it has no reply, evidence, or send authority |
| Answer eligibility projection | `app/services/admitted_answer_context_service.py` | diagnostic within opt-in convergence context | Rebuilds customer requested claims from canonical owner-stamped goals, then counts only goals whose exact current-message span and SHA-256 recomputation match; projects owner verdicts into Minimal Decision Context and leaves missing outputs unknown; cannot route, reply, audit, or grant send permission |
| Tool metadata | `app/agent/tools/base.py`, `app/agent/tools/registry.py` | formal utility | Planner metadata is limited to name, description, and input schema; deterministic eligibility reads freshness directly from the registry |
| Candidate reply | `app/services/model_first_answer_composer_service.py`, `app/llm/client.py` | P1.4 engineering checkpoint; DeepSeek V4 Flash Composer role qualified; opt-in, review-only, disabled | Partitions authoritative current-turn customer goals from dependencies, actions, media, and constraints; performs no Provider call when that partition has zero renderable customer goals; projects each applicable goal's eligible options under deterministic request aliases while retaining canonical policy/Pack identity server-side; accepts only `goal_ref`, customer text, and selected option aliases from the model, restores clause kind and evidence/premise bindings from validated server state, and leaves concrete option choice and wording to the model without adding evidence or send authority. By default it uses the unchanged formal LLM; an explicit complete and qualified `COPILOT_COMPOSER_LLM_*` override changes only this role and fails closed when incomplete or unqualified. Its optional transport thinking mode and minimum output budget are explicit role settings, not model-name branches; a non-default setting is bound into the qualification fingerprint. No credential or qualification fingerprint is stored in the repository |
| No-evidence strategy | `app/services/no_evidence_reply_policy_service.py` | formal but oversized | Safe strategy only; must not become another fact or reply engine |
| Handoff wording | `app/services/customer_facing_safe_handoff_service.py` | formal | Customer-facing wording without changing risk or task state |
| Deterministic Final Contract | `app/services/final_answer_auditor.py` | formal; candidate branch zero model calls | Validate goal/clause/evidence references, canonical truth, high-risk boundaries, action completion, media eligibility, privacy/process leakage, and `can_send` prerequisites |
| Unified Textual Audit | `app/services/final_semantic_quality_service.py` | formal legacy audit; v4 strict role default-off; engineering contract qualified, model role not qualified | The model-first candidate's sole textual LLM audit for factual faithfulness, unresolved polarity, goal coverage, continuity, query/reply fit, serious repetition, internal-process language, and semantic-budget compliance. It treats a Composer result as a candidate only when that result owns the final reply. V4 receives server-owned qualifier and prohibited-extension families in distinct dimensions and requires independent advice, factor, restricted-boundary, qualifier, prohibited-extension, and conclusion decisions. Its optional strict path uses one independent role request plus the existing local Validator; configuration, qualification, schema, or Provider failure never falls back to the Composer/formal model. For a review-only Supervisor Assist baseline, an unavailable/unqualified result is recorded as advisory quality evidence while Deterministic Final and the forced human-review/no-send boundary remain authoritative. Autonomous Send still requires this role to qualify. DeepSeek V4 Pro passed the safe half `5/5`, then incorrectly marked the first unsupported test-status counterexample as absent; the role remains disabled and Provider-blocked |
| Final orchestration | `app/services/final_response_orchestrator.py` | formal | Sequence, state synchronization, and fail-closed delivery shared by all entry points; enters model-first handling only for an accepted Composer result with `used_for_final_reply=true`; no model-first reply generation or rewriting |
| Media delivery | media services plus final reply blocks | formal | A candidate asset is not delivered media; role, identity, usability, approval, and block required |
| Runtime readiness | runtime readiness services and health routes | formal | Read-only deployment and knowledge readiness |
| Knowledge governance | knowledge review/publish and explicit sync services | formal writable owner | Agent and evaluation paths are readers |

The latest isolated dirty-candidate run kept this baseline's existing owner
boundaries intact: the compound service-result question remained three
review-only customer goals and granted no external action. Eight requests
completed with no formal-knowledge DML and no send authority. One unrelated
provider JSON failure degraded Turn Understanding, skipped Composer, and was
rejected by Deterministic Final. This is an expected fail-closed provider
stability signal, not a Fixed-8 quality pass; the reconstructed fixture's
claim-type-slot score is diagnostic-only until it represents goal kind, status,
and object scope.

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
dataset in three deterministic orderings. Its fixture uses the same canonical
goal-identity projection as the formal query classifier, and the manifest pins
both fixture content and evaluator-source hashes so a contract upgrade cannot
silently leave stale qualification data behind. The qualification script is an
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
| Synthetic safety benchmark | benchmark runner and versioned fixture | Regression only; not real accuracy. Its scenario SQLite and formal knowledge snapshot are separate sources: fixture runs require an explicit query-only snapshot and reject the scenario DB or live `knowledge_base.db` as retrieval input. The current anonymized-identity fixture can expose a context gap but cannot establish factual quality until an independently reviewed synthetic knowledge companion exists. |
| Historical knowledge snapshot recovery | `scripts/diagnose_knowledge_snapshot_recovery.py`, `scripts/build_knowledge_snapshot_recovery_candidate.py` | Recovery-governance utilities. The audit reads a historical SQLite snapshot query-only and reports only hashes/counts/controlled enums/field names. The builder can create a separate current-schema candidate only when text-typed historical `product_id` exactly equals a text-typed historically published product `i_id`. It writes only below Git-ignored `data/imports/`, rejects the formal database and SQLite sidecars, commits through a temporary candidate, resets copied product/fact rows to review-only state, recomputes the current `title|content` hash, clears policy bindings, and excludes QA, media, chunks, Answer Memory, and change logs. Candidate artifacts never configure runtime retrieval or Delivery. `ProductContextPackService` permits only `published` products to form structured profiles, so an isolated `pending_review` candidate cannot be admitted as formal evidence. |
| Real accuracy Gold Set | Gold/privacy/label services | Labels never enter Agent input; insufficient approval means `real_accuracy=null` |
| Formal answer QA | `scripts/run_full_answer_validation.py` | Read-only safety and response-contract validation |
| Real-derived capability slice | existing real-derived export and vertical-slice scripts | Proves evidence plumbing/capability, not customer accuracy |
| P1 Gold conversation baseline | `scripts/run_p1_gold_conversation_baseline.py`, `scripts/compare_model_first_answer_composer.py`, `app/services/high_quality_long_conversation_review_service.py` | 仅限开发诊断。旧 real-derived 合同保持兼容；恢复后新增独立 `conversation-reconstructed-v1` 合同，固定 8 条/40 个历史回合，并明确不是原 Fixed-8 或真实 Gold。统一 Owner 校验目标 provenance、控制引用别名、隐私、版本化哈希、query-only 知识快照和正式知识 DML；runtime binding 将调用方固定的本机 loopback 端口与 PID、快照和源码哈希一起校验，默认端口为 5013，不信任任意已占用的服务。审核 SPA 仅为该页面单独授予 reviewer 可读权限，其余管理页保持原有策略；reviewer 只能保存/提交，Cloudflare Access supervisor/admin 才能逐条批准或拒绝。review projection 复用正式 canonical history normalizer，并与 Composer 一致排除无客户 goal 的 legacy `supporting_only` dependency。重建合同只把 sidecar 中已审核的 direct evidence 投影到隔离快照，排除 unresolved/pending/media/评分标签，并用 archived/non-auto-reply 哨兵满足 readiness，绝不写源知识库。评分、case observation、checkpoint 与 summary 共用同一确定性分轨结果：Supervisor Assist 仅要求 accepted Composer、Deterministic Final、`requires_human_review=true`、`can_send=false` 以及无确定性安全、媒体或服务动作违规；Unified Audit 的失败只作为 advisory quality evidence。Autonomous Send 仍要求独立 Audit role qualification、真实准确率、安全与 Delivery 全部通过。评测字段不得进入 Agent payload，`real_customer_accuracy=null`，生产开关保持关闭 |
| Composer attribution diagnostics | opt-in sinks in `app/services/analysis_pipeline_service.py` and `app/services/model_first_answer_composer_service.py` | Evaluation-only and default-off; sink absence is zero-work, persisted references use the existing server-keyed HMAC/Base32 alias owner, and diagnostics cannot change provider payloads, calls, replies, evidence, audit, or `can_send` |
| Composer role qualification | `scripts/qualify_model_first_composer_role.py` | Evaluation-only five-run synthetic gate for an explicit `COPILOT_COMPOSER_LLM_*` model; its non-secret fingerprint binds a passing report to base/model/effective timeout and any explicit transport thinking/output-budget settings, with one Provider call per run and no retry/repair/fallback or delivery authority |
| Unified Audit role qualification | `scripts/qualify_unified_audit_role.py` | Evaluation-only frozen 5+5 gate for the independent strict-output role; a non-secret fingerprint binds a passing report to provider/base/model/capability/timeout/thinking before production may call it |

An earlier reconstructed baseline on `da4a0ad` verified the generic
product-scoped overall-dimension binding through the existing admission and
Claim Resolution contracts: supported attribution was `2/2`, unresolved
declaration was `14/14`, and no formal knowledge or send authority changed.
Offline review selected `multi-goal_completion` as the next P1 Owner. It may
repair only generic goal canonicalization and multi-goal completion through the
existing Turn Understanding and Claim Resolution contracts; it has no Composer,
Audit, Graph, delivery, or send authority.

The latest isolated query-only rerun validates one narrow Turn Understanding
boundary within that same Owner: a request to choose among alternative service
outcomes remains a review-only `customer_goal`, while only one definite external
operation is a `service_action`. The frozen reconstructed Fixed-8 preserved all
`16/16` renderable goals and `13/16` goal identities, with formal-knowledge DML
`0`, `can_send=0`, and mandatory human review for every candidate. Expert
quality remains below promotion at goal completion `1.375/2` and business
helpfulness `0.625/2`; it does not alter production authority or establish real
customer accuracy.

An earlier candidate additionally verified that the server's model-facing
FactType projection deduplicates the existing material aliases to the canonical
`material_composition` ID before the semantic call. This is input normalization,
not an unmapped-output promotion. Canonical customer goals are also the sole
source of customer-claim identity; with such goals present, untyped stale
derived items are discarded rather than entering Claim Resolution. The latest
reconstructed native gate completed `8/8` with review-only replies,
Deterministic Final `8/8`, direct attribution `4/4`, explicit unresolved
declaration `12/12`, formal-knowledge DML `0`, `can_send=0`, and human review
`8/8`. Unified Audit passed `7/8`; expert review found an unsupported
durability expansion from an unallocated material premise. The follow-up
default-off Composer projection keeps complete evidence server-side, but shows
the model only facts allocated to a renderable goal or an already-offered
policy premise. Material-to-durability and dimension-to-fit mutation tests
cover that boundary without product-specific rules. One subsequent
query-only `8/8` completed Composer, Deterministic Final, and Unified Audit at
`8/8`, with direct attribution `4/4`, explicit unresolved declaration `11/11`,
formal-knowledge DML `0`, `can_send=0`, and human review `8/8`. It is a safety
and attribution checkpoint, not a demonstrated quality gain: canonical goal
recall remains `4/18` with `13` unexpected goals. This remains a development
diagnostic: `real_customer_accuracy=null` and Autonomous Send remain blocked.

The current query-only `conversation-reconstructed-v1` Fixed-8 is the
Supervisor Assist diagnostic baseline. It records `8/8` deterministic candidate
eligibility, `16/16` goal-clause coverage, direct attribution `4/4`, explicit
unresolved handling `12/12`, formal-knowledge DML `0`, `can_send=0`, and human
review `8/8`. Unified Audit passed `6/8` calls and recorded two advisory
failures in the same case observations; this neither qualifies the role nor
changes the Autonomous Send block. The eight human-quality reviews are still
pending and `real_customer_accuracy=null`.

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
| Bounded low-risk inference | P1 component-qualified; default-off, review-only, not production-qualified | Pipeline-owned Domain Policy remains separate from evidence. A prohibited request boundary may coexist with one low/medium practical answer option without lowering requested risk. Composer sees only goal-local request aliases; required/optional/forbidden constrain selection count while exact policy/premise/scope/risk/Pack bindings remain server-side. Maternal-child/home v1.6.3 permits reviewed durability, routine cleaning, an unverified-high-temperature cleaning boundary, incidental-moisture guidance, and goal-owned oral-exposure risk handling while retaining absolute-guarantee, chemical-compatibility, heat-resistance, waterproof, sterilization, toxicity, ingestion-safety, certification, and product-safety prohibitions. Oral handling may have no factual premise only for `safety_handoff_required`; it remains unresolved, review-only, and limited to stopping contact, inspecting damage/fragments, and medical escalation after ingestion or symptoms. After the Understanding gate passed `15/15`, native Fixed-8 improved to `7/8` Composer acceptance and zero expert-rated failures; moisture passed `5/5` and oral-safety-only plus material-and-oral-safety passed `3/3` each. These component results grant no production or send authority |

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
