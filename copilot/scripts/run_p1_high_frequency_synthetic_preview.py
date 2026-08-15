"""Generate review-only Supervisor Assist previews for synthetic P1 dialogues."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.agent_decision_proposal_service import build_supervisor_partial_answer_preview
from app.services.agent_benchmark_fixture_service import scan_sensitive_content
from scripts.build_p1_high_frequency_synthetic_dialogue_set import SCHEMA_VERSION
from scripts.run_supervisor_partial_answer_preview_eval import _build_preview_context

FORMAL_REPORT_SCHEMA_VERSION = (
    "p1-high-frequency-synthetic-formal-pipeline-report/v2"
)


class SyntheticDialogueError(ValueError):
    """Raised when a synthetic dialogue fixture violates its safety contract."""


def _canonical_sha256(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def validate_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SyntheticDialogueError("unsupported_schema_version")
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    if source.get("classification") != "synthetic_anonymous" or source.get("contains_real_customer_conversations") is not False:
        raise SyntheticDialogueError("synthetic_source_declaration_required")
    constraints = payload.get("generation_constraints") if isinstance(payload.get("generation_constraints"), dict) else {}
    if constraints.get("requires_human_review") is not True or constraints.get("can_send") is not False:
        raise SyntheticDialogueError("review_only_delivery_contract_required")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) < 30:
        raise SyntheticDialogueError("at_least_thirty_scenarios_required")
    seen: set[str] = set()
    topics: Counter[str] = Counter()
    for item in scenarios:
        if not isinstance(item, dict):
            raise SyntheticDialogueError("scenario_must_be_object")
        uid = str(item.get("scenario_uid") or "")
        if not uid or uid in seen or not uid.startswith("hf-syn-"):
            raise SyntheticDialogueError("scenario_uid_invalid")
        seen.add(uid)
        turns = item.get("conversation_turns")
        if not isinstance(turns, list) or len(turns) < 5:
            raise SyntheticDialogueError("multi_turn_context_required")
        if str((turns[-1] or {}).get("speaker") or "").lower() != "buyer":
            raise SyntheticDialogueError("final_turn_must_be_buyer")
        raw = item.get("raw_context") if isinstance(item.get("raw_context"), dict) else {}
        if raw.get("customer_message") != (turns[-1] or {}).get("text"):
            raise SyntheticDialogueError("final_turn_and_context_must_match")
        identity = raw.get("product_identity") if isinstance(raw.get("product_identity"), dict) else {}
        if not all(str(identity.get(key) or "").startswith("SYN-") for key in ("sku_code", "i_id", "order_id")):
            raise SyntheticDialogueError("synthetic_identity_required")
        if not isinstance(raw.get("requested_claims"), list) or not raw["requested_claims"]:
            raise SyntheticDialogueError("requested_claim_required")
        expectation = item.get("review_expectations") if isinstance(item.get("review_expectations"), dict) else {}
        if expectation.get("requires_human_review") is not True or expectation.get("can_send") is not False:
            raise SyntheticDialogueError("scenario_review_only_contract_required")
        topics[str(item.get("demand_topic") or "unknown")] += 1
    privacy = scan_sensitive_content(payload)
    if not privacy["passed"]:
        raise SyntheticDialogueError("synthetic_privacy_scan_failed")
    return {"scenario_count": len(scenarios), "topic_counts": dict(sorted(topics.items())), "privacy_scan": privacy}


def build_report(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_dataset(payload)
    rows: list[dict[str, Any]] = []
    for item in payload["scenarios"]:
        raw = item["raw_context"]
        preview = build_supervisor_partial_answer_preview(
            _build_preview_context(raw),
            provider_status="not_qualified",
        )
        if preview.get("can_send") is not False or preview.get("requires_human_review") is not True or preview.get("used_for_final_reply") is not False:
            raise SyntheticDialogueError("preview_delivery_contract_regressed")
        rows.append({
            "scenario_uid": item["scenario_uid"],
            "title": item["title"],
            "demand_topic": item["demand_topic"],
            "customer_profile": item["customer_profile"],
            "conversation_turns": item["conversation_turns"],
            "candidate_reply": preview.get("candidate_text") or "",
            "requires_human_review": preview["requires_human_review"],
            "can_send": preview["can_send"],
            "used_for_final_reply": preview["used_for_final_reply"],
            "unresolved_claim_count": len(preview.get("pending_clauses") or []),
            "supported_claim_count": len(preview.get("confirmed_clauses") or []),
        })
    return {
        "report_schema_version": "p1-high-frequency-synthetic-preview-report/v1",
        "dataset_id": payload["dataset_id"],
        "dataset_version": payload["dataset_version"],
        "dataset_sha256": _canonical_sha256(payload),
        "source": payload["source"],
        "validation": validation,
        "generation_path": "existing_supervisor_assist_preview",
        "real_customer_accuracy": None,
        "optimization_unverified": True,
        "agent_call_is_formal_runtime_call": False,
        "rows": rows,
        "summary": {
            "scenario_count": len(rows),
            "requires_human_review_count": sum(row["requires_human_review"] for row in rows),
            "can_send_true_count": sum(row["can_send"] for row in rows),
            "formal_reply_use_count": sum(row["used_for_final_reply"] for row in rows),
            "supported_claim_count": sum(row["supported_claim_count"] for row in rows),
            "unresolved_claim_count": sum(row["unresolved_claim_count"] for row in rows),
        },
    }


def _loopback_analyze_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise SyntheticDialogueError("formal_analyze_url_must_be_loopback")
    if parsed.path.rstrip("/") != "/api/analyze":
        raise SyntheticDialogueError("formal_analyze_url_must_target_api_analyze")
    return value.rstrip("/")


def _formal_payload(item: dict[str, Any]) -> dict[str, Any]:
    turns = item["conversation_turns"]
    raw_context = item.get("raw_context") if isinstance(item.get("raw_context"), dict) else {}
    product_identity = (
        raw_context.get("product_identity")
        if isinstance(raw_context.get("product_identity"), dict)
        else {}
    )
    return {
        "conversation_id": f"p1-synthetic-{item['scenario_uid']}",
        "message": raw_context["customer_message"],
        "product_title": str(product_identity.get("product_title") or ""),
        "sku_code": str(product_identity.get("sku_code") or ""),
        "i_id": str(product_identity.get("i_id") or ""),
        "order_id": str(product_identity.get("order_id") or ""),
        "conversation_history": [
            {
                "role": "user" if turn["speaker"] == "buyer" else "assistant",
                "content": turn["text"],
                "turn_index": turn_index,
            }
            for turn_index, turn in enumerate(turns[:-1])
        ],
    }


def _response_reply(response: dict[str, Any]) -> str:
    for key in ("suggested_reply", "reply", "answer", "sendable_reply"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _issue_codes(value: Any) -> list[str]:
    codes: list[str] = []
    for item in value or []:
        if isinstance(item, str) and item.strip():
            codes.append(item.strip())
        elif isinstance(item, dict):
            code = str(item.get("code") or "unknown_issue").strip()
            if code:
                codes.append(code)
    return codes


def _build_formal_observation(
    item: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    """Build the single immutable observation used by reports and gates."""
    expected_history = _formal_payload(item)["conversation_history"]
    minimal_context = _dict(response.get("minimal_decision_context"))
    projected_history = _dict_list(
        minimal_context.get("recent_conversation_turns")
    )
    composer = _dict(response.get("model_first_answer_composer"))
    boundary = _dict(response.get("turn_understanding_boundary"))
    final_audit = _dict(response.get("final_answer_audit"))
    semantic_audit = _dict(response.get("final_semantic_fit_audit"))
    pipeline = _dict(response.get("analysis_pipeline"))
    pipeline_stages = _dict_list(pipeline.get("stages"))
    selected_evidence = _dict_list(
        minimal_context.get("admitted_evidence")
        or response.get("selected_evidence")
    )
    claim_resolutions = _dict_list(minimal_context.get("claim_resolutions"))
    reply = _response_reply(response)

    def history_projection(turns: list[dict[str, Any]]) -> list[dict[str, str]]:
        role_map = {
            "user": "customer",
            "customer": "customer",
            "assistant": "agent",
            "agent": "agent",
        }
        return [
            {
                "role": role_map.get(
                    str(turn.get("role") or "").strip().lower(),
                    "unknown",
                ),
                "content": str(
                    turn.get("content")
                    if turn.get("content") is not None
                    else turn.get("text") or ""
                ).strip(),
            }
            for turn in turns
        ]

    expected_projection = history_projection(expected_history)
    projected_projection = history_projection(projected_history)

    understanding_status = "authoritative"
    if boundary and (
        str(boundary.get("status") or "").strip().lower()
        in {"invalid", "degraded", "blocked"}
        or boundary.get("used_for_final_reply") is False
    ):
        understanding_status = "not_authoritative"

    history_status = (
        "complete"
        if projected_projection == expected_projection
        else "mismatch"
    )
    composer_accepted = (
        composer.get("status") == "accepted"
        and composer.get("used_for_final_reply") is True
    )
    final_passed = final_audit.get("passed") is True

    reason = ""
    if not reply:
        reason = "empty_reply"
    elif understanding_status != "authoritative":
        reason = "turn_understanding_not_authoritative"
    elif history_status != "complete":
        reason = "conversation_history_projection_mismatch"
    elif any(turn.get("turn_uid") for turn in projected_history):
        reason = "transport_uid_leaked"
    elif not composer_accepted:
        reason = "composer_entry_blocked"
    elif not final_passed:
        reason = "final_audit_failed"

    status_counts = {
        status: sum(
            str(claim.get("status") or "") == status
            for claim in claim_resolutions
        )
        for status in ("supported", "unresolved", "conflicting", "prohibited")
    }
    return {
        "candidate_reply": reply,
        "requires_human_review": response.get("requires_human_review") is True,
        "can_send": response.get("can_send") is True,
        "reply_status": str(response.get("reply_status") or ""),
        "expected_history_count": len(expected_history),
        "projected_history_count": len(projected_history),
        "projected_history_roles": [
            turn["role"] for turn in projected_projection
        ],
        "projected_transport_uid_count": sum(
            bool(turn.get("turn_uid")) for turn in projected_history
        ),
        "history_projection_status": history_status,
        "turn_understanding_status": understanding_status,
        "turn_understanding_boundary": (
            {
                "status": str(boundary.get("status") or ""),
                "earliest_reason_code": str(
                    boundary.get("earliest_reason_code") or ""
                ),
                "reason_codes": [
                    str(code) for code in (boundary.get("reason_codes") or [])
                ],
            }
            if boundary
            else None
        ),
        "selected_evidence_count": len(selected_evidence),
        "selected_evidence_roles": [
            str(evidence.get("evidence_role") or "")
            for evidence in selected_evidence
        ],
        "claim_status_counts": status_counts,
        "requested_claim_count": len(
            _dict_list(minimal_context.get("requested_claims"))
        ),
        "composer_status": str(composer.get("status") or ""),
        "composer_rejection_reason": str(
            composer.get("rejection_reason") or ""
        ),
        "composer_used_for_final_reply": (
            composer.get("used_for_final_reply") is True
        ),
        "composer_clause_count": len(_dict_list(composer.get("clauses"))),
        "pipeline_stages": [
            {
                "stage": str(stage.get("stage") or ""),
                "status": str(stage.get("status") or ""),
                "reason": str(stage.get("reason") or ""),
            }
            for stage in pipeline_stages
        ],
        "final_audit_passed": final_passed,
        "final_audit_issue_codes": _issue_codes(final_audit.get("issues")),
        "semantic_audit_status": str(
            semantic_audit.get("status") or ""
        ),
        "stability_status": "not_qualified" if reason else "qualified",
        "stability_reason_code": reason,
    }


def _formal_report(payload: dict[str, Any], validation: dict[str, Any], rows_by_uid: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [rows_by_uid[item["scenario_uid"]] for item in payload["scenarios"] if item["scenario_uid"] in rows_by_uid]
    failure_counts = Counter(
        str(row.get("stability_reason_code") or "")
        for row in rows
        if str(row.get("stability_reason_code") or "")
    )
    stop_reason = next(
        (
            str(row.get("stability_reason_code") or "")
            for row in rows
            if str(row.get("stability_reason_code") or "")
        ),
        "",
    )
    status = (
        "stopped"
        if stop_reason
        else "completed" if len(rows) == len(payload["scenarios"]) else "running"
    )
    return {
        "report_schema_version": FORMAL_REPORT_SCHEMA_VERSION,
        "dataset_id": payload["dataset_id"],
        "dataset_version": payload["dataset_version"],
        "dataset_sha256": _canonical_sha256(payload),
        "source": payload["source"],
        "validation": validation,
        "generation_path": "formal_analysis_pipeline",
        "real_customer_accuracy": None,
        "optimization_unverified": True,
        "agent_call_is_formal_runtime_call": True,
        "status": status,
        "stop_reason": stop_reason,
        "rows": rows,
        "summary": {
            "scenario_count": len(payload["scenarios"]),
            "completed_count": len(rows),
            "response_count": sum(bool(row["candidate_reply"]) for row in rows),
            "error_count": sum(bool(row["error"]) for row in rows),
            "requires_human_review_count": sum(row["requires_human_review"] for row in rows),
            "can_send_true_count": sum(row["can_send"] for row in rows),
            "stability_qualified_count": sum(
                row.get("stability_status") == "qualified" for row in rows
            ),
            "stability_failure_counts": dict(sorted(failure_counts.items())),
        },
    }


def _load_checkpoint(payload: dict[str, Any], checkpoint_path: Path) -> dict[str, dict[str, Any]]:
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyntheticDialogueError("formal_checkpoint_unreadable") from exc
    if checkpoint.get("report_schema_version") != FORMAL_REPORT_SCHEMA_VERSION:
        raise SyntheticDialogueError("formal_checkpoint_schema_mismatch")
    if (
        checkpoint.get("dataset_id") != payload.get("dataset_id")
        or checkpoint.get("dataset_version") != payload.get("dataset_version")
        or checkpoint.get("dataset_sha256") != _canonical_sha256(payload)
        or checkpoint.get("generation_path") != "formal_analysis_pipeline"
    ):
        raise SyntheticDialogueError("formal_checkpoint_dataset_mismatch")
    allowed_uids = {item["scenario_uid"] for item in payload["scenarios"]}
    rows_by_uid: dict[str, dict[str, Any]] = {}
    for row in checkpoint.get("rows") or []:
        if not isinstance(row, dict):
            raise SyntheticDialogueError("formal_checkpoint_row_invalid")
        uid = str(row.get("scenario_uid") or "")
        if uid not in allowed_uids or uid in rows_by_uid:
            raise SyntheticDialogueError("formal_checkpoint_row_invalid")
        rows_by_uid[uid] = row
    return rows_by_uid


def _write_checkpoint(report: dict[str, Any], checkpoint_path: Path) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_formal_report(
    payload: dict[str, Any],
    *,
    analyze_url: str,
    request_timeout: int = 150,
    checkpoint_path: Path | None = None,
    resume: bool = False,
    max_new_cases: int | None = None,
) -> dict[str, Any]:
    """Run fictional contexts through a caller-supplied loopback formal endpoint."""
    validation = validate_dataset(payload)
    if max_new_cases is not None and max_new_cases <= 0:
        raise SyntheticDialogueError("max_new_cases_must_be_positive")
    target = _loopback_analyze_url(analyze_url)
    rows_by_uid = _load_checkpoint(payload, checkpoint_path) if resume and checkpoint_path and checkpoint_path.exists() else {}
    attempted_count = 0
    for item in payload["scenarios"]:
        existing = rows_by_uid.get(item["scenario_uid"])
        if existing and not existing.get("error"):
            continue
        if max_new_cases is not None and attempted_count >= max_new_cases:
            break
        request = Request(
            target,
            data=json.dumps(_formal_payload(item), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=request_timeout) as response:  # nosec B310 - target is loopback-validated above
                body = json.loads(response.read().decode("utf-8"))
            if not isinstance(body, dict):
                raise SyntheticDialogueError("formal_response_must_be_object")
            row = {
                "scenario_uid": item["scenario_uid"],
                "title": item["title"],
                "demand_topic": item["demand_topic"],
                "customer_profile": item["customer_profile"],
                "conversation_turns": item["conversation_turns"],
                **_build_formal_observation(item, body),
                "error": "",
            }
        except Exception as exc:  # report failures; callers decide whether an incomplete run is acceptable
            row = {
                "scenario_uid": item["scenario_uid"],
                "title": item["title"],
                "demand_topic": item["demand_topic"],
                "customer_profile": item["customer_profile"],
                "conversation_turns": item["conversation_turns"],
                "candidate_reply": "",
                "requires_human_review": True,
                "can_send": False,
                "reply_status": "",
                "stability_status": "not_qualified",
                "stability_reason_code": "formal_pipeline_request_failed",
                "error": type(exc).__name__,
            }
            transport_failure = isinstance(
                exc,
                (ConnectionError, TimeoutError, URLError),
            )
        else:
            transport_failure = False
        if row["can_send"] or not row["requires_human_review"]:
            raise SyntheticDialogueError("formal_delivery_contract_regressed")
        rows_by_uid[item["scenario_uid"]] = row
        attempted_count += 1
        if checkpoint_path:
            _write_checkpoint(_formal_report(payload, validation, rows_by_uid), checkpoint_path)
        if transport_failure or row.get("stability_status") != "qualified":
            break
    return _formal_report(payload, validation, rows_by_uid)


def markdown_report(report: dict[str, Any]) -> str:
    reply_label = "正式管线回复草稿" if report["agent_call_is_formal_runtime_call"] else "Supervisor Assist 草稿"
    lines = [
        "# P1 高频问题合成对话正式管线基线" if report["agent_call_is_formal_runtime_call"] else "# P1 高频问题合成对话预览",
        "",
        "本报告全部来自虚构商品、虚构订单和虚构客户上下文，仅用于 Supervisor Assist 草稿检查。",
        "不代表真实客户准确率，也不授予自动发送权限。",
        "",
        f"- 场景总数：{report['summary']['scenario_count']}",
        f"- 已完成：{report['summary'].get('completed_count', report['summary']['scenario_count'])}",
        f"- 人工复核：{report['summary']['requires_human_review_count']}",
        f"- 可自动发送：{report['summary']['can_send_true_count']}",
        f"- 正式管线调用：{'是' if report['agent_call_is_formal_runtime_call'] else '否'}",
        "",
    ]
    for row in report["rows"]:
        lines.extend([f"## {row['scenario_uid']} · {row['demand_topic']}", ""])
        for turn in row["conversation_turns"]:
            speaker = "客户" if turn["speaker"] == "buyer" else "既有客服上下文"
            lines.append(f"- {speaker}：{turn['text']}")
        lines.extend(["", f"**{reply_label}**：{row['candidate_reply']}", "", "---", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--mode", choices=("preview", "formal"), default="preview")
    parser.add_argument("--analyze-url", default="")
    parser.add_argument("--request-timeout", type=int, default=150)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-new-cases", type=int)
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if args.mode == "formal":
        if not args.analyze_url:
            raise SyntheticDialogueError("formal_analyze_url_required")
        report = build_formal_report(
            payload,
            analyze_url=args.analyze_url,
            request_timeout=args.request_timeout,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            max_new_cases=args.max_new_cases,
        )
    else:
        report = build_report(payload)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
