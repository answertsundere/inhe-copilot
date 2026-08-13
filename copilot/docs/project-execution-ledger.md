# Gold Customer Service Execution Ledger

## Purpose

This is the operational ledger for the INHE customer-service Copilot. It does
not replace `docs/index.md`, the Project Charter, the architecture overview,
or the active-priority contract. Before an implementation task, read those
sources first; after the task, record its real outcome, verification, blockers,
and next owner here and in `docs/CHANGELOG.md`.

## Current Execution

| Field | Value |
|---|---|
| Task ID | `P1-E2-001-TEST-ENTRY` |
| Owner | Codex |
| Status | Safety verification complete; functional smoke blocked on isolated runtime configuration and E2 remains blocked on authorized deidentified conversations |
| Active priority | P1 - Gold Conversation Quality |
| Customer outcome | Preserve every explicit buyer goal, use confirmed context, answer supported parts naturally, and expose only the unresolved remainder. |
| In-scope owners | Turn Understanding, canonical conversation-goal lifecycle, Claim Resolution, P1 runner, and their contract tests. |
| Frozen owners | Composer wording, Unified Audit, Graph expansion, Delivery, live product data, recommendation runtime, emotion runtime, and `can_send`. |
| User-facing entry points | The existing formal `AnalysisPipeline` and `/api/analyze`; no new entry point is introduced. |
| Delivery authority | Unchanged: Supervisor Assist only, `requires_human_review=true`, `can_send=false`. |
| Real-dataset gate | Blocked. `real_customer_accuracy=null`; `optimization_unverified=true`. |

## Current Evidence

- `P1-MULTIGOAL-001` repaired a deterministic scope-conflict path in the
  existing Turn Understanding owner. When the exact source span for a
  dimension goal unambiguously names packaging, the complete product, a
  component, an accessory, or an included item, the canonical goal uses that
  scope rather than a conflicting model declaration. Mixed source spans remain
  unmodified. This changes no fact, retrieval, Composer wording, Final,
  delivery, or `can_send` authority.
- The focused HTTP diagnostic uses the existing `/api/analyze` path with an
  isolated dirty candidate worktree, `Qwen/Qwen3-VL-8B-Instruct`, a query-only
  formal-knowledge snapshot, and the reconstructed
  `conversation-reconstructed-v1` dataset. Its packaging-plus-product
  dimension case retained both scopes, stated that packaging dimensions were
  unavailable, used the reviewed product-only dimension only for the product,
  kept `can_send=false`, required human review, and created no knowledge DML.
  Report: `D:\桌面文件\客服\.codex-runtime\p1-multigoal-e1-20260813-r6-scope-one-case\scope_one_case_report.json`.
  This is an owner-local safety/correctness check, not a real-customer
  accuracy result.
- The full reconstructed E1 candidate run completed `8/8` in the isolated
  `r9` worktree on the same loopback model and query-only snapshot. The scope
  metric increased from `3/4` in the prior r3 diagnostic to `4/4`; clause
  coverage remained `16/16`, no knowledge content changed, DML attempts were
  `0`, `can_send=true` remained `0`, and all eight candidates required human
  review. Its immutable technical summary remains
  `awaiting_codex_expert_review`; the separately stored offline review artifact
  has now passed the runner contract for all eight aliases, is not supervisor
  approval, and selects `multi-goal_completion` as the next owner. The review
  found the scope repair correct but identified mechanically worded and
  non-actionable handling for several unresolved multi-goal cases. The run
  reports one unsupported high-risk case and eight advisory Unified-Audit
  failures, and therefore does not qualify P1, real accuracy, Autonomous Send,
  or a downstream phase.
  Report: `D:\桌面文件\客服\.codex-runtime\p1-multigoal-e1-20260813-r9-scope-full\full-run\summary.json`.
- The reconstructed `conversation-reconstructed-v1` assets contain eight
  completed-case files with valid recorded hashes, but their raw projection
  source is absent. The offline assessment therefore returns
  `diagnostic_only_projection_source_missing`; it cannot be an authoritative or
  comparable baseline.
- There are no persistent provider credentials or P1 HMAC values in the
  repository. The r9 diagnostic used process-scoped approved secrets and an
  ephemeral HMAC; it did not persist either. The formal runner fails closed
  when those runtime prerequisites are absent.
- The loopback vLLM service reports `Qwen/Qwen3-VL-8B-Instruct` at
  `127.0.0.1:8001`. Its five-call synthetic, read-only Composer-role
  qualification completed successfully, but that qualification cannot enable a
  feature, alter customer replies, load formal knowledge, or change `can_send`.
- The current code and existing reconstructed diagnostic identify the earliest
  remaining quality owner as multi-goal completion. The known symptoms are
  generic handling for unresolved after-sales or installation goals, repeated
  known-context requests, and uneven naturalness. This is a diagnosis, not a
  license to change the Composer or delivery contract.
- `P1-MULTIGOAL-001F` verified that the compound after-sales case already
  preserves condition confirmation, outcome selection, and compensation
  assessment as three separate unresolved customer goals. It neither loses a
  goal nor executes a service action. The customer-visible weakness is instead
  the frozen Composer rule for unresolved goals: without an approved live
  policy/service source or durable handoff receipt, it cannot state a specific
  evidence checklist, policy result, or promised next action. The full boundary
  and reauthorization conditions are recorded in
  `docs/p1-multigoal-completion-boundary.md`.
- `P1-E2-001` is the next P1 gate. It evaluates goal completeness, context
  continuity, factual restraint, unresolved handling, and human-review safety
  using the existing formal Pipeline and an authorized deidentified long-
  conversation set. It neither imports static product facts nor grants send or
  action authority. The contract is recorded in
  `docs/p1-e2-long-conversation-evaluation-plan.md`.
- `P1-E2-001-TEST-ENTRY` creates no Agent behavior. It makes the existing
  regression, development-loopback, and E2 validation procedures discoverable
  from root `PROJECT_INDEX.md`, `ROADMAP.md`, and
  `docs/testing-and-acceptance.md`. Its completion requires focused regression,
  compilation, and an isolated API smoke check; it cannot remove the E2 data
  authorization gate.
- The isolated 5012 smoke check completed with formal knowledge query-only and
  formal evidence convergence disabled. Health was reachable, and the
  high-risk after-sales request kept `can_send=false` and required human review.
  The same runtime reported `ready=false` because its knowledge entries,
  chunks, and FAQ records were empty and management authentication was absent;
  it also had no LLM credential, so no functional reply was available for
  review. This is an environment readiness block, not a quality pass or a
  reason to weaken the no-send boundary. The temporary server was stopped.

## Phase Plan

| Phase | Outcome | Status | Entry / exit gate |
|---|---|---|---|
| P0 | Reproducible, observable, fail-closed core | Partially established | Runtime identity, rollback, trace, and no-send boundary remain required. |
| P1 | Gold conversation quality | Active | E0 contracts, a qualified same-pipeline E1 diagnostic, then approved E2 long-conversation review. |
| P2 | Dynamic live evidence | Planned | Starts only after P1 E2 and a source-of-truth ADR. |
| P3 | Evidence-grounded service resolution | Planned | Requires typed identity and live evidence contracts. |
| P4 | Supervisor Assist and durable handoff | Planned | A handoff becomes a task with SLA, acknowledgement, status, and audit. |
| P5 | Real evaluation and improvement | Planned | Approved privacy-safe real Gold labels and replay. |
| P6 | Omnichannel adapters | Planned | Same formal pipeline and independent delivery rollback per channel. |
| P7 | Bounded automation | Planned | Scoped E5 canary, kill switch, audit, and product-owner approval. |

## Immediate Queue

1. Configure a 5012-only query-only runtime with approved knowledge,
   authentication, and ignored provider credentials; repeat functional API
   smoke without changing production 5011.
2. `P1-E2-001A` - Obtain data-owner authorization and create a deidentified,
   versioned, hashed long-conversation manifest. Keep raw content, direct
   identifiers, and label answers outside the repository and Agent prompt.
3. `P1-E2-001B` - Run the existing formal Pipeline with a query-only snapshot
   and review-only delivery. Compare only equivalent runtimes and preserve
   `can_send=false`.
4. `P1-E2-001C` - Independently review goal coverage, continuity, factual
   restraint, unresolved handling, and handoff necessity. Record failures by
   owner without modifying frozen owners.
5. `P2-LIVE-EVIDENCE-DESIGN` - After P1 acceptance, create the source-of-truth
   ADR and inventory read-only JST/platform authorities. Volatile product,
   price, promotion, order, and stock facts must be read at answer time.
6. `P3-P4-CX-CONTRACT` - After P1/P2 gates, obtain an ADR for typed current
   policy/service evidence, durable handoff receipts, non-factual action
   guidance, emotion-aware service strategy, and controlled recommendation.
   recommendation, and durable handoff only after P2/P4 prerequisites. The
   design is documented in
   `docs/research/customer-experience-and-controlled-recommendation.md`.

## Non-Negotiable Customer Experience Rules

- Solve the buyer's primary problem before considering a recommendation.
- Empathy is an interaction signal, never a diagnosis, product fact, or
  eligibility decision.
- A recommendation needs exact current identity, customer-visible live catalog
  evidence, active eligibility, and evidence-backed rationale. It is suppressed
  for complaints, risk, human requests, ambiguity, stale data, or opt-out.
- Never infer a child's age, health, development, budget, or product suitability
  from tone, history, or a broad category.
- A promised refund, replacement, compensation, escalation, or follow-up needs
  a typed completion receipt or a durable task. A sentence alone is not an
  action.

## Reporting Rule

All P1 reports state the runtime source hash, provider/model identity, enabled
flags, dataset identity, scorable/excluded counts, safety and handoff behavior,
latency, `can_send`, and delivery outcome. Until approved real labels exist,
reports must retain `real_customer_accuracy=null` and
`optimization_unverified=true`.
