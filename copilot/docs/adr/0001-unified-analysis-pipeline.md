# ADR 0001: Unified Analysis Pipeline

Status: accepted

Date: 2026-07-10

## Context

`/api/analyze` and `/api/copilot/context` previously persisted a graph result,
then applied media selection, final orchestration, and shadow diagnostics in
their route handlers. Benchmark and real replay used a different direct path.
This made a benchmark or replay result unable to prove the behavior of a user
entry point, and could leave trace/snapshot data behind the delivered decision.

## Decision

Keep the project as a modular Flask monolith and introduce
`AnalysisPipelineService` as the sole formal execution path. Every formal entry
point builds a canonical request and runs these stages in order:

```text
canonical input -> graph execution -> media delivery -> final response
orchestration -> shadow diagnostics -> final persistence -> response
```

`AnalysisExecutionService` owns trace lifecycle and persistence. It accepts one
post-graph processor so `AnalysisPipelineService` can complete formal stages
before the final response contract is saved. Routes keep HTTP parsing,
authorization, canonical input construction, metrics, and presentation only.

Phase 0.2.1 clarifies failure ownership: the post-graph processor runs exactly
once before persistence. If it fails, the returned response, SQLite snapshot,
file snapshot, and trace outcome remain the same review-only `pre_final`
response. The pipeline must never retry a formal stage after persistence.

Answer Memory and Grounded Reasoning remain shadow-only. Platform capabilities
are passed as canonical options; no platform name is used inside Agent-domain
branching.

## Alternatives Considered

- Keep route-specific post-processing: rejected because it duplicates delivery
  and audit behavior and persists pre-delivery results.
- Put media and platform behavior directly into the LangGraph: rejected because
  delivery is an application boundary, not an Agent fact or reasoning concern.
- Split Pipeline into microservices, queues, or streaming infrastructure now:
  rejected because the current problem is stage ownership within one process,
  not independent deployment or throughput. It would add operational failure
  modes without repairing the duplicated contract first.

## Business And Safety Consequences

- A media reference is not treated as delivery unless an actual image/video
  reply block is built.
- Media selection happens before the final audit and delivery contract.
- Missing media, media errors, final-stage errors, and shadow errors are
  recorded as diagnostics and degrade safely rather than being silently hidden.
- A failed final stage forces `can_send=false`, clears `sendable_reply`, marks
  human review, disables delivery auto-send, and changes image/video blocks to
  manual reference blocks.
- Shadow services receive a copy of the decision. Attempts to modify formal
  reply, delivery, audit, or sendability fields are restored and recorded as a
  contract violation before persistence.
- The pipeline does not alter FactType, evidence eligibility, response policy,
  or the `can_send` standard.

## Migration And Rollback

The migration keeps `execute_analysis` available for legacy callers. The new
pipeline uses its post-graph hook, so rollback is limited to restoring the four
entry-point callers without changing stored schemas. No queue, database, or
platform API migration is introduced.

## Verification

- Entry-point contract tests compare the canonical AgentDecision across API,
  copilot, benchmark, and replay paths.
- Phase 0.1 tests verify final response persistence.
- The read-only entrypoint diagnostic reports whether each formal caller uses
  the pipeline and whether it retains route-level formal stages.
- Runtime stage observations come from `response.analysis_pipeline.stages`.
  `AnalysisExecutionService` remains the persistence owner, so the pipeline
  does not report final persistence as a completed runtime stage before the
  save actually occurs.
