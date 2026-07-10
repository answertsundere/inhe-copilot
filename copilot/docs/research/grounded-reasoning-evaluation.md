# Grounded Reasoning Evaluation Research

## Decision

Phase 0.4A uses a local deterministic contract evaluation instead of adding a
runtime RAGAS, DeepEval, or model-graded dependency. The current question is
whether the shadow layer admits only eligible facts, keeps identity and conflict
boundaries, and produces a draft that exposes those facts. Those are
deterministic safety contracts; an LLM judge would add cost and grading variance
without validating the earlier failure boundary.

## Reused Evaluation Concepts

- [RAGAS metric catalog](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
  separates answer quality from retrieval-context quality. The local eval maps
  this to `expected_fact_coverage_rate` and `answer_relevance_rate`, while
  retaining explicit evidence-admission diagnostics.
- [DeepEval faithfulness](https://deepeval.com/docs/metrics-faithfulness) checks
  generated claims against retrieval context. The local equivalent is stricter:
  only facts in `used_facts` may count as admitted, and identity, review, role,
  and conflict controls are asserted before draft relevance is scored.
- [OpenAI Evals](https://github.com/openai/evals) distinguishes evaluation logic
  from the solver. The positive evaluation schema keeps expected facts,
  rejection reasons, and claim rules outside the input passed to Grounded
  Reasoning, so the evaluator cannot leak an answer into the shadow draft.

## Metrics

The evaluation emits direct-fact admission, invalid-evidence rejection, expected
fact coverage, draft relevance, unsupported inference, identity leakage, Answer
Memory leakage, conflict blocking, high-risk handoff, forbidden claims, and the
shadow `can_change_can_send` invariant. Results are grouped by reasoning tier
and fact type.

## Non-Decision

This does not promote Grounded Reasoning into the formal reply path or replace
human review. A later candidate-draft phase may add a calibrated judge only
after deterministic contract acceptance and human-labelled comparisons justify
the added dependency.
