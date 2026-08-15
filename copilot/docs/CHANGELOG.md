# Change Log

## 2026-08-15 - Canonical Goal Routing And Synthetic Gate Integrity

- Formal synthetic observations now distinguish Composer-owned replies from
  accepted non-applicable media/service no-ops without hiding either result.
- Safe media requests survive provider fact misclassification only after fact
  and policy authority are removed. Provenance-valid current-turn customer
  goals can enter the existing evidence path when legacy intent is `general`;
  invalid and non-factual goals cannot.
- The fixed price-validation single case passed the complete review-only path.
  The fresh fixed-40 run then stopped at row 1 on an invalid provider enum, so
  provider stability and conversation quality remain unqualified.
- The versioned synthetic safety regression passed `5/5` and `22/22` against
  an explicit readiness-qualified, query-only knowledge snapshot. All 22
  scenarios remained review-only and none became sendable. An empty snapshot
  was rejected as an input/context gap rather than scored as reply quality.
- No Graph node, service, model call, reply owner, knowledge write, delivery
  authority, or `can_send` condition was added.

## 2026-08-13 - Repeatable P1 Isolated Smoke

- Added `scripts/run_p1_isolated_smoke.py` and its contract tests for a
  loopback-only 5012 Supervisor Assist smoke check. The command requires an
  explicit read-only knowledge snapshot, starts and stops its child runtime,
  and reports response metadata rather than conversation or reply content.
- The runner rejects remote endpoints, fails closed for a non-ready runtime,
  nonempty low-risk draft failure, absent human review, or any automatic-send
  result. It leaves formal evidence convergence disabled and formal knowledge
  query-only.
- The real two-case execution with the local loopback model passed: readiness
  was true, both cases had review drafts and human review, and no case could
  send automatically. This is P1 regression/operability evidence only;
  `real_customer_accuracy` remains `null` and P1 E2 authorization remains
  blocked.

## 2026-08-13 - P1 Test Entry Verification

- Focused P1/API/workbench regression and `compileall` completed successfully.
- An isolated `127.0.0.1:5012` runtime started with formal knowledge query-only
  and formal evidence convergence disabled. Its health endpoint was reachable;
  a high-risk after-sales request retained `can_send=false` and required human
  review.
- Functional reply review did not pass and was not claimed: the isolated
  runtime lacked an LLM credential and reported `ready=false` because its
  knowledge entries, chunks, FAQ records, and management authentication were
  not configured. The test guide now stops before functional review under these
  conditions. The temporary server was stopped.
- No Agent behavior, product fact, evidence eligibility, knowledge content,
  delivery, handoff authority, or `can_send` behavior changed.

## 2026-08-13 - P1 Test And Acceptance Entry

- Added root `PROJECT_INDEX.md` and `ROADMAP.md` so every execution has a
  single operational entry point, active task, phase status, and blocker list.
- Added `docs/testing-and-acceptance.md` with focused regression, isolated
  development-loopback API smoke, and authorized E2 evaluation procedures.
- Updated `docs/index.md` and `docs/project-execution-ledger.md` to link the
  new operational documents and record `P1-E2-001-TEST-ENTRY`.
- This change does not alter Agent reasoning, product facts, evidence
  eligibility, knowledge writes, policy outcomes, delivery, handoff authority,
  human-review requirements, or `can_send`. The real E2 dataset gate remains
  blocked pending data-owner authorization and deidentified review material.

## 2026-08-13 - P1 Dimension Subject-Scope Contract Repair

- Updated the existing Turn Understanding owner so a canonical dimension goal
  takes its scope from an unambiguous exact source span when that span names
  packaging, the complete product, a component, an accessory, or an included
  item. Mixed spans remain unclassified by this rule.
- Added scope-conflict, mixed-span, and English word-boundary regression
  coverage. The rule does not retrieve evidence, create product facts, alter
  Composer wording, modify Final or Delivery, or change `can_send`.
- Verified 290 P1-focused tests across fact aliases, semantic fact typing,
  conversation-goal lifecycle, Claim Resolution, admitted answer context, and
  reconstructed P1 baseline contracts; `compileall` passed.
- Verified the existing `/api/analyze` path in an isolated temporary worktree
  with a query-only knowledge snapshot and loopback
  `Qwen/Qwen3-VL-8B-Instruct`. The packaging-plus-product dimensions scenario
  retained both scopes, did not apply the product dimension to packaging,
  kept `can_send=false`, required human review, and produced no formal
  knowledge DML. Report:
  `D:\桌面文件\客服\.codex-runtime\p1-multigoal-e1-20260813-r6-scope-one-case\scope_one_case_report.json`.
- A full reconstructed E1 candidate run subsequently completed; the focused
  diagnostic is not a real-customer accuracy claim; `real_customer_accuracy`
  remains `null` and `optimization_unverified=true`.

## 2026-08-13 - P1 Reconstructed E1 Scope Follow-Up

- Completed the full reconstructed `conversation-reconstructed-v1` E1 follow-up
  in isolated candidate runtime `r9`: execution and nonempty replies were
  `8/8`; dimension-scope attribution moved from `3/4` to `4/4`; and customer
  goal clause coverage remained `16/16`.
- Formal knowledge remained query-only and unchanged, with zero DML attempts;
  `can_send=true` remained zero and all eight candidates required human review.
- The r9 technical summary remains `awaiting_codex_expert_review`, records one
  unsupported high-risk case and eight advisory Unified-Audit failures, and is
  a dirty candidate reconstructed diagnostic only. It does not establish real
  customer accuracy, approve autonomous sending, or unblock P2-P7.
- Final local verification for this change: 304 focused P1 tests passed and
  `python -m compileall -q app tests` passed.

## 2026-08-13 - P1 Reconstructed E1 Offline Review

- Stored and validated a `p1-codex-expert-review/v1` artifact for every r9 case
  alias. It is explicitly not supervisor approval and does not update delivery
  authority.
- The review confirms the dimension scope repair and selects
  `multi-goal_completion` as the next P1 owner. Its actionable finding is that
  unresolved after-sales, installation, and multi-turn questions need a
  deterministic structured next action rather than a generic refusal or a
  premature policy outcome.
- No product fact, policy outcome, knowledge content, Composer, Unified Audit,
  Graph, Delivery, recommendation, emotion runtime, handoff authority, or
  `can_send` behavior changed.

## 2026-08-13 - P1 Multi-Goal Completion Boundary

- Verified through the existing formal Pipeline that the reviewed compound
  after-sales request preserves condition confirmation, outcome selection, and
  compensation assessment as three distinct unresolved `customer_goal` records.
  No refund, replacement, compensation, or other side effect was selected or
  executed.
- Recorded the actual customer-quality constraint: the frozen Composer contract
  may not invent a policy result, evidence checklist, or promised follow-up for
  an unresolved goal. This is not a missing-goal defect that P1 can safely
  repair without changing the approved owner boundary.
- Added `docs/p1-multigoal-completion-boundary.md` with the P1 limit and the
  required P3/P4 evidence, durable-handoff, and review contracts for a future
  customer-visible completion step. No runtime behavior changed.

## 2026-08-13 - P1 E2 Long-Conversation Evaluation Plan

- Registered `P1-E2-001` as the next review-only quality gate using authorized,
  deidentified long conversations through the existing formal Pipeline.
- The plan evaluates atomic goals, context continuity, factual restraint,
  unresolved coverage, forbidden outcome claims, human review, and no-send
  safety. It does not import static product facts or preferred replies.
- No runtime code, product fact, live-tool connection, recommendation, emotion
  runtime, handoff authority, delivery behavior, or `can_send` behavior changed.

## 2026-08-13 - Gold Customer Service Execution Plan

- Added `docs/gold-customer-service-delivery-plan.md` as the phased P0-P7
  delivery plan for the evidence-grounded customer-service Agent.
- Added `docs/research/customer-experience-and-controlled-recommendation.md`
  to record the design contract for empathetic service, controlled
  recommendation, and durable handoff. It does not enable runtime behavior.
- Added `docs/project-execution-ledger.md` to track the active P1 task,
  evidence, blockers, gates, and immediate queue.
- Recorded that the available reconstructed eight-case assets are diagnostic
  only: files hash-validate, but missing raw projection source prevents an
  authoritative baseline reconstruction.
- Recorded that the formal P1 run remains blocked pending a configured formal
  provider identity and P1 HMAC. A loopback vLLM is pending separate synthetic
  Composer-role qualification.
- No customer reply, evidence eligibility, product fact, delivery behavior,
  handoff behavior, or `can_send` behavior changed.
- Verification pending: documentation link/integrity checks and the synthetic
  Composer-role qualification listed in the active execution ledger.
