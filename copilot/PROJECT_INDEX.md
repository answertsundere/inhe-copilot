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

- 2026-09-09 assisted document import: an explicit manual_document_review mode
  reads stable historical conversation documents when native selection is absent.
  Buyer/shop re-entry and acknowledgment are required; native UIA/MSAA conflicts
  still block. Default mode remains strict, current question stays blank, and
  no unbound orders/products are imported. Related regression: 321 Python and
  26 frontend tests; real read: 18 turns, no Agent call. This is a default-off
  development capability, not a deployment or native identity qualification.

- 2026-09-09 native current-client probe: parent UIA selection is unsupported
  on the one Tree and two Tab controls; MSAA selection reads succeed but return
  no selected items. Import still returns buyer_binding_missing. Only bounded
  count/status diagnostics were added to the existing disabled reader; no
  identity fallback or production deployment. Native listening remains blocked.

- 2026-09-09 review-queue isolation is development-integrated, not deployed.
  The existing ReplyService now forwards execution identity to the existing
  JSONL queue. Only pending records with exact source/shop/conversation/message/
  request identity and unchanged review content can be reused. Missing identity
  and legacy records never fall back to text/order matching; no raw identity
  fields are added to storage. Related regression: 400 passed. Queue-only
  reconstructed fixture replay: 128 attempts / 96 distinct records, no model.
  Native platform identity, HTTP-retry identity and multi-process durability
  remain unqualified. Production services and can_send are unchanged.

- 2026-09-09 manual QianNiu integration is development-only and disabled by
  default. The existing Sidecar route and real-test page now support local
  authenticated preview/confirmation with canonical history and stale-state
  isolation; 145 related Python tests and 22 frontend tests passed. Final live
  qualification is blocked: native selected buyer/shop state is not exposed,
  and order-panel ownership is not proven. Supersede the earlier weaker 18-turn
  preview result; no real conversation was sent to an Agent or external model.
  Production 5012/5174 and knowledge data remain untouched. See the existing
  desktop-adapter research note and ADR 0011 manual-preview addendum.

- 2026-09-09 development source backup: the user authorized a normal push of
  current code/tests/docs to codex/product-hub-context-bridge. This is not a
  production release or default-branch merge. Runtime diagnostics/databases,
  credentials/customer exports and generated frontend declarations are excluded.
  Preparation requires staged/outgoing-history secret scans and integrity checks;
  verify the actual GitHub branch SHA after pushing. Existing quality limits
  below remain open, including the known JST classification test failure.

- 2026-09-09 product switches and multi-goal facts: three existing business
  files repaired candidate scope metadata, router label promotion into identity,
  and primary-type-only Hub fact projection. Four existing test files changed;
  42 new tests. Final related regression: 846 passed, one existing JST code-110
  classification failure also reproduced with the original router in memory.
  The frozen three fictional cases passed 2/3: current net weight 4.69kg and
  switched-back material PP+PE plus net weight 3.6kg. Product dimensions remain
  unsupported and the reply still unnecessarily asks for a link. All 12 native
  versioned runs are retained; no-send/human review, knowledge hash unchanged,
  DML zero and no observed blocked external-network/out-of-scope writes.
  Final samples take 18.013-29.686s, eight model calls each; no latency claim.
  Development-integrated only, formal 5012/5174 unchanged. Next: known-identity
  missing-fact progression and minimum clarification, JST classification, then
  qualified release/page acceptance. real_accuracy=null; optimization_unverified=true.

- 2026-09-09 Understanding failure boundary: invalid/degraded results no longer
  retain legacy suggested text, text blocks or supervisor/partial previews.
  The existing Pipeline repeats the boundary after Final success or exception;
  cause/evidence diagnostics and review-only delivery remain. One business
  file and its existing test file changed. Original 21 counterexamples failed;
  repaired 21 passed. Related regression 732 plus disjoint Final/preview suite
  96 passed (828 unique tests; 20 new). No model/customer run or release.
  Formal 5012/5174 unchanged. Provider capacity and broader quality remain
  unqualified; real_accuracy=null, optimization_unverified=true. Next: normal
  complex multi-turn/product switches, then qualified release/page acceptance.

- 2026-09-09 multi-turn context / net weight: three business files and two new
  test files are development-integrated. Understanding receives bounded,
  privacy-projected role-aware history only for interpreting current requests;
  current-turn provenance and evidence authority are unchanged. Net weight is
  a separate strict type mapped only from the exact confirmed Hub field.
  Candidate facts must also match the resolved Hub product code.
  User subsequently authorized the three fictional model cases/product context.
  Raw diagnostics exposed an incompatible subject_scope on non-dimension goals
  and a missing conversation_turns argument at reply-context assembly. The
  prompt now enforces the existing dimension-only field contract; Graph passes
  canonical history to the existing Composer, which preserves measured-object
  meaning and avoids ceremonial closure. Validators/send authority are unchanged.
  Follow-up regression: 712 passed, zero failures/errors/skips; 12 new cases.
  After the three failed diagnostic cases, the final one-shot-per-case batch
  passed all three: material, net weight and packaging dimensions; each has
  supported claims, Composer accepted, both Final audits passed, four history
  turns, no-send/human review, unchanged knowledge/DML zero and no observed
  external-network/out-of-scope writes. Eight model calls each, 16.609-18.052s.
  These are synthetic regressions, not real customer accuracy. real_accuracy=null;
  optimization_unverified=true. Next: broader multi-turn/product-switch/action
  evaluation and model-busy fallback/latency, then pinned release acceptance.
  Formal 5012/5174 are not updated; no real-customer replay or sending.

- 2026-09-09 closure/source-boundary follow-up: two scoped business changes are
  development-integrated. Composer accepts an explicitly empty closure when
  the answer is complete, rejects copied clauses and invalid closure values,
  and keeps one reply owner and both Final audits. The explicit Hub-only mode
  defers the legacy Graph identity lookup to the existing Context Pack instead
  of calling JST or trusting its cache; default order/logistics mode is unchanged.
  Native related regression: 726 passed, zero failures/errors/skips. The final
  independent product-only API diagnostic passed: supported material claim,
  non-repeated reply, both audits passed, no-send/human review, unchanged knowledge
  hash/DML zero, observed external-network/out-of-scope-write attempts zero.
  Two exact os.devnull opens are Git metadata, not persistent file writes.
  Before that success, Hub source readiness timed out and correctly stopped
  before a model request; it recovered without a service restart. The final
  request still took 21.632s with eight observed local model calls. This is one
  product diagnostic, not real accuracy or production qualification. 5012/5174
  remain on the old release. Next: bounded identity-entry business cases and
  source stability, then a pinned review-only release/page acceptance.

- 2026-09-09 full-reply diagnostic: the API treated typed candidate values as
  product names, causing an exact SKU to fail the Hub title check. One API file
  is now repaired; original normalization 12 failed/5 passed, candidate 17
  passed, native related regression 287 passed. Real titles and conflicting
  explicit titles remain intact; identity/admission rules were not weakened.
  The same product-only question now has two Hub candidates and a supported
  material claim, but Composer copied its clause into customer_care_closure,
  producing a duplicate. Unified textual audit rejected repeated_generic_reply;
  the full answer remains unaccepted and formal runtime is unchanged. The
  second isolated request observed eight local qwen3.8-27b calls, 15.424s,
  unchanged knowledge hash and zero knowledge DML. Two proxy-port attempts and
  two out-of-scope file writes were blocked; their callers remain unqualified.
  Real accuracy is null; no customer dataset or send capability was evaluated.

- 2026-09-08 knowledge-source follow-up: six scoped business files and three
  test files are integrated into this development checkout, with hash-guarded
  backups. Candidate and native regressions each passed 270 tests. Native
  in-process readiness is HTTP 200 in explicit Hub review-only mode; a separate
  real SKU now resolves to its current active Hub product and yields two
  material candidates from 12 returned records. The empty local DB hash is
  unchanged. The earlier auth failure was missing diagnostic development
  subject/role, not a production-auth defect. Default mode and formal 5012/5174
  remain unchanged. No model call or full /api/analyze reply was run; order
  lookup, reply quality and runtime promotion are still unverified. Real
  accuracy remains null (optimization_unverified).

- 2026-09-08 18:04 runtime follow-up: the original SYSTEM 5012 task is restored
  using the existing Copilot Python; 5012 health and the 5174 real-test page are
  HTTP 200. Knowledge readiness is still 503 (three empty core tables). Only
  the external launcher changed; the old bbd89e2 dirty release remains active,
  knowledge is query-only, and this development branch's Hub/manual changes
  have not been promoted. This supersedes the earlier no-listener observations,
  not the remaining data, interpretation or end-to-end acceptance gates.

- 2026-09-08 bounded manual file checks are integrated: only PDF prefix/size
  checked files reach review context. Three catalog entries in the same live
  product yielded two references and one explicit file failure. Baseline 193,
  candidate 219 and native post-integration 219 regressions passed. No formal
  facts, knowledge writes, model calls, runtime promotion or delivery change.
  Prefix checks do not prove complete PDF integrity, interpretation or SKU fit.
  Real customer accuracy remains null; the formal 5012 listener is still absent.

- Final independent recheck: source/output both accessible (health 47ms),
  both valid PDFs again returned 206; the dangling record still returned 500.
  A prior 4s health timeout was below the two sequential 2.5s path-check budget
  and did not establish a service-wide relapse. No second restart was made;
  long-term stability remains outside this sample verification.

- 2026-09-08 follow-up correction: interactive standard and elevated sessions
  both read the configured shares. SSH WinError 1326 was session-specific,
  not proof of service access failure. Two of three sample PDFs exist; one
  catalog record is dangling. The unresponsive existing Hub 8795 task was
  restarted unchanged after source/PID checks; both valid files now return
  HTTP 206. One PDF hash matches the catalog, with three pages and two rendered
  pages visually checked. Direct text extraction has damaged digits, so it
  remains unsuitable for factual admission. No Copilot runtime promotion or
  credential/permission change. This supersedes the shared-login blocker below.

- 2026-09-08 installation correction: the existing media reader and Context
  Pack now have a tested PDF-reference candidate path for installation queries.
  It resolves exact active SKU -> exact active product -> product-filtered
  manual assets. Product-level documents retain product scope, unverified
  variant applicability, and unverified file access; they are not facts or
  delivered media. See ADR 0010's product-manual addendum.
  Candidate regressions: 193 passed (34 new). One live product returned three
  PDF references, with zero model calls or business writes. The subsequent
  file-access verification is documented above; no Copilot production switch
  has occurred. Native post-integration regression also passed
  all 193 tests in 44.16 seconds. Current status: development source integrated,
  awaiting reliable document interpretation and end-to-end customer answering.

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
- Current production-correctness exception: the isolated candidate now carries
  one integration-verified exact JST outbound-item match through the existing
  exact-SKU Product Hub reader and canonical selected-evidence path. This
  remains query-only, review-only, and does not establish a response-quality
  improvement or bypass P1 E2.
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
