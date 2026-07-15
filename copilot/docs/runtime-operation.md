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

The default formal production boundary remains:

- `COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED=false`
- strict decision provider unqualified/disabled
- supervisor preview read-only

## Ports And Health

Use 5012 and 5174 for a pre-switch check. Set `COPILOT_WEB_PORT=5012` for the
backend. Start Vite with `VITE_API_PROXY_TARGET=http://127.0.0.1:5012` and a
different development port. Verify `http://127.0.0.1:5012/health` before
touching 5011 or 5173.

After the alternate runtime is healthy, record the old 5011/5173 process IDs
and launch commands. Only then stop those two old project processes and start
the same runtime worktree on 5011/5173. If health or the public route fails,
restart the recorded old commands.

Supervisor Preview is a review-only projection. It must retain
`can_send=false`, `requires_human_review=true`, and
`used_for_final_reply=false`; it cannot replace the formal suggestion or add a
delivery block.
