# Runtime Operation

## Active Runtime Worktree

Run the local service from a dedicated clean release worktree, never from a
source worktree that may contain uncommitted work. During Phase 0.7C.3A the
active loopback runtime is
`D:\桌面文件\客服\copilot-runtime-gold-review-c3\copilot`; its
`/api/runtime/version` response is the source of truth for the serving commit.
The historical `D:\桌面文件\客服\copilot` and older `copilot-runtime` worktrees
must not be assumed to be the active service source.

Before updating a release worktree, check that its status is clean and that the
target branch/commit is deliberate:

```powershell
$runtime = 'D:\桌面文件\客服\copilot-runtime-gold-review-c3\copilot'
git -C $runtime status --short
git -C $runtime rev-parse HEAD
```

## Local Configuration And Data

`run_prod.py` reads `copilot/.env`. Keep that file ignored and local. Do not
put keys, DSNs, cookies, or database files in Git.

The formal LLM uses the OpenAI-compatible transport in `app/llm/client.py`.
For a mainland-China MiniMax account, use `https://api.minimaxi.com/v1` with
`MiniMax-M3`; the international `api.minimax.io` endpoint is a separate
credential domain. M3 thinking is disabled for the short formal customer-service
calls, while MiniMax reasoning fields are still separated from response content.
The transport also enforces a safe output budget and rejects empty or truncated
responses. For JSON callers it accepts only a complete parseable object and does
not repair partial JSON. Keep the key only in the ignored runtime `.env`, and
qualify the exact endpoint and model before switching traffic.

For a first startup or a release smoke test, point `COPILOT_KNOWLEDGE_DB_PATH`
at a SQLite backup made with the SQLite backup API. Disable resident media
synchronization and automatic media refresh in that process. Do not point an
unverified runtime at the only production database.

The local ignored `.env` owns the concrete runtime path. It must point at a
non-empty, read-only-verified runtime database; do not rely on the default
`data/knowledge_base.db` placeholder after a restart. Before traffic is
accepted, verify `/api/runtime/readiness`: it checks the configured database
through a SQLite `mode=ro` URI, requires `knowledge_entries`,
`knowledge_chunks`, and `kb_qa`, and reports only basename, `content_sha256`,
`schema_fingerprint`, and counts. A missing, unreadable, incomplete, empty, or
changed-during-scan database is not ready.

`content_sha256` is a SHA-256 of the actual SQLite file bytes. It proves that
the runtime is answering from the intended database contents, not merely a
database with the same schema. `schema_fingerprint` is a SHA-256 of the sorted
table names and only detects schema differences. The content hash is cached per
process using the resolved path, file size, and `mtime_ns`; the file is
re-scanned only when metadata changes. If the file changes while it is being
read, readiness returns `ready=false` with
`knowledge_db_changed_during_fingerprint`.

The isolated benchmark runner is the sole exception: it sets an inherited
process-only evaluation flag and must prove its own versioned fixture metadata.
That fixture state is never available to the web runtime or formal QA runner.

The default formal production boundary remains:

- `COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED=false`
- strict decision provider unqualified/disabled
- supervisor preview read-only

The ignored runtime `.env` must keep
`COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED=false` until the real-derived
offline and API validation gates pass. A query-only Phase 0.8C inventory found
393 products with at least one eligible fact and 428 eligible facts. The
deterministic qualification fixture selected 12 products and 15 facts across
three reviewed low-risk types (`material`, `dimensions`, and `gross_weight`) and
validated 15/15 facts through Pack, canonical selection, admission, claim
resolution, and a review-only preview. Dimension attribute-slot coverage remains
incomplete. This is a Tier B capability probe, not customer accuracy and not
permission to enable the flag on 5011.

After the delivery-boundary correction, the isolated Phase 0.8C candidate
passed the three 1x1 API probes and the five-product by three-question slice
passed 15/15. All cases stayed review-only, no media block was created from a
candidate reference, and protected database counts remained unchanged. The
synthetic benchmark also remained 5/5 and 22/22 with zero auto-send cases.
These are capability and safety results, not customer accuracy. Keep the formal
flag disabled on 5011 until the independent Gold/Tier A gate is complete; do
not repair missing `detachable` or dimension attribute scope with placeholders,
visual inference, or broad role promotion.

Phase 0.8D owns an explicit Gold-30 supervisor queue and authoritative report
manifest under ignored `outputs/`. Tier A must not start unless the independent
label store contains at least 30 approved atomic claims across five domains and
each claim has a matching supervisor/admin audit event. With fewer approvals,
`run_real_accuracy_baseline.py --approved-only` exits `2` before any Agent call.
The current Gold v0.2 approval count is zero. Phase 0.8E adds the supervisor SPA route and
limits its API, draft creation, and batch review submission to the deterministic
Gold-30 queue. The isolated 5012 canary must report `ready`, matching boot/end
source hashes, and `source_tree_drift=false`; in Cloudflare Access mode both the
page and API must reject an unauthenticated request with 401. Test-only loopback
or injected principals may verify rendering and role contracts, but they do not
replace a real signed Access browser session. Gold v0.1 remains a read-only
historical dataset and label store; Gold v0.2 uses its own ignored database and
does not import v0.1 approval state. Runtime configuration must define the Gold
artifact and label database exactly once. The safe configuration diagnostic
reports only file names, hashes, counts, and duplicate-definition status.

Production 5011 now runs from the dedicated clean `copilot-release-5011`
worktree pinned to `97ebb637`. It reports `clean_commit`, `ready=true`,
`source_tree_drift=false`, `MiniMax-M3`, and Formal Evidence Convergence off.
The release was first verified on a temporary port and then observed for 60
seconds after replacement. Development-tree Git activity must not change its
source hash. Public `inhe.cc.cd` health/version/readiness are the active checks;
the historical `inhe.ccwu.cc` hostname currently returns Cloudflare 530 and is
not an application-health authority. Do not mutate the release worktree or
enable Formal Evidence Convergence until a separate promotion decision.

The 5012 review canary uses Cloudflare Access mode. Missing assertions and
forged role/name headers return 401. Without a real signed supervisor session,
the workflow stops at `awaiting_real_supervisor_approval`; development
principal tests are not authoritative approvals.

The v4.2 long-conversation review workbench is served at
`/ask/high-quality-conversation-review` and reads the immutable source from
`COPILOT_HQ_LONG_CONVERSATION_REVIEW_SET_PATH`. Human decisions are stored only
in the ignored SQLite path configured by
`COPILOT_HQ_LONG_CONVERSATION_LABEL_DB`; that path must differ from
`COPILOT_KNOWLEDGE_DB_PATH`. `COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY`
pseudonymises the human actor in the append-only audit trail. Reviewer sessions
may save and submit; approval and rejection require a signed Cloudflare Access
supervisor/admin session and a valid browser origin. There is no bulk-approval
route. The source JSON, formal knowledge database, Agent, and 5011 are not
modified by this workflow.

The immutable source validator owns schema, hashes, identifiers, privacy, text
quality, and conversation/claim structure only. Source `review` fields never
authorize evaluation; embedded approved/rejected decisions, approval audits,
supervisor/admin identity, Cloudflare authentication claims, or optimistic-lock
approval versions fail validation as `embedded_authoritative_review_forbidden`.
Address scanning is field-bounded and requires a concrete address marker,
administrative chain, or street/building number; room and space wording such as
`卧室` or `省空间` is not itself an address. Manifest text remains in the privacy
scan while only explicitly typed hashes and pseudonymous identifiers are exempt.
Only `build_approved_high_quality_long_conversation_manifest.py`, backed by the
independent label database and its append-only audit history, may return
`agent_call_allowed=true` or `accuracy_claim_allowed=true`. Until 26/26 pass,
the command exits `2` and real accuracy remains `null`.

The approved-only runner evaluates privacy and the independent approval gate
before requiring the Gold source-link HMAC. This keeps the current zero-approval
state explicit as `awaiting_supervisor_approval` with exit code 2 and no Agent
call. Once the approval gate passes, a trusted ignored runtime must provide the
original Gold HMAC for source joining; missing it remains fail closed.

## Management Access

The public Tunnel is not an authorization layer. Before a management UI or API
is exposed, configure an ignored runtime environment with
`COPILOT_ADMIN_AUTH_MODE=cloudflare_access`, the Cloudflare Access team domain,
the application audience, a non-empty verified-claim role-map JSON, allowed
browser origins, and `COPILOT_ADMIN_AUDIT_HMAC_KEY`. Do not put those concrete
values in Git, reports, or screenshots. Every human role, including
`operator`, must have an explicit allowlist mapping; an authenticated but
unmapped identity is denied.

Create a Cloudflare self-hosted Access application for management routes and
separate its user/group policies from any public customer endpoint. Service
automation must use an Access service token and an explicit local route
allowlist; it cannot obtain permission from a request role header. The origin
still verifies every received assertion, so Access misrouting fails closed.

`/health`, runtime version, and runtime readiness are public liveness
diagnostics only. They expose a status, a redacted readiness reason code, and
the deployment commit where applicable; they never expose database fingerprints,
knowledge counts, feature flags, process details, or Access configuration
status. Customer-runtime access is limited to the formal analysis POST
and feedback POST; order, product, SKU, live-query, metrics, stats, feedback
lists, and sidecar context are protected. `/api/runtime/readiness` exposes
only `ready`, `status`, and redacted reason codes; in a production runtime
it is not ready if Access configuration, origins, role map, audit HMAC, or
route governance is absent. A local `development_loopback` mode is for an
explicitly marked development/test process bound to loopback with a loopback
Host and no forwarded/Cloudflare client headers; it must never be used behind
the public Tunnel.

`GET /api/admin/runtime/diagnostics` is the authenticated `admin_only`
diagnostic endpoint. It may show database readiness fingerprints, counts, and
component versions, but never secrets, assertions, role-map values, Access
audience values, or environment dumps. Formal QA that needs a database
fingerprint must call this endpoint with a short-lived Access assertion from a
local environment variable; it must not recover the fingerprint from public
version or readiness responses.

### Temporary Public Management Override

For an explicitly approved short-term public deployment, set both
`COPILOT_ADMIN_AUTH_MODE=public_open` and
`COPILOT_PUBLIC_OPEN_ACKNOWLEDGED=true` in the ignored runtime `.env`. This
deliberately maps every request to the local `admin` role so the existing UI is
usable before a project-owned login flow is available. It exposes management
reads and writes to anyone who can reach the public URL. The mode is disabled
unless both values are present, is reported as `public_open_mode` by runtime
diagnostics, and must be removed when application login/RBAC is introduced.

### Cloudflare Access Rollout

The current safe deployment state is `blocked_external_configuration` until a
signed-in Cloudflare administrator creates matching policies for both public
hostnames. Keep application-layer route RBAC enabled during this step. Because
the customer analysis and feedback POST contracts may need a non-browser
caller, use path-scoped Access applications for management UI and management
APIs rather than silently protecting every `/ask/*` request. Do not create an
`Everyone` allow policy or a global bypass. A future canonical-domain decision
may retire one hostname only after both domains have equivalent policies and
the live login/RBAC checks have passed.

### Tunnel Connector Gate

An HTTP `530` page carrying Cloudflare error `1033` is a Tunnel connectivity
failure, not an application `502`: Cloudflare cannot find a healthy
`cloudflared` connector for the hostname. Confirm the tunnel is `Active` in the
Cloudflare dashboard, then inspect connector logs and outbound network policy.
Only after the connector is healthy should an origin `502` be diagnosed as an
ingress-to-local-service failure. Do not work around `1033` by publishing a
management route without Access or by changing the application authorization
mode. The public management acceptance sequence is: Tunnel healthy, Access
login, application JWT/RBAC, then reviewer/supervisor workflow.

## Ports And Health

Use 5012 and 5174 for a pre-switch check. Set `COPILOT_WEB_PORT=5012` for the
backend. Start Vite with `VITE_API_PROXY_TARGET=http://127.0.0.1:5012` and a
different development port. Verify `http://127.0.0.1:5012/health` before
touching 5011 or 5173.

After the alternate runtime is live, check both `/health` and
`/api/runtime/readiness`. Liveness stays HTTP 200 for diagnostics; readiness
returns HTTP 503 until the formal knowledge database is usable. Only then
record the old 5011/5173 process IDs
and launch commands. Only then stop those two old project processes and start
the same runtime worktree on 5011/5173. If health or the public route fails,
restart the recorded old commands.

Supervisor Preview is a review-only projection. It must retain
`can_send=false`, `requires_human_review=true`, and
`used_for_final_reply=false`; it cannot replace the formal suggestion or add a
delivery block.

## Tier D Evaluation Runtime

Tier D uses an isolated 5012 candidate and never changes the long-running 5011
process. Its runner pins the 5012 boot source hash, its own evaluator source
hash, exact feature flags, formal model, dataset manifest, and both evaluator
qualification reports. Formal evidence convergence remains disabled.

Before reading the dataset, the runner verifies complete formal,
buyer-simulator, and transcript-grader identities, then performs a minimal
non-customer completion against the exact formal provider. Authentication,
quota, rate-limit, timeout, truncation, or identity failure is an infrastructure
blocker. Do not accept deterministic Pipeline fallback as proof that the
configured formal model ran. Grader and simulator must also pass serial and
two-worker long-context qualification before 9x2 begins.

Different models behind one provider host are permitted only as a
`single_provider_family_diagnostic`. Such a run records
`same_provider_family_risk=true` and `independent_acceptance_allowed=false`; it
cannot be described as an independent-model acceptance result.

The fixed run is valid only with nine uniquely resolved sources and eighteen
completed trials. Checkpoints are atomic but remain evaluation output and are
not committed. Stop 5012 and any temporary evaluator-only provider process
after a blocked or completed run; keep 5011 untouched.

For the Phase 0.8A candidate, MiniMax M3 is qualified only for the isolated
5012 evaluation runtime. Its OpenAI-compatible `json_object` transport permits
one repeat request only when a complete response cannot be parsed as a JSON
object; empty, truncated, authentication, quota, timeout, and rate-limit
failures remain fail-closed. The formal-provider readiness probe must use this
same transport adapter rather than a raw SDK request with a different token or
thinking configuration.

The first infrastructure-valid 9x2 baseline completed 18/18 trials with zero
simulator errors and matching report/checkpoint hashes. Its 0/18 exploratory
pass result is retained as a diagnostic: it does not authorize changing 5011,
enabling formal evidence convergence, or loosening Safety/Delivery contracts.
The candidate process must be stopped after evaluation. That report is now
historical and marked `superseded_by_provider_change`; it is not the current
provider baseline.

### Phase 0.8B.1 stop-loss contract

Evidence Action is paused and unqualified. Runtime identity reports
`evidence_action_shadow=false` and `paused_not_qualified` even when a stale
environment flag is present. Pipeline does not call Action Policy, does not
produce a counterfactual preview, and cannot use that experiment to alter any
formal response field.

Tier D uses the smaller execution shape: canonical conversation, formal Agent,
deterministic turn checks, and at most one qualified transcript-semantic grade
per trial. If no grader is qualified, deterministic diagnostics remain usable
but semantic coverage and overall pass are `null`. No per-turn Action Provider
or counterfactual grader is part of the run.

Provider gates are layered: qualification, then 1x1, then 3x1, then fixed 9x2.
The current MiniMax M2.7-highspeed buyer candidate failed both strict-schema and
tool-call qualification with zero successful attempts, so 1x1, 3x1, grader
qualification, and 9x2 were not started. The timeout and schema contracts were
not relaxed.

### Fixed real-turn OFF/ON replay

The Phase 0.8G replay does not use a buyer simulator. It runs a versioned set of
fixed, privacy-checked real buyer turns through isolated port 5012. Restart 5012
after every OFF/ON switch and verify `/api/runtime/version`; do not infer the
active flag from the launch command. The runner pins commit, boot/current source
hash, model, feature flags, formal knowledge DB fingerprint, dataset hash, and
its own source hash. Checkpoints and reports are ignored evaluation artifacts.

Run the 1-, 3-, then 9-scenario tiers only when the prior OFF/ON pair has no
execution error, empty reply, drift, label leak, knowledge write, unsupported
media promise, media-role mismatch, or unsafe automatic send. Audit issues
`unsupported_media_claim` and `media_role_mismatch` are both media-role
failures, even when the deterministic text scanner does not find an explicit
send promise. Knowledge-write detection hashes the rows of `kb_product`,
`kb_qa`, `knowledge_entries`, and `knowledge_chunks` through a query-only
connection; whole-file SQLite hashes are not used because evaluation and trace
tables share the file. The initial diagnostic found a media-role failure at
three scenarios. After evaluator correction, an earlier run observed
`kb_product` changes during the request window. Phase 0.8G.1 traced the earliest
write owner to the resident DingTalk media refresh started by application boot:
the refresh invokes the explicit media sync path and commits `kb_product` rows.
The analysis request itself issued no formal-knowledge DML in isolated controls.

Evaluation runtimes must set `COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY=true` for
every pooled knowledge-database connection. Query-only mode skips resident
media refresh/sync startup, verifies `PRAGMA query_only=1`, and lets SQLite
reject any remaining DML. Optional diagnostics record only operation class,
logical table, HMAC correlation, thread/task kind, and a sanitized application
stack. SQL text, parameters, and field values are prohibited. A DML attempt
fails replay even when SQLite blocks it and final row hashes are unchanged.

Knowledge comparison uses an SQLite backup snapshot plus deterministic
row-level fingerprints for the four formal knowledge tables. Rows are
primary-key ordered; JSON, numbers, nulls, text, and timestamps are canonicalized
before keyed hashing. Reports expose only HMAC row identities, changed column
names, and before/after hashes. Whole-file SQLite hashes are not evidence of a
knowledge change because WAL, page layout, statistics, and non-knowledge tables
may change independently.

The writable owner remains the explicit governance/sync workflow. Agent API,
Pipeline, replay, readiness, and evidence admission are formal-knowledge
readers. After each evaluation run, stop 5012 and keep production convergence
disabled unless a separate promotion decision is approved.
