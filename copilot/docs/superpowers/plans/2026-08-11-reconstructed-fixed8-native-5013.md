# Reconstructed Fixed-8 Native 5013 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改生产 Agent 的前提下，用当前干净提交、隔离 query-only 知识快照和正式 `/api/analyze` 完成一次可信的重建 Fixed-8 原生模型工程基线。

**Architecture:** 继续复用唯一 `AnalysisPipeline`、现有 P1 Runner 和 `conversation-reconstructed-v1` 数据合同。生产默认开关保持关闭；隔离 5013 按既有 Runner 合同临时开启 Formal Evidence Convergence 与 Model-first Composer，所有候选固定人工复核且 `can_send=false`。

**Tech Stack:** Python 3.12、Flask/Waitress、SQLite query-only、PowerShell 子进程编排、pytest、Git。

## Global Constraints

- 不停止或修改 5011/5012。
- 不修改生产 Agent、Prompt、Graph、Evidence、Safety、Delivery、`can_send` 或回复 Owner。
- 不增加 retry、repair、fallback、模型调用角色或平行评测系统。
- Provider 密钥只进入本轮子进程环境，不写入仓库、环境文件、报告、日志或 Windows 用户环境。
- 运行产物、数据库快照和 DML 诊断只写入 `D:\桌面文件\客服\.codex-runtime`，不提交。
- 重建数据只能形成工程基线；`real_customer_accuracy=null`、`optimization_unverified=true`、`original_fixed8_restored=false`。

---

### Task 1: Freeze The Evaluation Contract

**Files:**
- Modify: `docs/superpowers/specs/2026-08-11-reconstructed-fixed8-native-5013-design.md`
- Create: `docs/superpowers/plans/2026-08-11-reconstructed-fixed8-native-5013.md`
- Modify: `docs/index.md`

**Interfaces:**
- Consumes: `scripts/run_p1_gold_conversation_baseline.py::_runtime_preflight()` and `_validate_runtime_binding()`.
- Produces: one reviewed operational contract that distinguishes production defaults from isolated P1 flags.

- [ ] **Step 1: Record the isolated flag contract**

Document that production keeps both features disabled, while isolated 5013 requires:

```text
COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED=true
COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED=true
COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY=true
```

- [ ] **Step 2: Run governance and whitespace checks**

```powershell
& $Python -m pytest tests/test_docs_governance.py -q
git diff --check
```

Expected: docs governance passes and no whitespace errors are reported.

- [ ] **Step 3: Commit only the design and plan checkpoint**

```powershell
git add docs/index.md docs/superpowers/specs/2026-08-11-reconstructed-fixed8-native-5013-design.md docs/superpowers/plans/2026-08-11-reconstructed-fixed8-native-5013.md
git commit -m "docs: plan native reconstructed fixed8 baseline"
```

Expected: worktree is clean and runtime identity can be pinned to the new commit.

---

### Task 2: Prepare A Query-Only Runtime Capsule

**Files:**
- Create outside Git: `D:\桌面文件\客服\.codex-runtime\native-fixed8-v1\orchestrate_native_fixed8.ps1`
- Create outside Git: `D:\桌面文件\客服\.codex-runtime\native-fixed8-v1\runtime_binding.json`
- Create outside Git: `D:\桌面文件\客服\.codex-runtime\native-fixed8-v1\dml.jsonl`
- Create outside Git: `D:\桌面文件\客服\.codex-runtime\native-fixed8-v1\knowledge_snapshot.sqlite`
- Read: `tests/fixtures/p1_conversation_reconstructed/v1.json`
- Read: `tests/fixtures/p1_conversation_reconstructed/v1.manifest.json`
- Read: `data/knowledge_base.db`

**Interfaces:**
- Consumes: current Git HEAD, runtime source hash, fixed fixture/manifest, operator-approved secret file supplied to the orchestrator at invocation.
- Produces: frozen pre-run manifest, immutable SQLite snapshot, DML diagnostics, runtime binding and a hidden 5013 process.

- [ ] **Step 1: Verify process and source identity before startup**

Probe `/api/health`, `/api/runtime/version`, and `/api/runtime/readiness` on 5011, 5012 and 5013. Refuse startup if 5013 is already occupied by a different commit. Record only status, commit, source hash and readiness; do not record URLs or credentials in reports.

- [ ] **Step 2: Prepare a fresh snapshot with the existing Runner**

Run the following through the external orchestrator after injecting a newly generated in-memory audit HMAC and the approved Provider credential:

```powershell
& $Python scripts/run_p1_gold_conversation_baseline.py `
  --operation prepare `
  --dataset tests/fixtures/p1_conversation_reconstructed/v1.json `
  --dataset-manifest tests/fixtures/p1_conversation_reconstructed/v1.manifest.json `
  --dataset-contract conversation-reconstructed-v1 `
  --output-dir $RuntimeRoot/preflight `
  --source-knowledge-db data/knowledge_base.db `
  --snapshot-db $RuntimeRoot/knowledge_snapshot.sqlite `
  --dml-diagnostics $RuntimeRoot/dml.jsonl
```

Expected: scenario count 8, privacy findings 0, snapshot and source fingerprints present, formal knowledge DML 0.

- [ ] **Step 3: Start only the isolated 5013 process**

The external orchestrator sets these child-process values without printing them:

```text
COPILOT_WEB_HOST=127.0.0.1
COPILOT_WEB_PORT=5013
COPILOT_RUNTIME_ENV=development
COPILOT_ADMIN_AUTH_MODE=development_loopback
COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY=true
COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED=true
COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED=true
COPILOT_KNOWLEDGE_DB_PATH=$RuntimeRoot/knowledge_snapshot.sqlite
COPILOT_FORMAL_KB_DML_DIAGNOSTIC_PATH=$RuntimeRoot/dml.jsonl
```

It starts `run_prod.py` with `Start-Process -WindowStyle Hidden`, leaving 5011/5012 untouched.

- [ ] **Step 4: Freeze runtime binding**

Read 5013 runtime version/readiness and write `p1-runtime-knowledge-binding/v1` with the exact snapshot file hash, source tree hash, PID, port 5013 and required true flags. Reject `ready=false`, dirty source, source drift, non-query-only knowledge, provider/model mismatch or any DML.

---

### Task 3: Run The One-Case Infrastructure Gate

**Files:**
- Create outside Git: `D:\桌面文件\客服\.codex-runtime\native-fixed8-v1\run_one_case.py`
- Create outside Git: `D:\桌面文件\客服\.codex-runtime\native-fixed8-v1\one_case_observation.json`

**Interfaces:**
- Consumes: the first immutable scenario through the existing dataset preflight and `compare_model_first_answer_composer._agent_payload()`.
- Produces: one minimal, sanitized observation and a go/no-go decision for the full run.

- [ ] **Step 1: Build the first payload without modifying the fixture**

The external probe imports the existing Runner/evaluator, validates the full dataset contract, selects index 0 only after validation, and constructs the payload with `_agent_payload()`. It scans the payload for evaluation-only labels, rubric text, expected replies and prohibited identity fields before any HTTP call.

- [ ] **Step 2: Call the formal API exactly once**

POST the payload to `http://127.0.0.1:5013/api/analyze` with the existing timeout. Do not retry on HTTP, Provider, schema or Pipeline failure.

- [ ] **Step 3: Validate the infrastructure gate**

Require HTTP success, non-empty customer-visible reply, valid Pipeline diagnostics, `can_send=false`, `requires_human_review=true`, DML count 0 and unchanged runtime source hash. Write only the sanitized observation and hashes outside Git. Any failure stops before 8x1.

---

### Task 4: Run The Immutable Eight-Case Baseline

**Files:**
- Create outside Git: `D:\桌面文件\客服\.codex-runtime\native-fixed8-v1\full-run\`
- Read: `scripts/run_p1_gold_conversation_baseline.py`

**Interfaces:**
- Consumes: the same 5013 process, provider identity, fixture, manifest, snapshot, runtime binding and feature flags used by 1x1.
- Produces: eight case observations, projection capsules, checkpoint, final report and integrity summary.

- [ ] **Step 1: Execute the existing Runner once**

```powershell
& $Python scripts/run_p1_gold_conversation_baseline.py `
  --operation run `
  --dataset tests/fixtures/p1_conversation_reconstructed/v1.json `
  --dataset-manifest tests/fixtures/p1_conversation_reconstructed/v1.manifest.json `
  --dataset-contract conversation-reconstructed-v1 `
  --analyze-url http://127.0.0.1:5013/api/analyze `
  --output-dir $RuntimeRoot/full-run `
  --expected-commit $Head `
  --expected-source-sha256 $SourceHash `
  --expected-model $FormalModel `
  --snapshot-db $RuntimeRoot/knowledge_snapshot.sqlite `
  --pre-run-manifest $RuntimeRoot/preflight/pre_run_manifest.json `
  --runtime-binding $RuntimeRoot/runtime_binding.json `
  --dml-diagnostics $RuntimeRoot/dml.jsonl `
  --timeout 180
```

- [ ] **Step 2: Recompute report integrity offline**

Require exactly 8 cases and 8 trials, matching checkpoint/case/report hashes, source drift false, Provider/HTTP/schema errors 0, DML 0, `can_send=true` count 0 and human review count 8. Quality failures remain valid baseline findings and must not be rerun.

- [ ] **Step 3: Classify the earliest business owner**

Using only the report observations, summarize current question/history, authoritative goals, selected evidence, full candidate reply, Final/Audit reason codes, latency and call counts. Classify each failure to the earliest one of Turn Understanding, Context, Identity, RAG/Evidence, Claim Resolution, Composer or Final/Audit without adding sample-specific rules.

---

### Task 5: Regression, Documentation And Recovery Checkpoint

**Files:**
- Modify only if the valid baseline completed: `docs/agent-core-priority-plan.md`
- Modify only if the valid baseline completed: `docs/architecture-overview.md`
- Modify only if the valid baseline completed: `docs/module-index.md`
- Modify only if the valid baseline completed: `docs/index.md`

**Interfaces:**
- Consumes: verified 8x1 report and synthetic safety regression.
- Produces: accurate project status, a scoped commit, remote push and an external Git bundle.

- [ ] **Step 1: Run focused regression**

```powershell
& $Python -m pytest tests/test_p1_reconstructed_conversation_baseline.py tests/test_p1_gold_conversation_baseline.py tests/test_analysis_pipeline_entrypoints.py tests/test_final_answer_auditor.py tests/test_final_response_orchestrator.py tests/test_docs_governance.py -q
& $Python -m py_compile scripts/run_p1_gold_conversation_baseline.py scripts/compare_model_first_answer_composer.py
git diff --check
```

- [ ] **Step 2: Run versioned synthetic safety regression**

Initialize a fresh external benchmark SQLite database from `active_benchmark_synthetic_v1`, then run the same fixture as smoke 5 and full 22. Require smoke `5/5`, full `22/22`, `can_send=true` count 0 and `requires_human_review=true` count 22.

- [ ] **Step 3: Verify JSON portability**

Load the authoritative fixture, manifest, one-case observation, checkpoint and full report with Python `json.load` and PowerShell `ConvertFrom-Json`.

- [ ] **Step 4: Update status without accuracy inflation**

Record the native 8x1 infrastructure result, earliest business owner and limitations. Preserve `real_customer_accuracy=null`, identify the source as reconstructed, and state that production feature flags and Autonomous Send remain disabled.

- [ ] **Step 5: Commit, push and bundle**

Stage only the listed docs and any directly required evaluation tests. Confirm no outputs, DB, `.env`, secrets or generated frontend files are staged, commit, push the current branch, and create a verified Git bundle under `D:\桌面文件\客服\.codex-runtime` with its SHA-256 recorded in the final report.
