# Runtime Operation

## Canonical Runtime Directory

Use `D:\桌面文件\客服\copilot-runtime\copilot` as the local runtime worktree.
The historical `D:\桌面文件\客服\copilot` worktree may contain uncommitted work and
must not be used as the service source directory.

The runtime worktree tracks `origin/codex/safe-github-sync`. Update it only
after checking that its status is clean:

```powershell
git -C D:\桌面文件\客服\copilot-runtime status --short
git -C D:\桌面文件\客服\copilot-runtime pull --ff-only
```

## Local Configuration And Data

`run_prod.py` reads `copilot/.env`. Keep that file ignored and local. Do not
put keys, DSNs, cookies, or database files in Git.

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
5-product by 4-fact validation gate passes. A synthetic 20-fact vertical slice
is a code-contract check only; it cannot justify enabling the formal flag on
5011. Process-only 5012 experiments may enable the flag after 5011 is healthy,
but must stop after verification.

As of 2026-07-16, the query-only inventory found zero products with all four
required reviewed low-risk facts (`material`, `dimensions`, `gross_weight`, and
`detachable`). Real-derived promotion is therefore
`blocked_by_product_data`. Placeholder, packaging-only, or visually inferred
values must not be repaired automatically or treated as product facts.

## Management Access

The public Tunnel is not an authorization layer. Before a management UI or API
is exposed, configure an ignored runtime environment with
`COPILOT_ADMIN_AUTH_MODE=cloudflare_access`, the Cloudflare Access team domain,
the application audience, a verified-claim role-map JSON, and allowed browser
origins. Do not put those concrete values in Git, reports, or screenshots.

Create a Cloudflare self-hosted Access application for management routes and
separate its user/group policies from any public customer endpoint. Service
automation must use an Access service token and an explicit local route
allowlist; it cannot obtain permission from a request role header. The origin
still verifies every received assertion, so Access misrouting fails closed.

`/health` stays a public liveness endpoint. `/api/runtime/readiness` exposes
only `admin_auth_mode`, `admin_auth_ready`,
`access_audience_configured`, and `insecure_header_auth_disabled`; in a
production runtime it is not ready if Access configuration is absent. A local
`development_loopback` mode is for an explicitly marked development/test
process bound to loopback only and must never be used behind the public Tunnel.

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
