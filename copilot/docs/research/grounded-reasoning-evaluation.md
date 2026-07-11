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

## Multi-Fact Composition Evaluation

Admission, planning, and rendering are separate checks. A legal fact can be
admitted but omitted by the plan, or planned but absent from the rendered draft;
neither case is a successful answer. The evaluator therefore checks every
required fact's evidence UID through all three states and records unattributed
or irrelevant clauses separately. It also rebuilds each scenario with reversed
evidence order and compares selected/rendered UID sets, so a hidden input-order
dependency is observable.

The plan is a small deterministic data structure rather than a new response
engine: it can only restate selected fact text and cannot infer conclusions.
This follows the general structured-output principle of validating a schema at
the boundary, while keeping the current formal generation path unchanged.
See [OpenAI Structured Outputs](https://openai.com/index/introducing-structured-outputs-in-the-api/)
for the general schema-adherence principle; this project keeps the plan local
and deterministic rather than introducing a model call for shadow composition.

### Requested Attributes And Render Integrity

Multi-fact relevance cannot be inferred from stable sort order. The local
planner therefore consumes only canonical structured request attributes from
upstream and treats their absence as observable input quality, rather than
parsing buyer wording with a new keyword layer. Explicit attributes restrict
selection to matching admitted clauses; broad or unavailable requests with too
many candidates produce an ambiguity diagnostic instead of silently presenting
an arbitrary subset.

The rendered shadow draft is represented as structured customer-copy and
factual segments. Every factual segment carries an admitted, planned evidence
UID, and the evaluator deterministically re-renders the segments. This applies
the schema-boundary principle above without adding a model call or treating
deterministic segment checks as complete semantic-faithfulness evaluation.

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
