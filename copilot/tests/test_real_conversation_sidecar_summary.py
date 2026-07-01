from app.api.eval_routes import _build_run_summary


class _Trace:
    def __init__(self, *, passed, should_score, sidecar):
        self.passed = passed
        self.requires_human_review = False
        self.latency_ms = 10
        self.turn_uid = sidecar.get("turn_uid", "")
        self._turn_understanding = {
            "should_score": should_score,
            "turn_actionability": "actionable_question" if should_score else "acknowledgement",
        }
        self._raw_response = {"sidecar_context": sidecar}
        self._answer_trace = {}
        self._failure_labels = []

    def get_turn_understanding(self):
        return self._turn_understanding

    def get_raw_response(self):
        return self._raw_response

    def get_answer_trace(self):
        return self._answer_trace

    def get_failure_labels(self):
        return self._failure_labels


class _Run:
    total_turns = 1
    passed_turns = 0


def test_sidecar_summary_rates_use_all_traces_not_only_scored_traces():
    traces = [
        _Trace(
            passed=False,
            should_score=True,
            sidecar={
                "turn_uid": "turn_product",
                "sidecar_context_quality": "complete",
                "has_sidecar_product_context": True,
                "has_sidecar_order_context": False,
                "missing_context_fields": [],
            },
        ),
        _Trace(
            passed=True,
            should_score=False,
            sidecar={
                "turn_uid": "turn_order",
                "sidecar_context_quality": "partial",
                "has_sidecar_product_context": False,
                "has_sidecar_order_context": True,
                "missing_context_fields": ["product"],
            },
        ),
    ]

    summary = _build_run_summary(_Run(), traces, [], [])

    assert summary["sidecar_product_context_rate"] == 0.5
    assert summary["sidecar_order_context_rate"] == 0.5
    assert summary["missing_sidecar_context_count"] == 1
    assert summary["context_gap_due_to_missing_sidecar_count"] == 0
