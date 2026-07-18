"""Run privacy-safe gold-CSR evaluation through the formal analyze endpoint."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_text
from app.services.material_gold_csr_validation_service import (
    MATERIAL_CUSTOMER_QUESTIONS,
    evaluate_material_gold_csr_dataset,
)
from app.services.product_structured_evidence_service import material_direct_answer_block_reason


_FAMILY_CLAIM_TYPES = {
    # The legacy primary material route uses `material`; dependency-expanded
    # multi-claim requests use `material_composition`.  Both are the same
    # narrow composition boundary for reporting, not a safety alias.
    "material_composition": ("material", "material_composition"),
    "material_safety": ("material_safety",),
    "bite_or_toxicity": ("bite_or_toxicity",),
    "odor": ("odor",),
    "cleaning_or_moisture": ("cleaning_care", "moisture_resistance"),
    "certification_or_food_grade": ("certification_report", "food_grade"),
}


def _pseudonym(secret: str, value: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return "product_" + base64.b32encode(digest).decode("ascii").rstrip("=")[:20]


def _load_products(database: Path, *, limit: int, offset: int = 0) -> tuple[list[dict[str, str]], str]:
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    products = []
    try:
        rows = connection.execute(
            "SELECT i_id, product_name, specs_json FROM kb_product "
            "WHERE lower(status) IN ('published','approved','reviewed','verified') ORDER BY i_id"
        ).fetchall()
        for row in rows:
            try:
                specs = json.loads(row["specs_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(specs, dict):
                continue
            material = sanitize_text(specs.get("material")).strip()
            if not material or material_direct_answer_block_reason({"specs": specs}):
                continue
            products.append({
                "i_id": sanitize_text(row["i_id"]),
                "product_name": sanitize_text(row["product_name"]),
                "material": material,
            })
            if len(products) >= offset + limit:
                break
    finally:
        connection.close()
    return products[offset:offset + limit], hashlib.sha256(database.read_bytes()).hexdigest()


def _request(api_url: str, product: dict[str, str], family: str, *, timeout: float) -> dict[str, Any]:
    payload = {
        "message": MATERIAL_CUSTOMER_QUESTIONS[family],
        "product_name": product["product_name"],
        "i_id": product["i_id"],
        "conversation_id": f"material_gold_csr_{family}",
        "copilot_context": {
            "display_product_name": product["product_name"],
            "sidecar_context": {
                "product_title": product["product_name"],
                "i_id": product["i_id"],
            },
        },
    }
    request = Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                return {"_request_error": "invalid_response"}
            contract_error = _response_contract_error(value)
            return value if not contract_error else {**value, "_request_error": contract_error}
    except HTTPError as exc:
        return {"_request_error": f"http_{exc.code}"}
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"_request_error": type(exc).__name__}


def _response_contract_error(response: dict[str, Any]) -> str:
    """Count a successful HTTP response without customer copy as a failed run."""
    if not sanitize_text(response.get("suggested_reply")).strip():
        return "response_contract_missing_suggested_reply"
    return ""


def _evidence_uids(response: dict[str, Any]) -> list[str]:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    values = response.get("selected_evidence") or debug.get("selected_evidence") or []
    return sorted({
        _safe_evidence_uid(item.get("evidence_uid") or item.get("evidence_id") or item.get("chunk_id"))
        for item in values if isinstance(item, dict)
        and sanitize_text(item.get("evidence_uid") or item.get("evidence_id") or item.get("chunk_id"))
    })


def _safe_evidence_uid(value: Any) -> str:
    """Keep reports linkable without exporting internal evidence identifiers."""
    raw = sanitize_text(value).strip()
    if not raw:
        return ""
    return "evidence_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _claim_statuses(response: dict[str, Any]) -> dict[str, str]:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    context = debug.get("admitted_answer_context") if isinstance(debug.get("admitted_answer_context"), dict) else {}
    return {
        sanitize_text(item.get("claim_type")): sanitize_text(item.get("status"))
        for item in context.get("claim_resolutions") or []
        if isinstance(item, dict) and sanitize_text(item.get("claim_type"))
    }


def _family_claim_status(response: dict[str, Any], family: str) -> tuple[str, dict[str, str]]:
    statuses = _claim_statuses(response)
    targets = _FAMILY_CLAIM_TYPES.get(family, ())
    target_statuses = {claim_type: statuses.get(claim_type, "missing") for claim_type in targets}
    if family == "material_composition" and any(status == "supported" for status in target_statuses.values()):
        return "supported", target_statuses
    if target_statuses and all(status == "supported" for status in target_statuses.values()):
        return "supported", target_statuses
    if any(status == "conflicting" for status in target_statuses.values()):
        return "conflicting", target_statuses
    return "unresolved", target_statuses


def _reply_block_summary(response: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "type": sanitize_text(block.get("type") or block.get("block_type")),
            "send_mode": sanitize_text(block.get("send_mode")),
        }
        for block in response.get("reply_blocks") or []
        if isinstance(block, dict)
    ]


def _response_diagnostics(response: dict[str, Any]) -> dict[str, Any]:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    audit = response.get("final_answer_audit") if isinstance(response.get("final_answer_audit"), dict) else {}
    semantic = response.get("final_semantic_fit") if isinstance(response.get("final_semantic_fit"), dict) else {}
    context = debug.get("admitted_answer_context") if isinstance(debug.get("admitted_answer_context"), dict) else {}
    direct_facts = context.get("direct_product_facts") if isinstance(context.get("direct_product_facts"), list) else []
    return {
        "answer_mode": sanitize_text(response.get("answer_mode") or debug.get("answer_mode")),
        "generation_mode": sanitize_text(response.get("generation_mode") or debug.get("generation_mode")),
        "query_fact_type": sanitize_text(response.get("query_fact_type") or debug.get("query_fact_type")),
        "final_answer_audit_issues": [sanitize_text(value) for value in audit.get("issues") or []],
        "semantic_fit_issues": [sanitize_text(value) for value in semantic.get("issues") or []],
        "claim_resolutions": [
            {
                "claim_type": sanitize_text(item.get("claim_type")),
                "status": sanitize_text(item.get("status")),
                "reason": sanitize_text(item.get("reason")),
                "evidence_count": len(item.get("evidence_uids") or []),
            }
            for item in context.get("claim_resolutions") or []
            if isinstance(item, dict)
        ],
        "requested_claims": [
            {
                "claim_type": sanitize_text(item.get("claim_type")),
                "supporting_only": bool(item.get("supporting_only")),
                "supporting_for_claim_type": sanitize_text(item.get("supporting_for_claim_type")),
            }
            for item in context.get("requested_claims") or []
            if isinstance(item, dict)
        ],
        "admitted_direct_evidence": [
            {
                "evidence_uid": _safe_evidence_uid(item.get("evidence_uid") or item.get("evidence_id")),
                "role": sanitize_text(item.get("evidence_role") or item.get("role") or item.get("source")),
                "fact_type": sanitize_text(item.get("fact_type")),
                "attribute_key": sanitize_text(item.get("attribute_key")),
            }
            for item in direct_facts
            if isinstance(item, dict)
        ],
    }


def _redact(text: str, product: dict[str, str], product_uid: str) -> str:
    value = sanitize_text(text)
    for raw, replacement in ((product["product_name"], "这款商品"), (product["i_id"], product_uid)):
        if raw:
            value = value.replace(raw, replacement)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-database", required=True, type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:5012/api/analyze")
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--product-limit", type=int, default=5)
    parser.add_argument("--product-offset", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    secret = os.environ.get("COPILOT_MATERIAL_AUDIT_HMAC_KEY", "")
    if not secret:
        print(json.dumps({"status": "blocked", "reason": "pseudonymization_key_required"}))
        return 2
    if args.product_offset < 0:
        parser.error("--product-offset must be non-negative")
    products, database_sha256 = _load_products(
        args.source_database,
        limit=args.product_limit,
        offset=args.product_offset,
    )
    if len(products) < args.product_limit:
        print(json.dumps({"status": "blocked", "reason": "insufficient_composition_ready_products"}))
        return 2

    rows = []
    request_errors = 0
    for product in products:
        product_uid = _pseudonym(secret, product["i_id"])
        for family, question in MATERIAL_CUSTOMER_QUESTIONS.items():
            response = _request(args.api_url, product, family, timeout=args.timeout_seconds)
            if response.get("_request_error"):
                request_errors += 1
            candidate = _redact(response.get("suggested_reply") or "", product, product_uid)
            claim_status, claim_statuses = _family_claim_status(response, family)
            diagnostics = _response_diagnostics(response)
            rows.append({
                "case_uid": f"formal-{product_uid}-{family}",
                "source_kind": "real_derived",
                "evaluation_mode": "formal_runtime",
                "product_identity": {"i_id": product_uid},
                "query_family": family,
                "customer_question": question,
                "admitted_evidence_uids": _evidence_uids(response),
                "claim_status": claim_status,
                "claim_statuses": claim_statuses,
                "admitted_evidence_roles": [
                    item["role"] for item in diagnostics["admitted_direct_evidence"] if item["role"]
                ],
                "candidate_preview": candidate,
                "can_send": response.get("can_send"),
                "requires_human_review": response.get("requires_human_review"),
                "reply_blocks": _reply_block_summary(response),
                "request_error": response.get("_request_error") or "",
                "response_diagnostics": diagnostics,
                "evaluation_reference": {"material_value": product["material"]},
            })

    evaluation = evaluate_material_gold_csr_dataset({"rows": rows})
    report = {
        "schema_version": "material-gold-csr-formal-runtime-v1",
        "source_kind": "query_only_real_derived",
        "source_database_sha256": database_sha256,
        "api_url": args.api_url,
        "product_count": len(products),
        "case_count": len(rows),
        "request_error_count": request_errors,
        "gold_csr_evaluation": evaluation,
        "rows": rows,
        "formal_contract": {
            "writes_formal_knowledge": False,
            "changes_agent_reply": False,
            "can_change_can_send": False,
        },
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "case_count": len(rows),
        "request_error_count": request_errors,
        "passed_count": evaluation["passed_count"],
        "failed_count": evaluation["failed_count"],
        "pass_rate": evaluation["pass_rate"],
    }, ensure_ascii=False))
    return 0 if request_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
