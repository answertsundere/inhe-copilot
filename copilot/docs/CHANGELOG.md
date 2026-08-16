# Change Log

## 2026-08-16 - Unresolved Source-Faithfulness Boundary

- Traced the fixed-40 unsupported negative-absence reply to the existing
  Composer. An unresolved customer observation had been upgraded into an
  objective product-instruction absence claim despite zero admitted evidence.
- Added a per-goal statement contract for unresolved clauses: factual
  assertions require admitted evidence, customer observations require
  attribution, negative source facts are forbidden without evidence, and
  internal no-evidence state cannot become a customer-visible reason. No Graph,
  service, model call, reply owner, Final, Safety, Delivery, or send condition
  changed.
- DeepSeek V4 Flash requalified `5/5`. Final-source installation, logistics,
  and damage/packaging checks passed Composer and Deterministic Final `3/3`
  with mandatory human review, `can_send=0`, selected evidence `0`, and
  formal-knowledge DML `0`. This is a synthetic engineering result;
  business helpfulness and real accuracy remain unqualified.
- The versioned default-off smoke repeated `3/5`: after-sales `3/3`,
  installation `0/2`, mandatory human review `5/5`, and `can_send=0`.
  Full 22 was not run after the failed smoke.
- Scoped regression and docs governance passed `663/663`. Full pytest
  retained the same five known unrelated failures and introduced no new
  failure.

## 2026-08-16 - Product Fact Review Lifecycle Closure

- Closed a formal-knowledge governance bypass before the Agent path. Published
  products now return to `pending_review` whenever identity, SKU, structured
  facts, logistics, warranty, or reviewed policy binding actually changes.
  Equal updates remain published and do not create review churn.
- Product HTTP create/update, single publish, and batch lifecycle operations
  now use the existing repository lifecycle. Client payloads cannot create or
  generically update a product directly to `published`; only supervisor
  approval of a pending product can publish it, with the existing change log.
- Structured backfill now reports review-required transitions and removes
  changed products from Product Context Pack answer authority until approval.
  It records a lifecycle audit and keeps only an internal source SHA-256;
  legacy and current backfill metadata are excluded from model-facing specs.
  Recovered-source audit still found no safe material or product-dimension
  coverage to auto-promote, so no recovered fact was approved or published.
- Focused product lifecycle, context, authentication, Evidence Convergence,
  admitted-context, and docs regression passed `213/213`. Full pytest retained
  the same five unrelated failures and two skips across 4,568 collected tests.
  Synthetic smoke repeated the existing `3/5`, review-only, no-send baseline;
  full 22 was correctly not run. Agent replies, model calls, Graph, Delivery,
  formal knowledge content, and `can_send` did not change.

## 2026-08-16 - Recovery Product Identity Review Boundary

- Confirmed that the fixed-40 zero-evidence result comes from fictional
  `SYN-*` identities and an empty eligible-fact snapshot, while the existing
  positive Evidence Convergence path remains healthy.
- Extended the existing product-card importer to stage identity-only
  `KBProduct` drafts. Recovered card facts are not copied into product specs,
  logistics, or warranty, and published or manually managed products are not
  overwritten.
- An isolated copy staged 1,898 product drafts idempotently while all 2,593
  existing knowledge entries remained drafts; published records, chunks,
  formal knowledge DML, Agent behavior, and send authority did not change.
- Focused knowledge/evidence/safety/documentation regression passed `324/324`.
  The full repository retained its five known unrelated failures and two skips
  across 4,558 collected tests; no new failure was introduced by this slice.

## 2026-08-15 - Offered Customer Input Boundary

- The existing Composer may request new customer input only when an offered
  `request_customer_input` service action explicitly authorizes the matching
  input slots. A resolved product scope may not trigger another product-
  identity request. This is a prompt-level ownership clarification; no action,
  evidence, Graph, Final, Delivery, or send authority changed.
- DeepSeek V4 Flash requalified `5/5`. The frozen identity-sensitive case no
  longer asked for product or order information already present in the formal
  request. A fresh fixed-four and fixed-40 completed without execution errors;
  the fixed-40 had Composer acceptance and Deterministic Final `40/40`,
  `can_send=0`, mandatory human review `40/40`, and formal-knowledge DML `0`.
- The fixed-40 again selected zero formal evidence. It remains a synthetic
  unresolved/context diagnostic, not supported-fact quality or real accuracy;
  `real_customer_accuracy=null` and `optimization_unverified=true` remain.

## 2026-08-15 - Concrete Verification Guidance Boundary

- Corrected a Composer redline that rejected a concrete, customer-visible
  request for photos or location details solely because it contained
  `帮您核对`. Vague future-work, evidence, review, RAG, knowledge-base, and
  Final-Gate process language remains blocked.
- DeepSeek V4 Flash requalified `5/5` and completed one fixed-40 structural run
  with Composer and Deterministic Final `40/40`, no empty or duplicate replies,
  mandatory human review, `can_send=false`, and formal-knowledge DML `0`.
- The fixed-40 had zero selected evidence and exposed an unsupported negative
  absence claim. It is not a factual-quality or real-accuracy result.
- Composer-enabled and default-off Composer versioned smokes scored `0/5` and
  `3/5` respectively; full 22 was not run. The failures remain recorded and no
  scenario wording, rubric, safety gate, or send authority was changed.

## 2026-08-15 - Customer-Visible Promise Boundary Semantics

- Corrected a shared redline conflict that classified legitimate refusals of
  absolute promises as internal system language. Evidence, review,
  knowledge-base, RAG, and Final-Gate process terms remain blocked.
- GLM-4.7-Flash passed the changed-source Composer role gate `5/5`, and the
  frozen promotion regression passed with Final accepted, human review
  required, `can_send=false`, and formal-knowledge DML `0`.
- The following fixed-40 run stopped at row 3 on the existing 180-second
  timeout. GLM-4.6 was rate-limited on its first qualification call. Provider
  stability, synthetic conversation quality, and real accuracy remain
  unqualified.
- No Graph node, service, model call, reply owner, knowledge authority,
  delivery authority, or automatic-send condition was added.

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
