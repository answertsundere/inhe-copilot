"""Read-only attribution and qualification for provider-bound privacy projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.runtime_routes import _source_tree_sha256
from app.llm.client import LLMClient
from app.services.canonical_conversation_turn_service import (
    project_provider_message_text,
    project_text_for_external_model,
    project_value_for_external_model,
)
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.semantic_fact_type_service import (
    SYSTEM_PROMPT as TURN_UNDERSTANDING_SYSTEM_PROMPT,
)


_MARKER = re.compile(r"\[[A-Z_]+_REDACTED(?::[0-9a-f]+)?\]")
_SENSITIVE_REPORT_PATTERN = re.compile(
    r"(?:"
    r"(?<!\d)1[3-9]\d{9}(?!\d)"
    r"|[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
    r"|https?://"
    r"|sk-[A-Za-z0-9_-]{8,}"
    r"|(?:token|secret|password|signature)\s*[:=]"
    r")",
    re.IGNORECASE,
)
_OPAQUE_REPORT_FIELDS = frozenset({
    "sha256",
    "content_sha256",
    "candidate_sha256",
    "input_sha256",
    "output_sha256",
    "report_content_sha256",
    "scenario_uid_sha256",
    "snapshot_uid_sha256",
    "snapshot_source_tree_sha256",
    "current_source_tree_sha256",
    "provider_model_fingerprint",
})


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report_sensitive_value_count(value: Any, *, field_name: str = "") -> int:
    if field_name in _OPAQUE_REPORT_FIELDS or field_name.endswith("_sha256"):
        return 0
    if isinstance(value, str):
        return int(bool(_SENSITIVE_REPORT_PATTERN.search(value)))
    if isinstance(value, list):
        return sum(
            _report_sensitive_value_count(item)
            for item in value
        )
    if isinstance(value, dict):
        return sum(
            _report_sensitive_value_count(item, field_name=str(key))
            for key, item in value.items()
        )
    return 0


def _marker_summary(value: Any) -> dict[str, Any]:
    text = str(value or "")
    markers = _MARKER.findall(text)
    return {
        "types": sorted(set(markers)),
        "count": len(markers),
        "address_count": text.count("[ADDRESS_REDACTED]"),
    }


def _stage(
    *,
    sequence: int,
    stage: str,
    field_path: str,
    value: Any = None,
    available: bool = True,
    reason_code: str,
) -> dict[str, Any]:
    text = str(value or "") if available else ""
    return {
        "sequence": sequence,
        "stage": stage,
        "schema_version": "privacy-projection-stage/v1",
        "field_path": field_path,
        "available": available,
        "sha256": _sha256_text(text) if available else "",
        "character_count": len(text) if available else 0,
        "redaction_markers": _marker_summary(text),
        "reason_code": reason_code,
    }


def _first_dict(
    values: Any,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    for value in values if isinstance(values, list) else []:
        if isinstance(value, dict) and predicate(value):
            return value
    return {}


def _read_snapshot(
    trace_db: Path,
    snapshot_uid: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    uri = f"file:{trace_db.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        row = connection.execute(
            """
            SELECT execution_debug_json, evidence_debug_json,
                   copilot_context_json, created_at
            FROM analysis_snapshots
            WHERE snapshot_id = ?
            """,
            (snapshot_uid,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("snapshot_not_found")
    return (
        json.loads(row[0]) if row[0] else {},
        json.loads(row[1]) if row[1] else {},
        json.loads(row[2]) if row[2] else {},
        str(row[3] or ""),
    )


def _read_scenario(dataset_path: Path, scenario_uid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8-sig"))
    scenario = _first_dict(
        dataset.get("scenarios"),
        lambda item: str(item.get("scenario_uid") or "") == scenario_uid,
    )
    if not scenario:
        raise ValueError("scenario_not_found")
    return dataset, scenario


def _projection_qualification(repeats: int = 5) -> dict[str, Any]:
    semantic_fixtures = [
        ("room-bedroom", "text", "卧室使用", ("卧室使用",)),
        ("room-bathroom", "text", "浴室使用", ("浴室使用",)),
        ("room-living", "text", "客厅摆放", ("客厅摆放",)),
        ("space-saving", "text", "省空间，也省力", ("省空间，也省力",)),
        ("moisture", "text", "防潮吗，怕不怕水", ("防潮吗，怕不怕水",)),
        ("indoor-outdoor", "text", "室内和室外都能用吗", ("室内和室外都能用吗",)),
        ("room-size", "text", "房间比较小，会不会占地方", ("房间比较小，会不会占地方",)),
        (
            "product-facts",
            "text",
            "主体材质为PP，宽80厘米，颜色为白色",
            ("主体材质为PP", "宽80厘米", "颜色为白色"),
        ),
        ("bathroom-question", "text", "能不能放浴室", ("能不能放浴室",)),
        ("bedroom-question", "text", "放卧室会不会占地方", ("放卧室会不会占地方",)),
        (
            "structured-business",
            "structured_json",
            {
                "product_title": "客厅卧室浴室收纳凳",
                "category": "家居收纳",
                "attribute_name": "材质",
                "content": "主体材质为PP，宽80厘米，颜色为白色",
            },
            ("客厅卧室浴室收纳凳", "家居收纳", "主体材质为PP"),
        ),
        (
            "markdown-json",
            "provider_text",
            '资料 ```json\n{"product_title":"客厅收纳凳","fact":"PP材质"}\n```',
            ("资料", "客厅收纳凳", "PP材质"),
        ),
        (
            "system-business",
            "provider_text",
            "保留卧室、浴室、客厅等商品使用语义。",
            ("卧室", "浴室", "客厅"),
        ),
    ]
    privacy_fixtures = [
        ("phone", "provider_text", "手机号13812345678", ("13812345678",)),
        ("email", "provider_text", "邮箱buyer@example.test", ("buyer@example.test",)),
        (
            "address",
            "text",
            "收货地址：北京市朝阳区幸福路12号",
            ("北京市朝阳区幸福路12号", "幸福路12号"),
        ),
        ("order", "provider_text", "订单号 A-12345", ("A-12345",)),
        (
            "tracking",
            "provider_text",
            "物流单号 SF1234567890123",
            ("SF1234567890123",),
        ),
        (
            "structured-private",
            "structured_json",
            {
                "buyer_id": "buyer-private-001",
                "account": "buyer-account-001",
                "order_id": "ORDER-PRIVATE-001",
                "tracking_no": "TRACKING-PRIVATE-001",
                "sku_code": "SKU-PRIVATE-001",
            },
            (
                "buyer-private-001",
                "buyer-account-001",
                "ORDER-PRIVATE-001",
                "TRACKING-PRIVATE-001",
                "SKU-PRIVATE-001",
            ),
        ),
        (
            "url",
            "provider_text",
            "https://example.test/private/path?token=value",
            ("https://example.test/private/path?token=value",),
        ),
        (
            "secret",
            "provider_text",
            "api_key=secret-value token=secret-token",
            ("secret-value", "secret-token"),
        ),
    ]

    def project(field_type: str, value: Any) -> Any:
        if field_type == "text":
            return sanitize_text(value)
        if field_type == "structured_json":
            return project_value_for_external_model(value)
        if field_type == "provider_text":
            return project_provider_message_text(value)
        raise ValueError("fixture_field_type_invalid")

    rows: list[dict[str, Any]] = []
    for fixture_kind, fixtures in (
        ("semantic_preservation", semantic_fixtures),
        ("privacy_redaction", privacy_fixtures),
    ):
        for fixture_uid, field_type, value, protected_values in fixtures:
            outputs = [project(field_type, value) for _ in range(repeats)]
            output_hashes = [_sha256_json(item) for item in outputs]
            input_hash = _sha256_json(value)
            stable = len(set(output_hashes)) == 1
            rendered_output = _stable_json(outputs[0])
            address_marker_count = rendered_output.count("[ADDRESS_REDACTED]")
            leakage_count = 0
            if fixture_kind == "semantic_preservation":
                semantic_values_present = all(
                    item in rendered_output for item in protected_values
                )
                passed = (
                    stable
                    and semantic_values_present
                    and address_marker_count == 0
                )
                reason_code = (
                    "semantic_preserved"
                    if passed
                    else "semantic_projection_changed"
                )
            else:
                leakage_count = sum(
                    item in rendered_output for item in protected_values
                )
                passed = (
                    stable
                    and leakage_count == 0
                    and outputs[0] != value
                )
                reason_code = (
                    "privacy_redacted"
                    if passed
                    else "privacy_projection_incomplete"
                )
            rows.append({
                "fixture_uid": fixture_uid,
                "fixture_kind": fixture_kind,
                "field_type": field_type,
                "input_sha256": input_hash,
                "output_sha256": output_hashes[0],
                "repeat_count": repeats,
                "stable": stable,
                "passed": passed,
                "reason_code": reason_code,
                "address_marker_count": address_marker_count,
                "leakage_count": leakage_count,
            })

    semantic_rows = [
        item for item in rows
        if item["fixture_kind"] == "semantic_preservation"
    ]
    privacy_rows = [
        item for item in rows
        if item["fixture_kind"] == "privacy_redaction"
    ]
    return {
        "schema_version": "privacy-projection-qualification/v1",
        "rows": rows,
        "semantic_preservation": {
            "passed": sum(item["passed"] for item in semantic_rows),
            "total": len(semantic_rows),
            "rate": (
                sum(item["passed"] for item in semantic_rows)
                / len(semantic_rows)
            ),
        },
        "privacy_redaction": {
            "passed": sum(item["passed"] for item in privacy_rows),
            "total": len(privacy_rows),
            "rate": (
                sum(item["passed"] for item in privacy_rows)
                / len(privacy_rows)
            ),
        },
        "false_address_redaction_count": sum(
            item["address_marker_count"] for item in semantic_rows
        ),
        "privacy_leakage_count": sum(
            item["leakage_count"] for item in privacy_rows
        ),
        "stability_rate": (
            sum(item["stable"] for item in rows) / len(rows)
        ),
        "model_call_count": 0,
        "retry_count": 0,
        "repair_count": 0,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    dataset, scenario = _read_scenario(args.dataset, args.scenario_uid)
    _execution, evidence, _context, snapshot_created_at = _read_snapshot(
        args.trace_db,
        args.snapshot_uid,
    )
    current_message = str(
        scenario.get("current_buyer_message")
        or (scenario.get("api_request_template") or {}).get("message")
        or ""
    )
    understanding = evidence.get("turn_understanding") or {}
    raw_goals = understanding.get("customer_goals") or []
    admitted = evidence.get("admitted_answer_context") or {}
    admitted_claims = admitted.get("requested_claims") or []
    marker_claim = _first_dict(
        admitted_claims,
        lambda item: "[ADDRESS_REDACTED]" in str(
            item.get("goal_summary") or ""
        ),
    )
    goal_ref = str(marker_claim.get("goal_ref") or "")
    raw_goal = _first_dict(
        raw_goals,
        lambda item: str(item.get("goal_ref") or "") == goal_ref,
    )
    raw_requested = _first_dict(
        understanding.get("requested_claims"),
        lambda item: str(item.get("goal_ref") or "") == goal_ref,
    )
    admitted_resolution = _first_dict(
        admitted.get("claim_resolutions"),
        lambda item: str(item.get("goal_ref") or "") == goal_ref,
    )
    minimal = evidence.get("minimal_decision_context") or {}
    minimal_resolution = _first_dict(
        minimal.get("claim_resolutions"),
        lambda item: str(item.get("goal_ref") or "") == goal_ref,
    )
    composer = evidence.get("model_first_answer_composer") or {}

    provider_payload = {
        "customer_message": current_message,
        "current_intent": str(evidence.get("final_intent") or ""),
        "canonical_fact_type_candidates": "server_owned",
        "policy_intent_candidates": "server_owned",
    }
    provider_messages = [
        {"role": "system", "content": TURN_UNDERSTANDING_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(provider_payload, ensure_ascii=False),
        },
    ]
    projected_messages = LLMClient._privacy_project_messages(
        provider_messages
    )
    raw_goal_summary = str(raw_goal.get("goal_summary") or "")
    post_owner_projection = sanitize_text(raw_goal_summary)

    stages = [
        _stage(
            sequence=1,
            stage="canonical_current_customer_message",
            field_path="scenario.current_buyer_message",
            value=current_message,
            reason_code="canonical_input",
        ),
        _stage(
            sequence=2,
            stage="provider_projection_input",
            field_path="turn_understanding.payload.customer_message",
            value=current_message,
            reason_code="before_provider_projection",
        ),
        _stage(
            sequence=3,
            stage="provider_projection_output",
            field_path="messages[1].content",
            value=projected_messages[1]["content"],
            reason_code="field_aware_provider_projection",
        ),
        _stage(
            sequence=4,
            stage="turn_understanding_provider_request",
            field_path="messages",
            value=_stable_json(projected_messages),
            reason_code="current_source_probe",
        ),
        _stage(
            sequence=5,
            stage="provider_raw_response",
            field_path="response.choices[0].message.content",
            available=False,
            reason_code="snapshot_contract_not_persisted",
        ),
        _stage(
            sequence=6,
            stage="schema_parsed_source_span",
            field_path="turn_understanding.customer_goals[].source_text",
            value=raw_goal_summary,
            reason_code="persisted_normalized_goal",
        ),
        _stage(
            sequence=7,
            stage="turn_understanding_goal_summary",
            field_path="turn_understanding.customer_goals[].goal_summary",
            value=raw_goal_summary,
            reason_code="persisted_before_admission",
        ),
        _stage(
            sequence=8,
            stage="turn_understanding_requested_claim",
            field_path="turn_understanding.requested_claims[].goal_summary",
            value=raw_requested.get("goal_summary"),
            reason_code="persisted_before_admission",
        ),
        _stage(
            sequence=9,
            stage="admitted_context_claim_resolution",
            field_path="admitted_answer_context.claim_resolutions[].goal_summary",
            value=admitted_resolution.get("goal_summary"),
            reason_code="eval_sanitizer_address_projection",
        ),
        _stage(
            sequence=10,
            stage="composer_input_goal_summary",
            field_path="minimal_decision_context.claim_resolutions[].goal_summary",
            value=minimal_resolution.get("goal_summary"),
            reason_code="propagated_from_admitted_context",
        ),
        _stage(
            sequence=11,
            stage="composer_candidate",
            field_path="model_first_answer_composer.candidate_reply",
            value=composer.get("candidate_reply"),
            reason_code="propagated_to_candidate",
        ),
    ]
    first_marker = next(
        (
            item for item in stages
            if item["redaction_markers"]["address_count"] > 0
        ),
        None,
    )
    current_owner_probe = {
        "input_sha256": _sha256_text(raw_goal_summary),
        "output_sha256": _sha256_text(post_owner_projection),
        "input_character_count": len(raw_goal_summary),
        "output_character_count": len(post_owner_projection),
        "redaction_markers": _marker_summary(post_owner_projection),
        "reason_code": (
            "semantic_preserved"
            if post_owner_projection == raw_goal_summary
            else "address_projection_changed_semantics"
        ),
    }
    source_files = {
        "privacy_projection_owner": (
            PROJECT_ROOT / "app/services/eval_sanitizer_service.py"
        ),
        "provider_request_adapter": PROJECT_ROOT / "app/llm/client.py",
        "turn_understanding": (
            PROJECT_ROOT / "app/services/semantic_fact_type_service.py"
        ),
    }
    qualification = _projection_qualification(args.repeats)
    qualification_status = (
        "qualified"
        if (
            qualification["semantic_preservation"]["rate"] == 1
            and qualification["privacy_redaction"]["rate"] == 1
            and qualification["stability_rate"] == 1
            and current_owner_probe["reason_code"] == "semantic_preserved"
        )
        else "not_qualified"
    )
    report = {
        "schema_version": "p0.2a-privacy-projection-attribution/v1",
        "priority_id": "P0.2a",
        "architecture_drift_gate": {
            "existing_owner_only": True,
            "new_graph_node_count": 0,
            "new_model_call_count": 0,
            "new_reply_owner_count": 0,
        },
        "dataset": {
            "dataset_id": str(dataset.get("dataset_id") or ""),
            "dataset_version": str(dataset.get("dataset_version") or ""),
            "content_sha256": str(
                (dataset.get("manifest") or {}).get("content_sha256")
                or dataset.get("content_sha256")
                or ""
            ),
            "scenario_uid_sha256": _sha256_text(args.scenario_uid),
        },
        "snapshot": {
            "snapshot_uid_sha256": _sha256_text(args.snapshot_uid),
            "created_at": snapshot_created_at,
            "candidate_sha256": _sha256_text(
                composer.get("candidate_reply")
            ),
        },
        "runtime_identity": {
            "snapshot_source_tree_sha256": args.snapshot_source_tree_sha256,
            "current_source_tree_sha256": _source_tree_sha256(),
            "source_files": {
                key: _file_sha256(path)
                for key, path in source_files.items()
            },
            "provider_model_fingerprint": args.provider_model_fingerprint,
            "canary_boot_identity_status": "snapshot_contract_not_persisted",
            "classification": "current_regression",
        },
        "stages": stages,
        "first_redaction_marker": {
            "sequence": first_marker["sequence"] if first_marker else None,
            "stage": first_marker["stage"] if first_marker else "",
            "field_path": first_marker["field_path"] if first_marker else "",
            "owner": (
                "app.services.eval_sanitizer_service.sanitize_obj"
                if first_marker
                else ""
            ),
        },
        "owner_probe_after_fix": current_owner_probe,
        "qualification_status": qualification_status,
        "qualification": qualification,
        "invariants": {
            "formal_knowledge_accessed": False,
            "formal_knowledge_dml_count": 0,
            "formal_reply_changed": False,
            "can_send_changed": False,
            "model_call_count": 0,
            "retry_count": 0,
            "repair_count": 0,
        },
        "contains_raw_customer_text": False,
        "contains_full_prompt": False,
        "contains_provider_response": False,
        "contains_product_or_order_identity": False,
    }
    report["report_content_sha256"] = _sha256_json(report)
    rendered = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if _report_sensitive_value_count(report):
        raise ValueError("diagnostic_report_contains_sensitive_content")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--trace-db", type=Path, required=True)
    parser.add_argument("--scenario-uid", required=True)
    parser.add_argument("--snapshot-uid", required=True)
    parser.add_argument("--snapshot-source-tree-sha256", required=True)
    parser.add_argument("--provider-model-fingerprint", required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["qualification_status"],
        "first_marker_stage": report["first_redaction_marker"]["stage"],
        "report_content_sha256": report["report_content_sha256"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
