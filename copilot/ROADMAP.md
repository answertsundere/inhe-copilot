# Delivery Roadmap

## Current Execution

| Field | Value |
|---|---|
| Task ID | `P1-FORMAL-EVIDENCE-COVERAGE-001` |
| Owner | Codex |
| Goal | Restore a governed product-identity review surface without promoting recovered facts, then prove whether the existing formal evidence path is structurally healthy. |
| Scope | Existing recovery importer, KBProduct draft lifecycle, Product Context Pack, Evidence Convergence tests, isolated candidate databases, and durable documentation. No Agent, Prompt, Graph, model, reply owner, or Delivery change. |
| Status | Root cause confirmed: the synthetic fixed-40 uses intentionally absent `SYN-*` identities and the snapshot contains no eligible reviewed product facts. Existing positive evidence-chain tests pass. The recovery importer now stages identity-only KBProduct drafts while leaving all facts in per-fact draft review. |
| Gate | Recovered records are not formal evidence. Human review and publication are still required; `selected_evidence=0`, `real_customer_accuracy=null`, `can_send=false`, and mandatory review remain correct until governed facts exist for real identities. |

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
4. The completed synthetic fixed-40 selected zero formal evidence because its
   fictional `SYN-*` identities do not exist in the query-only knowledge
   snapshot. This is correct fail-closed behavior, not an Evidence Convergence
   failure, and it cannot establish factual accuracy.
5. The Composer-enabled versioned smoke scored `0/5`; the default-off Composer
   safety smoke scored `3/5` and left both installation replies empty. The full
   22-scenario run was correctly not started. These reports are retained as
   failures, not rewritten as passing safety or quality evidence.

## Immediate Queue

1. `P1-FORMAL-KNOWLEDGE-REVIEW-002`: use the existing supervisor lifecycle to
   review identity-linked, high-frequency fact drafts. Do not bulk approve,
   infer missing material or dimensions, or use synthetic identities as truth.
2. `P1-E2-001A`: data owner creates an authorized, versioned, hashed,
   deidentified review package outside the repository; no raw conversations or
   label answers enter an Agent prompt.
3. `P1-E2-001B`: run the existing formal Pipeline on a query-only snapshot,
   retaining `can_send=false` and human review.
4. `P1-E2-001C`: independent reviewers record completeness, continuity,
   factual restraint, unresolved coverage, and handoff needs.
5. After P1 acceptance, create the P2 dynamic-evidence source-of-truth ADR.

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
