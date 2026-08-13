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
- Current gate: `P1-E2-001`, an authorized, deidentified, review-only
  long-conversation evaluation through the existing formal `/api/analyze`
  pipeline.
- Delivery boundary: Supervisor Assist only. Every candidate remains
  `requires_human_review=true` and `can_send=false`.
- Dynamic truth boundary: volatile product, price, stock, promotion, order,
  logistics, policy, and service-outcome facts are resolved from approved
  current sources at answer time. They are never hardcoded into tests or
  prompts.
- Accuracy status: `real_customer_accuracy=null` and
  `optimization_unverified=true` until the authorized E2 data and independent
  reviews are complete.

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

The repeatable `scripts/run_p1_isolated_smoke.py` check has passed with an
explicit query-only knowledge snapshot and a loopback model. It verifies
readiness, no-send, human review, and nonempty review drafts without retaining
reply content in its report. It is still regression and operability evidence,
not real customer accuracy. E2 evaluation may start only when a data owner
supplies the authorized, deidentified review package outside this repository
and the existing validator accepts it.
