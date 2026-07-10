# Architecture Overview

## Status

Current architecture source of truth as of 2026-07-10. Historical status and
delivery reports remain evidence of past work, not current completion claims.

## Current System

```text
Flask API and local UI entry points
-> AnalysisExecutionService
-> LangGraph customer-service graph
-> product identity, tools, SQLite RAG, evidence and generation nodes
-> no-evidence policy and final safety/polish layers
-> response, trace, replay, benchmark, and review tooling
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

- The formal answer path is the single AnalysisPipeline that will be shared by
  `/api/analyze`, `/api/copilot/context`, replay, and benchmark.
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

- `/api/analyze`, `/api/copilot/context`, benchmark, and replay currently execute
  different media, final-orchestration, and shadow stages.
- `AnalysisExecutionService` builds a final response, while snapshot and trace
  persistence still receive the pre-final graph result.
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

1. Fix final response, trace, and snapshot consistency with regression tests.
2. Move media, final orchestration, Answer Memory shadow, and Grounded shadow
   behind one AnalysisPipeline used by every entry point.
3. Correct Grounded Reasoning evidence admission and evaluation inputs.
4. Establish canonical fact-type, evidence-role, risk, and delivery registries.
5. Define canonical conversation, Agent decision, and platform port schemas.
6. Add durable handoff tasks, assignment, SLA, acknowledgement, and audit.
7. Separate web and worker processes; adopt managed schema migrations and CI.
8. Promote retrieval/reasoning shadow modules only after acceptance gates pass.
9. Connect QianNiu, Pinduoduo, and JD through adapters without changing Agent
   domain logic.

Feature work that conflicts with this order requires an ADR.
