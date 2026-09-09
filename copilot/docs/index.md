# Project Documentation Index

This is the durable documentation entry point for the INHE customer-service Copilot. New agents should start here, then read the documents relevant to the module they are changing.

## Mandatory Reading Order

Every AI or engineer must read these before implementation:

1. Parent workspace `AGENTS.md`, project `AGENTS.md`, `PROJECT_INDEX.md`, and
   `ROADMAP.md`.
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

- External product titles and structured order references resolve through JST/internal product identity before product facts are selected. An untyped sidebar order value is not classified from its length; it uses the bounded JST identifier surface and only an unambiguous verified single order item, an order with one primary item and gifts, or one exact JST outbound-item identifier match may supply an exact SKU to the Product Context Pack. An explicit shop ID, or a shop label resolving to exactly one enabled JST shop, may constrain a direct outbound lookup and bounded scan only when paired with that explicit order reference; it cannot prove an order or product by itself. A JST SKU maps to Product Hub facts, and separately to review-only Hub media candidates, only through the exact Hub SKU natural key, never by treating JST `i_id` as a Hub product code; context-selected multi-item orders remain fail-closed. Hub media is never factual evidence or delivered media merely by being present in context.
- The knowledge base stores reviewed base facts and described media; bounded reasoning may connect eligible facts but may not invent strong safety, compliance, order, refund, replacement, compensation, or platform claims.
- Product facts, policy facts, service actions, media references, and Answer Memory are separate roles.
- Historical reviewed answers teach handling and wording, not product truth.
- A media candidate is not sent media. Actual delivery requires an eligible role, platform support, and matching reply blocks.
- High-risk or human-only work creates a durable handoff task for the cross-platform supervisor queue.
- QianNiu, Pinduoduo, and JD remain adapters around one platform-neutral Agent and control plane.
- Benchmark and replay results are valid only when they exercise the same final pipeline and context contract as the user-facing path.

## Current Architecture Direction

### Product Hub Answer Context Shadow (2026-09-08)

The existing Hub client can read `answer-context-v1` with
`COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED=true` (default false).
Existing Product Context Pack adapters produce aggregate diagnostics only;
formal facts, media, reply ownership and delivery are unchanged. No model call
or production database write is involved. See
[Product Hub read contract](research/product-hub-agent-read-api.md) and
[ADR 0010](adr/0010-product-hub-reviewed-fact-read-bridge.md).
Three deterministic products from the existing read-only snapshot resolved
successfully. They returned 13 fact candidates and 104 review-only media
candidates; nine unsupported media types were excluded. In the four queried
fact types, only two color-options candidates mapped; dimensions/material
coverage is not established by this sample. Two additional contract-targeted
snapshot probes independently mapped material (two candidates) and overall
dimensions (one candidate); they do not replace the original three samples.
This is transport/contract evidence,
not a customer-answer accuracy result or a production rollout.

### Local Review Candidate Check (2026-09-07)

The single authorized historical-order dimensions check through isolated 5023
returned HTTP 200, four selected evidence records, and a supported dimensions
claim using `overall_dimensions`. The candidate still failed semantic audit:
it requested available-space dimensions instead of answering the product-size
question. Runtime `model_first_answer_composer=false` skipped the existing
Composer; the recorded generation mode was `rule_based`. Next ownership check
is the isolated candidate launch configuration and existing generation path.
The response retained `can_send=false` and `requires_human_review=true`.
No additional model request was run. This one-case diagnostic does not qualify
answer quality or establish real customer accuracy.

The isolated launcher was subsequently corrected to enable the existing
review-only Composer together with convergence and query-only knowledge access.
Two launcher tests passed; restarted 5023 reported ready, Composer enabled, and
no source drift. Offline construction of `ComposerDecisionInput` from the saved
snapshot succeeded without a model call. Post-configuration generated reply
quality remains unverified; the earlier one-request authorization was consumed.

Follow-up verification found one renderable customer goal in the saved
dimensions observation, with no provider-material error. Existing Composer,
Pipeline entrypoint, and ReplyService regression tests passed (273 cases).
The stopped local 5175 frontend was restored; its page returned HTTP 200 and
its proxied runtime reported Composer enabled with no source drift. These
offline and routing checks do not substitute for a generated-reply evaluation.

One generated review-only rerun then confirmed the Composer used one admitted
fact, passed final audit, and retained human review, but the provider returned
an overly terse 13-character fact-only reply. Prompt and provider-input hashes
had changed from the prior run while the provider completion hash had not, so
the final pipeline did not overwrite the candidate. The Composer contract now
requires a brief, fact-neutral natural closure after a directly supported
answer; local Composer, Pipeline, and ReplyService regressions passed. The
updated contract was subsequently corrected: a complete answer may explicitly
return an empty closure rather than repeat itself; copied closures are rejected,
not removed by a second reply formatter. One native product-only check now
passes both Final audits and the scoped no-send/read-only diagnostic. This is
not production or real-conversation qualification. See the current
architecture overview and root execution index for the remaining gates.

- `docs/PROJECT_CHARTER.md` - authoritative business direction and non-negotiable boundaries.
- `docs/architecture-overview.md` - authoritative current/target architecture,
  thin-LangGraph boundary, context-first reasoning model, and convergence order.
- `docs/agent-core-priority-plan.md` - operational priority authority for the
  gold-service Agent Core, including the active priority, protocol-work budget,
  promotion gates, domain portability, and required task header.
- `docs/gold-customer-service-delivery-plan.md` - authoritative execution
  sequence for the Gold Customer Service Agent, including dynamic-truth source
  policy, P0-P7 gates, and the active P1 work queue.
- `docs/project-execution-ledger.md` - current task ledger, stage gates, blockers, and immediate execution queue.
- `PROJECT_INDEX.md` - root execution entry point, current gate, and required
  documentation sequence.
- `ROADMAP.md` - active task record, phase status, blockers, and immediate
  implementation queue.
- `docs/testing-and-acceptance.md` - reproducible regression, development
  loopback, API smoke, and P1 E2 evaluation procedures.
- `docs/p1-multigoal-completion-boundary.md` - verified P1 multi-goal result,
  frozen-owner boundary, and the required P3/P4 reauthorization for
  customer-visible completion steps.
- `docs/p1-e2-long-conversation-evaluation-plan.md` - privacy-safe, review-only
  P1 E2 evaluation of multi-turn quality on the existing formal Pipeline.
- `docs/p1-high-frequency-synthetic-dialogues.md` - fictional five-turn P1
  dialogue fixture, review-only preview, and loopback formal-baseline contract;
  it is synthetic regression evidence, not a real-customer accuracy claim.
- `docs/CHANGELOG.md` - dated implementation and verification record.
- `docs/module-index.md` - module ownership and status (`formal`, `shadow`, `legacy`, or `planned`).
- `docs/agent-core-candidate-change-ownership.md` - P0-R0 ownership and
  disposition manifest for the 45-file feature-disabled Agent Core checkpoint,
  plus the P1.2k.6i 25-file disabled bounded-inference/Audit checkpoint
  addendum.
- `docs/superpowers/specs/2026-08-10-conversation-reconstructed-fixed8-design.md`
  - 已批准的八案例 P1 对话重建工程基线设计；来源可追溯，但不得宣称真实客户
    准确率，也不能替代尚未恢复的原始 Fixed-8 资产。
- `docs/superpowers/plans/2026-08-10-conversation-reconstructed-fixed8.md`
  - 上述重建基线的 TDD 实施计划，限定数据合同、标签隔离、原生 Pipeline
    运行、回归验证和恢复检查点。
  - 当前实现已完成版本化 8 条/40 回合 fixture、独立 manifest、不可变
    `DatasetContract`、评测字段隔离、query-only 快照及干净提交 `52a7e1b` 的
    原生 `1×1 -> 8×1`。该运行只形成重建工程基线，真实准确率和生产资格仍为空。
  - 后续 `bd1af55` 修复了可选 unmapped semantic hint 清空多目标回合的确定性
    断点；专项与相邻回归通过，但修复后的原生案例尚未执行，质量结论保持未验证。
- `docs/superpowers/specs/2026-08-11-reconstructed-fixed8-native-5013-design.md`
  - 定义重建 Fixed-8 在当前源码 5013 上的原生 `1×1 -> 8×1` 运行合同、
    query-only/review-only 边界、基础设施失败与业务质量失败分离，以及继续保持
    `real_customer_accuracy=null` 的报告要求。
- `docs/superpowers/plans/2026-08-11-reconstructed-fixed8-native-5013.md`
  - 固化当前源码 5013 的快照准备、运行身份、`1×1 -> 8×1` 分层门槛、
    报告复算、安全回归和恢复检查点。
  - 当前隔离 query-only 重跑已完成 `8/8`，但只形成重建工程诊断：正式知识
    DML 为 0、`can_send=0`、全部人工复核。`da4a0ad` 已验证商品整体宽高的
    直接证据绑定 `2/2`；下一 Owner 是 `multi-goal_completion`，真实准确率和
    生产资格仍未证明。
- `docs/superpowers/plans/2026-08-12-knowledge-snapshot-recovery-audit.md`
  - Read-only verification of historical SQLite knowledge snapshots. It reports
    schema, identity, review, media, and potential-sensitive-field diagnostics
    without exposing content or permitting direct formal-database replacement.
- `docs/superpowers/plans/2026-08-12-knowledge-snapshot-recovery-candidate.md`
  - TDD plan for turning only exact-identity historical published product facts
    into an isolated current-schema candidate database. Candidate rows require
    fresh review and cannot become formal evidence, runtime retrieval, or send
    authority without a separate governed acceptance path.
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
  the active mainline, defines outcome-based promotion metrics, and records the
  default-off request-risk/answer-strategy boundary and goal-scoped Composer
  option-reference plus tri-state selection-completeness contract for bounded
  inference.
- `docs/adr/0010-product-hub-reviewed-fact-read-bridge.md` - defines the
  default-off, exact-identity, read-only Product Hub facts source and separate
  review-only media projection inside the existing Product Context Pack;
  neither changes formal admission or delivery ownership.
- `docs/adr/0011-tmall-order-identity-read-boundary.md` - defines the exact
  JST identity boundary for Tmall external order references and the
  default-disabled, session-bound read adapter option; it does not add a
  second Agent flow or delivery authority.
- `docs/research/product-hub-agent-read-api.md` - records the existing Product
  Hub natural-key Agent API, its release-contract requirement, and the bounded
  Copilot read integration.
- `docs/superpowers/plans/2026-08-29-product-hub-reviewed-fact-bridge.md` -
  implementation and verification plan for the default-off reviewed Product Hub
  fact reader; it preserves the existing Product Context Pack and admission
  ownership boundary.
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
The native P1.4 fixed-eight gate on clean commit `0c301046` completed `8/8` but
expert review still found three failed replies. After the Turn Understanding
role, attribute, and policy-family correction qualified `15/15`, a fresh native
gate on `7096269d` again completed `8/8` without transport interception.
Composer acceptance improved from `6/8` to `7/8`; formal knowledge and DML were
unchanged, `can_send=true` stayed zero, and all eight results remained review-
only. Expert review moved from `2 pass / 3 partial / 3 fail` to
`2 pass / 6 partial / 0 fail`. Pipeline p50/p95 were `45.958s/96.480s`, so
latency regressed and bulk-seat readiness remains blocked.

The remaining bathroom-moisture gap exposed one incomplete data binding: an
exact trusted policy family could be derived while its only non-empty intent
kind remained absent, causing Claim Resolution to reject the option. The owner
projection now derives that kind only when every trusted candidate in the exact
family agrees on one value; ambiguous families remain empty and fail closed.
The frozen five-run moisture qualification passed `5/5` with no retry, repair,
or fallback. A fresh full native gate is still required. None of these results
enable the disabled features or establish real-customer accuracy.
The next oral-exposure component keeps toxicity and ingestion safety unresolved
while allowing only goal-owned, review-only risk handling with no factual
premise. Oral-safety-only and material-plus-oral-safety cases passed the full
Composer, Deterministic Final, and Unified Audit chain `3/3` each; formal
knowledge, DML, and send authority remained unchanged. This is still a
component result, and the next gate is one fresh native Fixed-8.
That gate ran once on clean commit `1ed24db5`: Composer, Deterministic Final,
Unified Audit, and Delivery completed `8/8`, both oral-exposure cases passed
expert review, formal knowledge/DML/send changes stayed zero, and Pipeline
p50/p95 were `26.256s/36.480s`. Expert review was `2 pass / 4 partial / 0 fail /
2 not scorable`.

The following P1 qualification closed the missing contract projection but did
not qualify the current models. Unified Textual Audit v3 receives every
`required_qualifier` and `prohibited_extension` in separate Audit dimensions;
Composer also states the general epistemic rule that missing direct evidence is
not a negative fact. Deterministic and adjacent tests passed, but local Qwen
models that obeyed the strict schema still accepted the unsupported product
test-status claim, thinking-mode strict channels were unavailable, MiniMax-M3
did not complete the unsafe qualification, and DeepSeek V4 Pro passed the safe
half `5/5` then accepted the first unsafe counterexample under the v4 contract.
A current Composer-only run later qualified DeepSeek V4 Flash `5/5` on the
current transport. The following native Fixed-8 on clean commit `451be614`
completed execution, Composer, and Deterministic Final `8/8`; Unified Audit
remained explicitly unqualified with zero calls, all eight results stayed
human-review-only, formal knowledge/DML/send changes were zero, and Pipeline
p50/p95 were `10.688s/11.925s`. Expert review was
`3 pass / 3 partial / 1 fail / 1 not scorable`. The earliest repeated business
gap is now Turn Understanding atomic-goal completeness and canonicalization,
including a lost context-carried material goal and a collapsed gross-weight/
load-capacity comparison. P1 does not need another graph or validator layer.
The recovered P1.4i checkpoint keeps this work inside the existing Pipeline:
its optional HMAC-addressed open-goal projection is default-disabled, sends
only opaque typed aliases to the existing semantic call, and cannot change
evidence, reply ownership, delivery, or `can_send`. The explicit DeepSeek V4
Flash Composer role now requalified `5/5` on the recovered source with one
call per attempt, no retry/repair/fallback, zero knowledge DML, and no send
authority. A fresh blind Fixed-8 remains required before any P1 quality claim,
but its exact versioned dataset, manifest, query-only snapshot, and runtime
binding must first be restored; no replacement synthetic fixture may stand in.
P1 separates a deterministic-Final-protected,
review-only Supervisor Assist baseline from Autonomous Send: an unqualified
independent Audit remains advisory quality evidence for the former, while the
latter still requires Audit, real-accuracy, Safety, and Delivery qualification.
`real_customer_accuracy=null` and production readiness remain unproved.
The canonical answer-eligibility projection is diagnostic only, and Fast Path
remains disabled. The priority plan is mandatory: work outside its current
active stage is frozen unless a documented production/security exception or an
explicit plan update applies.

The current reconstructed Fixed-8 follow-up is a native, query-only diagnostic
run on a clean candidate source. It verifies that model-facing FactType choices
deduplicate the existing material aliases to `material_composition` before the
semantic call. The run completed `8/8` with Composer and Deterministic Final
`8/8`, direct attribution `3/3`, unresolved declaration `13/13`, formal
knowledge DML `0`, `can_send=0`, and human review `8/8`. The fresh v2 run also
has eight nonempty customer-visible replies, selected evidence `9` across four
cases, direct attribution `3/3`, unresolved declaration `13/13`, and canonical
goal recall `3/18`. Codex offline review keeps `multi-goal_completion` as the
next owner because unresolved service/install goals remain generic and one
everyday-use explanation was not policy-bound. The evaluation-only v2 comparison
reuses existing material and overall-dimension aliases; the raw v1 value is not
comparable. The P1 finalizer now preserves its checkpoint nonempty-reply count
when rebuilding a report, which is evaluation-only and cannot change customer
replies or delivery. This remains
engineering evidence only: `real_customer_accuracy=null`,
`optimization_unverified=true`, and `original_fixed8_restored=false`.

## Architecture Decisions And Research

- `docs/research/qianniu-desktop-adapter-selection.md` - 2026-09-09 primary-source
  comparison of desktop adapter libraries, license constraints, existing UIA
  reuse limits, and read-only qualification. After the user enabled accessibility
  and restarted QianNiu, one current-conversation probe read 18 timestamped
  headings, two order references and a separate product code. Panel loading and
  viewport scope remain explicit gaps. An owner-approved, local structured
  preview contract now reuses canonical turns and retains unverified candidates;
  its opt-in stdin mode prints counts only and never posts. Manual capture and
  a default-off loopback preview/confirmation button now have deterministic and
  frontend coverage. Final native qualification is blocked by missing active
  buyer/shop selection; unbound order references are omitted. The earlier weaker
  18-turn preview is superseded; new-message detection and delivery are unchanged.
- `docs/adr/README.md` - ADR rules and required format.
- `docs/adr/0001-unified-analysis-pipeline.md` - accepted decision establishing
  one formal AnalysisPipeline before any service decomposition.
- `docs/research/mature-customer-service-systems.md` - official-source comparison of mature routing, handoff, task, AI, and self-hosted control-plane patterns.
- `docs/research/customer-experience-and-controlled-recommendation.md` -
  mature-system findings and the proposed emotion, handoff, and
  evidence-grounded recommendation contract; it does not authorize runtime
  behavior before the stated phase gates.
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
  contracts, including five-run role-isolated Composer and Unified Audit qualification
  for approved or tenant/BYOK configurations.
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
