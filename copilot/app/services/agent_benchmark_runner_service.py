"""Run curated Agent benchmark scenarios with deterministic MVP scoring."""

from __future__ import annotations

from typing import Any, Callable

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


AgentCallable = Callable[[dict[str, Any]], dict[str, Any]]

SCENARIO_FACT_TYPE_COMPATIBILITY = {
    "presales": {
        "material",
        "dimensions",
        "load_capacity",
        "gross_weight",
        "accessory_availability",
        "accessory_compatibility",
        "stability",
        "space_fit",
        "placement_scene",
    },
    "aftersales": {"aftersales", "aftersales_policy", "after_sales"},
    "logistics": {"logistics", "order_status", "delivery_not_received"},
    "installation": {"installation", "accessory_usage", "accessory_availability", "accessory_compatibility"},
    "promotion": {"promotion", "promotion_policy", "price_negotiation", "coupon", "discount"},
    "mixed": set(),
}

BLOCKING_FAILURE_LABELS = {
    "unsupported_media_claim",
    "evidence_misuse",
    "semantic_mismatch",
}


def _contains(text: str, needle: str) -> bool:
    return sanitize_text(needle).lower() in sanitize_text(text).lower()


def _extract_reply(response: dict[str, Any]) -> str:
    return sanitize_text(
        response.get("sendable_reply")
        or response.get("suggested_reply")
        or response.get("draft_reply")
        or response.get("reply")
        or ""
    )


def _response_query_fact_type(response: dict[str, Any]) -> str:
    answer_trace = response.get("answer_trace") if isinstance(response.get("answer_trace"), dict) else {}
    evidence_debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    return sanitize_text(
        response.get("query_fact_type")
        or answer_trace.get("query_fact_type")
        or evidence_debug.get("query_fact_type")
        or ""
    )


def _response_failure_labels(response: dict[str, Any]) -> list[str]:
    raw = response.get("failure_labels") or response.get("block_reasons") or []
    if isinstance(raw, str):
        raw = [raw]
    answer_trace = response.get("answer_trace") if isinstance(response.get("answer_trace"), dict) else {}
    for key in ("failure_labels", "block_reasons"):
        value = answer_trace.get(key)
        if isinstance(value, list):
            raw = [*raw, *value]
    return [sanitize_text(item) for item in raw if sanitize_text(item)]


def _buyer_turns(conversation_turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns = []
    for item in conversation_turns or []:
        if not isinstance(item, dict):
            continue
        speaker = sanitize_text(item.get("speaker")).lower()
        text = sanitize_text(item.get("text") or item.get("message"))
        if text and speaker in {"buyer", "customer", "客户", "买家", ""}:
            turns.append({**item, "text": text})
    return turns


class AgentBenchmarkRunnerService:
    def __init__(self, agent_callable: AgentCallable | None = None):
        self.agent_callable = agent_callable

    def _call_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.agent_callable is not None:
            return self.agent_callable(payload) or {}
        from app.main import get_reply_service
        from app.services.analysis_execution_service import execute_analysis

        return execute_analysis(
            reply_service=get_reply_service(),
            customer_message=payload.get("message", ""),
            conversation_id=payload.get("conversation_id", "agent_benchmark"),
            product_name=payload.get("product_name", ""),
            copilot_context=payload.get("copilot_context") or {},
            source="agent_benchmark",
            scenario="benchmark",
            final_orchestration=True,
        ) or {}

    def run_scenarios(
        self,
        status: str = "active",
        limit: int | None = None,
        scenario_uids: list[str] | None = None,
        run_uid: str | None = None,
        db_factory=None,
    ) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import AgentBenchmarkScenario

        db_factory = db_factory or SessionLocal
        db = db_factory()
        try:
            query = db.query(AgentBenchmarkScenario)
            if scenario_uids:
                query = query.filter(AgentBenchmarkScenario.scenario_uid.in_([sanitize_text(uid) for uid in scenario_uids]))
            else:
                query = query.filter(AgentBenchmarkScenario.status == sanitize_text(status or "active"))
            query = query.order_by(AgentBenchmarkScenario.id.asc())
            if limit:
                query = query.limit(max(int(limit), 1))
            rows = query.all()
            results = [self._run_one(row, run_uid=run_uid or "") for row in rows]
            passed = sum(1 for item in results if item.get("passed"))
            total = len(results)
            failure_reasons: dict[str, int] = {}
            for item in results:
                for reason in item.get("failure_reasons", []):
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            return sanitize_obj({
                "run_uid": sanitize_text(run_uid or ""),
                "status": status,
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": round(passed / total, 4) if total else 0,
                "failure_reasons": failure_reasons,
                "per_scenario_result": results,
            })
        finally:
            db.close()

    def _run_one(self, scenario, run_uid: str = "") -> dict[str, Any]:
        sidecar = scenario.get_sidecar_context()
        expected = scenario.get_expected_reply()
        conversation_turns = scenario.get_conversation_turns()
        buyer_turns = _buyer_turns(conversation_turns)
        responses = []
        history: list[dict[str, Any]] = []
        for turn in buyer_turns:
            payload = self._build_payload(scenario.scenario_uid, turn, history, sidecar, run_uid)
            response = sanitize_obj(self._call_agent(payload))
            responses.append({"turn_uid": turn.get("turn_uid", ""), "payload": sanitize_obj(payload), "response": response})
            history.append({"role": "customer", "text": turn["text"]})
            reply = _extract_reply(response)
            if reply:
                history.append({"role": "agent", "text": reply})
        score = self._score(scenario.scenario_type, expected, responses[-1]["response"] if responses else {})
        return sanitize_obj({
            "scenario_uid": scenario.scenario_uid,
            "scenario_type": scenario.scenario_type,
            "passed": score["passed"],
            "failure_reasons": score["failure_reasons"],
            "agent_reply": score["agent_reply"],
            "responses": responses,
        })

    def _build_payload(
        self,
        scenario_uid: str,
        turn: dict[str, Any],
        history: list[dict[str, Any]],
        sidecar: dict[str, Any],
        run_uid: str,
    ) -> dict[str, Any]:
        product_title = sanitize_text(sidecar.get("product_title") or sidecar.get("product_name"))
        return {
            "message": sanitize_text(turn.get("text")),
            "conversation_id": f"benchmark_{scenario_uid}",
            "product_name": product_title,
            "product_title": product_title,
            "sku_code": sanitize_text(sidecar.get("sku_code")),
            "i_id": sanitize_text(sidecar.get("i_id")),
            "order_id": sanitize_text(sidecar.get("order_id")),
            "platform_order_id": sanitize_text(sidecar.get("platform_order_id")),
            "copilot_context": {
                "source_type": "agent_benchmark",
                "benchmark_run_uid": sanitize_text(run_uid),
                "benchmark_scenario_uid": scenario_uid,
                "sidecar_context": sanitize_obj(sidecar),
                "conversation_history": sanitize_obj(history[-8:]),
                "product_name": product_title,
                "product_title": product_title,
                "sku_code": sanitize_text(sidecar.get("sku_code")),
                "i_id": sanitize_text(sidecar.get("i_id")),
                "order_id": sanitize_text(sidecar.get("order_id")),
                "platform_order_id": sanitize_text(sidecar.get("platform_order_id")),
            },
        }

    def _score(self, scenario_type: str, expected: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
        agent_reply = _extract_reply(response)
        reasons: list[str] = []
        if bool(response.get("can_send")) != bool(expected.get("auto_send_allowed")):
            reasons.append("auto_send_allowed_mismatch")
        if bool(response.get("requires_human_review")) != bool(expected.get("must_handoff")):
            reasons.append("must_handoff_mismatch")
        for point in expected.get("key_points") or []:
            if sanitize_text(point) and not _contains(agent_reply, point):
                reasons.append("missing_key_point")
                break
        for forbidden in expected.get("forbidden_claims") or []:
            if sanitize_text(forbidden) and _contains(agent_reply, forbidden):
                reasons.append("forbidden_claim_present")
                break
        labels = set(_response_failure_labels(response))
        if labels & BLOCKING_FAILURE_LABELS:
            reasons.append("blocking_failure_label")
        fact_type = _response_query_fact_type(response)
        allowed = SCENARIO_FACT_TYPE_COMPATIBILITY.get(sanitize_text(scenario_type), set())
        if allowed and fact_type and fact_type not in allowed:
            reasons.append("query_fact_type_mismatch")
        return {
            "passed": not reasons,
            "failure_reasons": reasons,
            "agent_reply": agent_reply,
        }
