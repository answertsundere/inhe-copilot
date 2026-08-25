# Project Execution Index

This is the operational entry point for the INHE customer-service Copilot.
It complements the architecture documentation index at `docs/index.md`; it
does not replace the Project Charter, architecture, or the active-priority
contract.

## Required Reading Before Every Change

1. Parent workspace `AGENTS.md` and project `AGENTS.md`.
2. This file and `ROADMAP.md`.
3. `docs/index.md`, `docs/PROJECT_CHARTER.md`,
   `docs/architecture-overview.md`, and `docs/agent-core-priority-plan.md`.
4. The documents and tests for the owner being changed.

Before implementation, register the task and its gate in `ROADMAP.md`.
After implementation, update this index, `ROADMAP.md`, and
`docs/CHANGELOG.md` with actual verification and remaining risks.

## Current State

- Active priority: `P1 - Gold Conversation Quality`.
- Current gate: `P1 Gold Conversation Quality`, using the frozen reconstructed
  Fixed-8 to locate the earliest existing Owner for factual coverage,
  conversation continuity, and useful next actions. This is review-only
  development evidence, not real-customer accuracy.
- Delivery boundary: Supervisor Assist only. Every candidate remains
  `requires_human_review=true` and `can_send=false`.
- Attached-media boundary: an authoritative current-turn media request is
  retained as non-factual context, and the existing Composer must acknowledge
  it only when a validated image/video block is already present. The block is
  the sole delivery authority; no candidate or request grants a send promise.
- Dynamic truth boundary: volatile product, price, stock, promotion, order,
  logistics, policy, and service-outcome facts are resolved from approved
  current sources at answer time. They are never hardcoded into tests or
  prompts.
- Current evidence/action checkpoint: Product Hub continues to materialize
  explicit product/component dimensions as atomic scoped facts. Its isolated
  source commit `bf6df88` now also turns only approved/live assets carrying the
  exact `安装说明` registry label and a non-empty note into one deterministic,
  provenance-preserving product-level installation fact. An isolated source
  snapshot produced 57 installation facts from 168 eligible assets across 57
  products; the source database remained unchanged. Copilot's existing
  read-only path then carried one such fact through Product Context Pack,
  Product-first answerability, Admitted Answer Context, and Claim Resolution as
  a supported installation claim. Media remained a separate non-factual role.
  The after-sales funnel separately preserves its existing planner-owned input
  action. Neither change grants send authority or changes `can_send`.
- Accuracy status: `real_customer_accuracy=null` and
  `optimization_unverified=true` until the authorized E2 data and independent
  reviews are complete.
- Strict Turn Understanding status: the default-off role and fictional
  qualification v3 harness exist. DeepSeek V4 Pro passed the fixed `8x3`
  Provider matrix at `24/24` after owner-correct source/semantic stability
  normalization; isolated `1x1` and `3x1` are still pending. DeepSeek remains
  separately qualified for Composer; no result changed formal replies or
  delivery.

## Active Documents

- `docs/project-execution-ledger.md` - current task, evidence, blockers, and
  immediate queue.
- `docs/p1-e2-long-conversation-evaluation-plan.md` - E2 data, isolation, and
  review contract.
- `docs/testing-and-acceptance.md` - developer, operator, API, and E2 test
  procedures.
- `docs/runtime-operation.md` - isolated runtime, readiness, and rollback
  procedure.
- `docs/agent-core-priority-plan.md` - active-owner and frozen-owner contract.

## Next Step

The upstream installation-fact break is closed in an isolated Product Hub
source branch and verified end to end against a candidate database. It is not
yet deployed to the formal Product Hub database. The next P1 step is a backed-up,
audited fact rebuild and query-only runtime verification before rerunning the
same quality gate. Detachability still has no formal source fact and must remain
unresolved; installation media remains governed by its separate delivery role.
Unified Audit stays advisory for Supervisor Assist and mandatory for future
Autonomous Send qualification.
This reconstructed baseline remains engineering evidence;
`real_customer_accuracy=null` and `optimization_unverified=true`.
