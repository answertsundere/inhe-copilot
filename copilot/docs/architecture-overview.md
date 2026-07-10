# Architecture Overview

## Status

Current architecture source of truth as of 2026-07-10. Historical status and
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
- Service actions are fallback handling guidance, not product facts.
- Media references are candidates; actual sending requires approved role,
  supported platform capability, and matching reply blocks.
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
- Grounded Reasoning trace currently risks treating reviewed answers or
  ineligible evidence as facts and must not be promoted.

### P1: Contract Fragmentation

- Fact-type, evidence eligibility, risk, and safety term groups are distributed
  across many modules instead of one versioned registry.
- Multiple guard, policy, audit, semantic, and polishing layers can rewrite the
  same reply, causing drift and robotic fallback language.
- Retriever configuration recognizes only the current SQLite backend; pgvector
  is not a formal retriever implementation yet.

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
2. Correct Grounded Reasoning evidence admission and evaluation inputs.
3. Establish canonical fact-type, evidence-role, risk, and delivery registries.
4. Define canonical conversation, Agent decision, and platform port schemas.
5. Add durable handoff tasks, assignment, SLA, acknowledgement, and audit.
6. Separate web and worker processes; adopt managed schema migrations and CI.
7. Promote retrieval/reasoning shadow modules only after acceptance gates pass.
8. Connect QianNiu, Pinduoduo, and JD through adapters without changing Agent
   domain logic.

Feature work that conflicts with this order requires an ADR.
