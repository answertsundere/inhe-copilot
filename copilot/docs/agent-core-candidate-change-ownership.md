# Agent Core Candidate Change Ownership

This manifest classifies the 45 files that were dirty before the P0-R0
consolidation. It is a checkpoint inventory, not evidence of production
qualification.

## Interpretation

- `Default effect` describes the file's behavior before P0-R0 documentation and
  test cleanup.
- `Flag only` means the candidate behavior requires the disabled model-first
  Composer and/or Formal Evidence Convergence flags.
- `Pipeline evidence` distinguishes direct unit coverage from the historical
  fixed-eight candidate run or the real formal Pipeline.
- All 45 files remain used by the candidate, its safety/provenance boundary, or
  its read-only evaluation tools. No file was proven both superseded and
  unreferenced, so P0-R0 deletes none.

## A. validated_candidate_core

| File | Owner | Purpose | Source phase | Default effect | Flag only | Direct tests | Pipeline evidence | Still used | Superseded | Evaluation only | Commit | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `app/agent/nodes/evidence_builder.py` | Evidence builder | Preserve admitted evidence/provenance for claims | P0.9-P1.11 | Existing evidence projection | No | Yes | Real Pipeline | Yes | No | No | Yes | Candidate depends on the canonical evidence shape |
| `app/repositories/file_policy_repository.py` | Domain policy data | Validate versioned policy packs | P1.9 | Policy-data validation | No | Yes | Unit and Pipeline projection | Yes | No | No | Yes | Existing owner; no routing or reply authority |
| `app/services/admitted_answer_context_service.py` | Evidence admission | Reuse admission and project answer eligibility | P0.5-P1.10 | Diagnostic projection plus existing admission | Mixed | Yes | Fixed-eight and Pipeline | Yes | No | No | Yes | Canonical admission owner; P0-R0 fixes claim-type compatibility only |
| `app/services/analysis_pipeline_service.py` | Analysis Pipeline | Wire convergence, claim state, and disabled candidate | P0.5-P1.11 | Candidate disabled | Yes | Yes | Four entry points/fixed-eight | Yes | No | No | Yes | The single application Pipeline |
| `app/services/claim_resolution_service.py` | Claim Resolution | Resolve supported/unresolved/conflicting/prohibited goals | P0.5-P1.11 | Formal projection | No | Yes | Fixed-eight and Pipeline | Yes | No | No | Yes | Authoritative claim-state owner |
| `app/services/fact_type_alias_service.py` | Fact-type compatibility | Canonical alias compatibility without new FactType | P1.11 | Existing compatibility utility | No | Yes | Pipeline contract | Yes | No | No | Yes | Shared deterministic compatibility owner |
| `app/services/final_answer_auditor.py` | Deterministic Final Contract | Validate candidate truth, references, risk, action, media, and send prerequisites | P1.6-P0.2e | Candidate branch disabled; legacy retained | Yes | Yes | Fixed-eight candidate | Yes | No | No | Yes | Candidate zero-model final contract |
| `app/services/final_response_orchestrator.py` | Final orchestration | Sequence candidate contract/audit and synchronize fail-closed delivery | P1.4-P0.2e | Candidate disabled; legacy retained | Yes | Yes | Pipeline/fixed-eight | Yes | No | No | Yes | State/order owner, not candidate reply generator |
| `app/services/final_semantic_quality_service.py` | Unified Textual Audit | One candidate textual audit over truth and continuity | P1.5-P0.2e | Candidate disabled; legacy retained | Yes | Yes | Fixed-eight candidate | Yes | No | No | Yes | Sole model-first textual audit |
| `app/services/model_first_answer_composer_service.py` | Candidate reply | Render one attributed clause per customer goal | P1.1-P1.11 | Disabled | Yes | Yes | Fixed-eight candidate | Yes | No | No | Yes | Sole candidate reply generator |
| `rules/domain_policy_packs/maternal_child_home.yaml` | Domain policy data | Declare risk/inference/freshness policy only | P1.9 | Data projection only | No | Yes | Eligibility qualification | Yes | No | No | Yes | Contains no product facts or reply templates |
| `docs/architecture-overview.md` | Architecture governance | Record thin graph and candidate owner sequence | P0.9-P0-R0 | Documentation | No | Governance | N/A | Yes | No | No | Yes | Durable architecture source |
| `docs/module-index.md` | Ownership governance | Map behavior to authoritative owners | P0.9-P0-R0 | Documentation | No | Governance | N/A | Yes | No | No | Yes | Durable module ownership source |
| `docs/research/evidence-first-llm-decision-loop.md` | Research record | Preserve verified candidate and evaluation findings | P0.8-P0-R0 | Documentation | No | Governance | Historical fixed-eight | Yes | No | No | Yes | Records results without promoting them |
| `tests/test_admitted_answer_context_service.py` | Admission tests | Positive/negative admission and eligibility | P0.5-P1.10 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Direct regression coverage |
| `tests/test_analysis_pipeline_entrypoints.py` | Pipeline tests | Four-entry contract and candidate isolation | P0.2-P1.11 | Test only | N/A | Self | Four entry points | Yes | No | No | Yes | Guards the single Pipeline |
| `tests/test_answer_eligibility_context.py` | Eligibility tests | Owner provenance and fail-closed projection | P1.9-P1.10 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Direct owner-boundary coverage |
| `tests/test_claim_resolution_service.py` | Claim tests | Claim state, attribution, and goal linkage | P0.5-P1.11 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Direct Claim Resolution coverage |
| `tests/test_fact_type_alias_service.py` | Compatibility tests | Alias and canonical claim compatibility | P1.11 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Prevents sample-specific mapping |
| `tests/test_final_answer_auditor.py` | Final Contract tests | Risk, truth, media, privacy, and zero-call candidate checks | P1.6-P0.2e | Test only | N/A | Self | Unit/fixed-eight fixtures | Yes | No | No | Yes | Direct deterministic contract coverage |
| `tests/test_final_answer_auditor_canonical_truth.py` | Final Contract tests | Canonical truth versus conversation continuity | P1.6-P0.2e | Test only | N/A | Self | Unit | Yes | No | No | Yes | Guards authoritative truth ownership |
| `tests/test_final_response_orchestrator.py` | Orchestration tests | Candidate ordering and delivery fail-closed behavior | P1.4-P0.2e | Test only | N/A | Self | Unit/Pipeline | Yes | No | No | Yes | Guards non-generator ownership |
| `tests/test_final_semantic_quality_service.py` | Unified Audit tests | Strict schema, polarity, coverage, and continuity | P1.5-P0.2e | Test only | N/A | Self | Fake provider/fixed-eight fixtures | Yes | No | No | Yes | No formal provider call |
| `tests/test_model_first_answer_composer_service.py` | Composer tests | Goal/clause/evidence completeness and mutations | P1.1-P1.11 | Test only | N/A | Self | Fake provider/fixed-eight fixtures | Yes | No | No | Yes | Direct sole-generator coverage |

## B. validated_safety_or_provenance

| File | Owner | Purpose | Source phase | Default effect | Flag only | Direct tests | Pipeline evidence | Still used | Superseded | Evaluation only | Commit | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `app/agent/nodes/query_fact_type_classifier.py` | Turn Understanding boundary | Replace public goal state with server-owned result | P0.8-P1.10 | Formal provenance hardening | No | Yes | Real API/Pipeline | Yes | No | No | Yes | Prevents request-side goal injection |
| `app/llm/client.py` | LLM transport privacy | Preserve safe structured facts while redacting real PII | P0.8/P0.2 | Formal privacy hardening | No | Yes | Provider compatibility | Yes | No | No | Yes | Last-resort field-aware privacy boundary |
| `app/services/canonical_conversation_turn_service.py` | Canonical conversation | Normalize turns and privacy projection provenance | P0.8/P0.2 | Formal context hardening | No | Yes | API/Pipeline | Yes | No | No | Yes | Shared conversation contract |
| `app/services/eval_sanitizer_service.py` | Evaluation privacy | Avoid semantic false positives while retaining PII redaction | P0.7-P0.2 | Evaluation/log safety | No | Yes | Diagnostic | Yes | No | No | Yes | Does not relax real PII scanning |
| `app/services/semantic_fact_type_service.py` | Turn Understanding | Produce typed atomic goals and source spans | P0.9-P1.11 | Formal understanding/provenance | No | Yes | Real API/Pipeline | Yes | No | No | Yes | Existing single semantic owner |
| `tests/test_canonical_conversation_turn_service.py` | Canonical tests | Ordering, privacy projection, and provenance | P0.8-P0.2 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Direct safety coverage |
| `tests/test_llm_client_provider_compatibility.py` | Transport tests | Structured/text privacy consistency | P0.8/P0.2 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Guards semantic preservation and PII |
| `tests/test_query_fact_type_classifier.py` | Understanding tests | Server ownership and API behavior | P0.8-P1.10 | Test only | N/A | Self | API | Yes | No | No | Yes | Direct injection/provenance coverage |
| `tests/test_real_analyze_fact_type_contract.py` | API contract tests | General semantic and fail-closed behavior | P0.9-P0-R0 | Test only | N/A | Self | Real analyze route | Yes | No | No | Yes | Assertions target behavior, not fixed wording |
| `tests/test_semantic_fact_type_service.py` | Understanding tests | Goal schema, span provenance, and semantic mapping | P0.9-P1.11 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Direct owner coverage |
| `tests/test_atomic_goal_span_contract.py` | Provenance mutation tests | Reject invalid current-message spans and hashes | P1.9-P1.11 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Generic provenance defense |
| `tests/test_eval_sanitizer_service.py` | Privacy tests | Preserve ordinary product/use semantics and redact PII | P0.2 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Guards privacy without address-word overreach |
| `tests/test_semantic_fact_type_known_unmapped_contract.py` | Understanding diagnostics | Observe known-unmapped semantics without hard-coded fallback | P0.2 | Test only | N/A | Self | Unit | Yes | No | No | Yes | Fail-closed diagnostic contract |
| `tests/test_turn_understanding_failure_diagnostics.py` | Understanding diagnostics | Preserve observable failure provenance | P0.2 | Test only | N/A | Self | Unit | Yes | No | No | Yes | No reply or routing authority |

## C. evaluation_only

| File | Owner | Purpose | Source phase | Default effect | Flag only | Direct tests | Pipeline evidence | Still used | Superseded | Evaluation only | Commit | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `scripts/compare_model_first_answer_composer.py` | Candidate evaluator | Compare disabled Composer/Final/Audit outcomes | P1.1-P0.2 | None | N/A | Yes | Fixed-eight evaluator | Yes | No | Yes | Yes | Read-only evaluation asset |
| `scripts/diagnose_privacy_projection_semantic_preservation.py` | Privacy diagnostic | Trace field-aware privacy projection | P0.2 | None | N/A | Yes | Diagnostic | Yes | No | Yes | Yes | No production import |
| `scripts/qualify_unified_textual_audit.py` | Audit evaluator | Run strict fake/real qualification contract | P0.2e | None | N/A | Yes | Qualification only | Yes | No | Yes | Yes | No production authority |
| `tests/test_compare_model_first_answer_composer.py` | Evaluator tests | Report, classification, and immutable input checks | P1.1-P0.2 | Test only | N/A | Self | Unit | Yes | No | Yes | Yes | Validates evaluation, not Agent policy |
| `tests/test_diagnose_privacy_projection_semantic_preservation.py` | Diagnostic tests | Privacy diagnostic JSON and attribution | P0.2 | Test only | N/A | Self | Unit | Yes | No | Yes | Yes | Read-only diagnostic coverage |
| `tests/test_partial_answer_goal_ref_evaluator.py` | Evaluator tests | Goal-ref outcome scoring and polarity | P1.11 | Test only | N/A | Self | Unit | Yes | No | Yes | Yes | Evaluator cannot become Agent rule input |
| `tests/test_qualify_unified_textual_audit.py` | Qualification tests | Attempt/schema accounting and fail-closed status | P0.2e | Test only | N/A | Self | Fake provider | Yes | No | Yes | Yes | No formal model call |

## Summary

| Category | Count | Disposition |
|---|---:|---|
| A. `validated_candidate_core` | 24 | Commit as feature-disabled candidate/core plus direct tests |
| B. `validated_safety_or_provenance` | 14 | Commit as formal provenance/privacy hardening plus direct tests |
| C. `evaluation_only` | 7 | Commit as read-only diagnostics/evaluation contract |
| D. `superseded_experiment` | 0 | None proven safe to delete |
| E. `unrelated_or_historical` | 0 | None in the original 45-file set |
| F. `generated_or_runtime_artifact` | 0 | None in the original 45-file set |
| **Total** | **45** | All classified |

P0-R0 does not enable feature flags, add model calls, change `can_send`, write
formal knowledge, deploy a runtime, or claim real accuracy.

## P1.2k.6i Disabled Checkpoint Addendum

This addendum classifies the 25 files that were dirty before the P1.2k.6i
checkpoint audit. It does not reclassify the earlier 45-file P0-R0 set. The
categories below are the P1.2k.6i ownership categories: bounded-inference
contracts (A), Composer contracts (B), Unified Audit contracts (C),
safety/provenance hardening (D), tests (E), evaluation-only code (F), and
documentation (G). No file was left unexplained in category H.

`Default change` describes whether a file can affect the existing formal path
while the Composer flag is off. `Rollback unit` identifies the smallest safe
group; linked schema/validator files are not individually revertible. The
checkpoint saves engineering contracts only. It does not qualify an Audit
Provider, enable a feature, or establish customer accuracy.

| File | Category | Purpose and source phase | Deterministic evidence | Default change | Unqualified Audit Provider dependency | Checkpoint | Hard-coded business sample | Rollback unit |
|---|---|---|---|---|---|---|---|---|
| `app/repositories/file_policy_repository.py` | A | Validate semantic-budget policy fields; P1.2k.6f | repository, admission, resolution, and mutation tests | No reply effect while candidate is off | No | Yes | No | A contract set |
| `app/services/admitted_answer_context_service.py` | A | Project policy budget metadata outside evidence; P1.2k.6f | admission and eligibility tests | No reply effect while convergence/candidate are off | No | Yes | No | A contract set |
| `app/services/claim_resolution_service.py` | A | Preserve restricted request risk and expose attributed bounded alternatives; P1.2e-P1.2k.6f | resolution and negative-matrix tests | No reply effect while candidate is off | No | Yes | No | A contract set |
| `app/services/final_answer_auditor.py` | D | Revalidate canonical clause, boundary, policy, premise, scope, risk, and Pack identity; P1.2e-P1.2k.6f | deterministic Final and canonical-truth tests | Candidate branch only | No | Yes | No | A/D contract set |
| `app/services/final_semantic_quality_service.py` | C | Unified Audit v2 strict checks, canonical findings, and semantic-budget validation; P1.2k.6e-P1.2k.6h | schema, mutation, polarity, attribution, and fake-provider tests | v2 branch requires accepted disabled candidate | Yes, for live capability only | Yes | No | C contract set |
| `app/services/model_first_answer_composer_service.py` | B | Decision Input v1, minimal output, goal-local aliases, tri-state selection, canonical reconstruction, and presentation checks; P1.2f-P1.2k.6d | Composer, transport-equivalence, replay, and mutation tests | Composer remains off by default | No | Yes | No | A/B contract set |
| `app/services/semantic_fact_type_service.py` | D | Preserve separately answerable current-turn goals at the existing Understanding owner; P1.2i | unit/mutation tests plus frozen Understanding `5/5` with zero retry/repair | Yes, formal provenance hardening; no new call or owner | No | Yes | No | D with its direct test |
| `rules/domain_policy_packs/maternal_child_home.yaml` | A | Add conclusion, variability-factor, and advice-budget control data; P1.2k.6f | strict loader and negative-matrix tests | No reply effect while candidate is off | No | Yes | No product/SKU/reply text | A contract set |
| `scripts/compare_model_first_answer_composer.py` | F | Report boundary, policy, semantic-budget, and outcome diagnostics; P1.2e-P1.2k.6f | evaluator tests and immutable-input checks | None; evaluation only | No | Yes | No production branch | F with its test |
| `docs/adr/0009-agent-core-capability-mainline.md` | G | Record retained owners and disabled rollback boundary | docs governance | Documentation only | No | Yes | No | G documentation set |
| `docs/agent-core-priority-plan.md` | G | Record stage gates, failures, and non-qualification | docs governance | Documentation only | No | Yes | No | G documentation set |
| `docs/architecture-overview.md` | G | Record the unchanged owner sequence and disabled status | docs governance | Documentation only | No | Yes | No | G documentation set |
| `docs/index.md` | G | Keep the sole durable index aligned | docs governance | Documentation only | No | Yes | No | G documentation set |
| `docs/module-index.md` | G | Record current owner and authority boundaries | docs governance | Documentation only | No | Yes | No | G documentation set |
| `docs/research/evidence-first-llm-decision-loop.md` | G | Preserve qualification evidence and Provider blocker | docs governance | Documentation only | No | Yes | No | G documentation set |
| `tests/test_admitted_answer_context_service.py` | E | Policy projection and evidence-role isolation | self | Test only | No | Yes | Fixture only | A test set |
| `tests/test_answer_eligibility_context.py` | E | Trusted context and fail-closed eligibility | self | Test only | No | Yes | Fixture only | A test set |
| `tests/test_claim_resolution_service.py` | E | Risk separation, policy/premise attribution, and negative matrix | self | Test only | No | Yes | Fixture only | A test set |
| `tests/test_compare_model_first_answer_composer.py` | E | Evaluator metric and immutable-input integrity | self | Test only | No | Yes | Fixture only | F test set |
| `tests/test_final_answer_auditor.py` | E | Deterministic Final option/boundary/provenance validation | self | Test only | No | Yes | Fixture only | A/D test set |
| `tests/test_final_answer_auditor_canonical_truth.py` | E | Canonical truth and continuity integrity | self | Test only | No | Yes | Fixture only | A/D test set |
| `tests/test_final_semantic_quality_service.py` | E | Unified Audit v2 schema, mutation, finding, and attribution | self | Test only | No live Provider | Yes | Fixture only | C test set |
| `tests/test_model_first_answer_composer_service.py` | E | Decision Input, minimal output, option selection, canonical reconstruction, and presentation mutations | self | Test only | No | Yes | Fixture only | B test set |
| `tests/test_semantic_fact_type_service.py` | E | Independent multi-goal Understanding contract | self | Test only | No | Yes | Fixture only | D test set |
| `tests/test_composer_decision_input_contract.py` | E | Decision Input privacy, shape, determinism, and Provider equivalence | self | Test only | No | Yes | Fixture only | B test set |

P1.2k.6i also updates `tests/test_analysis_pipeline_entrypoints.py`, outside
the original 25-file set, so the Pipeline test derives the expected Pack
reference from the trusted repository instead of pinning the superseded
`1.2.0` data version. That test-only alignment is part of the A checkpoint.

The deterministic checkpoint gate covers 664 direct contract tests, 160
Pipeline/Replay/Benchmark/docs tests, 86 formal-knowledge/evidence/safety
tests, and the versioned synthetic Benchmark at `5/5` and `22/22`. The
Composer and bounded-inference paths remain disabled, the v2 Audit branch has
no approved live model, `can_send=true` remains zero in the synthetic runs,
and `real_customer_accuracy=null`.
