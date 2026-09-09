# Change Log

## 2026-09-09 - Explicit Assisted Conversation Document Import

- Extended the existing manual reader/route/parser and preview modal, not the
  Agent. Omitted mode remains strict native_selection; manual_document_review
  requires explicit choice and returns manual_confirmation_required with
  current_customer_binding_verified=false. Buyer/shop re-entry and acknowledgment
  gate local import; all turns remain history and the current question is blank.
- Preserved default-off, human auth, direct loopback, CSRF, isolated child,
  snapshot/role/order gates and no generation/send. Buyer labels remain transient
  preview data; prior conversation, order, product, media and async state clear.
- Added RED/GREEN tests for explicit mode and human confirmation. Independent
  review caught MSAA selection conflict omission; four negative variants now
  block without treating matching MSAA as positive native identity.
- 321 Python tests and 26 frontend behavioral tests passed; one existing
  LangChain dependency warning. Synthetic browser import verified incorrect
  shop stays disabled, correct matching import keeps the question empty, and
  the modal fits desktop/narrow viewports. No Vue build was needed.
- Two actual assisted reads returned 18 turns (7 buyer/11 agent), no orders or
  products; final strict native read still blocked. Real-data evaluation and
  reply-quality optimization were not run: real_accuracy=null,
  optimization_unverified. Source-only adapter checkpoint, not production rollout.
- py_compile and post-edit documentation governance passed. Temporary 5030 was
  stopped; original 5012/5174 processes were retained. Existing generated
  declarations and runtime outputs are excluded from the local commit.

## 2026-09-09 - Native Selection Diagnostic, Import Still Blocked

- Added count/status-only UIA/MSAA parent-selection diagnostics to the existing
  disabled native reader. Selection members and exception text are never read
  into the diagnostic. Unsupported/error remains distinct from a valid zero.
- TDD: 12 diagnostic assertions failed before implementation; the final scoped
  suite adds 23 tests including no-authority and unrelated-control coverage.
  Related Python tests: 276 passed, one dependency warning. Existing executable
  frontend behavior tests: 22 passed. py_compile and scoped diff checks passed.
- Independent review caught diagnostics participating in snapshot equality.
  Three red/green variants now ignore only the diagnostic field; six negative
  cases preserve comparison of all prior identity/structure fields.
- Two private native captures returned buyer_binding_missing: one Tree and two
  Tabs do not support UIA Selection; MSAA reads succeed with zero selected items.
  Single-item selection remains absent. No native context was imported, and
  no model, real-dataset evaluation, JST or knowledge write was performed.
- This diagnoses a platform compatibility gap, not a fixed customer binding or
  Agent-quality improvement. The selected-client/order ownership gates remain;
  no frontend, canonical, Agent, review/send or production-service change.
  Production 5012/5174 retained their processes; no temporary server was started.
  real_accuracy=null; listening, reconnection and delivery remain unqualified.

## 2026-09-09 - Review Queue Execution Identity Isolation

- Fixed the existing ReplyService -> ReviewQueueService boundary: source,
  conversation, message, request and optional structured shop identity now reach
  enqueue. Exact tuple encoding avoids delimiter collisions; only a versioned
  SHA-256 is stored, not additional raw buyer/shop/event identifiers. This is an
  internal matching fingerprint, not encryption or proof of platform ownership.
- Removed text/order and last-200-record deduplication. Only an identical
  pending review payload with the same execution identity can be reused;
  changed input/reply/risk/action and decided records create independent pending
  records. Missing, malformed or generic identity never guesses a match. No
  migration, deletion or reidentification of historical records was performed.
- The existing JSONL owner uses a shared in-process RLock for enqueue/read/review
  consistency. No database, service, Graph, model, reply owner or send condition
  added. Multi-process/crash-safe persistence is not qualified.
- Red/green tests reproduced legacy text merging and discarded identity. Final
  related regression: 211 passed, 14 dependency deprecation warnings. Controlled
  ExecutionService/ReplyService tests preserve generation/send fields and show
  per-analysis IDs reaching the queue. They do not exercise a live model.
- Independent review caught unencodable identity dropping enqueue. Five red/green
  surrogate cases now remain independent. Event-controlled concurrent decision
  rewrite/append also passes, and an in-memory lock-removal mutation is caught.
- Disjoint Final/Audit/Evidence/Replay/benchmark-fixture regression: 189 passed,
  199 dependency deprecation warnings. Total: 400 related tests; py_compile
  passed. No live model benchmark was run for this non-generative queue fix.
- Existing reconstructed v1.2.0 fixture queue replay: 8 scenarios, 32 customer
  events, 128 attempts, 96 distinct pending rows; 32 exact retries reused rows.
  The existing semantic content validator passed; file bytes do not match the
  fixture manifest. This fixture check is not native benchmark qualification;
  neither data nor evaluator gates were changed. real_accuracy=null.
- Production 5012/5174 and knowledge data were not changed. Stable native
  QianNiu identity and HTTP retry idempotency remain separate open gates; current
  execution IDs are regenerated per analysis. No quality/latency improvement
  claim, automatic approval, live conversation read or outbound message.

## 2026-09-09 - Manual QianNiu Preview, Native Ownership Gate Still Blocked

- Reused the existing adapter, Sidecar blueprint, canonical normalizer and
  real-test template. Added a default-off local human/CSRF preview POST, a bounded
  no-log subprocess, explicit window/order selection and separate confirmation.
  No shared Sidecar cache, polling, model request, business write or send action.
- Reset stale buyer/order/product/media/candidate state and ignore late replies;
  preserve canonical content and leave the question blank on a seller tail.
- Review mutations caught list-membership versus selection, cross-document
  orders and skipped message subtrees. Final code requires native selection,
  blocks unknown content, and omits sidebar identifiers lacking buyer ownership.
- 145 related Python tests and 22 executable JS tests passed. Local browser
  window selection/preview/import/reset was observed with an intermediate
  18-turn capture; this weaker capture is superseded, not final qualification.
  Final current-client selection is absent through UIA/MSAA, so live import is
  blocked. Production and external models were not touched. No accuracy claim.

## 2026-09-09 - Authorized Development Source Backup

- User requested pushing the latest existing customer-service project. Prepare
  code, tests and durable docs for the existing product-hub-context-bridge branch;
  exclude local runtime data and generated frontend declaration churn.
- No new business-code edits, evidence-policy changes, production deployment,
  default-branch merge or forced history update. Preserve known quality gaps
  documented below. Secret scans and exact remote-SHA comparison are required;
  backup publication is not a release/accuracy qualification.

## 2026-09-09 - Product Switch And Multi-Goal Fact Coverage

- Understanding candidates now advertise allowed subject_scope values from the
  existing type predicate/constants. Validation is unchanged. Intent-router
  product labels stay diagnostic in router_decision and cannot overwrite
  upstream matched identity or mask an explicit title conflict.
- The existing Hub adapter reuses its per-type projection over one already-read
  snapshot for all valid server-understood customer goals, merging evidence_uid.
  Confirmed/source/SKU/measurement/object and downstream admission gates remain.
- Three business files/four existing test files changed, 42 tests added. Final
  related 20-file run: 846 passed, one existing JST code-110 classification
  failure (also reproduced with the original router loaded in memory), zero
  errors/skips. This is not a full-project test pass.
- The same three fictional four-turn inputs ran once per version, 12 native runs
  retained. Final 2/3 pass: current net weight 4.69kg; switched-back PP+PE plus
  net weight 3.6kg. Product dimensions remain unsupported with a redundant link
  request; Composer/Final approval is not sufficient quality acceptance.
- All runs retained no-send/human review, knowledge hash unchanged/DML zero,
  zero observed blocked external-network/out-of-scope writes. Last samples
  18.013-29.686s/eight model calls each, no real-accuracy or latency claim.
  Formal5012/5174 and knowledge/credentials unchanged, no commit/push. Evidence
  is at C:/Users/sshuser/jst-source-export/product-switch-20260909; roadmap
  records remaining missing-fact progression, minimum clarification and release gates.

## 2026-09-09 - Understanding Failure Candidate Boundary

- Pipeline previously retained degraded legacy suggestions and preview inputs;
  Final could restore text even after invalid-state clearing. One business-file
  repair clears these surfaces before Final and after its success/exception.
  Cause/evidence diagnostics, human review and blocked sending remain.
- One prior test corrected, 20 added. Original 21 failed; repaired 21 passed.
  Related 732 plus disjoint Final/preview/ReplyService 96 passed: 828 unique
  tests, no errors/skips. Scoped diff check and source/test hashes passed.
- No model/customer evaluation, runtime promotion, knowledge writes, secrets,
  commit or push. Formal PIDs unchanged. Capacity/latency and real accuracy
  remain unqualified; real_accuracy=null, optimization_unverified=true.
  Backups/XML: C:/Users/sshuser/jst-source-export/understanding-fallback-20260909.

## 2026-09-09 - Authorized Multi-Turn Model Recheck

- User explicitly authorized the three fictional dialogues and corresponding
  product context to the existing 8001 model. No real customer data or sends.
- The first three actual checks failed. Material/net-weight classification was
  correct in raw model output, but a non-applicable dimension subject_scope
  degraded the goals. Corrected the prompt conflict, not the validator. Graph
  evidence_builder also omitted conversation_turns, leaving the Composer blind
  to dialogue history; supplied the existing canonical context argument.
- Composer prompt preserves measured objects and weight meaning, places any
  needed empathy in the answer and avoids ceremonial closure. No post-processor,
  alternate reply engine, new permission or evidence eligibility relaxation.
- Focused pre-fix tests 4 failed/8 passed. Final 16-file related suite: 712
  passed, zero failures/errors/skips, 12.179s; 12 new cases. Final native batch
  passed the same 3 fictional cases once each: supported/Composer/both Final,
  four history turns, human review/no-send, knowledge unchanged/DML zero,
  observed external-network/out-of-scope writes zero. Eight model calls each;
  18.052/16.609/17.874s, no latency SLO or customer-accuracy claim.
- Kept failed and successful raw results and byte backups in the existing task
  export folder. 5012/5174 and model/Hub processes unchanged; no Git commit/push.
  real_accuracy=null; broader conversations, busy fallback and release remain.

## 2026-09-09 - Conversation Context And Net Weight

- COPILOT-CHAT-INTELLIGENCE-20260909, P1: Understanding now receives a bounded
  canonical/private-data-projected view of recent buyer/agent dialogue. It
  interprets the current request only; historical text cannot become current
  provenance, product evidence, instructions or action authorization.
- Registered net_weight separately from gross_weight/load_capacity, with an
  exact confirmed Hub tuple (weight, net-weight attribute, whole product, kg).
  Added fact-level equality with the resolved Hub product code. Three business
  files, two new tests; no reply templates or new owner/framework.
- Original context tests 5 failed/7 passed; net-weight tests 2 failed/14 passed.
  Combined 524 passed/1 cross-product failure, then final 525 passed with zero
  failures/errors/skips (11 related files, 28 new cases, 6.671s).
- Three fictional multi-turn baseline and three context-only after requests
  failed the quality gate. After included a model-capacity 429 and legacy
  degradation; net-weight/binding final code is not model-verified. Auto-review
  blocked the next diagnostic because it sends product context to a model;
  asked the user for authorization and did not bypass. No accuracy uplift or
  gold-service qualification claimed. real_accuracy=null; no customer replay.
- Preserved byte backups/intermediate evidence in the task export directory;
  no formal 5012/5174 release, knowledge writes, credential changes or sends.

## 2026-09-09 - Composer Closure And Hub-Only Graph Boundary

- COPILOT-CLOSURE-20260909, P1: a forced nonempty closure duplicated already
  complete clauses. Keep the field required in its existing opt-in mode, allow
  an explicit empty string, remove forced padding from the prompt, reject
  invalid/overlong values and exact whitespace-normalized copied clauses.
  No rewriting, extra reply owner, factual admission or Final/send relaxation.
- COPILOT-HUB-ONLY-GRAPH-20260909: the identified external calls came from the
  legacy Graph JST SKU fallback. Explicit Hub-only mode now defers that node
  to the existing exact-SKU Context Pack owner, without identity updates or
  cache acceptance. Default order/logistics mode is unchanged.
- Focused baseline: closure 19 failed/4 passed; Graph 5 failed/3 passed. Native
  related regression: 726 passed, zero failures/errors/skips, 23.254s; 28 new
  cases. Source and tests have original-byte backups and SHA-256 guards.
- Three generated native product-only requests: baseline repeated; Composer
  repair passed both audits; combined check passed with a supported fact,
  non-repeated reply, can_send=false, human review=true, unchanged knowledge
  hash, zero DML and zero observed blocked network/file operations. Two exact
  os.devnull opens are correctly classified as read-only Git diagnostic sinks.
- The combined check was preceded by a source-readiness failure and a no-model
  preflight. Hub read access recovered without restart. Final elapsed time
  21.632s, eight observed local qwen3.8-27b calls; no performance or real-customer
  accuracy claim. real_accuracy=null and optimization_unverified remain.
- No formal 5012/5174 deployment, restart, credentials, data restoration,
  real-customer replay, automatic delivery, Git commit or push. Canonical API,
  copilot and replay share the changed owners only in the development checkout.
  The bounded live check used /api/analyze, not a new browser/reply path.
- Runtime evidence and byte backups:
  C:/Users/sshuser/jst-source-export/closure-20260909. No new ADR/architecture
  owner; current architecture and execution documents updated.

## 2026-09-09 - Typed API Identity Repair And Full Reply Counterexample

- COPILOT-FULL-REPLY-20260909, P1 context correctness. The canonical API inferred
  product_name/platform title from any candidate value, including SKU and ID.
  An exact SKU then failed the existing title conflict check. The API now uses
  explicit name fields or title-typed values, preserving identifiers separately.
  No sample-specific branch, resolver exception, evidence or send relaxation.
- Original 17-case boundary suite: 12 failed/5 passed; candidate 17 passed;
  native integrated related regression 287 passed, 25 warnings in 6.37s.
  Only app/api/analyze_routes.py and one new test file changed in business/test
  scope. Original source backup and pre/post hashes are in the task export.
- Two product-only synthetic HTTP requests used independent active SKUs for
  source readiness and question input; no customer chat/order data. Before:
  no admitted material fact. After: 12 Hub records, 2 candidates, supported
  material claim. Both retained final human review/no-send and no knowledge DML.
- The post-fix Composer candidate duplicated the supported clause in its
  customer_care_closure. Existing concatenation preserved it; it was already
  duplicated before Final. Unified textual audit rejected repeated_generic_reply.
  No formatter deduplication, new prompt, or weakened audit was applied.
- Post-fix: 8 observed existing LLMClient calls to local qwen3.8-27b, 15.424s.
  The first diagnostic wrapped the wrong transport surface and observed none;
  native diagnostics prove at least 3 calls, so zero is not an actual count.
  Both isolated commands were nonzero, with 2 blocked proxy-port attempts and
  2 blocked out-of-scope writes. Their callers were not established; no clean
  end-to-end acceptance or model qualification is claimed.
- Formal 5012/5174 PIDs unchanged; no service restart, credentials, knowledge
  import, commit, push or actual send. Full real-dataset comparison was not run;
  approved labels remain insufficient, real_accuracy=null/optimization_unverified.

## 2026-09-08 - Native Hub Source And Exact Identity Integration

- Task: COPILOT-KNOWLEDGE-RUNTIME-20260908, existing readiness, identity, Hub
  client and Context Pack owners only. Six business files and three tests were
  hash-guarded and backed up before development integration; no formal release.
- Native in-process readiness passes after adding development subject/role to
  the isolated diagnostic, without changing authentication. This corrects the
  earlier unverified loopback-host hypothesis. Remote approval is now available.
- Exact Hub mode resolves only a current active SKU and product binding. Local
  sample/catalog fallback and SKU-prefix-derived JST IDs are excluded in that
  explicit mode. Conflicting titles/identifiers, inactive products, revoked
  mappings and source failures block; namespaces remain separate.
- Candidate 270 passed; native 270 passed, 25 warnings in 5.79s. Two pre-existing
  identity tests were independently reproduced failing on the original source
  because their fixture omitted product_identity_mappings. The fixture now
  creates the real required table; no assertion was weakened or test skipped.
- Native source probe YH04K27 and independent context product YH02K08: distinct
  active SKUs; Pipeline preflight ready; Context Pack identity resolved with
  12 returned records and 2 material candidates. Whole empty-DB hash unchanged.
  Source-check 1292ms is a single observation, not pipeline latency percentiles.
- No full /api/analyze request, model call, knowledge write, auto-send, service
  restart, commit or push. Final can_send/admission/media/handoff owners are
  unchanged. Formal 5012/5174 stay on their existing processes. Real labels
  remain insufficient: real_accuracy=null, optimization_unverified. No customer
  accuracy improvement or order-lookup recovery is claimed.

## 2026-09-08 - Initial Knowledge Source Candidate Attempt (Historical)

- Task: COPILOT-KNOWLEDGE-RUNTIME-20260908. Existing readiness service and
  public runtime projection only; no new retrieval or reply owner.
- The historical snapshot audit denied direct recovery (2,472 reviewed facts
  without current hashes, identity/media and governance issues).
- Explicit development/test Hub review-only mode requires existing safeguards,
  empty local application tables, exact-SKU source proof and eligible fields.
  Probe data is not returned as customer context; positive reads are not cached.
- Candidate: 162 related tests passed (12 warnings). One live source check
  found two eligible candidates, with unchanged local DB SHA-256; warm source
  check 67 ms is a single observation, not pipeline latency or accuracy.
- HTTP remained 503 at admin_auth_mode_not_ready. A possible loopback-host
  omission was corrected locally using the saved launch pattern,
  but not rerun. The next remote read was rejected by automatic approval usage
  limits; no workaround or retry through another channel was attempted.
- Remote source and formal services were not changed. Remote ROADMAP contains
  the initial task registration only; result docs and integration are pending.
  Real accuracy remains null; no model call, customer request or auto-send.

## 2026-09-08 - Restore Original 5012 Transport

- External launcher only: reuse existing Copilot venv instead of the unrelated
  Hermes interpreter, fix embedded FOR path quotes, and pin the original release.
  Keep the same SYSTEM task and JST environment allowlist; restore in knowledge
  query-only mode with writable media workers disabled.
- In-process app and ordinary/SYSTEM import checks passed. Original selection
  reproduced binary-as-script failure; canonicalized selection passed. First
  failed deployment rolled back; corrected deployment restored 5012 PID74208.
- Independent 5012 health/version and 5174 real-test/proxy checks return 200.
  Knowledge readiness remains 503 for three empty core tables. No production
  source promotion, model request, customer evaluation or knowledge write.
- Backup: C:\Users\sshuser\jst-source-export\recovery-5012-20260908-180406.
  Other monitored services stayed unchanged; one-off SYSTEM probe task removed.

## 2026-09-08 - Bounded Manual File Checks

- Existing client now checks PDF prefix, type and catalog size without following
  redirects or reading more than five bytes. At most three file checks start,
  within a five-second scheduling budget and the existing per-request timeout.
- Failed and unchecked files never become review references; partial success
  preserves good files, while zero verified files is unavailable rather than
  empty-catalog success. Context preserves header_verified, check time and the
  existing product/SKU, review-only, no-fact and no-send boundaries.
- Baseline 193 passed; candidate 219 and native 219 passed (26 new). Same real
  product: three unchecked records before, two valid-prefix references and one
  HTTP failure after. Native sample 109ms versus baseline 79ms; no latency
  percentile or customer accuracy claim. Formal /api/analyze quality evaluation
  remains unverified without comparable approved labels.
- Only two business files and the focused test were integrated with source-hash
  checks and backups. No runtime restart, model call, formal-knowledge write,
  automatic delivery or production promotion. 5012 still has no listener.

## 2026-09-08 - Manual File Access Follow-Up

- Final independent recheck: health body confirms both roots accessible in
  47ms, valid PDFs again return 206, and the dangling record remains 500.
  A prior 4s timeout was below the health route's two sequential 2.5s checks;
  it did not prove service-wide relapse. No second restart was performed.
  Short sample checks do not establish long-term stability.
- Standard/elevated interactive probes both read the shares; the SSH 1326
  result was specific to its independent logon context. No password or
  permission change was needed. Two sample PDFs exist and one catalog path
  is missing; both temporary probe tasks were removed.
- Hub 8795 health was repeatedly unresponsive. Its unchanged existing task
  was restarted after source/PID checks (25816 -> 66488); other observed
  service PIDs remained unchanged. Both valid PDF URLs returned 206.
- One three-page PDF matches its catalog SHA-256 and the first two pages
  rendered correctly. pypdf extracted replacement characters in digits
  (59/0/59 per page); no extracted content entered formal knowledge or facts.
  Copilot production promotion and full installation answering remain pending.

## 2026-09-08 - Product-Bound Installation PDF References

- Post-integration verification ran directly against the development checkout,
  without overlay modules: 193 passed, 683 warnings, 44.16 seconds, exit 0.
  Hub runs as sshuser (session 1); SSH also runs as sshuser, but the NAS login
  is rejected. Restoring an interactive session alone is not a verified fix
  until both the original-file API and runtime identity can read the document.

- Added a narrow installation-query path to the existing reviewed-media client:
  exact active SKU, exact active product and product-filtered manual API. PDF
  references preserve source binding and never prove SKU applicability or
  file availability. Unapproved, cross-product/cross-SKU, source-format,
  unsafe-URL, duplicate and incomplete-list responses cannot supply candidates.
- The existing Context Pack projects these as review-only `product_manual`
  media, not packing-list images, product facts, thumbnails or delivery blocks.
  Other query types retain the existing image path; no new service or library.
- Candidate verification: 193 tests passed in 48.24 seconds, including 34 new
  cases. One live exact-SKU/API probe returned three product-scoped PDF
  references; it selected a diagnostic input from the catalog read-only and
  still resolved that input through the exact-SKU HTTP API. No model calls or
  business writes. Initial cross-drive pytest collection failed on an unrelated
  mount point; moving the four-file overlay inside the project resolved that
  test-harness issue. The passport diagnostic timed out and is not used by the
  production reader or final successful probe.
- Shared-storage access remains blocked: TCP 445 succeeds, but the configured
  NAS roots return WinError 1326. Original-file URLs had 3/3 HTTP 500 failures.
  This is candidate integration, not a file-reading or production rollout pass.
  No credentials, business data, Hub code, runtime flags or services changed.

## 2026-09-05 - Exact JST Outbound-Item Identity To Reviewed Hub Facts

- Repaired the existing read-only order identity flow so an
  integration-verified, exact JST outbound-item match can reuse only that
  item's exact SKU through the existing resolver. It remains distinct from a
  context-selected multi-item order and cannot fall back to titles, substrings,
  first rows, or cross-namespace `i_id` values.
- The existing Product Context Pack now recognizes the same trusted exact-item
  result for its default-off Product Hub SKU reader. The Hub remains an exact
  natural-key read source; only confirmed, non-conflicting facts continue into
  the existing admission path.
- Added contract coverage for exact multi-item selection, ambiguous-order
  refusal, Hub reuse, direct-lookup shop-scope behavior, and a legal long graph
  path. The isolated query-only API check reached canonical selected evidence;
  no formal knowledge DML, external model call, media delivery, or automatic
  send occurred.
- The review-only workbench now identifies itself as human-confirmation mode
  rather than claiming a provider is connected when a candidate intentionally
  disables model calls.
- Added the missing declared `langgraph` runtime dependency. This is an
  identity/evidence correctness repair, not a customer-quality result:
  `real_customer_accuracy=null` and `optimization_unverified=true` remain.

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
