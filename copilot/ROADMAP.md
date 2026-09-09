# Delivery Roadmap

## Post-Binding Multiturn Reply Check (2026-09-09)

Active priority: P1 Gold Conversation Quality. User confirmed the next single
synthetic candidate after the `8973f60` propagation repair. Reuse the same four
history turns, current question, exact Hub source, Provider and isolated entry
point; preserve the previous result without replacement.

- [x] Verify commit, existing process ownership and the reusable launcher.
- [x] Run one review-only candidate on disposable 5030, then stop that process.
- [x] Compare trusted policy, goal/premise attribution, reply and final gates.
- [x] Record actual quality findings and remaining limitations.

No Agent, prompt, policy-data or formal-runtime edits are planned. No production
data write, auto-send or additional scenario/model retry is permitted in this
check. This is a synthetic diagnostic, not a real-accuracy qualification.

Result: failed candidate, not a passed reply. One API request returned HTTP 200
with an empty reply after 6,726 ms; the launcher recorded exit_code=2. Composer
was blocked and made zero calls. The existing human-review boundary remained
true and can_send=false. No retry or extra external scenario was run.

The propagation repair is visible in the actual trace: trusted policy selected,
13 bounded policies available, exact source identity equal to the previous run,
and 54 Hub source facts returned. These are candidates, not 54 admitted facts.
The Understanding response contained two raw goals and passed JSON schema and
source-span checks, but post-schema goal normalization was not authoritative.
Final canonical goals=0, selected evidence=0 and claim resolutions=0. This is
not evidence that the source has no product facts.

Read-only code attribution and a generic no-model reproducer confirm that
semantic_fact_type_service._fallback_from_rule drops the normalizer's specific
goal_understanding_diagnostics and leaves llm_goal_understanding_unavailable.
The reproducer's unknown-policy case does not identify the actual failed model
nomination: that live reason was lost. Do not infer it from the generic example.
Next bounded repair: retain deterministic rejection reason codes in the existing
diagnostic contract, without making rejected goals authoritative or changing
Composer, policy content, prompts, Safety or Delivery. Not implemented here.

Runtime commit=8973f60669649e1a4957e4574906412d153befd6, clean source identity,
no source drift, readiness ready and formal SQLite query-only. The isolated
knowledge fingerprint was unchanged, observed formal DML=0, and 5030 stopped.
No Hub writes or original-service changes. Whole-Pipeline model-call counts are
not complete: the strict Understanding call count is one (1,826 ms including
local validation), while Composer count is zero. No single-case p50/p95 claim.
Related deterministic regression: 654 passed; documentation governance: 5 passed.
Python/PowerShell report parsing and scoped diff check passed. Original
5012/5174/8795 PIDs are unchanged; no network push attempted. real_accuracy=null and
optimization_unverified remain; this empty candidate cannot be graded for tone,
naturalness or business helpfulness. Detailed attempt/trace stay outside Git.

## Hub Policy Binding Propagation (2026-09-09)

Active priority: P1 Gold Conversation Quality. Repair control metadata only in
the existing isolated `product_hub_review_only` source. The Agent product detail
omits `domainPolicyId`; the existing read-only product passport exposes it.

- [x] Verify the actual source API and freeze the previous synthetic result.
- [x] Add negative/positive tests for exact identity and control-only projection.
- [x] Reuse the identity owner and Pack loader before Understanding.
- [x] Run deterministic regression and a read-only source comparison, no models.
- [x] Review the scoped change and prepare the local milestone.

No Hub writes/restart, model request, reply/prompt or delivery changes are planned.
Real accuracy remains null; candidate answer quality is optimization_unverified.

Read-only comparison of the same frozen synthetic source: the parent selector
returned missing/domain_policy_id_missing; the candidate selected the existing
Pack through three bounded GETs (two identity, one passport). Current product,
SKU and fact-row HMACs were unchanged, as were all four empty formal tables;
SQLite query_only=1 and observed local formal DML attempts=0. Preparation took
47 ms before and 109 ms after in the final post-review observation, not an end-to-end
latency benchmark. Graph/model calls=0; no new reply or send decision was made.
The private comparison artifact remains outside Git. Related deterministic
regression: 1023 passed; compile, scoped diff check and Python/PowerShell JSON
passed. Review caught a public-identity conflict before canonical normalization;
the selector now reuses that existing projection before resolving. Five new
negative cases reproduced the defect before the repair. Re-review found no
remaining blocker, with 36 focused tests and seven independent probes. Existing
5012/5174/8795 PIDs remain unchanged. No network push is attempted this round.

## Isolated Multiturn Candidate (2026-09-09)

Active priority: P1 Gold Conversation Quality. Reuse the existing application,
qualified Understanding configuration and exact-SKU Product Hub source for one
synthetic history/current-question request. This is not a real-customer test.

- [x] Confirm existing runtime ownership, credential source and ready-source contract.
- [x] Run one bounded review-only DeepSeek candidate on disposable loopback 5030.
- [x] Inspect history continuity, partial-answer quality, evidence and safety.
- [x] Stop the disposable server; record verification and the earliest remaining gap.

No Agent, prompt, graph, safety or formal-runtime changes are planned. Approved
credentials stay in child-process memory only; real chat and orders are excluded.

Execution status: one real API candidate completed after explicit disclosure
approval. Two earlier launcher/preflight failures made no Agent request; the
external script now uses keyword-only helper arguments and registers the existing
knowledge models when creating its empty temporary schema. No production repair.

Ready=true, source drift=false, query-only=true. Four synthetic history turns
reached minimal context without trimming (386 estimated tokens). Two customer
goals became material=supported and cleaning_care=unresolved. Final selected
evidence=2 (both PE); Composer accepted and Deterministic Final passed. Actual
reply deferred cleaning to documentation/manufacturer: safe uncertainty, but poor
service progression. Semantic judge was unavailable, not qualified. can_send=false,
human review=true, DML=0 and isolated DB fingerprint unchanged. HTTP latency
7,497 ms; Understanding/Composer each called once with zero retries/repair in
their diagnostics. Other legacy node calls were not fully counted.

Read-only attribution found an exact-source product policy binding with a valid
local Pack, including cleaning boundary policies. However, the existing
_verified_product_domain_policy_selector reads only published local KBProduct
rows; Hub-only empty-store mode loses that control metadata before Understanding.
Do not inject a global policy or seed local facts to conceal this gap. The next
owner is trusted exact-product policy propagation, not a canned reply/prompt.

The single-request result is synthetic diagnostic evidence, not real accuracy or
multiturn qualification. 5030 stopped; original 5012/5174/8795 PIDs unchanged.
Detailed Chinese review remains outside Git in the workspace .codex-runtime.
Post-run related regression: 369 passed. No extra model benchmark or real-data
evaluation was run; this diagnostic does not claim an Agent improvement.

## Assisted Import Application Boundary (2026-09-09)

Active priority: P1 Gold Conversation Quality; verify the existing manual
adapter boundary before exposing it as a usable connected workbench.

- [x] Inspect the real Flask route, app-level authentication, CSRF and canonical
  Pipeline entry; preserve production 5012/5174 and existing dirty files.
- [x] Exercise the complete app route registration and real loopback verifier
  with synthetic native documents, including hostile origins and missing auth.
- [x] Verify explicit current message/history separation at the existing
  canonical Pipeline boundary; no real chat or model request in this check.
- [x] Record runtime prerequisites, remaining live-candidate gap and regression.

No Agent or authentication policy change. This is integration regression, not
model quality, native-client continuity or real-customer accuracy qualification.

337 Python regressions and 26 executable frontend tests passed. New full-app
tests restore the real auth verifier (rather than the shared pytest principal),
cover the /ask prefix, and stop synthetic positive analysis at actual canonical
preparation. They do not substitute a mock reply for a model-quality result.

Live temporary 5030 HTTP checks found two configuration prerequisites: DML
diagnostics require an ephemeral HMAC key, and the workbench page requires
supervisor/admin even though the preview API permits all human roles. Neither
policy was changed. The final no-credential check returned page=200,
untrusted-origin=403, empty-message=400, query-only=true, source drift=false,
ready=false. Three nonempty synthetic negative requests reached the unchanged
Pipeline and produced provider_auth_error, empty reply, can_send=false and
requires_human_review=true. HTTP 200 was not treated as candidate qualification.
Temporary knowledge fingerprints stayed unchanged and DML was zero. Every
temporary process was stopped; no production restart, credentials, real chat,
native desktop read, external model completion or customer sending occurred.

Next: a separately configured isolated candidate with a legitimate ready data
source and approved model configuration, then a synthetic end-to-end candidate.
Do not present the current production page as containing this undeployed adapter.

## Assisted QianNiu Document Import (2026-09-09)

- [x] Read active P1 context and record the bounded adapter trust decision.
- [x] Add explicit document-review mode without changing native defaults.
- [x] Require buyer/shop confirmation in the existing preview modal.
- [x] Run adapter/auth/frontend regression and read-only live checks.
- [x] Record limitations and verification for a scoped local checkpoint.

No Agent, provider, production runtime, knowledge write or automatic-send change.

Python regression: 321 passed; executable frontend tests: 26 passed. Browser
fixture import passed at desktop and 390x844 modal width. Two actual assisted
reads returned 18 historical turns (7 buyer, 11 agent), zero order/product
candidates and current_customer_binding_verified=false. Final native-mode read
still returned buyer_binding_missing. No real conversation was imported into
Agent, no model ran, and real_accuracy remains null.

Independent review identified MSAA conflicts being ignored. Four reproduced
negative cases now block; matching MSAA never grants native identity. This
development checkpoint enables assisted document selection only, not automatic
current-client detection, continuous listening or reconnect qualification.
The temporary 5030 fixture server was stopped after UI verification; original
5012/5174 process IDs were unchanged. py_compile and post-edit docs governance
passed. No push or production deployment is part of this checkpoint.

## Native Current-Client Selection Probe (2026-09-09)

- Active priority: P1 Gold Conversation Quality; bounded native identity diagnosis.
- [x] Preserve the queue checkpoint, generated files and production processes.
- [x] Probe UIA/MSAA parent selection using existing native adapter diagnostics;
  retain only counts/status, never names, order values or message contents.
- [x] Test that diagnostics cannot grant identity or change preview admission.
- [x] Run private local native capture and record the observed limitation;
  repeat once after the review-found diagnostic-comparison fix (two total).
- One Tree and two Tabs: UIA pattern unsupported, MSAA readable with zero
  selected items. Single-item selected states also remain zero; import blocked.
- No Agent, model, database, auto-listener, input, send or production changes.
- Native current-client qualification remains blocked until ownership is proven.
- Regression: 276 Python tests and 22 executable frontend tests passed;
  py_compile/scoped diff checks passed. This is diagnostic qualification only.

## Review Queue Conversation Isolation (2026-09-09)

- Active priority: P1 Gold Conversation Quality; approved bounded queue fix.
- [x] Root cause: ReplyService discards execution identity at enqueue; the
  JSONL queue merges pending records by customer text plus order alone.
- [x] Regressions: separate conversations/sources/shops/repeated-message events,
  missing identity, changed review content, old records, restart and concurrency.
- [x] Reuse existing source/conversation/message/request fields and optional
  structured shop scope; no text/time/window-derived identity or new service.
- [x] Wire the existing ReplyService call, preserve review/send contracts, run
  queue/entrypoint/final regression and update the existing document index.
- Existing execution IDs are per analysis, not native platform event IDs. This
  fix cannot qualify HTTP retries, continuous QianNiu capture or reconnects.
- Tests use temporary queues only; no migration of live records, model calls,
  production restart, knowledge writes, auto-approval or sending.
- Development verification: 211 related tests passed (14 existing dependency
  deprecation warnings). Versioned reconstructed v1.2.0 queue-only replay used
  8 scenarios / 32 customer events, 128 attempts / 96 independent pending rows;
  only the 32 exact-identity/content retries reused rows. Content hash
  `50d351316e87b0cce4d31ad5bf34a7eabf53cc1aca6c0d5355f23c366d7ff012`
  passed the existing validator. Native fixture byte hash differs from its
  manifest; neither fixture nor benchmark validator was changed. This is not a
  native Fixed-8 model run or accuracy qualification.
- In-process locking covers queue reads/appends/decisions across instances;
  multi-process and crash-safe storage remain unqualified. Production 5012/5174
  are unchanged. Next: reliable native active-client identity, not auto-listening.
- Independent review's invalid-Unicode identity finding is fixed with five
  red/green cases. Event-controlled enqueue-versus-decision coverage passes;
  an in-memory lock-removal mutation was detected. No live queue was opened.
- Disjoint Final/Audit/Evidence/Replay/benchmark-fixture regression: 189 passed,
  199 dependency warnings. Total related tests: 400; py_compile passed. No full
  model benchmark or live-customer accuracy run was performed.

## Manual QianNiu Conversation Import (2026-09-09)

- Owner-approved bounded P1 integration exception: native read -> local preview
  -> explicit seat confirmation -> existing manual analyze workflow.
- [ ] Native capture qualification: implementation reuses pywinauto and the existing adapter; bind a specific
  QianNiu window, parse only message headers/containers, preserve order and
  non-factual card tokens, and reject changed or ambiguous snapshots.
- [x] Existing Sidecar API: default-disabled, authenticated, CSRF-protected,
  loopback-only manual read; no background loop, model call, database write,
  automatic order selection, or sending. Return preview to the requesting seat
  only, never to the shared legacy Sidecar status cache.
- [x] Existing real-test page: manual read/confirm controls, separate order
  choice, clear stale candidate state on import, canonical history, and explicit
  generation through the existing analyze endpoint only.
- [x] Verify fake-window mutations, route/auth/no-side-effect tests, browser
  interactions and a local native capture; record missing native capabilities
  without representing them as an end-to-end pass.
- Final native gate: blocked by buyer_binding_missing. The current QianNiu
  exposes zero selected buyers/tabs via both UIA SelectionItem and MSAA state.
  Earlier 18-turn previews used weaker list-membership checks and are superseded,
  not current qualification. Unknown native order ownership causes omission of
  all sidebar order/product-code candidates, not a guessed association.
- Related Python regression: 145 passed; frontend behavior suite: 22 passed.
  Desktop/mobile popup checked, no model/JST call. Native switched-customer
  acceptance and read-to-Agent canary remain unrun. Next is native active-client
  ownership, not another Agent/Prompt change or automatic listening.
- Production 5012/5174 remain unchanged. No live customer transcript is sent to
  an external model by the import action. New-message listening and automatic
  sending remain out of scope; real_accuracy=null, optimization_unverified=true.

## Authorized Development GitHub Backup (2026-09-09)

- Task COPILOT-GITHUB-PUSH-20260909; owner Codex; status prepared_for_verification.
- User authorized latest source push to answertsundere/inhe-copilot, existing
  codex/product-hub-context-bridge only. Initial local cc5b6a8 is four commits
  ahead of remote 267fdc2. No staged files existed before this task.
- Include source, tests and durable documentation. Exclude .codex-runtime,
  databases, logs, customer exports, credentials and generated frontend typings.
- Required: exact-file staging, redacted gitleaks on staged/outgoing content,
  syntax/diff checks, normal commit/push and remote-SHA verification. The final
  verification is kept outside this commit to avoid claiming an unperformed push.
- No force push, default-branch changes, service deployment/restart or new
  business behavior. Existing synthetic 2/3 result and known JST classification
  test failure are not waived or converted into production acceptance.

## Product Switch And Multi-Goal Check (2026-09-09)

| Field | Value |
|---|---|
| Task / Owner / Priority | COPILOT-PRODUCT-SWITCH-20260909; Codex; P1 |
| Status | development_integrated_partial_quality_verified_not_released; 2/3 fictional native cases pass |
| Customer outcome | Current SKU facts and latest object/weight scope supersede old-product facts or guesses; answer supported current goals together. |
| Earliest failing owner | Three sequential defects established: Understanding candidate scopes, router model-label identity promotion, Hub primary-type-only fact projection. |
| Comparable dataset | gold-product-switch-prospective / 1.0.0, three fictional four-turn contexts and current exact SKU, no customer history; labels excluded from Agent payload. |
| One target metric | Correct current identity/scope and supported goal coverage across all three cases, with missing facts explicit rather than fabricated. |
| Allowed modules | Existing native API diagnostic runner unchanged, current Hub exact-SKU facts for two products, existing 8001 model; bounded task outputs and existing project docs. |
| Forbidden modules | No formal deployment, live customer data, knowledge writes, credentials, Sidecar, sending, new recommendation engine or retries. |
| Hard stop | Source preflight, source-drift or diagnostic safety failure; first case checked before remaining two; preserve failures rather than reroll. |
| Safety and delivery | Query-only knowledge, hash/DML evidence, forced no-send/human review, diagnostic output only under its run directory. |
| Documentation impact | Existing index/roadmap/changelog; code change only if an earliest existing-owner defect is demonstrated, then same-input regression. |
| Must / After / Not now | Related identity/context regressions and three-case native check; then narrow repair or gap report; no runtime release, real accuracy or persistent conversation-state claim. |

Explicit current SKU plus supplied fictional history tests evidence isolation,
not a real sidebar-switch event or cross-request persistent memory.
real_accuracy=null; optimization_unverified=true.

### Established First Defect

All three initial native runs completed without writes or send authority.
Net-weight and material-plus-net-weight chose the right types but supplied
dimension-only subject_scope=product; local validation degraded both. Text was
correctly cleared. The product-size case was unresolved, preserved product
scope but unnecessarily requested a link despite current identity being known.
This latter quality gap is separate from the first defect.

Allowed narrow repair: existing semantic_fact_type_service candidate projection
will advertise subject_scope_candidates from the existing dimension predicate
and scope constant for every type, with an explicit selected-candidate prompt
rule. Do not broaden output validation or rewrite model output. Tests belong
in the existing context test file; durable contract update in architecture.
Then compare the same frozen three inputs once, preserving both runs.

### Established Second Defect

The scope projection passed 736 related tests. The same three native cases
were each run once again: current net weight passed (4.69kg); two fact goals
were understood but identity failed; product dimensions remained unsupported.
The existing llm_intent_router._result promoted its model-generated product
label into matched_product_name, causing a false exact-SKU/title conflict.
Allowed repair: preserve upstream matched identity, retain the model label in
router_decision only, and keep explicit title/identity conflict checks intact.
Use the existing Hub identity tests for generic provenance counterexamples;
then run related regressions and the same three inputs once on the new version.
The missing product-dimension evidence and redundant link request remain open.

### Established Third Defect

The router counterexamples now pass (17); the 736-test suite passes. Adjacent
router/order regression is 89 passed, 1 JST code-110 classification failure,
also reproduced with the original router loaded in memory. The next three
native runs preserved identity, but the two-goal case admitted material only.
The existing Hub adapter filters the already-loaded facts by primary type only.
Allowed repair: reuse its per-type projection for each server-understood valid
goal, merge by evidence_uid, and retain source/SKU/object/measurement gates.
No additional reads or new evidence authority. Test in the existing net-weight
contract file and compare the frozen inputs once on the new version.

### Final Verification And Remaining Gates

- Three existing business files and four existing test files changed; 42 new
  tests. The final 20-file regression has 847 tests: 846 passed, one pre-existing
  JST code-110 classification failure, no errors/skips. Do not sum overlapping
  intermediate test runs or report this as a full-project pass.
- Four versions of the same three fictional inputs, one call per case/version,
  total 12 native runs. Last batch: net weight 4.69kg supported; material PP+PE
  and net weight 3.6kg both supported; product dimensions unresolved and the
  reply still requests a link despite known identity. Quality result is 2/3,
  not 3/3 merely because Composer and both Final audits accepted.
- Final runs: after-switch-net-weight-20260909-134424 (29.686s),
  after-switch-back-two-facts-20260909-134456 (19.993s),
  after-switch-object-scope-20260909-134518 (18.013s); eight model calls each.
- Evidence root: C:/Users/sshuser/jst-source-export/product-switch-20260909.
  All result/response JSON and XML retained, including original failures.
  Knowledge hash unchanged/DML zero; no-send/human review remained; observed
  external-network/out-of-scope write blocks zero on every native run.
- No formal release, knowledge changes, credentials, real customers or Git
  commit/push. Original runtime PIDs remain 5012=74208, 5174=28300. HEAD remains
  cc5b6a836fa39d92708eb41eb93d976c8537fb92 with pre-existing dirty worktree.
- Next: distinguish known-product missing facts from identity ambiguity and
  remove unnecessary link requests through the existing owners; independently
  check JST code-110 classification, qualify latency and a fixed release.
  Do not invent missing dimensions or relax admission. Real accuracy is null.

## Understanding Failure Reply Boundary (2026-09-09)

| Field | Value |
|---|---|
| Task / Owner | COPILOT-UNDERSTANDING-FALLBACK-20260909; Codex |
| Priority ID | P1 Gold Conversation Quality |
| Status | development-integrated; 828 related tests passed; no runtime promotion |
| Customer outcome | A failed understanding must not expose an ungrounded legacy answer as a candidate, including wrong weight or object scope. |
| Earliest failing owner | Existing AnalysisPipeline understanding boundary preserves degraded suggested_reply and rechecks after Final without clearing regenerated text. |
| Comparable dataset and baseline | Synthetic failure injection on the same Pipeline API/copilot/replay/benchmark paths; original source SHA 824FA5D9EA42204709CF05ECD9F69C992E99F50FDBD9FF50CB1D79667C5795ED. No new live-model or customer-data run. |
| One target metric | Zero surfaced candidate texts/blocks/previews for invalid or degraded Understanding, including Final failure and repopulation. |
| Allowed modules | Existing analysis_pipeline_service.py and its entrypoint tests; existing architecture/index/roadmap/changelog. |
| Forbidden modules | No classifier prompt/type change, new reply generator, retries, provider changes, source/knowledge mutation, UI or deployment. |
| Hard stop | A valid Understanding or legitimate no-renderable-goal path regresses, an unrelated source hash changes, or tests need live credentials/data. |
| Safety and delivery invariants | Preserve evidence diagnostics, cause codes, Final execution, human review and can_send=false on failures; no media/action delivery. |
| Documentation impact | Clarify existing failure boundary in architecture; record exact regression scope, not gold-service accuracy. |
| Must do | New failing counterexamples, smallest existing-owner repair, adjacent tests and hash-guarded development integration. |
| After verification | Inspect saved outcomes/versions and record remaining broader-conversation and latency gaps. |
| Not now | Formal 5012/5174 promotion, full environment copy, real customer replay, model calls or performance architecture. real_accuracy=null; optimization_unverified=true. |

### Result

- Existing Pipeline clears invalid/degraded candidate text, blocks and
  supervisor/partial previews before Final and after its success/exception.
  Evidence/cause diagnostics remain; no alternative generator or retry.
- One existing preserve-text test corrected and 20 new cases. Original
  21 failed (1.811s); repaired 21 passed (1.397s); related 16 files 732 passed
  (12.156s); disjoint six-file Final/preview/ReplyService suite 96 passed.
  No failures/errors/skips in either final suite. Scoped git diff --check and
  source/test hashes passed. Backups/XML: C:/Users/sshuser/jst-source-export/understanding-fallback-20260909.
- Four Pipeline source values and injected failure states are regression,
  not a native HTTP/model-capacity or real-customer quality evaluation.
  Formal 5012/5174 PIDs remain 74208/28300; 8001/8795/8830 remain
  46968/70928/27364. No restart, credentials, knowledge write or send.
  Next: complex normal-path/product-switch quality. Capacity, latency and
  page acceptance remain unqualified, with real_accuracy=null.

## Gold Conversation Context (2026-09-09)

| Field | Value |
|---|---|
| Task / Owner | COPILOT-CHAT-INTELLIGENCE-20260909; Codex; P1 existing context/Understanding/Claim Resolution owners |
| Status | Follow-up fixes development-integrated; 712 related tests and 3/3 fictional native model cases passed; no production or real-customer qualification |
| Authorization | User confirmed continuation after the explicit request to submit these three fictional dialogues and corresponding product identifiers/parameters to the existing 8001 model service. No real customer history, sending, model switch or production promotion. |
| Must do | Test correction of prior guesses, net-weight follow-up and packaging dimensions through native /api/analyze with current exact-SKU Hub facts; inspect actual goals and evidence before choosing one narrow repair. |
| After verification | Same input/source/model comparison, relevant regression and hash-guarded development integration. |
| Not this run | No new reply engine, fabricated service action, real-customer replay, knowledge restoration, runtime promotion or send-authority changes. |
| Quality boundary | New fictional contexts inspired by existing high-frequency topics, not a completed 40-case evaluation. real_accuracy=null; optimization_unverified until the real-data gate qualifies. |

### Authorized Follow-up Outcome

- User approved the previously blocked model disclosure scope. Initial actual
  output chose material/net_weight correctly but supplied dimension-only scope;
  the existing validator degraded it. Corrected the conflicting prompt, without
  accepting non-dimension scope. Added the missing canonical conversation_turns
  argument to the existing evidence-builder/Composer path; four turns now arrive.
- Composer must preserve measured-object/weight meaning and omit ceremonial
  status closure. Three business files, two modified tests and one new test;
  focused pre-fix 4 failed/8 passed, final 712 related tests passed (16 files,
  zero failures/errors/skips, 12.179s, 12 new tests).
- Final native /api/analyze: three original fictional cases, one attempt each,
  3/3 passed, exclusions zero. Material reply is direct; net weight stays net;
  carton dimensions explicitly stay packaging. Supported/Composer/both Final
  pass, no-send/human-review, knowledge hash unchanged/DML zero; observed
  external-network and out-of-scope writes zero. Eight model calls each with
  18.052/16.609/17.874s latency. No general quality or latency SLO claim.
- Final runs: after-correction-20260909-112358,
  after-net-weight-followup-20260909-112419,
  after-packaging-multigoal-20260909-112438 in the existing task export directory.
- Preserve earlier failed results. Model-busy/degraded fallback remains a
  separate risk; these passing normal-path cases do not qualify it. Next:
  broader multi-turn/product-switch/helpful-next-step evaluation and latency,
  then a pinned runtime release. No formal services or knowledge data changed.

### Initial Result Before Authorization And Follow-up

- Understanding passed only the current message to its provider. It now uses
  the existing canonical normalizer/privacy projection for up to eight recent
  buyer/agent turns, 280 characters each, with explicit truncation. Dialogue
  only resolves current references; it is not evidence or action authority.
- Net weight was absent from the canonical type registry and exact Hub field
  contract. Added it without inferring from gross weight or load capacity.
  An independent negative test also required fact-level product-code equality.
- Context baseline: 5 failed/7 passed. Net-weight baseline: 2 failed/14 passed.
  Initial combined suite: 524 passed/1 failed (cross-product fact). After the
  binding repair: 525 passed, failures/errors/skips zero, 6.671s, 11 test files.
- The original three fictional full-chain cases failed. The context-only
  after batch also failed; one received model capacity 429, the others degraded
  to legacy replies. One displayed gross weight for a net-weight follow-up;
  human-review/no-send remained enforced. These are unresolved quality issues,
  not passing examples. The later net-weight/binding changes have no live-model
  result. Next diagnostic was rejected by auto-review over product context
  disclosure to the model destination; approval requested, no workaround.
- Evidence/backups: C:/Users/sshuser/jst-source-export/chat-intelligence-20260909.
  Keep all six intermediate results, regression-before-binding.xml and final
  regression.xml. No production runtime, credentials, knowledge data or Git
  commit/push changed. Next: authorized bounded model evaluation and earliest
  degradation diagnostics before any pinned production release.

## Composer Closure Contract (2026-09-09)

| Field | Value |
|---|---|
| Task / Owner | COPILOT-CLOSURE-20260909; Codex; existing ModelFirstAnswerComposerService |
| Priority / Status | P1 Gold Conversation Quality; development-integrated, scoped native diagnostic passed; no production qualification |
| Must do | Reproduce forced/repeated closure; clarify the model-owned closure contract without a second formatter; retain evidence and Final gates. Identify isolated probe network/write callers without widening access. |
| After verification | Focused and adjacent regressions, then a bounded independent product-only native API comparison; hash-guarded development integration only. |
| Not this run | No formal 5012/5174 promotion, customer replay, knowledge restoration, credentials, extra Agent owner or sending. |
| Accuracy boundary | Synthetic regression and one product check are not customer accuracy; real_accuracy=null, optimization_unverified. |

### Follow-up Owner: Hub-Only Graph Boundary

- Composer change is development-integrated. One native reply now passes both
  Final audits without a repeated closure; network/write isolation still fails.
- Task: COPILOT-HUB-ONLY-GRAPH-20260909; Codex; P1; development-integrated and verified.
- Proven caller: legacy order_product_resolver tries two JST SKU reads before
  the existing Hub-only identity/context owner. In explicit Hub-only mode,
  defer this legacy node without creating identity or changing default mode.
- The two blocked file opens target Windows os.devnull from read-only Git
  metadata. Correct only that exact diagnostic classification; arbitrary
  external files and external network connections remain denied.
- Verify focused mode/cached-input/default-path tests, then the same bounded
  native product question. No runtime promotion or customer/order accuracy claim.

### Verified Outcome

- Closure baseline: 19 failed/4 passed; Graph boundary baseline: 5 failed/3 passed.
- Final native related suite: 726 passed, zero failures/errors/skips, 23.254s;
  28 new cases. This is not the full repository suite.
- Native API baseline repeated the material answer. Composer-only repair passed
  both Final audits but retained the identified diagnostic boundary failures.
- Combined native check: HTTP 200, one supported material answer without
  repetition, both Final audits passed, can_send=false, human review=true,
  knowledge hash unchanged and DML zero. The diagnostic exited zero, with zero
  blocked network/file attempts and two classified exact os.devnull opens.
- An earlier combined attempt and a read-only preflight stopped on
  product_hub_probe_unavailable; no model request on those attempts. The source
  resumed responding without restart; stability remains unqualified.
- Three actual generated requests this run; final request observed eight local
  qwen3.8-27b calls and 21.632s. No latency/real-accuracy improvement claim.
- Remaining: title/order/tracking business cases, source stability, clean pinned
  release/page acceptance and approved real-conversation evaluation. No formal
  service, credentials, knowledge, delivery or Git commit/push change.

## Full Reply Diagnostic (2026-09-09)

| Field | Value |
|---|---|
| Task / Owner | COPILOT-FULL-REPLY-20260909; Codex; existing API/Pipeline/context owners |
| Priority / Status | P1 context and reply correctness; API repair integrated, full answer still rejected for duplicate closure |
| Must do | One baseline independent product-only synthetic question through native /api/analyze, then one post-fix check of that same input; use the existing loopback model, no customer data, source/evidence/final no-send gates unchanged. |
| After verification | Next owner is Composer customer_care_closure versus clause composition; preserve the repeated_generic_reply rejection, do not hide it with a formatter or relax evidence. Separately identify blocked proxy/cache side effects before promotion. |
| Not this run | No formal 5012/5174 switch, bulk model evaluation, real customer replay, credential changes, historical knowledge restoration or automatic send. |
| Boundary | Local model discovery changed since the previous assumption; qualification is not inferred from listing. The single review-only request is diagnostic, not production/provider or real-label acceptance. |
| Verification | Original API normalization: 12 failed/5 passed. Single-file candidate: 17 passed. Native integrated regression: 287 passed/25 warnings/6.37s. Baseline full reply lacked facts and repeated uncertainty, so it is not accepted. |
| Post-fix | Native API 200; independent SKU, 12 Hub records, 2 candidates, supported material claim; actual candidate repeated the same fact twice. Semantic audit rejected it. can_send=false, human review=true, unchanged knowledge hash and zero DML. |
| Diagnostic limits | Two full requests only. Second observed 8 existing local LLMClient calls, all qwen3.8-27b, 15.424s. First counter missed the real client, so its empty list is not zero calls; existing diagnostics prove at least Understanding/Composer/Audit calls. Two port-7897 attempts and two out-of-scope writes were denied in each run. No production or quality pass. |
| Rollback / Remaining | API original-byte backup C:/Users/sshuser/jst-source-export/full-reply-20260909/analyze_routes.before.py; new tests under tests/test_analyze_identifier_titles.py. Formal 5012/5174 unchanged; no Git commit or push. |

## Knowledge Source Candidate (2026-09-08)

| Field | Value |
|---|---|
| Task / Owner | `COPILOT-KNOWLEDGE-RUNTIME-20260908`; Codex; existing runtime readiness owner |
| Priority / Status | P1 production-correctness exception; development integrated, native source/context verification passed |
| Must do | Explicit opt-in Product Hub review-only readiness using the existing exact-SKU reader and field adapter; retain schema, source, identity, evidence and final review gates. |
| Verify next | The canonical full /api/analyze reply with independent input and final review; qualify a pinned runtime only after that gate, never promote the entire dirty tree. |
| Not this run | No historical knowledge restoration, fabricated readiness rows, model calls, new service, automatic sending or dirty-branch production promotion. |
| Discovery | The old 865 MB snapshot has 2,472 historically reviewed facts without current content hashes; its existing recovery audit explicitly rejects direct restoration. |
| Verification | Candidate 270 passed; native 270 passed (25 warnings, 5.79s). Native in-process readiness 200. Independent real SKU: identity resolved, 12 Hub records, 2 material candidates; original empty knowledge DB hash unchanged. No model/customer request. |
| Fixed blockers | Diagnostic development subject/role were missing. Exact SKU resolution still depended on an empty local catalog, and two normalizers synthesized a JST i_id from the SKU prefix. Explicit Hub mode now uses active exact-SKU/product bindings with no historical or title fallback and no namespace conversion. |
| Remaining | Full customer reply, title/order/tracking identity paths, installation interpretation and runtime promotion are not qualified. Approved real labels remain insufficient: real_accuracy=null, optimization_unverified. Production 5012/5174 PIDs are unchanged. |
| Rollback | Nine-file integration manifest and original-byte backup: C:/Users/sshuser/jst-source-export/knowledge-runtime-20260908/source-backup-20260908-212837. Default mode remains local; no runtime flag or service was changed. |

## Runtime Recovery (2026-09-08)

| Field | Value |
|---|---|
| Task / Owner | `COPILOT-5012-RECOVERY-20260908`; Codex; existing launcher only |
| Priority / Status | P1 runtime incident; transport restored, knowledge not ready |
| Result | Existing SYSTEM task starts the original release with Copilot venv; 5012 health and 5174 real-test page return 200. Other observed service PIDs unchanged. |
| Guard | Knowledge query-only and writable media workers disabled; readiness stays 503 for empty knowledge_entries, knowledge_chunks and kb_qa. No model call or fabricated data. |
| Remaining | This development branch is not promoted; original dirty bbd89e2 runtime is not a fresh clean release. Knowledge source, unified runtime and formal Pipeline answering remain unverified. |

## Manual File Check (2026-09-08)

| Field | Value |
|---|---|
| Task / Owner | `COPILOT-MANUAL-FILE-CHECK-20260908`; Codex; existing Hub reader and Context Pack |
| Priority / Status | P1 installation correctness follow-up; development integrated and verified |
| Must do | Verify bounded PDF prefix/size reads before projecting review references; preserve exact identity, variant review, no-fact and no-send boundaries. |
| Verify next | Same-product before/after file-access comparison and native regression; then reliable page interpretation and the formal entry point. |
| Not this run | No parser service, formal knowledge write, model change, automatic delivery, unrelated service restart or production switch. Real customer accuracy stays null without comparable approved labels. |
| Result | Baseline 193 / candidate 219 / native 219 passed. Same live product: 3 unchecked records before, 2 header-verified references and 1 file failure after. Single-case latency 79ms/109ms, not p50/p95 or customer-quality evidence. |
| Remaining | Reliable page interpretation, variant applicability and formal runtime/pipeline acceptance; 5012 still has no listener. |

## Installation Reference Correction (2026-09-08)

| Field | Value |
|---|---|
| Task ID | `COPILOT-INSTALLATION-ACCESS-FIX-20260908` |
| Priority / Owner | P1 user-approved correctness exception; existing Hub reader and Product Context Pack |
| Goal | Stop reporting no installation resources merely because approved PDFs are product-bound rather than SKU-bound. |
| Status | Integrated into the development checkout; native regressions passed. Two sample files are HTTP-readable and one has been visually checked. Copilot runtime promotion remains pending. |
| Must do | Preserve exact identity, source scope, safe URLs and review-only/no-send gates; integrate only the two verified source files and focused tests, protecting pre-existing worktree changes by hashes and backups. |
| Validation | 193 candidate regressions passed, including 34 new manual cases; native post-copy run independently passed 193 in 44.16 seconds. One live product returned three PDF candidates without model calls or business writes. |
| Blocker | Follow-up interactive probes prove shared access works. Two valid PDF URLs now return 206 after unchanged Hub task recovery; one dangling record still returns 500. Direct PDF text extraction damages digits; factual use and the formal customer path remain unverified. |
| Next | Resolve dangling-record handling, validate page-based extraction and SKU applicability, then test the formal user-facing path before runtime promotion. No shared-login change is needed. |
| Final recheck | Health source/output both accessible in 47ms; both valid PDFs again 206. A 4s timeout cannot diagnose failure of sequential 2.5s path checks. No second restart or long-term stability claim. |
| Not this run | No knowledge writes, generated installation facts, automatic sending, source-file relocation, credential changes, 5012/5174 switch or Git push. Follow-up recovered only the unchanged existing 8795 task. |

## Current Execution

| Field | Value |
|---|---|
| Task ID | `P1-E2-001-ISOLATED-SMOKE` |
| Owner | Codex |
| Goal | Make the formal P1 Supervisor Assist smoke check repeatable on an isolated 5012 runtime without changing Agent behavior. |
| Scope | P1 runner, contract test, test documentation, and review-only diagnostic verification. |
| Status | Complete; E2 remains blocked on authorized deidentified conversations |
| Gate | No live product or order data, no knowledge write, no delivery action, and no change to `can_send`. |

## Current Production-Correctness Exception

| Field | Value |
|---|---|
| Task ID | `P1-EXCEPTION-IDENTITY-READ-001` |
| Goal | Repair the existing sidebar-order -> JST -> exact product identity -> Product Context Pack path when JST already returns one exact outbound order item. |
| Scope | Existing JST reader, existing identity resolver, existing Product Context Pack, Product Hub read bridge, and their contract tests. |
| Status | Candidate verification complete; clean-commit integration remains pending because the current worktree contains unrelated changes. |
| Gate | Exact returned identity only; no title/substring/first-row fallback, no formal-knowledge write, no new reply owner, and `can_send=false`. |

This is a user-facing correctness exception, not a P2 promotion or a customer-
quality claim. The isolated query-only check proved the existing flow can carry
one exact JST outbound-item match through exact SKU mapping, reviewed Hub facts,
and canonical selected evidence. It did not evaluate response quality or change
the P1 E2 approval requirement.

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

1. `P1-E2-001` cannot claim real quality until a data owner authorizes a
   deidentified long-conversation review package and independent labels.
2. The P1 frozen-owner boundary prevents inventing a policy outcome, product
   fact, compensation, refund, replacement, or promised completion step.
3. No test result may promote the current Supervisor Assist runtime to
   autonomous sending.

## Immediate Queue

1. `P1-E2-001A`: data owner creates an authorized, versioned, hashed,
   deidentified review package outside the repository; no raw conversations or
   label answers enter an Agent prompt.
2. `P1-E2-001B`: run the existing formal Pipeline on a query-only snapshot,
   retaining `can_send=false` and human review.
3. `P1-E2-001C`: independent reviewers record completeness, continuity,
   factual restraint, unresolved coverage, and handoff needs.
4. After P1 acceptance, create the P2 dynamic-evidence source-of-truth ADR.

## Completion Record

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
