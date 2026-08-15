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


def _formal_report(payload: dict[str, Any], validation: dict[str, Any], rows_by_uid: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [rows_by_uid[item["scenario_uid"]] for item in payload["scenarios"] if item["scenario_uid"] in rows_by_uid]
    return {
        "report_schema_version": "p1-high-frequency-synthetic-formal-pipeline-report/v1",
        "dataset_id": payload["dataset_id"],
        "dataset_version": payload["dataset_version"],
        "dataset_sha256": _canonical_sha256(payload),
        "source": payload["source"],
        "validation": validation,
        "generation_path": "formal_analysis_pipeline",
        "real_customer_accuracy": None,
        "optimization_unverified": True,
        "agent_call_is_formal_runtime_call": True,
        "rows": rows,
        "summary": {
            "scenario_count": len(payload["scenarios"]),
            "completed_count": len(rows),
            "response_count": sum(bool(row["candidate_reply"]) for row in rows),
            "error_count": sum(bool(row["error"]) for row in rows),
            "requires_human_review_count": sum(row["requires_human_review"] for row in rows),
            "can_send_true_count": sum(row["can_send"] for row in rows),
        },
    }


def _load_checkpoint(payload: dict[str, Any], checkpoint_path: Path) -> dict[str, dict[str, Any]]:
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyntheticDialogueError("formal_checkpoint_unreadable") from exc
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
                "candidate_reply": _response_reply(body),
                "requires_human_review": bool(body.get("requires_human_review")),
                "can_send": bool(body.get("can_send")),
                "reply_status": str(body.get("reply_status") or ""),
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
        if transport_failure:
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
