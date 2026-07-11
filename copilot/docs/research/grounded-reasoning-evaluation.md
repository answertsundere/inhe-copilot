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

## Deterministic Scoring Contract

The evaluator reports separate numerator, denominator, and rate values for:

- fact admission: every required legal evidence UID entered `used_facts`;
- invalid fact rejection: every expected rejected evidence UID has the expected
  reason and never appears in `used_facts`;
- draft fact coverage: each required fact has its own deterministic text matcher;
- answer relevance: every required fact for a scored scenario is covered;
- declared unsupported claims and formal forbidden-claim diagnostics;
- conflict blocking and high-risk handoff.

Identity leakage is based on an expected rejected evidence UID appearing in
`used_facts`, not on a source-name substring. Evidence provenance carries a
stable, non-secret `evidence_uid`, source, role, attribute key, and identity
scope for this diagnostic only.

`allowed_inferences` is retained as scenario documentation and explicitly marked
`not_scored`. A deterministic matcher cannot discover arbitrary open-ended
hallucinations. Full faithfulness evaluation needs human labels or a calibrated
judge after the deterministic contract is accepted; it must not be approximated
with a growing phrase blacklist.

## Non-Decision

This does not promote Grounded Reasoning into the formal reply path or replace
human review. A later candidate-draft phase may add a calibrated judge only
after deterministic contract acceptance and human-labelled comparisons justify
the added dependency.
