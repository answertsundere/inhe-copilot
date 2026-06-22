"""Daily eval replay service for deterministic quality contracts."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from datetime import datetime
from typing import Any, Callable

from app.db import Base
from app.models.eval_tables import EvalCase, EvalFailure, EvalRun, EvalTrace
from app.services.eval_failure_classifier import classify_eval_failure
from app.services.eval_repair_task_service import generate_repair_tasks
from app.services.eval_sanitizer_service import sanitize_case_payload, sanitize_json, sanitize_payload, sanitize_text

ResponseRunner = Callable[[dict[str, Any]], dict[str, Any]]


class EvalReplayService:
    def __init__(self, response_runner: ResponseRunner | None = None):
        self.response_runner = response_runner or _default_response_runner

    def create_case(self, data: dict[str, Any]) -> dict[str, Any]:
        ensure_eval_tables()
        sanitized = sanitize_case_payload(data or {})
        case_uid = str(data.get("case_uid") or f"eval_{uuid.uuid4().hex[:12]}")
        db = _session()
        try:
            row = EvalCase(
                case_uid=case_uid,
                source=str(data.get("source") or "manual")[:64],
                source_ref=sanitize_text(data.get("source_ref") or "", max_len=255),
                status=str(data.get("status") or "active")[:32],
                priority=_safe_int(data.get("priority"), 50),
                category=str(data.get("category") or "")[:128],
                customer_message_sanitized=sanitized["customer_message_sanitized"],
                context_sanitized_json=sanitize_json(sanitized["context_sanitized"]),
                expected_intent=str(data.get("expected_intent") or "")[:64],
                expected_fact_types_json=sanitize_json(data.get("expected_fact_types") or []),
                expected_behavior_json=sanitize_json(data.get("expected_behavior") or {}),
                forbidden_terms_json=sanitize_json(data.get("forbidden_terms") or []),
                required_evidence_types_json=sanitize_json(data.get("required_evidence_types") or []),
                product_scope_json=sanitize_json(sanitized["product_scope"]),
                created_by=str(data.get("created_by") or "api")[:64],
                metadata_json=sanitize_json(sanitized["metadata"]),
            )
            db.add(row)
            db.commit()
            return eval_case_to_dict(row)
        finally:
            db.close()

    def run_replay(
        self,
        *,
        limit: int = 30,
        category: str = "",
        run_type: str = "manual",
        apply: bool = True,
        config_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ensure_eval_tables()
        run_uid = f"eval_run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        started = datetime.utcnow()
        cases = self._load_cases(limit=limit, category=category)
        if not apply:
            return {
                "run_uid": run_uid,
                "run_type": run_type,
                "status": "dry_run",
                "total_cases": len(cases),
                "case_uids": [case.case_uid for case in cases],
            }

        db = _session()
        try:
            run = EvalRun(
                run_uid=run_uid,
                run_type=str(run_type or "manual")[:64],
                status="running",
                started_at=started,
                total_cases=len(cases),
                code_version=_git_value(["rev-parse", "--short", "HEAD"]),
                branch_name=_git_value(["branch", "--show-current"]),
                config_snapshot_json=sanitize_json(config_snapshot or {"limit": limit, "category": category}),
            )
            db.add(run)
            db.commit()

            counts = {"passed": 0, "failed": 0, "error": 0}
            failure_rows: list[dict[str, Any]] = []
            for case in cases:
                result = self._run_case(case, run_uid)
                counts[result["status"]] += 1
                failure_rows.extend(result.get("failures", []))

            run.status = "completed"
            run.finished_at = datetime.utcnow()
            run.passed_cases = counts["passed"]
            run.failed_cases = counts["failed"]
            run.error_cases = counts["error"]
            run.summary_json = sanitize_json({"counts": counts, "failure_count": len(failure_rows)})
            db.commit()
        finally:
            db.close()

        repair_tasks = generate_repair_tasks(run_uid)
        return get_run_detail(run_uid) | {"repair_tasks": repair_tasks}

    def _load_cases(self, *, limit: int, category: str) -> list[EvalCase]:
        db = _session()
        try:
            query = db.query(EvalCase).filter(EvalCase.status == "active")
            if category:
                query = query.filter(EvalCase.category == category)
            return query.order_by(EvalCase.priority.desc(), EvalCase.id.asc()).limit(_bounded_limit(limit)).all()
        finally:
            db.close()

    def _run_case(self, case: EvalCase, run_uid: str) -> dict[str, Any]:
        case_dict = eval_case_to_dict(case)
        t0 = time.time()
        try:
            response = self.response_runner(case_dict)
            latency_ms = int((time.time() - t0) * 1000)
            failures = evaluate_contracts(case_dict, response)
            status = "passed" if not failures else "failed"
        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            response = {"error": type(exc).__name__}
            failures = [classify_eval_failure(case_dict, response, "runner_error", "no error", type(exc).__name__)]
            status = "error"

        trace = _build_trace(run_uid, case.case_uid, status, latency_ms, response)
        failure_rows = []
        db = _session()
        try:
            db.add(EvalTrace(**trace))
            for failure in failures:
                row = EvalFailure(
                    run_uid=run_uid,
                    case_uid=case.case_uid,
                    failure_type=failure["failure_type"],
                    severity=failure["severity"],
                    root_cause_hint=sanitize_text(failure["root_cause_hint"], max_len=1000),
                    failed_contract=str(failure["failed_contract"])[:128],
                    expected_json=sanitize_json(failure.get("expected")),
                    actual_json=sanitize_json({
                        "actual": failure.get("actual"),
                        "suggested_files": failure.get("suggested_files") or [],
                    }),
                    suggested_fix_area=failure["suggested_fix_area"],
                    status="open",
                )
                db.add(row)
                failure_rows.append(failure)
            db.commit()
        finally:
            db.close()
        return {"status": status, "failures": failure_rows}


def evaluate_contracts(case: dict[str, Any], response: dict[str, Any]) -> list[dict[str, Any]]:
    behavior = dict(case.get("expected_behavior") or {})
    if case.get("expected_intent"):
        behavior.setdefault("must_have_intent", case["expected_intent"])
    if case.get("expected_fact_types"):
        behavior.setdefault("must_have_fact_type", case["expected_fact_types"][0])
    if case.get("forbidden_terms"):
        behavior.setdefault("must_not_contain", case["forbidden_terms"])
    if case.get("required_evidence_types"):
        behavior.setdefault("must_have_evidence_type", case["required_evidence_types"])

    failures = []
    reply = str(response.get("suggested_reply") or response.get("reply") or "")
    debug = response.get("evidence_debug") or {}
    answer_trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    tool_trace = debug.get("tool_policy_trace") or response.get("tool_policy_trace") or {}
    actual_intent = response.get("intent") or debug.get("normalized_intent") or debug.get("final_intent") or ""
    actual_fact_type = response.get("query_fact_type") or debug.get("query_fact_type") or answer_trace.get("query_fact_type") or ""

    for term in _as_list(behavior.get("must_not_contain")):
        if term and term in reply:
            failures.append(classify_eval_failure(case, response, "must_not_contain", term, term))
    any_terms = _as_list(behavior.get("must_contain_any"))
    if any_terms and not any(term in reply for term in any_terms):
        failures.append(classify_eval_failure(case, response, "must_contain_any", any_terms, reply[:120]))
    if behavior.get("must_have_intent") and actual_intent != behavior["must_have_intent"]:
        failures.append(classify_eval_failure(case, response, "must_have_intent", behavior["must_have_intent"], actual_intent))
    if behavior.get("must_have_fact_type") and actual_fact_type != behavior["must_have_fact_type"]:
        failures.append(classify_eval_failure(case, response, "must_have_fact_type", behavior["must_have_fact_type"], actual_fact_type))
    if "must_not_require_human" in behavior and bool(response.get("requires_human_review")) != bool(behavior["must_not_require_human"]):
        failures.append(classify_eval_failure(case, response, "must_not_require_human", behavior["must_not_require_human"], response.get("requires_human_review")))
    for evidence_type in _as_list(behavior.get("must_have_evidence_type")):
        if not _has_evidence_type(evidence_type, response, answer_trace, debug):
            failures.append(classify_eval_failure(case, response, "must_have_evidence_type", evidence_type, _evidence_shape(answer_trace, debug)))
    called_tools = _called_tools(tool_trace)
    for tool in _as_list(behavior.get("must_not_call_tools")):
        if tool in called_tools:
            failures.append(classify_eval_failure(case, response, "must_not_call_tools", tool, called_tools))
    for tool in _as_list(behavior.get("must_call_tools")):
        if tool not in called_tools:
            failures.append(classify_eval_failure(case, response, "must_call_tools", tool, called_tools))
    return failures


def ensure_eval_tables() -> None:
    from app.models.eval_tables import EvalCase, EvalFailure, EvalRepairTask, EvalRun, EvalTrace

    from app import db as db_module

    Base.metadata.create_all(bind=db_module.engine, tables=[
        EvalCase.__table__,
        EvalRun.__table__,
        EvalTrace.__table__,
        EvalFailure.__table__,
        EvalRepairTask.__table__,
    ])


def get_run_detail(run_uid: str) -> dict[str, Any]:
    ensure_eval_tables()
    db = _session()
    try:
        run = db.query(EvalRun).filter(EvalRun.run_uid == run_uid).first()
        if not run:
            return {}
        traces = db.query(EvalTrace).filter(EvalTrace.run_uid == run_uid).order_by(EvalTrace.id.asc()).all()
        failures = db.query(EvalFailure).filter(EvalFailure.run_uid == run_uid).order_by(EvalFailure.id.asc()).all()
        return {
            "run": eval_run_to_dict(run),
            "traces": [eval_trace_to_dict(row) for row in traces],
            "failures": [eval_failure_to_dict(row) for row in failures],
        }
    finally:
        db.close()


def eval_case_to_dict(row: EvalCase) -> dict[str, Any]:
    return {
        "id": row.id,
        "case_uid": row.case_uid,
        "source": row.source,
        "source_ref": row.source_ref,
        "status": row.status,
        "priority": row.priority,
        "category": row.category,
        "customer_message_sanitized": row.customer_message_sanitized,
        "context_sanitized": _loads(row.context_sanitized_json, {}),
        "expected_intent": row.expected_intent,
        "expected_fact_types": _loads(row.expected_fact_types_json, []),
        "expected_behavior": _loads(row.expected_behavior_json, {}),
        "forbidden_terms": _loads(row.forbidden_terms_json, []),
        "required_evidence_types": _loads(row.required_evidence_types_json, []),
        "product_scope": _loads(row.product_scope_json, []),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "metadata": _loads(row.metadata_json, {}),
    }


def eval_run_to_dict(row: EvalRun) -> dict[str, Any]:
    return {
        "run_uid": row.run_uid,
        "run_type": row.run_type,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else "",
        "finished_at": row.finished_at.isoformat() if row.finished_at else "",
        "total_cases": row.total_cases,
        "passed_cases": row.passed_cases,
        "failed_cases": row.failed_cases,
        "error_cases": row.error_cases,
        "code_version": row.code_version,
        "branch_name": row.branch_name,
        "config_snapshot": _loads(row.config_snapshot_json, {}),
        "summary": _loads(row.summary_json, {}),
    }


def eval_trace_to_dict(row: EvalTrace) -> dict[str, Any]:
    return {
        "run_uid": row.run_uid,
        "case_uid": row.case_uid,
        "status": row.status,
        "latency_ms": row.latency_ms,
        "intent": row.intent,
        "query_fact_type": row.query_fact_type,
        "required_fact_types": _loads(row.required_fact_types_json, []),
        "requires_human_review": row.requires_human_review,
        "final_quality_pass": row.final_quality_pass,
        "answer_trace_summary": _loads(row.answer_trace_summary_json, {}),
        "model_trace_summary": _loads(row.model_trace_summary_json, {}),
        "tool_trace_summary": _loads(row.tool_trace_summary_json, {}),
        "evidence_summary": _loads(row.evidence_summary_json, {}),
        "reply_preview": row.reply_preview,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def eval_failure_to_dict(row: EvalFailure) -> dict[str, Any]:
    return {
        "run_uid": row.run_uid,
        "case_uid": row.case_uid,
        "failure_type": row.failure_type,
        "severity": row.severity,
        "root_cause_hint": row.root_cause_hint,
        "failed_contract": row.failed_contract,
        "expected": _loads(row.expected_json, {}),
        "actual": _loads(row.actual_json, {}),
        "suggested_fix_area": row.suggested_fix_area,
        "repair_task_uid": row.repair_task_uid,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _build_trace(run_uid: str, case_uid: str, status: str, latency_ms: int, response: dict[str, Any]) -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
    answer_trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    tool_trace = debug.get("tool_policy_trace") or response.get("tool_policy_trace") or {}
    reply = response.get("suggested_reply") or response.get("reply") or ""
    return {
        "run_uid": run_uid,
        "case_uid": case_uid,
        "status": status,
        "latency_ms": latency_ms,
        "intent": str(response.get("intent") or debug.get("normalized_intent") or debug.get("final_intent") or "")[:64],
        "query_fact_type": str(response.get("query_fact_type") or debug.get("query_fact_type") or answer_trace.get("query_fact_type") or "")[:64],
        "required_fact_types_json": sanitize_json(answer_trace.get("required_fact_types") or debug.get("required_fact_types") or []),
        "requires_human_review": bool(response.get("requires_human_review")),
        "final_quality_pass": _final_quality_pass(response, debug),
        "answer_trace_summary_json": sanitize_json(_summary(answer_trace, ["query_fact_type", "required_fact_types", "mode", "answered_fact_types"])),
        "model_trace_summary_json": sanitize_json(_summary(debug.get("model_trace") or response.get("model_trace") or {}, ["model", "alias", "status"])),
        "tool_trace_summary_json": sanitize_json(_summary(tool_trace, ["allowed_tools", "blocked_tools", "tool_call_count", "high_risk_tool_called"])),
        "evidence_summary_json": sanitize_json(_evidence_shape(answer_trace, debug)),
        "reply_preview": sanitize_text(reply, max_len=200),
    }


def _default_response_runner(case: dict[str, Any]) -> dict[str, Any]:
    from app.main import get_reply_service
    from app.services.analysis_execution_service import execute_analysis

    return execute_analysis(
        reply_service=get_reply_service(),
        customer_message=case.get("customer_message_sanitized", ""),
        conversation_id=f"eval_{case.get('case_uid', 'case')}",
        copilot_context=case.get("context_sanitized") or {},
        source="eval_replay",
        final_orchestration=True,
    )


def _has_evidence_type(evidence_type: str, response: dict, answer_trace: dict, debug: dict) -> bool:
    if evidence_type == "media":
        return bool(answer_trace.get("asset_evidence_used") or response.get("recommended_assets") or debug.get("selected_assets"))
    if evidence_type == "rag":
        return bool(answer_trace.get("rag_evidence_used") or debug.get("selected_evidence") or debug.get("used_knowledge_entry_ids"))
    if evidence_type == "product_card":
        return bool((debug.get("product_context_pack_summary") or {}).get("evidence_pack") or debug.get("product_facts"))
    return evidence_type in json.dumps(_evidence_shape(answer_trace, debug), ensure_ascii=False)


def _called_tools(tool_trace: dict) -> set[str]:
    tools = set(tool_trace.get("allowed_tools") or [])
    for item in tool_trace.get("evaluated_tools") or []:
        if item.get("status") in {"success", "error"}:
            tools.add(item.get("tool_name", ""))
    return {tool for tool in tools if tool}


def _evidence_shape(answer_trace: dict, debug: dict) -> dict[str, Any]:
    return {
        "rag_fact_types": list((answer_trace.get("rag_evidence_used") or {}).keys()),
        "asset_fact_types": list((answer_trace.get("asset_evidence_used") or {}).keys()),
        "selected_evidence_count": len(debug.get("selected_evidence") or []),
        "used_knowledge_count": len(debug.get("used_knowledge_entry_ids") or []),
        "selected_assets_count": len(debug.get("selected_assets") or []),
    }


def _summary(data: dict, keys: list[str]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return sanitize_payload({key: data.get(key) for key in keys if key in data})


def _final_quality_pass(response: dict, debug: dict) -> bool:
    audit = debug.get("final_answer_audit") or debug.get("final_semantic_fit_audit") or {}
    if isinstance(audit, dict) and "passed" in audit:
        return bool(audit.get("passed"))
    return not bool(response.get("error"))


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _loads(raw: str, default):
    try:
        parsed = json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return default
    return parsed if parsed is not None else default


def _bounded_limit(value: int) -> int:
    return max(1, min(_safe_int(value, 30), 200))


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _git_value(args: list[str]) -> str:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return result.stdout.strip()[:128]
    except Exception:
        pass
    return ""


def _session():
    from app import db as db_module

    return db_module.SessionLocal()
