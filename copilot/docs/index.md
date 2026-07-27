# Project Documentation Index

This is the durable documentation entry point for the INHE customer-service Copilot. New agents should start here, then read the documents relevant to the module they are changing.

## Mandatory Reading Order

Every AI or engineer must read these before implementation:

1. Parent workspace `AGENTS.md` and project `AGENTS.md`.
2. `docs/PROJECT_CHARTER.md` - business mission, truth flow, non-goals, and quality definition.
3. `docs/architecture-overview.md` - current system, target system, confirmed gaps, and convergence order.
4. `docs/agent-core-priority-plan.md` - mandatory delivery order, stage gates,
   frozen work, and the architecture-drift check for every implementation task.
5. `docs/module-index.md` - behavior ownership and cross-cutting change checklist.
6. The topic-specific documents below.

For major features or architecture changes, review maintained external solutions first and record durable findings under `docs/research/`. Record production-flow or module-ownership decisions under `docs/adr/` before implementation.

## Document Center

This file is the only active architecture and project-documentation index.

- `docs/document-location-policy.md` - explains which Markdown belongs in this documentation center, which root entry files must stay in place, and which module-local or historical documents must not be treated as current architecture.

Do not create another competing architecture index. Root `AGENTS.md`, `CLAUDE.md`, project `AGENTS.md`, and module-local README files remain in their discovery locations and point back to this center.

## Business Architecture Invariants

- External product titles resolve through JST/internal product identity before product facts are selected.
- The knowledge base stores reviewed base facts and described media; bounded reasoning may connect eligible facts but may not invent strong safety, compliance, order, refund, replacement, compensation, or platform claims.
- Product facts, policy facts, service actions, media references, and Answer Memory are separate roles.
- Historical reviewed answers teach handling and wording, not product truth.
- A media candidate is not sent media. Actual delivery requires an eligible role, platform support, and matching reply blocks.
- High-risk or human-only work creates a durable handoff task for the cross-platform supervisor queue.
- QianNiu, Pinduoduo, and JD remain adapters around one platform-neutral Agent and control plane.
- Benchmark and replay results are valid only when they exercise the same final pipeline and context contract as the user-facing path.

## Current Architecture Direction

- `docs/PROJECT_CHARTER.md` - authoritative business direction and non-negotiable boundaries.
- `docs/architecture-overview.md` - authoritative current/target architecture,
  thin-LangGraph boundary, context-first reasoning model, and convergence order.
- `docs/agent-core-priority-plan.md` - operational priority authority for the
  gold-service Agent Core, including the active priority, protocol-work budget,
  promotion gates, domain portability, and required task header.
- `docs/module-index.md` - module ownership and status (`formal`, `shadow`, `legacy`, or `planned`).
- `docs/agent-core-candidate-change-ownership.md` - P0-R0 ownership and
  disposition manifest for the 45-file feature-disabled Agent Core checkpoint.
- `docs/adr/0002-product-media-observation-review-lifecycle.md` - immutable
  local-VLM observation candidates, supervisor review, hash invalidation, and
  shadow-only approval boundary.
- `docs/adr/0003-product-media-object-binding-observations.md` - v3
  object-bound product-media observations and the shadow-only Product
  Understanding Graph boundary.
- `docs/adr/0004-composable-vision-grounding-shadow-poc.md` - separates OCR,
  object proposals, geometry binding, and optional VLM verification for a
  shadow-only grounding qualification PoC.
- `docs/adr/0005-product-media-annotation-external-authoring.md` - adopts a
  query-only Label Studio authoring export and detector-feasibility path
  without promoting annotations or model output into formal evidence.
- `docs/adr/0006-evidence-first-llm-decision-loop-shadow.md` - establishes one
  deterministic admission context and a strict-schema, post-graph LLM decision
  proposal isolated from formal reply and delivery decisions.
- `docs/adr/0007-formal-evidence-convergence.md` - makes canonical selected
  evidence an opt-in, admitted-only formal graph output and defines bounded
  decision context without changing the final delivery contract.
- `docs/adr/0008-cloudflare-access-rbac-management-boundary.md` - defines the
  Cloudflare Access JWT, application RBAC, CSRF, service-identity, route-policy,
  and readiness boundary for public management routes.
- `docs/adr/0009-agent-core-capability-mainline.md` - freezes evaluator and
  shadow expansion, restores one real-conversation Agent Core vertical slice as
  the active mainline, and defines outcome-based promotion metrics.
- `docs/omnichannel-control-plane.md` - target architecture for a platform-neutral customer-service core, QianNiu/Pinduoduo/JD adapters, central supervision, and desktop handoff notifications.
- `docs/top_rag_development_roadmap.md` - evidence-first RAG and knowledge-governance roadmap. Some status statements are historical; use it for direction, not current completion claims.
- `docs/langgraph-architecture.md` - LangGraph runtime responsibility, target
  macro stages, state/context rules, and incremental migration constraints. It
  is an implementation companion, not the overall architecture authority.
- `rules/domain_policy_packs/` - strict, versioned claim-policy data selected
  only by explicit metadata. Packs are not product knowledge, reply templates,
  Agent plugins, routers, or safety verdict owners.

The durable operating model is:

```text
platform-neutral adapters
-> one AnalysisPipeline
-> thin stateful LangGraph runtime
-> compact Decision Context and admitted evidence
-> model-led claim decision and reply composition
-> deterministic final safety/delivery gate
-> outbound delivery or durable HandoffTask
```

Do not optimize for graph-node count, add parallel shadow subsystems without a
promotion path, or pass complete traces and candidate stores to the model.
Formal Evidence Convergence and the model-first composer are implemented but
disabled in production. P0 has qualified the feature-disabled ADR 0009 Agent
Core correctness slice: real context, admitted evidence and tools, one reply
owner, and deterministic final safety. The active priority is now P1 Gold
Conversation Quality through outcome-based long-conversation evaluation. Gold
review remains an accuracy prerequisite, but building more review
infrastructure is not the active development mainline.
The canonical answer-eligibility projection is diagnostic only, and Fast Path
remains disabled. The priority plan is mandatory: work outside its current
active stage is frozen unless a documented production/security exception or an
explicit plan update applies.

## Architecture Decisions And Research

- `docs/adr/README.md` - ADR rules and required format.
- `docs/adr/0001-unified-analysis-pipeline.md` - accepted decision establishing
  one formal AnalysisPipeline before any service decomposition.
- `docs/research/mature-customer-service-systems.md` - official-source comparison of mature routing, handoff, task, AI, and self-hosted control-plane patterns.
- `docs/research/grounded-reasoning-evaluation.md` - official-source-informed, deterministic evaluation contract for the shadow Grounded Reasoning layer.
- `docs/research/multimodal-grounded-customer-service.md` - mature-product patterns, verified current gaps, and the target contract for product-media understanding, bounded derivation, and claim-level safety.
- `docs/research/vision-grounding-provider-qualification.md` - provider-neutral, read-only 10-image grounding qualification contract and reuse assessment.
- `docs/research/product-media-annotation-and-detector-feasibility.md` -
  product-independent visual annotation schema, external authoring rationale,
  and bounded detector-feasibility criteria.
- `docs/research/evidence-first-llm-decision-loop.md` - official-provider
  structured-output and tool-use principles, evidence role separation,
  compound-claim handling, canonical decision context, and model-led
  supervisor-candidate promotion gates.
- `docs/research/strict-decision-provider-qualification.md` - strict provider
  capability classes, isolated configuration, and read-only qualification
  contract for the Evidence-First decision shadow.
- `docs/research/real-customer-service-accuracy-evaluation.md` - privacy-safe,
  read-only Gold Set with structured de-identified conversation turns,
  independent output scanning, human claim-label audit storage, formal-pipeline
  baseline, query-driven evidence coverage, and the Tier D AI-buyer multi-turn
  contract. Tier A, Tier B, Tier C, and Tier D remain separate; only Tier A may
  establish production accuracy after its manual claim-label gate is met.

The durable target is an omnichannel customer-service control plane. QianNiu is the first planned platform adapter, not the system core. Platform payloads must be normalized before they enter the Agent, and Agent decisions must remain independent of any platform's native fields.

## Agent Graph Reference

- `docs/agent/customer_service_graph_nodes.md` - graph node inventory.
- `docs/agent/customer_service_graph_edges.md` - graph edges and routing paths.
- `docs/agent/customer_service_graph_traces.md` - graph trace and observability notes.

These documents describe the Agent graph. They do not replace the application-level pipeline, delivery contract, or platform adapter design.

## Evidence, Retrieval, And Reasoning

- `docs/embedding_config.md` - local embedding configuration and preflight process.
- `docs/llamaindex_shadow_poc.md` - historical LlamaIndex shadow experiment.
- `docs/answer_memory_layer.md` - Answer Memory safety contract, data model, import flow, and shadow guidance.
- `docs/grounded_reasoning_draft_layer.md` - shadow-only grounded reasoning draft contract.
- `docs/research/evidence-first-llm-decision-loop.md` - canonical admission
  context and strict decision-proposal shadow contract.

Current boundaries:

- pgvector remains shadow-only until the formal retriever contract is implemented and evaluated.
- Answer Memory is action/style guidance, not product fact evidence.
- Grounded Reasoning is shadow-only and cannot change `can_send` or the final reply.
- The Evidence-First LLM Decision Loop is post-graph and shadow-only. It may
  execute only the application-owned eligible local read-only portion of a tool
  plan; unsupported order, media, and side-effect operations remain deferred.
  Factual proposal clauses may cite admitted evidence UIDs only.
- `service_action` and `media_reference` cannot be promoted to product facts.
- Product media roles do not prove that image contents have been understood. Model-extracted OCR or visual observations require product scope, provenance, confidence, and review state before they can support formal claims.
- Product Media Observation v3 resolves observed source bytes with SHA-256 provenance and uses deterministic panel proposals plus staged panel, object, label, and object-label binding only for shadow diagnostics. Its normalised regions and graph relations remain outside formal evidence, customer replies, and `can_send` until a separate reviewed-evidence promotion decision.
- Low-risk bounded derivations must declare their inputs and assumptions. Dimensions or visible structure cannot be upgraded into load, child-safety, toxicity, certification, or installation-safety claims.

## Replay, Evaluation, And Training Data

- `docs/REAL_REPLAY_SIDECAR_DATA_REQUIREMENTS.md` - required per-sample product and order context for realistic replay.
- `docs/real_conversation_daily_replay.md` - daily real-conversation replay process.
- `docs/training_sample_eval_set_conversion.md` - reviewed training-sample conversion into evaluation scenarios.
- `docs/training_sample_report.md` - historical training-sample UI and workflow delivery report.
- `docs/real_golden_delivery_report.md` - historical real-golden delivery report.

Evaluation results are valid only when the evaluated entry point, context, media stage, final pipeline, and delivery contract match the real user-facing path.

Every behaviour-affecting change must also satisfy the pinned real-dataset
before/after gate in `docs/research/real-customer-service-accuracy-evaluation.md`;
synthetic benchmark success alone cannot establish an optimisation.

## Operations And Platform Setup

- `docs/sidecar_client_setup.md` - current local sidecar setup notes. Treat QianNiu-specific details as adapter guidance, not Agent-domain contracts.
- `docs/runtime-operation.md` - canonical clean runtime worktree, local configuration, formal LLM provider transport, safe SQLite backup startup, health checks, port switching, and rollback.
- `docs/gray_trial_readiness_report.md` - historical gray-trial readiness snapshot.

## Historical Status Snapshots

- `docs/current-system-status.md` - system snapshot dated 2026-06-01. It is not the current architecture source of truth.

Historical reports must keep their date and must not be used as current completion evidence without live verification.

Workspace-root `docs/`, `验收报告*.md`, and `客服系统/` are historical or generated documentation collections. They are intentionally not moved into the authoritative center because some are untracked, contain Obsidian links, or describe older implementations. Their location and authority are recorded in `docs/document-location-policy.md`.

## Documentation Rules

- Long-lived modules, contracts, and architecture decisions must be linked from this index.
- Narrow bug fixes should update an existing relevant document when behavior or a contract changes; they do not require a new document each time.
- New platform integrations must use the canonical conversation and decision contracts described in `docs/omnichannel-control-plane.md`.
- New retrieval, reasoning, memory, safety, or delivery modules must declare whether they are `formal`, `shadow`, `legacy`, or `planned`.
- Architecture decisions that change module ownership or production data flow must be recorded under `docs/adr/` before implementation.
- New major capabilities must document what maintained external products or open-source systems were evaluated for reuse.
- Every new durable document must be linked from this index; historical snapshots must keep their date and status.

## Known Architecture Gaps

- `/api/analyze`, `/api/copilot/context`, benchmark, and replay now use the
  formal AnalysisPipeline. Presentation and HTTP metadata remain intentionally
  route-specific.
- Final response persistence is covered by Phase 0.1 and Pipeline contract
  tests. Pipeline failures return and persist one review-only `pre_final`
  contract; legacy direct callers still need inventory before they are treated
  as formal entry points.
- `app.main` still combines dependency initialization, Flask routing, and resident background workers.
- Fact-type and safety group definitions remain distributed across multiple modules.
- Formal Product Context Pack convergence is opt-in through
  `COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED`; it remains subject to the
  existing reviewed, identity, role, claim-compatibility, placeholder, and
  conflict admission contract.
- Formal product-fact and exact-FAQ modes still primarily render retrieved facts
  instead of using one compact admitted-fact, claim-level composition stage.
- Understanding, routing, guard, fallback, semantic, and polishing
  responsibilities overlap across the current graph and post-graph services.
  LangGraph must be reduced incrementally after evidence and behavior parity
  tests exist, not through a big-bang rewrite.
- Customer and product media are not yet represented as reviewed, queryable visual observations. Some text product questions with known context skip image VLM analysis.
- Durable platform adapters and HandoffTask workflow are not implemented.
- A project-level governance baseline and accepted ADR history now exist, but CI
  enforcement and managed schema migrations are still missing.

These gaps are the next architecture-convergence work. They should be addressed before adding platform-specific behavior to the Agent core.
