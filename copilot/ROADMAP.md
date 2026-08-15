# Delivery Roadmap

## Current Execution

| Field | Value |
|---|---|
| Task ID | `P1-SYNTHETIC-BASELINE-AUTHORITATIVE-GOAL-ROUTING` |
| Owner | Codex |
| Goal | Preserve safe non-factual media goals and route a provenance-valid canonical customer goal into the existing evidence path even when the legacy intent remains `general`. |
| Scope | Existing Turn Understanding sanitizer, response-strategy router, P1 synthetic runner, direct tests, external runtime harness, and durable result documentation. No new node, service, model call, or reply owner. |
| Status | Engineering contract complete; the fresh fixed-40 run stopped at row 1 because GLM-4.5-Air emitted an invalid `claim_type_status`. Provider stability is not qualified. |
| Gate | Keep schema validation fail-closed, formal knowledge query-only, `can_send=false`, and human review mandatory. Do not retry for a lucky pass or treat synthetic execution as real accuracy. |

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
