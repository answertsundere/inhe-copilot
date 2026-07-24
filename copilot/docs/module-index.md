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
| Conversation turns | `app/services/canonical_conversation_turn_service.py` | formal utility | Bounded role-aware history and provider privacy projection |
| Turn understanding | `app/services/semantic_fact_type_service.py`, `app/agent/nodes/query_fact_type_classifier.py` | formal | One semantic call returns typed atomic goals; only verified `customer_goal` items become requested claims, while evidence dependencies, service actions, and contextual constraints stay distinct |
| Agent orchestration | `app/agent/graph.py`, `app/agent/nodes/` | formal but overweight | Stateful routing, tools, retries, and flow transitions; not final reply ownership |
| Formal LLM transport | `app/llm/client.py` | formal | Provider transport, privacy projection, timeout/truncation handling |
| Product/order identity | identity services and resolver nodes | formal | External references to JST/internal scoped identity |
| Retrieval | `app/retrieval/` | formal SQLite | Explicit backend and observable fail-closed retrieval |
| Product context candidates | `app/services/product_context_pack_service.py` | formal | Preserve role, review, identity, attribute, and provenance metadata |
| Evidence admission | `app/services/admitted_answer_context_service.py` | formal utility; convergence opt-in | Single reusable review/identity/role/claim/conflict admission contract |
| Claim resolution | `app/services/claim_resolution_service.py` | formal utility | Supported, unresolved, conflicting, and prohibited state from admitted context |
| Domain policy data | `app/repositories/file_policy_repository.py`, `rules/domain_policy_packs/` | formal data utility; no routing authority | Strict versioned claim policy selected only by explicit metadata; no product facts, customer text, identities, or reply templates |
| Answer eligibility projection | `app/services/admitted_answer_context_service.py` | diagnostic within opt-in convergence context | Projects owner verdicts into Minimal Decision Context; unknown stays unknown; cannot route, reply, audit, or grant send permission |
| Candidate reply | `app/services/model_first_answer_composer_service.py` | opt-in, review-only, disabled | One validated clause per customer goal from compact admitted context; supported clauses cite admitted evidence, unresolved clauses cite none, supporting-only dependencies are excluded; no tools, fact creation, delivery, or send permission |
| No-evidence strategy | `app/services/no_evidence_reply_policy_service.py` | formal but oversized | Safe strategy only; must not become another fact or reply engine |
| Handoff wording | `app/services/customer_facing_safe_handoff_service.py` | formal | Customer-facing wording without changing risk or task state |
| Final factual/safety audit | `app/services/final_answer_auditor.py` | formal | Audit model-first replies against admitted canonical truth while retaining historical turns only for non-factual continuity; enforce claim/evidence structure, high-risk boundaries, privacy, and actual media wording; style remains owned by Semantic Quality |
| Semantic fit | `app/services/final_semantic_quality_service.py` | formal | Question-answer fit after facts and actions are settled |
| Final orchestration | `app/services/final_response_orchestrator.py` | formal | Final audited response and delivery contract shared by all entry points |
| Media delivery | media services plus final reply blocks | formal | A candidate asset is not delivered media; role, identity, usability, approval, and block required |
| Runtime readiness | runtime readiness services and health routes | formal | Read-only deployment and knowledge readiness |
| Knowledge governance | knowledge review/publish and explicit sync services | formal writable owner | Agent and evaluation paths are readers |

## Answer Eligibility Owner Matrix

| Field | Authoritative owner | Allowed outcome boundary |
|---|---|---|
| `goal_understanding_status` | Turn Understanding | `valid`, `degraded`, `invalid`, or explicit `unknown`; admission cannot recalculate it |
| `conversation_reference_status` | Canonical conversation/context resolution | `not_required`, `resolved`, `ambiguous`, `missing`, or `unknown`; no pronoun or text heuristic |
| `tool_requirement_status` | Tool Router plus Tool Executor | Distinguishes not required, static completion, live pending/completed/failed, action required, and unknown |
| `inference_requirement_status` | Claim Resolution | Direct evidence, bounded inference required/completed, prohibited, not applicable, or unknown; no inference is executed by the projection |
| `risk_policy_status` | Domain Pack policy plus deterministic Claim/Safety runtime verdict | Low verified, medium/review, high, prohibited, or unknown; model hints cannot lower deterministic risk |
| Minimal Decision Context | Existing context builder | Projection only; cannot replace owner output, change formal reply fields, or change `can_send` |

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
| Model-first composer | active candidate | Review-only; no `can_send` |

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
