# Architecture Overview

## Status

Current architecture source of truth as of 2026-07-13. Historical status and
delivery reports remain evidence of past work, not current completion claims.

## Current System

```text
Flask API and local UI entry points
-> AnalysisPipelineService
-> AnalysisExecutionService
-> LangGraph customer-service graph
-> product identity, tools, SQLite RAG, evidence and generation nodes
-> media delivery blocks -> no-evidence policy and final safety/polish layers
-> optional shadow diagnostics -> final response, trace, replay, benchmark, and review tooling
```

Reusable capabilities already exist for product identity, JST lookup, structured
product context, evidence filtering, media governance, replay, benchmark,
bad-case review, Answer Memory, embedding, and pgvector shadow retrieval.

The formal path is currently stronger at retrieval, deterministic rendering,
and safety blocking than at evidence composition. Product-fact and exact-FAQ
modes primarily render selected evidence before the current LLM composition
branch. Product media carry roles and delivery metadata, but they are not yet a
reviewed visual-observation source that can support query-time reasoning. See
`docs/research/multimodal-grounded-customer-service.md`.

Candidate observations now have an ADR 0002 staging lifecycle with immutable
model provenance, supervisor review, hash invalidation, and append-only audit
events. `approved_shadow` remains isolated from Product Evidence Pack,
Grounded Reasoning, and customer delivery until future promotion acceptance.

ADR 0003 adds a separate v3 object-binding contract for product-media
understanding. It distinguishes the product from packaging, components,
accessories, included items, and display props before a measurement can be
interpreted. The graph is a shadow diagnostic only; it cannot alter formal
evidence, replies, delivery, or `can_send`.

Phase 0.4H.1 adds a local external-authoring pilot for twenty source-byte
verified media tasks. It uses human rectangle/relation annotation and a
read-only export validator only. Generic visual providers remain unqualified
for semantic scope grounding, OCR remains a text-box candidate, and no model
training or annotation promotion is part of the formal evidence path.

Phase 0.5A adds a post-graph Evidence-First LLM Decision Loop shadow. One
deterministic admission service separates direct product facts, direct policy
facts, service actions, and media candidates before a strict-schema proposal
can cite them. Compound claims remain independently unresolved when their own
eligible evidence is missing. The application executes only the eligible local
read-only portion of the shadow tool plan before admission; unsupported order
or media capabilities are explicitly deferred. The formal graph still owns
formal tool execution, and the proposal cannot alter replies, delivery, review
status, or `can_send`.

## Target System

```text
platform adapters
-> canonical ConversationEvent
-> durable event or work queue
-> one AnalysisPipeline
-> identity -> tools -> retrieval -> evidence gate
-> bounded reasoning -> one final safety and delivery gate
-> canonical AgentDecision
-> outbound adapter or durable HandoffTask
-> supervisor control plane and audit stream
```

See `docs/omnichannel-control-plane.md` for platform and handoff contracts.

## Authoritative Boundaries

- The formal answer path is `AnalysisPipelineService`, shared by `/api/analyze`,
  `/api/copilot/context`, replay, and benchmark.
- Product facts require product-scoped eligible evidence.
- A semantic fallback may ask to verify product information, but it must not
  describe retrieval keyword hits or unqualified summaries as evidence already
  available for the current product.
- Service actions are fallback handling guidance, not product facts.
- Media references are candidates; actual sending requires approved role,
  supported platform capability, matching product identity, and matching reply
  blocks. Final customer wording must name only the media types actually
  attached to those blocks.
- Installation safety prescriptions such as wall fixing, anti-tip measures,
  expansion screws, structural modification, or stability/load guarantees need
  direct reviewed installation evidence for the current product. A generic
  installation image or catalog recommendation is not sufficient support.
- Answer Memory is action/style reference only.
- pgvector and Grounded Reasoning remain shadow until their promotion contracts
  pass replay and safety acceptance.
- The final delivered response is the object that must be persisted and traced.

## Confirmed Architecture Gaps

### P0: Pipeline And Trace Consistency

- Phase 0.2 moves graph execution, media delivery, final orchestration, shadow
  diagnostics, and final persistence behind one formal AnalysisPipeline for all
  four entry points.
- Phase 0.1 establishes the persistence contract inside
  `AnalysisExecutionService`: when it executes final orchestration, SQLite
  snapshots, file snapshots, trace outcomes, and the returned response share
  one `final_response_contract`. Non-final and error paths are explicitly
  labelled `graph_result`, `pre_final`, or `error` instead of being presented as
  delivered output.
- Routes now retain only canonical input construction, authorization/HTTP work,
  metrics, and presentation. The Pipeline performs delivery and final stages
  before Phase 0.1 persistence runs.
- Phase 0.2.1 removes post-persistence Pipeline retries. A post-processor or
  final-orchestration failure returns and persists one review-only `pre_final`
  decision with delivery auto-send disabled; it cannot produce a newer reply
  after the trace or snapshot has been saved.
- Pipeline runtime stages are observed from the response itself. Final
  persistence is owned and observed by `AnalysisExecutionService`, not claimed
  as a completed Pipeline runtime stage before persistence happens.
- Grounded Reasoning remains shadow-only. Phase 0.5A moves its product-fact
  eligibility checks to the shared read-only admission service; reviewed
  answers remain offline references and never reasoning facts.

### P1: Contract Fragmentation

- Fact-type, evidence eligibility, risk, and safety term groups are distributed
  across many modules instead of one versioned registry.
- Multiple guard, policy, audit, semantic, and polishing layers can rewrite the
  same reply, causing drift and robotic fallback language.
- Retriever configuration recognizes only the current SQLite backend; pgvector
  is not a formal retriever implementation yet.

### P1: Multimodal Evidence And Bounded Reasoning

- Text product questions with known product or order context can skip customer
  image VLM analysis, including questions where the image contains the missing
  structure or dimension evidence.
- Product media are classified by role but do not yet expose reviewed OCR,
  regions, layer counts, labelled dimensions, or other queryable observations.
- Formal product answers primarily render retrieved facts; the admitted-fact
  planner and segmented draft remain shadow-only.
- There is no formal claim contract separating direct observations, bounded
  derivations, general guidance, and high-risk facts or actions.
- Model-extracted media facts need an explicit staging and review workflow before
  they can enter published product knowledge.

### P1: Runtime And Data Boundaries

- `app.main` combines dependency construction, Flask application setup, routes,
  and resident background workers.
- SQLite stores operational, knowledge, evaluation, trace, and memory workloads,
  and schema changes use startup-time manual migration code.
- There is no durable platform/shop/account ownership model or production
  HandoffTask workflow.

### P2: Governance And Delivery

- CI, migration tooling, ADR history, and explicit module ownership are still
  incomplete.
- The Vue application and legacy server-rendered pages overlap.

## Convergence Order

1. Inventory legacy direct callers and compare their contracts before treating
   them as formal entry points.
2. Define a reviewed Product Media Observation contract and prove a shadow
   dimension/structure vertical slice without changing formal answers.
3. Correct Grounded Reasoning evidence admission and add a claim plan for direct
   observations, bounded derivations, guidance, and prohibited claims.
4. Establish canonical fact-type, evidence-role, risk, and delivery registries.
5. Define canonical conversation, Agent decision, and platform port schemas.
6. Add durable handoff tasks, assignment, SLA, acknowledgement, and audit.
7. Separate web and worker processes; adopt managed schema migrations and CI.
8. Promote retrieval/reasoning shadow modules only after acceptance gates pass.
9. Connect QianNiu, Pinduoduo, and JD through adapters without changing Agent
   domain logic.

Feature work that conflicts with this order requires an ADR.
