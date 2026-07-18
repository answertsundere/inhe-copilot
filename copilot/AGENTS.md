# Project Agent Instructions

These instructions supplement the parent workspace `AGENTS.md` and apply to the
entire `copilot` project.

## Mandatory Startup Reading

Before analyzing or changing code, read these files in order:

1. The parent workspace `AGENTS.md`.
2. This file.
3. `docs/index.md`.
4. `docs/PROJECT_CHARTER.md`.
5. `docs/architecture-overview.md`.
6. `docs/module-index.md`.
7. The documents linked by `docs/index.md` for the modules being changed.

Do not begin implementation from a single failing sample or an old delivery
report. Verify the current code path and current data first.

## Research Before Architecture Work

Before adding a major capability, platform integration, framework, queue,
retriever, workflow engine, or control-plane module:

- research mature existing products and maintained open-source projects;
- prefer primary sources such as official documentation and source repositories;
- identify what can be reused before proposing custom infrastructure;
- record durable findings under `docs/research/` when they affect architecture;
- record a decision under `docs/adr/` before changing ownership or production
  data flow.

Narrow bug fixes do not require new research when the existing contract already
defines the intended behavior.

## Business Invariants

- QianNiu, Pinduoduo, and JD are adapters. Platform-native fields must not enter
  Agent-domain branching.
- External product titles resolve through product identity and JST/internal
  product mappings before product facts are selected.
- Product facts, policy facts, service actions, media references, and Answer
  Memory are different evidence roles and must not be interchanged.
- Answer Memory may guide tone and handling actions; it is not product truth.
- Media may support an answer only when its role and description match the
  question. A media reference does not mean the media was sent.
- Common-sense reasoning may connect verified facts only within a declared risk
  policy. It must not invent certification, toxicity, age suitability, load
  limits, order status, refund, replacement, compensation, or platform actions.
- `can_send` requires eligible evidence, final safety approval, and actual
  platform delivery capability. Missing evidence must never be hidden by fluent
  wording.
- Human handoff is a durable task with assignment, status, SLA, acknowledgement,
  and audit history. A customer-facing sentence or browser toast is not a task.
- Replay and benchmark inputs must use the same canonical context and final
  pipeline as the user-facing path. Global product fixtures cannot represent
  mixed real conversations.

## Change Discipline

- Fix the earliest broken contract, not the latest visible sentence.
- Do not branch on sample text, run IDs, scenario IDs, SKUs, order IDs, product
  names, or test fixture values.
- Do not loosen evidence or safety gates to increase pass rate.
- Keep shadow modules out of production decisions until their acceptance contract
  and replay evidence are documented.
- Preserve unrelated dirty-worktree changes.
- Update an existing durable document when a long-lived contract changes. Add a
  new document only for a genuinely new durable concept.

## Required Verification

### Real-dataset change gate

Every change that can affect Agent understanding, context, retrieval, evidence,
reasoning, prompts, model transport, reply composition, safety, media, handoff,
or delivery must run a comparable real-dataset evaluation before it may be
reported as an improvement:

- pin the dataset ID, version/content hash, runtime commit, feature flags,
  provider/model, entry point, and sidecar mode;
- preserve a before-change baseline from the parent commit, or rerun it when no
  directly comparable baseline exists;
- run the after-change evaluation through the same formal user-facing pipeline;
- report the scorable denominator and every excluded/context-gap case;
- compare claim/action correctness, evidence selection, handoff, unsafe
  auto-send, empty/error responses, timeouts, and p50/p95 latency;
- treat synthetic fixtures as regression and safety evidence only, never as
  proof that real customer accuracy improved; and
- when approved real labels are insufficient, report `real_accuracy=null` and
  `optimization_unverified` rather than claiming success.

A change passes this gate only when its declared target metric improves (or its
target defect count decreases), no safety contract regresses, and latency/error
changes are disclosed. Documentation-only and test-infrastructure-only changes
still run their relevant integrity/governance checks, but they do not create an
Agent-accuracy claim.

Every implementation report must state:

- which user-facing entry points use the changed path;
- whether replay and benchmark exercise the same path;
- whether `can_send`, evidence eligibility, media delivery, or handoff behavior
  changed;
- tests and live checks actually run;
- the real dataset/version, before/after metrics, and whether the real-dataset
  change gate passed, was not applicable, or was blocked by missing labels;
- documentation and ADR impact;
- unverified risks and environment dependencies.
