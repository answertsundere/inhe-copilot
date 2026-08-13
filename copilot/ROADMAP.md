# Delivery Roadmap

## Current Execution

| Field | Value |
|---|---|
| Task ID | `P1-E2-001-TEST-ENTRY` |
| Owner | Codex |
| Goal | Establish the project execution index and verify the formal API and P1 regression entry points without changing Agent behavior. |
| Scope | Documentation, test invocation, and review-only diagnostic verification. |
| Status | Safety verification complete; functional smoke blocked on isolated runtime configuration |
| Gate | No live product or order data, no knowledge write, no delivery action, and no change to `can_send`. |

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

1. The isolated 5012 smoke runtime reports `ready=false`: its configured
   knowledge store has no `knowledge_entries`, `knowledge_chunks`, or `kb_qa`,
   and management authentication is not configured. It also has no LLM
   credential, so it cannot produce a functional draft for review.
2. `P1-E2-001` cannot claim real quality until a data owner authorizes a
   deidentified long-conversation review package and independent labels.
3. The P1 frozen-owner boundary prevents inventing a policy outcome, product
   fact, compensation, refund, replacement, or promised completion step.
4. No test result may promote the current Supervisor Assist runtime to
   autonomous sending.

## Immediate Queue

1. Configure an isolated 5012 runtime with an approved query-only knowledge
   database, required management authentication, and an ignored LLM credential;
   rerun the functional API smoke check without changing production 5011.
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
