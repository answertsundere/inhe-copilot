# Testing And Acceptance

## Purpose

This guide separates regression safety, local API smoke checks, and real
quality evaluation. A passing synthetic test proves a contract regression did
not occur; it does not prove customer accuracy or authorize automatic replies.

## Preconditions

Run commands from the project root. Use Python 3.10 or later. Keep credentials
only in the ignored `.env` file or process environment; never paste keys into a
test report. Do not use the production 5011 runtime for development testing.

```powershell
Set-Location 'D:\桌面文件\客服\copilot-rebuild\copilot'
python --version
python -m pytest --version
```

If dependencies are missing, create an isolated environment and install the
declared requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 1. Fast Contract Regression

Run this before manual API testing. It exercises the formal API contract,
current P1 goal/context behavior, and the human-reviewed long-conversation
workbench without using live product facts or external tools.

```powershell
python -m pytest -q `
  tests/test_acceptance_p0_regressions.py `
  tests/test_fact_type_alias_service.py `
  tests/test_semantic_fact_type_service.py `
  tests/test_p1_gold_conversation_baseline.py `
  tests/test_high_quality_long_conversation_review_workbench.py
python -m compileall -q app tests scripts
```

Expected result: pytest exits `0`; compileall exits `0`. A pass is regression
evidence only. Do not label it real customer accuracy.

For a broader pre-merge check, run:

```powershell
python -m pytest tests -q
```

## 2. Development-Loopback API Smoke Check

Use a non-production port and a query-only knowledge configuration. The
development run is for a human to inspect a review-only draft; it must not be
connected to a delivery adapter.

```powershell
$env:COPILOT_WEB_HOST = '127.0.0.1'
$env:COPILOT_WEB_PORT = '5012'
$env:COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY = 'true'
$env:COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED = 'false'
python run_web.py
```

In a second PowerShell window, check liveness and submit a non-factual,
deidentified example:

```powershell
Invoke-RestMethod 'http://127.0.0.1:5012/api/health'

$body = @{
  conversation_id = 'manual-smoke-001'
  message = '我前面问的安装步骤还有一个地方没有明白，请帮我整理需要人工确认的部分。'
  conversation_history = @(
    @{ role = 'customer'; text = '我正在安装，已经看过说明。' },
    @{ role = 'assistant'; text = '我会基于已有说明协助你核对。' }
  )
} | ConvertTo-Json -Depth 6

if (-not (Invoke-RestMethod 'http://127.0.0.1:5012/api/health').ready) {
  throw 'runtime_not_ready: configure the isolated knowledge/auth runtime before functional reply review'
}

$response = Invoke-RestMethod 'http://127.0.0.1:5012/api/analyze' `
  -Method Post -ContentType 'application/json' -Body $body
$response | ConvertTo-Json -Depth 20
```

Accept only a response that is a review-only suggestion. Inspect that
`can_send` is `false`, `requires_human_review` is `true`, and no reply asserts
an unverified product, policy, order, compensation, refund, replacement, or
media-delivery result. Stop the test server with `Ctrl+C`.

If `/api/health` reports `ready=false`, treat it as a configuration/readiness
diagnostic. Do not submit it as a functional quality check or bypass it by
enabling production flags or changing the production worktree. If the start log
reports that `COPILOT_LLM_API_KEY` is absent, it is expected that no
human-reviewable LLM draft can be produced; configure the ignored credential in
the isolated runtime, then repeat the test.

## 3. P1 E2 Authorized Long-Conversation Gate

Only the data owner may provide the review data. Keep the authorized,
deidentified source file and label database outside this repository. Before
any Agent call, validate the source package:

```powershell
python scripts/validate_high_quality_long_conversation_review_set.py `
  --input 'E:\authorized-evaluation\hq-long-conversation-review.json' `
  --json-output 'E:\authorized-evaluation\validation-report.json'
```

The source must pass its privacy, identifier, hash, and label-isolation
contracts. Use the existing approved-manifest and P1 baseline procedures in
`docs/p1-e2-long-conversation-evaluation-plan.md` and
`scripts/run_p1_gold_conversation_baseline.py`; they require query-only
runtime identity, dataset hashes, and independent review. Until that gate is
accepted, report `real_customer_accuracy=null` and
`optimization_unverified=true`.

## Failure Handling

- Test failure: keep the Agent behavior unchanged, save the sanitized failure
  output outside the repository, and diagnose the earliest owner.
- Runtime readiness failure: stop the 5012 test process and fix the isolated
  runtime configuration; never replace production 5011 as a workaround.
- External API/key failure: classify it as infrastructure blocked, not a
  quality pass or failure.
- Unsupported fact or action in a draft: reject the draft, keep human review,
  and open an evidence or policy gap rather than hardcoding a reply.
