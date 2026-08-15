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
| Task ID | `P1-E2-001-ISOLATED-SMOKE` |
| Owner | Codex |
| Status | Repeatable isolated smoke complete; E2 remains blocked on authorized deidentified conversations |
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
- `P1-E2-001-ISOLATED-SMOKE` replaces manual environment assembly with
  `scripts/run_p1_isolated_smoke.py`. It allows only loopback endpoints,
  requires an explicit isolated SQLite snapshot, supplies the development
  loopback role only to its child process, starts and stops port 5012, and
  reports no input or reply text. Its successful two-case execution used an
  eligible query-only snapshot and a local loopback model: runtime readiness
  was true, both drafts were present, all candidates required human review,
  and `can_send=true` was zero. The result is a P1 safety/operability check,
  not a real-customer quality or promotion result.

## P1 Customer-Conditional Space-Fit Slice

- Frozen symptom: a customer supplied an available-space height and asked for
  the consequence of a separately stated product-height condition, but Turn
  Understanding classified the request as a measurement lookup and the
  no-evidence path asked for product identity again.
- Earliest corrected owner: the existing FactType semantic boundary. The
  model-visible candidate contract now distinguishes measurement values from
  fit conclusions without deterministic phrase matching.
- Customer-supplied quantities remain conversation context, not admitted
  evidence. The existing Composer may state only their direct conditional
  consequence and must preserve the unresolved actual-product boundary.
- Deterministic Final rejects `supported_fact` clauses with zero canonical
  evidence. Conditional unresolved clauses remain review-only with
  `can_send=false`.
- The next live-provider 1x1 located a second, earlier transport defect: Formal
  Evidence Convergence omitted the normalized history when calling the existing
  Minimal Decision Context service. The repair passes that history through the
  existing field-aware privacy projection and strips transport-only turn IDs;
  it does not promote customer statements to evidence.
- On the repaired current source, the Composer role qualified `5/5`. The frozen
  synthetic 1x1 retained all four prior turns, produced the direct conditional
  comparison, used zero selected formal evidence, kept the formal knowledge
  snapshot and DML unchanged, required human review, and kept `can_send=false`.
  This is a synthetic capability result only; `real_customer_accuracy=null`.
- The pinned legacy 26-case long-conversation asset is absent from the recovered
  workspace. Repository and external-runtime searches found only its contract
  references, not the versioned dataset or manifest. It remains blocked and
  must not be substituted with synthetic or reconstructed content.
- The first GLM-backed 40-case synthetic attempt stopped after 14 rows, but its
  evaluator omitted the fixture's structured product and order identity from
  `/api/analyze`. The attempt is therefore superseded for reply-quality use,
  although its zero-DML, review-only, and no-send observations remain valid.
  The evaluator now sends only the public API's four identity fields alongside
  canonical history; it sends no labels or expected answers. A corrected
  single-case logistics gate passed Final with history `4/4`, transport UID
  leakage `0`, formal DML `0`, and `can_send=false`. The full 40-case formal
  baseline is still incomplete and cannot support a quality or accuracy claim.
- The corrected four-case identity-sensitive gate passed `4/4`. The following
  fixed attempt reached `18/40` and then stopped fail-closed because one
  logistics/service turn projected history `0/4`. A diagnosis-only replay of
  that exact row projected `4/4`, so the failure is not yet a deterministic
  production-code reproduction and cannot justify a reply or routing patch.
  The stopped attempt had Final `18/18`, Composer use `14/18`, no-send `18/18`,
  formal DML `0`, and latency p50/p95 `8.913s/23.209s`. All 18 rows selected
  zero formal evidence because their `SYN-` identities are intentionally absent
  from the query-only snapshot. The next gate is fixed-input understanding and
  Composer-entry stability; rows 19-40 remain unexecuted.
- `P1-SYNTHETIC-STABILITY-001` moved the stability gate into the existing
  formal evaluator. One response now owns the checkpoint, summary, exact
  ordered-history comparison, Turn Understanding boundary, Composer entry,
  and Final result. Deterministic qualification passed `57/57`. The bounded
  live gate stopped on attempt `1/3`: Turn Understanding was invalid with
  earliest reason `canonical_claim_type_not_allowed`; Composer was correctly
  blocked, `can_send` remained false, human review remained required, and
  formal-knowledge DML remained zero. Attempts 2-3 and rows 19-40 were not run.

## P1 Synthetic Authoritative Goal Routing

- The formal evaluator now distinguishes a Composer-owned result from an
  accepted, contractually non-applicable media/service no-op. Both remain
  observable, but only the former counts as Composer ownership.
- Turn Understanding preserves a fact-misclassified media request only after
  clearing all fact and policy authority. Separately, the existing response
  strategy router recognizes a provenance-valid canonical customer goal even
  when the legacy intent is `general`, sending it through the existing Graph
  and Evidence Builder without keyword or scenario branches.
- The frozen price-validation single case passed with history `4/4`, one
  unresolved claim, one Composer clause, Deterministic Final passed,
  `can_send=false`, mandatory human review, and formal-knowledge DML `0`.
- A fresh fixed-40 attempt stopped at row 1 because GLM-4.5-Air emitted an
  invalid `claim_type_status`. Strict schema validation remained fail-closed;
  the run was not retried and no quality or accuracy result is claimed.
- Direct and related regression coverage passed `640` tests. The versioned
  synthetic benchmark passed `5/5` and `22/22` against a readiness-qualified
  query-only snapshot, with zero sendable replies and all scenarios requiring
  human review. Full-repository pytest retained the five pre-existing failures
  outside this change's ownership; no additional failure was introduced.
- `P1-COMPOSER-BOUNDARY-LANGUAGE-001` removed four legitimate negative-promise
  phrases from the shared internal-language redline. Internal evidence,
  review, knowledge-base, RAG, and Final-Gate terms remain blocked. The change
  resolves the reproducible row-10 promotion Composer rejection without
  weakening evidence, safety, media, service-action, or delivery contracts.
- GLM-4.7-Flash requalified for the Composer role `5/5` on the changed source,
  with no retry, repair, fallback, DML, or send-authority change. Its next
  fixed-40 attempt timed out at row 3 after 180 seconds, so the model is not a
  stable baseline Provider. GLM-4.6 was also not qualified because its first
  call returned a rate-limit error. No quality or accuracy result is claimed.
- `P1-COMPOSER-PROCESS-LANGUAGE-002` removed only the overbroad
  customer-visible phrase `帮您核对` from the Composer process-language redline.
  Generic future work, evidence, review, RAG, knowledge-base, and Final-Gate
  language remains blocked. The frozen information-request row then passed.
- DeepSeek V4 Flash requalified `5/5` and completed one fresh fixed-40 run:
  execution, Composer acceptance, and Deterministic Final were `40/40`; empty
  replies, DML, sendable replies, and duplicate replies were `0`; all 40 rows
  required human review. Pipeline latency p50/p95 was `5.658s/8.820s`.
- The completed set contained zero selected evidence, `32/40` generic
  inability-to-confirm replies, and an unsupported negative statement that no
  image/text instructions were available. It is a structure/safety diagnostic,
  not factual quality; `real_customer_accuracy=null` and
  `optimization_unverified=true` remain unchanged.
- A Composer-enabled DeepSeek safety smoke scored `0/5`; a separate default-off
  Composer smoke scored `3/5` and returned empty installation drafts. Both kept
  `can_send=false` and mandatory human review. Full `22` was not run after the
  failed smoke, and neither failure was patched with scenario wording.
- The scoped regression suite passed `555/555`, documentation governance and
  `py_compile` passed, and staged-diff checks were clean. Full-repository pytest
  retained the same five existing failures outside this change: odor-bridge
  FactType ownership, two reconstructed-fixture file hashes, partial-answer
  evaluator polarity, and the fast-path evaluator source hash.

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

1. `P1-NEGATIVE-ABSENCE-001` - Freeze the first unsupported negative-absence
   claim and identify whether Claim Resolution, Composer, Deterministic Final,
   or Unified Audit first loses the unresolved polarity.
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
