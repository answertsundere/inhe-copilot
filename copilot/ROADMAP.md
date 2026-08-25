# Delivery Roadmap

## Current Execution

| Field | Value |
|---|---|
| Task ID | `P1-EXPLICIT-MEDIA-REQUEST-CLOSURE-003` |
| Owner | Codex |
| Goal | Preserve an authoritative explicit media request and require a natural acknowledgement when the existing delivery path already attached the requested media. |
| Scope | Existing Admitted Answer Context, Composer response contract, role qualifier, direct tests, and existing documentation. No Graph node, service, extra model call, reply owner, Evidence role, or Delivery change. |
| Status | Engineering-qualified and verified in an isolated 5013 canary. Composer v8/response v5 selected the exact current attachment obligation while the unresolved fact stayed unresolved and every reply remained review-only. |
| Gate | A fully provenance-valid current-turn media request and an actual validated image/video block must coexist. The exact anonymous reference set is mandatory; missing, duplicate, unknown, detached, or untrusted refs fail closed. Candidate availability never authorizes future-send wording. Unified semantic judgment remains unavailable/advisory, so P1 and Autonomous Send are not qualified. |

## Phase Status

| Phase | Outcome | Status | Gate |
|---|---|---|---|
| P0 | Reproducible, observable, fail-closed core | Partially established | Existing runtime and regression contracts remain required. |
| P1 | Gold conversation quality | Active | Authorized E2 review must validate atomic goals, continuity, factual restraint, and human-review safety. |
| P2 | Dynamic live evidence | Planned | Starts after P1 E2 acceptance and a source-of-truth ADR. |
| P3 | Evidence-grounded service resolution | Planned | Requires typed current policy/service evidence. |
| P4 | Durable supervisor handoff | Planned | Requires durable task lifecycle, acknowledgement, SLA, and audit. |
| P5 | Real evaluation and improvement | Planned | Requires approved privacy-safe real labels and replay. |
| P6 | Omnichannel adapters | Planned | Requires formal-pipeline and delivery rollback parity. |
| P7 | Bounded automation | Planned | Requires scoped canary, kill switch, audit, and owner approval. |

## Current Blockers

1. `P1-E2-001` has data-owner authorization for the deidentified internal
   package, but cannot claim real quality until independent human labels and an
   evidence-enabled Supervisor Assist quality run exist.
2. The P1 frozen-owner boundary prevents inventing a policy outcome, product
   fact, compensation, refund, replacement, or promised completion step.
3. No test result may promote the current Supervisor Assist runtime to
   autonomous sending.
4. The completed synthetic fixed-40 selected zero formal evidence because its
   fictional `SYN-*` identities do not exist in the query-only knowledge
   snapshot. This is correct fail-closed behavior, not an Evidence Convergence
   failure, and it cannot establish factual accuracy.
5. The Composer-enabled versioned smoke scored `0/5`; the default-off Composer
   safety smoke scored `3/5` and left both installation replies empty. The full
   22-scenario run was correctly not started. These reports are retained as
   failures, not rewritten as passing safety or quality evidence.
6. The strict Turn Understanding fictional Provider matrix is qualified.
   Strict-role-only clause normalization and role-aware semantic signatures
   corrected two non-authoritative stability mismatches without changing the
   legacy path. DeepSeek V4 Pro then passed one fixed `8x3` at `24/24` across
   execution, schema, current-source, semantics, and semantic/source
   repeatability. The isolated clean-runtime sequence subsequently passed
   `1x1`, fixed `3x1`, and the authorized deidentified internal `20x1`, with
   strict understanding `20/20`, formal-knowledge DML `0`, and `can_send=0`.
   The role remains production-disabled: Formal Evidence Convergence was off,
   selected evidence was zero, and this gate does not establish reply quality
   or real accuracy.
7. The `P1-E2-001B` evidence preflight found an earlier input-contract gap.
   The authorized candidate contains 21 conversations but zero structured
   `sku`/`i_id`/`product_id`/order identities; its product and order context
   contains only evidence-required flags. The query-only snapshot is not empty:
   it contains 585 identified products, 1,743 published QA rows, and 7,889
   knowledge entries. Therefore an evidence-enabled rerun cannot safely bind
   these conversations to product truth. This is an input/Sidecar gap, not an
   Evidence Admission failure. Title or conversation-text matching is forbidden.
8. The source QA SQLite needed to reconstruct the exact Sidecar is not present
   in the current local database set or the NAS extracted-asset inventory. The
   candidate builder requires `chats`, `quality_scores`, and `chat_messages`;
   none of the available extracted databases has that schema. The NAS retains a
   full physical-drive image, but mounting or scanning that recovery image is a
   separate recovery responsibility and is not part of the Agent runtime task.

## Immediate Queue

1. `P1-FORMAL-KNOWLEDGE-REVIEW-002`: a query-only preflight confirmed 695/695
   color/weight drafts have one exact `i_id` binding, and a deterministic
   30-item local shortlist is ready with 20 color and 10 weight facts across
   30 products. Every shortlist row exactly reconstructs from the recovered
   product card and existing importer. An exact `i_id` cross-check against the
   read-only formal snapshot found 28 matching product identities, but only
   three matching color values and no provably independent source. A
   supervisor must still review each item through the existing
   lifecycle; do not bulk approve, infer missing material or dimensions, or
   use synthetic identities as truth.
2. `P1-E2-001B`: restore or independently review an exact structured identity
   Sidecar for the authorized conversations before any evidence-enabled run.
   The Sidecar must bind by durable source identity, remain outside Agent labels,
   and fail closed on missing or ambiguous mappings. Do not infer identity from
   titles or conversation text.
   The preferred recovery input is the original read-only QA SQLite with its
   existing alias key; otherwise a source-system supervisor must create the
   mapping from durable source records. Do not use the physical image directly
   from an Agent evaluation process.
3. `P1-E2-001B-RUN`: after the Sidecar preflight has nonzero exact coverage,
   run the evidence-enabled Supervisor Assist quality slice separately without
   changing production defaults. Report missing-identity and missing-fact cases
   as context gaps rather than silently evaluating them as zero evidence.
4. `P1-E2-001C`: independent reviewers record completeness, continuity,
   factual restraint, unresolved coverage, and handoff needs.
5. After P1 acceptance, create the P2 dynamic-evidence source-of-truth ADR.

## Completion Record

`P1-EXPLICIT-MEDIA-REQUEST-CLOSURE-003` completed its engineering gate on
2026-08-25:

- Closed the earliest canonical-context loss of a fully provenance-valid
  current-turn `media_request` without converting media into Evidence.
- Upgraded the existing Composer to response v5 so an actual attached media
  block requires exact anonymous request selection and current-attachment
  acknowledgement; candidate-only and future-send wording remain unauthorized.
- Composer role qualification passed `20/20`, p50/p95 about
  `2.737s/6.320s`, with one call per attempt and no retry/repair.
- The isolated same-product canary returned text plus one installation video,
  preserved the unresolved fact boundary, passed Deterministic Final, recorded
  formal DML `0`, and kept `can_send=false` with human review. Semantic judgment
  was unavailable, so no Gold-quality or real-accuracy claim is made.
- Versioned synthetic regression passed `5/5` and `22/22`; all 22 remained
  review-only and automatic sends were zero.

`P1-E2-001-TEST-ENTRY` completed on 2026-08-13:

- Focused P1/API/workbench regression passed with exit code `0`.
- `python -m compileall -q app tests scripts` passed with exit code `0`.
- Root-index and newly added document UTF-8 checks passed.
- An isolated 5012 runtime started with query-only knowledge and formal
  evidence convergence disabled. `/api/health` returned HTTP success;
  a high-risk after-sales request retained `can_send=false` and
  `requires_human_review=true`.
- Functional reply validation is blocked, not passed: no LLM credential is
  configured and readiness is `false` for the knowledge/auth reasons recorded
  above. The temporary 5012 server was stopped after the check.

`P1-E2-001-ISOLATED-SMOKE` completed on 2026-08-13:

- Added `scripts/run_p1_isolated_smoke.py`, which refuses non-loopback URLs,
  requires an explicit knowledge snapshot, starts and stops a 5012-only
  development process, and emits reply-free report metadata only.
- The checked runtime used an explicit query-only snapshot, development
  loopback admin role, local loopback model, and formal evidence convergence
  disabled. Health was `ready=true`; both scenarios returned review drafts,
  required human review, and had `can_send=true` count `0`.
- Script tests, related readiness/auth tests, and a real two-case 5012 run
  passed. This does not assess product facts, policies, real customers, or
  autonomous delivery.

`P1-COMPOSER-PROCESS-LANGUAGE-002` completed its engineering gate on
2026-08-15:

- A concrete request for photos or location details so the same reply can
  verify a relationship is no longer rejected solely because it contains the
  customer-visible phrase `帮您核对`. More specific internal/future-process
  expressions remain blocked.
- DeepSeek V4 Flash requalified `5/5`. One fixed-40 run completed all rows with
  40 accepted Composer results, 40 Deterministic Final passes, 40 mandatory
  human reviews, zero sendable replies, and zero formal-knowledge DML.
- The run selected no formal evidence and therefore cannot prove factual
  quality. The next owner is the unsupported negative-absence claim, not a new
  reply template or graph layer.

`P1-NEGATIVE-ABSENCE-001` completed its engineering gate on 2026-08-16:

- The frozen installation reply was traced to the existing Composer: an
  unresolved customer observation was converted into an objective statement
  that product instructions lacked a marking.
- Unresolved goals now carry a source-faithfulness statement contract. Product,
  order, document, and source assertions require admitted evidence; customer
  observations require attribution; missing evidence remains an internal
  assertion boundary and cannot be exposed as a customer-visible reason.
- DeepSeek V4 Flash requalified `5/5`. The frozen installation case plus
  logistics and damage/packaging adjacent cases passed Composer and
  Deterministic Final on clean commit `ab80c1c`, with `can_send=false`,
  mandatory human review, zero selected evidence, and formal-knowledge DML
  `0`.
- This closes the unsupported negative-absence defect only. The logistics
  mutation remains weak on concrete next-step guidance, so business
  helpfulness and service-action completion remain P1 review owners.
- The versioned default-off safety smoke repeated the existing `3/5`
  baseline: after-sales `3/3`, installation `0/2`, all five review-only and
  `can_send=0`. Full 22 was not run after the failed smoke.

`P1-TURN-UNDERSTANDING-PROVIDER-QUALIFICATION` stopped at its Provider gate on
2026-08-16:

- A default-off strict role and fictional eight-case qualification path reuse
  the existing Turn Understanding owner and validators.
- GLM candidates were rate-limited; DeepSeek V4 Flash passed `7/8`; DeepSeek V4
  Pro passed all `24/24` structural and semantic attempts but only `22/24`
  repeat stability.
- Qualification report v3 adds strict-role clause provenance normalization,
  role-aware semantic-key authority, and separate semantic/source stability;
  it retains no model output or field values and keeps the `100%` gate.
- DeepSeek V4 Pro passed one fixed `8x3` with every rate at `100%`, zero
  timeout/schema failure, zero formal-knowledge write, and zero send change.
- No 5013 or real-conversation gate has run yet. The Composer role remains
  independent.

`P1-DYNAMIC-PRODUCT-FACT-READ-001` completed its deterministic contract gate on
2026-08-17:

- The existing Product Context Pack opens a fresh database session per request;
  mutable published product facts are not copied into a second cache or held
  behind a manual re-verification queue.
- Structured product evidence now carries the source version, source update
  time, and a value-sensitive digest. A value change produces a new evidence
  UID, while deletion removes the direct fact on the next request.
- SKU-derived facts require an exact `sku_code`, `sku_id`, or
  `sku_variant_key` match. An unknown variant fails closed instead of borrowing
  another variant's value; a product-level query may still expose explicitly
  stored variant rows.
- Focused and adjacent deterministic tests passed, with zero new Graph nodes,
  services, model calls, writes, caches, reply owners, or send authority.
- This establishes current-value read semantics only. It does not approve
  recovered draft facts, qualify reply quality, or change
  `real_customer_accuracy=null` / review-only delivery.

`P1-DYNAMIC-ACTIVITY-RULE-READ-001` completed its deterministic contract gate
on 2026-08-17:

- The existing activity-rule owner continues to query active rows at request
  time. Expired rows disappear without a restart or cache invalidation.
- When structured product/SKU identity is available, every populated common
  namespace must match. A variant-scoped rule cannot be borrowed by another
  SKU, and a same-title rule cannot override an exact product identity.
- Activity evidence now binds its UID to the current content hash and carries
  source update time/value digest. Updating a rule therefore produces a new
  evidence identity on the next request.
- The change does not promote `active` to a reviewed Evidence Admission status,
  add a model/tool call, or alter Safety, Delivery, or `can_send`.

## 2026-08-25 Composer Language Boundary Checkpoint

- Fixed an existing Composer presentation gap where isolated lowercase schema
  labels could leak into otherwise Chinese replies. Customer/evidence terms and
  numeric units remain valid; unattributed internal labels are rejected and the
  Prompt requires natural-Chinese rendering.
- The comparable Product Hub Fixed-8 executed `8/8`, with Composer `7/8`,
  Deterministic Final `8/8`, goal clauses `14/14`, supported attribution `5/5`,
  unresolved declaration `9/9`, selected evidence `16`, formal DML `0`, human
  review `8/8`, and `can_send=0`.
- The remaining case is blocked before Composer by strict Turn Understanding
  current-source provenance. Exact diagnostic goal recall remains `3/16`; do
  not add another reply rule before resolving that owner boundary.
- Versioned synthetic safety regression passed smoke `5/5` and full `22/22`,
  all review-only. `real_customer_accuracy=null` and
  `optimization_unverified=true` remain authoritative.

## 2026-08-25 Turn Understanding And Dimension Admission Checkpoint

- DeepSeek V4 Flash passed strict Turn Understanding qualification v7
  `36/36` over twelve fictional cases repeated three times. The matrix now
  checks exact goal count/signatures, coexisting speech boundaries, and scoped
  aggregate dimensions.
- The Product Data Hub admission boundary now canonicalizes aggregate dimension
  labels but rejects concatenated values that are not one coherent two- or
  three-axis tuple. It does not split or guess multi-mode values.
- The comparable reconstructed Fixed-8 completed `8/8`: semantic goal recall
  moved `9/16 -> 12/16`, unexpected semantic goals `7 -> 4`, Composer and
  Deterministic Final passed `8/8`, selected evidence was `14`, formal DML was
  `0`, all eight required review, and `can_send=0`.
- The next true quality defect is unbound durability expansion at the existing
  bounded-reasoning/Composer-Audit boundary. Evaluator alias drift must be kept
  separate from production behavior.

## 2026-08-25 Required Service-Action Selection Checkpoint

- The Frozen Fixed-8 after-sales case already reached the existing
  `response_strategy_planner` with a typed `request_customer_input` action, but
  Composer treated the action as optional context and returned three generic
  unresolved clauses. Separately, legacy generation exposed an arbitrary SOP
  heading as `action_proposal`.
- Composer response v4 now gives only trusted, incomplete, non-factual
  customer-input actions a stable anonymous reference. The Provider must select
  every required reference exactly once and express it inside an existing goal
  clause; missing, duplicate, unknown, or untrusted references fail closed.
  This does not add a customer goal, evidence, Graph owner, model call, retry,
  repair, or send authority.
- The isolated after-sales replay now asks for one of the already-authorized
  order or tracking identifiers. The unchanged full Fixed-8 completed `8/8`
  Composer and Deterministic Final, retained 22 selected evidence rows, selected
  the one required service action only in the after-sales case, kept formal DML
  at `0`, required review `8/8`, and kept `can_send=0`.
- Unified Audit remained unavailable/advisory in all eight cases, so Autonomous
  Send stays blocked. Raw goal-identity recall remains `9/16`; the known
  after-sales alias drift is an evaluator issue and was not used to alter the
  production owner contract. Synthetic safety regression remains `5/5` and
  `22/22`, all review-only.
