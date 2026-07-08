"""Run curated Agent benchmark scenarios with deterministic MVP scoring."""

from __future__ import annotations

import re
import time
import uuid
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
CUSTOMER_SPEAKER_ROLES = {"buyer", "customer", "\u5ba2\u6237", "\u4e70\u5bb6", ""}
AGENT_SPEAKER_ROLES = {"service", "agent", "csr", "seller", "\u5ba2\u670d"}


def _contains(text: str, needle: str) -> bool:
    return sanitize_text(needle).lower() in sanitize_text(text).lower()


def _mentions_specific_current_product_context(text: str) -> bool:
    normalized_text = sanitize_text(text)
    direct_aliases = (
        "\u5f53\u524d\u8fd9\u6b3e",
        "\u8fd9\u6b3e\u5546\u54c1",
        "\u6309\u5f53\u524d\u8fd9\u6b3e",
        "\u6309\u8fd9\u6b3e",
        "\u6309\u60a8\u8fd9\u6b3e",
        "\u60a8\u8fd9\u6b3e",
        "\u8fd9\u6b3e\u300c",
        "\u8fd9\u6b3e\u7684",
    )
    if any(alias in normalized_text for alias in direct_aliases):
        return True
    return bool(re.search(
        r"\u8fd9\u6b3e[\u300c\u300a]?[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff·\-\s]{1,30}[\u300d\u300b]?(?:\u7684|\u5546\u54c1|\u8d44\u6599|\u5b89\u88c5|\u7ed3\u6784|\u914d\u4ef6|\u5c3a\u5bf8|\u627f\u91cd|\u4f18\u60e0|\u6d3b\u52a8|\u552e\u540e)",
        normalized_text,
    ))


def _key_point_satisfied(text: str, key_point: str) -> bool:
    if _contains(text, key_point):
        return True
    normalized_key = sanitize_text(key_point)
    normalized_text = sanitize_text(text)
    if any(term in normalized_key for term in ("\u8f6c\u4eba\u5de5", "\u4eba\u5de5\u6838\u5b9e", "\u4eba\u5de5\u786e\u8ba4")):
        handoff_aliases = (
            "\u8f6c\u4eba\u5de5",
            "\u4eba\u5de5\u6838\u5b9e",
            "\u4eba\u5de5\u786e\u8ba4",
            "\u6838\u5b9e\u540e\u5904\u7406",
            "\u5904\u7406\u65b9\u6848",
            "\u786e\u8ba4\u540e\u7ed9\u60a8",
            "\u6838\u5bf9\u540e\u5904\u7406",
            "\u51c6\u786e\u56de\u590d",
            "\u786e\u8ba4\u540e\u56de\u590d",
            "\u6211\u4e00\u8d77\u5e2e\u60a8\u6838\u5bf9",
        )
        return any(alias in normalized_text for alias in handoff_aliases)
    if any(term in normalized_key for term in ("不直接承诺有安装视频", "不承诺有安装视频")):
        video_promises = ("一定有安装视频", "可以发安装视频", "我把安装视频发您", "把安装视频发您", "发安装视频")
        return not any(term in normalized_text for term in video_promises)
    if any(term in normalized_key for term in ("\u5f53\u524d\u5546\u54c1", "\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1", "\u6309\u5f53\u524d\u5546\u54c1", "\u6309\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1")):
        return _mentions_specific_current_product_context(normalized_text)
    alias_groups = [
        (
            ("\u5b89\u88c5\u56fe", "\u8bf4\u660e\u4e66", "\u5b89\u88c5\u56fe\u6216\u8bf4\u660e\u4e66"),
            (
                "\u5b89\u88c5\u56fe",
                "\u5b89\u88c5\u793a\u610f\u56fe",
                "\u8bf4\u660e\u4e66",
                "\u56fe\u7eb8",
                "\u6309\u56fe",
                "\u6b65\u9aa4\u8bf4\u660e",
            ),
        ),
        (
            ("\u5f53\u524d\u5546\u54c1", "\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1", "\u6309\u5f53\u524d\u5546\u54c1", "\u6309\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1"),
            (
                "\u5f53\u524d\u8fd9\u6b3e",
                "\u8fd9\u6b3e\u5546\u54c1",
                "\u6309\u5f53\u524d\u8fd9\u6b3e",
                "\u6309\u8fd9\u6b3e",
                "\u6309\u60a8\u8fd9\u6b3e",
                "\u60a8\u8fd9\u6b3e",
                "\u8fd9\u6b3e\u300c",
                "\u8fd9\u6b3e\u7684",
            ),
        ),
        (
            ("\u4e0d\u80fd\u76f4\u63a5\u627f\u8bfa\u989d\u5916\u964d\u4ef7", "\u4e0d\u627f\u8bfa\u989d\u5916\u964d\u4ef7", "\u4e0d\u76f4\u63a5\u627f\u8bfa\u4f18\u60e0"),
            ("\u4ee5\u60a8\u4e0b\u5355\u9875\u9762\u663e\u793a\u4e3a\u51c6", "\u4ee5\u60a8\u4e0b\u5355\u9875\u663e\u793a\u4e3a\u51c6", "\u4ee5\u4e0b\u5355\u9875\u9762\u663e\u793a\u4e3a\u51c6", "\u4ee5\u4e0b\u5355\u9875\u663e\u793a\u4e3a\u51c6", "\u4ee5\u9875\u9762\u663e\u793a\u4e3a\u51c6", "\u6309\u9875\u9762\u89c4\u5219\u6838\u5bf9", "\u6838\u5bf9\u6d3b\u52a8\u89c4\u5219"),
        ),
        (
            ("\u4e0d\u76f4\u63a5\u627f\u8bfa\u6709\u5b89\u88c5\u89c6\u9891", "\u4e0d\u627f\u8bfa\u6709\u5b89\u88c5\u89c6\u9891"),
            ("\u6682\u65f6\u6ca1\u6709\u53ef\u76f4\u63a5\u53d1\u9001\u7684\u5b89\u88c5\u89c6\u9891", "\u6ca1\u6709\u53ef\u76f4\u63a5\u53d1\u9001\u7684\u5b89\u88c5\u89c6\u9891", "\u4e0d\u76f4\u63a5\u627f\u8bfa\u6709\u5b89\u88c5\u89c6\u9891", "\u4e0d\u627f\u8bfa\u6709\u5b89\u88c5\u89c6\u9891"),
        ),
        (("先别着急", "安抚", "别着急"), ("先别着急", "别担心", "我先帮您核实", "我来帮您处理", "给您处理")),
        (("订单信息", "当前订单"), ("当前订单", "订单信息", "按订单", "订单")),
        (("实物照片", "问题照片", "问题位置"), ("实物照片", "问题位置", "拍照", "拍一下", "图片")),
        (("转人工", "人工核实", "人工确认"), ("转人工", "人工核实", "人工确认", "核实后处理", "处理方案", "确认后给您", "核对后处理", "准确回复", "确认后回复")),
    ]
    alias_groups.append((
        ("\u8f6c\u4eba\u5de5", "\u4eba\u5de5\u6838\u5b9e", "\u4eba\u5de5\u786e\u8ba4"),
        (
            "\u8f6c\u4eba\u5de5",
            "\u4eba\u5de5\u6838\u5b9e",
            "\u4eba\u5de5\u786e\u8ba4",
            "\u6838\u5b9e\u540e\u5904\u7406",
            "\u5904\u7406\u65b9\u6848",
            "\u786e\u8ba4\u540e\u7ed9\u60a8",
            "\u6838\u5bf9\u540e\u5904\u7406",
            "\u51c6\u786e\u56de\u590d",
            "\u786e\u8ba4\u540e\u56de\u590d",
            "\u6211\u4e00\u8d77\u5e2e\u60a8\u6838\u5bf9",
        ),
    ))
    for triggers, aliases in alias_groups:
        if any(trigger in normalized_key for trigger in triggers):
            return any(alias in normalized_text for alias in aliases)
    return False


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


def _answer_trace_summary(response: dict[str, Any]) -> dict[str, Any]:
    trace = response.get("answer_trace") if isinstance(response.get("answer_trace"), dict) else {}
    return sanitize_obj({
        "query_fact_type": trace.get("query_fact_type"),
        "required_fact_types": trace.get("required_fact_types"),
        "evidence_answered_fact_types": trace.get("evidence_answered_fact_types"),
        "mode": trace.get("mode"),
        "rag_evidence_used": trace.get("rag_evidence_used"),
        "block_reasons": trace.get("block_reasons"),
    })


def _reply_status(response: dict[str, Any], agent_reply: str) -> str:
    if bool(response.get("can_send")) and agent_reply:
        return "can_send"
    if bool(response.get("requires_human_review")):
        return "requires_human_review"
    if not agent_reply:
        return "no_sendable_reply"
    return "blocked"


def _buyer_turns(conversation_turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns = []
    for item in conversation_turns or []:
        if not isinstance(item, dict):
            continue
        speaker = sanitize_text(item.get("speaker")).lower()
        text = sanitize_text(item.get("text") or item.get("message"))
        if text and speaker in CUSTOMER_SPEAKER_ROLES:
            turns.append({**item, "text": text})
    return turns


def _speaker_role(speaker: str) -> str:
    normalized = sanitize_text(speaker).lower()
    if normalized in CUSTOMER_SPEAKER_ROLES:
        return "customer"
    if normalized in AGENT_SPEAKER_ROLES:
        return "agent"
    return "system"


def _target_buyer_turn(conversation_turns: list[dict[str, Any]], target_turn_uid: str) -> dict[str, Any] | None:
    buyers = _buyer_turns(conversation_turns)
    target_turn_uid = sanitize_text(target_turn_uid)
    if target_turn_uid:
        for turn in buyers:
            if sanitize_text(turn.get("turn_uid")) == target_turn_uid:
                return turn
    return buyers[-1] if buyers else None


def _history_before_target(conversation_turns: list[dict[str, Any]], target_turn_uid: str) -> list[dict[str, str]]:
    target_turn_uid = sanitize_text(target_turn_uid)
    history: list[dict[str, str]] = []
    for turn in conversation_turns or []:
        if not isinstance(turn, dict):
            continue
        if target_turn_uid and sanitize_text(turn.get("turn_uid")) == target_turn_uid:
            break
        text = sanitize_text(turn.get("text") or turn.get("message"))
        if not text:
            continue
        history.append({"role": _speaker_role(turn.get("speaker")), "text": text})
    return history


def _scenario_query_fact_type(scenario) -> str:
    metadata = scenario.get_metadata()
    expected = scenario.get_expected_reply()
    rubric = scenario.get_rubric()
    return sanitize_text(
        metadata.get("query_fact_type")
        or expected.get("query_fact_type")
        or rubric.get("query_fact_type")
        or ""
    )


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
        scenario_type: str | None = None,
        limit: int | None = None,
        scenario_uids: list[str] | None = None,
        run_uid: str | None = None,
        include_full_trace: bool = False,
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
            scenario_type = sanitize_text(scenario_type)
            if scenario_type:
                query = query.filter(AgentBenchmarkScenario.scenario_type == scenario_type)
            query = query.order_by(AgentBenchmarkScenario.id.asc())
            if limit:
                query = query.limit(max(int(limit), 1))
            rows = query.all()
            benchmark_run_uid = sanitize_text(run_uid or "") or f"bench_run_{uuid.uuid4().hex[:12]}"
            results = [self._run_one(row, run_uid=benchmark_run_uid, include_full_trace=include_full_trace) for row in rows]
            passed = sum(1 for item in results if item.get("passed"))
            total = len(results)
            failure_reasons: dict[str, int] = {}
            by_scenario_type: dict[str, dict[str, Any]] = {}
            by_query_fact_type: dict[str, dict[str, Any]] = {}
            by_reply_status: dict[str, int] = {}
            for item in results:
                self._add_group_result(by_scenario_type, item.get("scenario_type") or "unknown", bool(item.get("passed")))
                self._add_group_result(by_query_fact_type, item.get("query_fact_type") or "unknown", bool(item.get("passed")))
                reply_status = sanitize_text(item.get("reply_status") or "unknown")
                by_reply_status[reply_status] = by_reply_status.get(reply_status, 0) + 1
                for reason in item.get("failure_reasons", []):
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            return sanitize_obj({
                "benchmark_run_uid": benchmark_run_uid,
                "run_uid": benchmark_run_uid,
                "status": status,
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "total_scenarios": total,
                "passed_count": passed,
                "failed_count": total - passed,
                "pass_rate": round(passed / total, 4) if total else 0,
                "failure_reasons": failure_reasons,
                "by_scenario_type": by_scenario_type,
                "by_query_fact_type": by_query_fact_type,
                "by_failure_reason": failure_reasons,
                "by_reply_status": by_reply_status,
                "per_scenario_result": results,
            })
        finally:
            db.close()

    def _add_group_result(self, container: dict[str, dict[str, Any]], key: str, passed: bool) -> None:
        item = container.setdefault(sanitize_text(key) or "unknown", {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0})
        item["total"] += 1
        if passed:
            item["passed"] += 1
        else:
            item["failed"] += 1
        item["pass_rate"] = round(item["passed"] / item["total"], 4) if item["total"] else 0

    def _run_one(self, scenario, run_uid: str = "", include_full_trace: bool = False) -> dict[str, Any]:
        sidecar = scenario.get_sidecar_context()
        expected = scenario.get_expected_reply()
        conversation_turns = scenario.get_conversation_turns()
        metadata = scenario.get_metadata()
        target_turn_uid = sanitize_text(metadata.get("source_turn_uid"))
        target_turn = _target_buyer_turn(conversation_turns, target_turn_uid)
        responses = []
        history = _history_before_target(conversation_turns, target_turn_uid)
        total_latency_ms = 0
        if target_turn:
            payload = self._build_payload(
                scenario.scenario_uid,
                target_turn,
                history,
                sidecar,
                run_uid,
                query_fact_type=_scenario_query_fact_type(scenario),
            )
            started = time.perf_counter()
            response = sanitize_obj(self._call_agent(payload))
            latency_ms = int((time.perf_counter() - started) * 1000)
            total_latency_ms += latency_ms
            responses.append({"turn_uid": target_turn.get("turn_uid", ""), "payload": sanitize_obj(payload), "response": response})
        score = self._score(scenario.scenario_type, expected, responses[-1]["response"] if responses else {})
        last_response = responses[-1]["response"] if responses else {}
        fact_type = _response_query_fact_type(last_response)
        result = {
            "scenario_uid": scenario.scenario_uid,
            "title": scenario.title,
            "scenario_type": scenario.scenario_type,
            "query_fact_type": fact_type,
            "sidecar_context": self._sidecar_summary(sidecar),
            "conversation_turns": conversation_turns,
            "expected_reply": expected,
            "passed": score["passed"],
            "failure_reasons": score["failure_reasons"],
            "missing_key_points": score["missing_key_points"],
            "forbidden_claims_hit": score["forbidden_claims_hit"],
            "agent_reply": score["agent_reply"],
            "sendable_reply": sanitize_text(last_response.get("sendable_reply")),
            "draft_reply": sanitize_text(last_response.get("draft_reply") or last_response.get("suggested_reply")),
            "can_send": bool(last_response.get("can_send")),
            "requires_human_review": bool(last_response.get("requires_human_review")),
            "reply_status": score["reply_status"],
            "latency_ms": total_latency_ms,
            "answer_trace": _answer_trace_summary(last_response),
        }
        if include_full_trace:
            result["responses"] = responses
        return sanitize_obj(result)

    def _sidecar_summary(self, sidecar: dict[str, Any]) -> dict[str, Any]:
        return sanitize_obj({
            "product_title": sidecar.get("product_title") or sidecar.get("product_name"),
            "sku_code": sidecar.get("sku_code"),
            "i_id": sidecar.get("i_id"),
            "order_id": sidecar.get("order_id"),
            "platform_order_id": sidecar.get("platform_order_id"),
        })

    def _build_payload(
        self,
        scenario_uid: str,
        turn: dict[str, Any],
        history: list[dict[str, Any]],
        sidecar: dict[str, Any],
        run_uid: str,
        query_fact_type: str = "",
    ) -> dict[str, Any]:
        product_title = sanitize_text(sidecar.get("product_title") or sidecar.get("product_name"))
        query_fact_type = sanitize_text(query_fact_type)
        turn_understanding = {}
        if query_fact_type:
            turn_understanding = {
                "turn_actionability": "actionable_question",
                "query_fact_type": query_fact_type,
                "expected_query_fact_type": query_fact_type,
                "source": "agent_benchmark_reviewed_rubric",
            }
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
                "benchmark_query_fact_type": query_fact_type,
                "customer_message": sanitize_text(turn.get("text")),
                "current_query": sanitize_text(turn.get("text")),
                "turn_understanding": turn_understanding,
            },
        }

    def _score(self, scenario_type: str, expected: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
        agent_reply = _extract_reply(response)
        reasons: list[str] = []
        missing_key_points: list[str] = []
        forbidden_claims_hit: list[str] = []
        reply_status = _reply_status(response, agent_reply)
        if bool(response.get("can_send")) != bool(expected.get("auto_send_allowed")):
            if bool(response.get("can_send")) and not bool(expected.get("auto_send_allowed")):
                reasons.append("auto_send_not_allowed")
            else:
                reasons.append("auto_send_missing")
        if bool(response.get("requires_human_review")) != bool(expected.get("must_handoff")):
            reasons.append("handoff_mismatch")
        for point in expected.get("key_points") or []:
            if sanitize_text(point) and not _key_point_satisfied(agent_reply, point):
                missing_key_points.append(sanitize_text(point))
                reasons.append("missing_key_point")
                break
        for forbidden in expected.get("forbidden_claims") or []:
            if sanitize_text(forbidden) and _contains(agent_reply, forbidden):
                forbidden_claims_hit.append(sanitize_text(forbidden))
                reasons.append("forbidden_claim_present")
                break
        labels = set(_response_failure_labels(response))
        if labels & BLOCKING_FAILURE_LABELS:
            reasons.append("blocking_failure_label")
        fact_type = _response_query_fact_type(response)
        allowed = SCENARIO_FACT_TYPE_COMPATIBILITY.get(sanitize_text(scenario_type), set())
        if allowed and fact_type and fact_type not in allowed:
            reasons.append("fact_type_mismatch")
        if reply_status == "no_sendable_reply" and bool(expected.get("auto_send_allowed")):
            reasons.append("no_sendable_reply")
        elif reply_status == "blocked" and bool(expected.get("auto_send_allowed")):
            reasons.append("blocked_reply")
        return {
            "passed": not reasons,
            "failure_reasons": reasons,
            "missing_key_points": missing_key_points,
            "forbidden_claims_hit": forbidden_claims_hit,
            "agent_reply": agent_reply,
            "reply_status": reply_status,
        }
