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
- Current evidence checkpoint: Product Hub materializes explicit
  product/component dimension subjects as atomic scoped facts. A fully
  fictional isolated canary admitted product width/height/depth, excluded
  component axes, and produced a grounded width/height reply with no send
  authority. The current-source DeepSeek Composer qualification passed `25/25`;
  the subsequent reconstructed Fixed-8 completed `8/8`, selected evidence in
  only three scenarios, kept formal-knowledge DML at `0`, required review
  `8/8`, and kept `can_send=0`.
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

The fresh Fixed-8 is complete and moves the active P1 owner to
`formal_knowledge_tool_coverage`. Dimension and material facts were useful when
admitted, but installation, detachability, installation media, and after-sales
turns lacked a customer-visible fact or executable service action and fell back
to repeated uncertainty. The next change must trace those existing source and
tool paths into the canonical answer context before any wording work. Unified
Audit stays advisory for Supervisor Assist and mandatory for future Autonomous
Send qualification. This reconstructed baseline remains engineering evidence;
`real_customer_accuracy=null` and `optimization_unverified=true`.
