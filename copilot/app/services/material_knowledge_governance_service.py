"""Read-only governance audit for material knowledge and answer behaviour.

The audit deliberately separates material composition from strong safety or
compliance claims.  It produces review bundles and pseudonymous product rows;
it never edits the knowledge database or changes Agent delivery decisions.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.admitted_answer_context_service import is_placeholder_evidence_text
from app.services.eval_sanitizer_service import sanitize_text
from app.services.product_structured_evidence_service import (
    STRONG_MATERIAL_CLAIM_TERMS,
    structured_field_source_kind,
)


MATERIAL_AUDIT_SCHEMA_VERSION = "material-knowledge-governance-v1"
REVIEWED_STATUSES = {"published", "approved", "reviewed", "verified"}

MATERIAL_QUERY_POLICIES = (
    {
        "query_family": "material_composition",
        "customer_goal": "询问商品或部件是什么材质",
        "required_evidence": "reviewed_scoped_material_composition",
        "composition_may_answer": True,
        "strong_claim_requires_direct_evidence": False,
        "human_service_behaviour": "先直接回答已确认的材质和对应部位，不追加无依据的安全结论。",
    },
    {
        "query_family": "material_safety",
        "customer_goal": "询问材质是否安全、是否有害",
        "required_evidence": "reviewed_scoped_material_safety_or_test_evidence",
        "composition_may_answer": False,
        "composition_may_support_partial_answer": True,
        "strong_claim_requires_direct_evidence": True,
        "human_service_behaviour": "已确认材质可以先说明；安全结论单独核验，不能由 PP、ABS 等名称推导。",
    },
    {
        "query_family": "bite_or_toxicity",
        "customer_goal": "宝宝啃咬、误入口或担心中毒",
        "required_evidence": "reviewed_scoped_non_toxic_or_food_contact_evidence_and_safety_policy",
        "composition_may_answer": False,
        "composition_may_support_partial_answer": True,
        "strong_claim_requires_direct_evidence": True,
        "human_service_behaviour": "先处理即时风险，再说明已知材质；无专项依据时不得承诺没事、无毒或食品级。",
    },
    {
        "query_family": "odor",
        "customer_goal": "询问气味来源、散味或是否正常",
        "required_evidence": "reviewed_scoped_odor_fact_or_care_instruction",
        "composition_may_answer": False,
        "strong_claim_requires_direct_evidence": True,
        "human_service_behaviour": "区分材质构成与气味事实；没有气味资料时不从材料名称猜测。",
    },
    {
        "query_family": "cleaning_or_moisture",
        "customer_goal": "询问水洗、清洁、防水、防潮或发霉",
        "required_evidence": "reviewed_scoped_cleaning_or_moisture_instruction",
        "composition_may_answer": False,
        "composition_may_support_partial_answer": True,
        "strong_claim_requires_direct_evidence": True,
        "human_service_behaviour": "材质可先说明，清洁和防潮按独立说明回答；不能用塑料、木材等常识替代商品说明。",
    },
    {
        "query_family": "certification_or_food_grade",
        "customer_goal": "询问检测报告、认证、食品级或环保等级",
        "required_evidence": "reviewed_scoped_certificate_or_compliance_evidence",
        "composition_may_answer": False,
        "composition_may_support_partial_answer": True,
        "strong_claim_requires_direct_evidence": True,
        "human_service_behaviour": "只引用当前商品的已审核报告或认证；材质名称和宣传文字都不能替代证明。",
    },
)


class MaterialKnowledgeAuditError(ValueError):
    """Raised when the audit cannot preserve its read-only/privacy contract."""


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.stat().st_size == 0:
        raise MaterialKnowledgeAuditError("source_database_unavailable")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        connection.close()
        raise MaterialKnowledgeAuditError("source_database_not_query_only")
    return connection


def _table_state(connection: sqlite3.Connection, table: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not row:
        return {"table": table, "exists": False, "row_count": 0, "schema_sha256": ""}
    return {
        "table": table,
        "exists": True,
        "row_count": int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]),
        "schema_sha256": hashlib.sha256(str(row[0] or "").encode("utf-8")).hexdigest(),
    }


def _pseudonym(secret: str, namespace: str, value: Any) -> str:
    text = sanitize_text(value)
    digest = hmac.new(secret.encode("utf-8"), f"{namespace}:{text}".encode("utf-8"), hashlib.sha256).digest()
    token = base64.b32encode(digest).decode("ascii").rstrip("=")[:20]
    return f"{namespace}_{token}"


def classify_material_value(value: Any) -> str:
    text = sanitize_text(value).strip()
    if not text:
        return "missing_material"
    if is_placeholder_evidence_text(text):
        return "placeholder_material"
    if any(term in text for term in STRONG_MATERIAL_CLAIM_TERMS):
        return "composition_with_strong_claim"
    return "composition_ready"


def _material_source(specs: dict[str, Any]) -> str:
    return structured_field_source_kind({"specs": specs}, "material")


def _review_action(classification: str) -> str:
    return {
        "missing_material": "collect_verified_material_source",
        "placeholder_material": "replace_placeholder_with_verified_composition",
        "composition_with_untrusted_provenance": "verify_value_source_before_direct_answer",
        "composition_with_strong_claim": "split_composition_from_strong_claim_and_review_both",
        "composition_ready": "confirm_scope_and_keep_as_composition_only",
    }[classification]


def _product_material_classification(value: Any, source_kind: str) -> str:
    classification = classify_material_value(value)
    if classification == "composition_ready" and sanitize_text(source_kind).lower() in {
        "conservative_placeholder",
        "placeholder",
        "unverified",
    }:
        return "composition_with_untrusted_provenance"
    return classification


def _entry_scope_present(row: sqlite3.Row) -> bool:
    if sanitize_text(row["product_id"]) or sanitize_text(row["sku_id"]):
        return True
    for field in ("product_scope_json", "sku_scope_json"):
        try:
            values = json.loads(row[field] or "[]")
        except Exception:
            values = []
        if isinstance(values, list) and any(sanitize_text(item) for item in values):
            return True
    return False


def _material_entry_summary(
    connection: sqlite3.Connection,
    product_classifications: dict[str, str],
    *,
    pseudonymization_key: str,
) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT rowid AS entry_rowid, source_type, status, fact_review_status, auto_reply_allowed, "
        "human_review_required, product_id, sku_id, product_scope_json, "
        "sku_scope_json, content FROM knowledge_entries "
        "WHERE lower(coalesce(fact_type,'')) IN ('material','material_composition')"
    ).fetchall()
    statuses: Counter[str] = Counter()
    placeholder_count = 0
    unscoped_count = 0
    direct_count = 0
    direct_revalidation_count = 0
    direct_identity_outside_reviewed_products_count = 0
    direct_entry_review_candidates: list[dict[str, Any]] = []
    for row in rows:
        key = ":".join((
            str(row["source_type"] or "").strip() or "unknown",
            str(row["status"] or "").strip() or "unknown",
            str(row["fact_review_status"] or "").strip() or "unknown",
        ))
        statuses[key] += 1
        if is_placeholder_evidence_text(row["content"]):
            placeholder_count += 1
        if not _entry_scope_present(row):
            unscoped_count += 1
        is_direct = (
            sanitize_text(row["status"]).lower() in REVIEWED_STATUSES
            and sanitize_text(row["fact_review_status"]).lower() in REVIEWED_STATUSES
            and bool(row["auto_reply_allowed"])
            and not bool(row["human_review_required"])
            and not is_placeholder_evidence_text(row["content"])
            and _entry_scope_present(row)
        )
        if is_direct:
            direct_count += 1
            product_id = sanitize_text(row["product_id"])
            classification = product_classifications.get(product_id)
            if classification and classification != "composition_ready":
                direct_revalidation_count += 1
                direct_entry_review_candidates.append({
                    "entry_uid": _pseudonym(pseudonymization_key, "material-entry", row["entry_rowid"]),
                    "classification": classification,
                    "source_type": sanitize_text(row["source_type"]) or "unknown",
                    "provenance_kind": "knowledge_entry",
                    "fact_type": "material_composition",
                    "review_status": sanitize_text(row["fact_review_status"]) or sanitize_text(row["status"]),
                    "direct_answer_state": "direct_allowed",
                    "strong_claim_mixed": classification == "composition_with_strong_claim",
                    "identity_scope_quality": "scoped",
                })
            elif not classification:
                direct_identity_outside_reviewed_products_count += 1
    return {
        "material_entry_count": len(rows),
        "direct_scoped_reviewed_entry_count": direct_count,
        "placeholder_entry_count": placeholder_count,
        "unscoped_entry_count": unscoped_count,
        "direct_entry_revalidation_count": direct_revalidation_count,
        "direct_entry_identity_outside_reviewed_products_count": direct_identity_outside_reviewed_products_count,
        "status_distribution": dict(sorted(statuses.items())),
        "direct_entry_review_candidates": direct_entry_review_candidates,
    }


def build_material_governance_report(
    source_database: str | Path,
    *,
    pseudonymization_key: str,
) -> dict[str, Any]:
    """Audit formal material knowledge without exposing product identifiers."""
    if not sanitize_text(pseudonymization_key):
        raise MaterialKnowledgeAuditError("pseudonymization_key_required")
    path = Path(source_database).expanduser().resolve()
    connection = _connect_read_only(path)
    tables = ("kb_product", "knowledge_entries", "knowledge_chunks", "kb_qa")
    before = [_table_state(connection, table) for table in tables]
    if not next((item for item in before if item["table"] == "kb_product" and item["exists"]), None):
        connection.close()
        raise MaterialKnowledgeAuditError("kb_product_table_missing")
    try:
        all_products = connection.execute(
            "SELECT i_id, category_l1, category_l2, category_l3, specs_json, status "
            "FROM kb_product "
            "ORDER BY i_id"
        ).fetchall()
        reviewed_products = [
            product for product in all_products
            if sanitize_text(product["status"]).lower() in REVIEWED_STATUSES
        ]
        rows: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        material_values: Counter[str] = Counter()
        product_classifications: dict[str, str] = {}
        for product in all_products:
            try:
                specs = json.loads(product["specs_json"] or "{}")
            except Exception:
                specs = {}
            if not isinstance(specs, dict):
                specs = {}
            value = sanitize_text(specs.get("material")).strip()
            source_kind = _material_source(specs)
            classification = _product_material_classification(value, source_kind)
            product_classifications[sanitize_text(product["i_id"])] = classification
            if sanitize_text(product["status"]).lower() not in REVIEWED_STATUSES:
                continue
            counts[classification] += 1
            if value and classification != "placeholder_material":
                material_values[value] += 1
            rows.append({
                "product_uid": _pseudonym(pseudonymization_key, "product", product["i_id"]),
                "category_path": [
                    sanitize_text(product[field])
                    for field in ("category_l1", "category_l2", "category_l3")
                    if sanitize_text(product[field])
                ],
                "classification": classification,
                "review_action": _review_action(classification),
                "material_value": "" if classification == "placeholder_material" else value,
                "material_source_kind": source_kind,
                "formal_status": sanitize_text(product["status"]),
                "may_support_material_composition": classification == "composition_ready",
                "may_support_strong_safety_claim": False,
            })

        bundles = []
        for classification in (
            "composition_ready",
            "composition_with_untrusted_provenance",
            "composition_with_strong_claim",
            "placeholder_material",
            "missing_material",
        ):
            matching = [item for item in rows if item["classification"] == classification]
            bundles.append({
                "classification": classification,
                "count": len(matching),
                "review_action": _review_action(classification),
                "one_time_business_decision": {
                    "composition_ready": "材质构成可按商品身份直接回答，但不能顺带承诺安全、无毒或食品级。",
                    "composition_with_untrusted_provenance": "字段虽然有值，但来源仍标为保守占位；先核验来源，不能仅凭商品发布状态直接回答。",
                    "composition_with_strong_claim": "将材质构成与环保、食品级等强声明拆开；强声明须单独核验证据。",
                    "placeholder_material": "占位说明不是商品事实，需从资料、实物标识或供应链来源补值。",
                    "missing_material": "缺失值进入资料补齐队列，不生成通用材质猜测。",
                }[classification],
                "example_product_uids": [item["product_uid"] for item in matching[:10]],
            })

        after = [_table_state(connection, table) for table in tables]
        entry_summary = _material_entry_summary(
            connection,
            product_classifications,
            pseudonymization_key=pseudonymization_key,
        )
        with path.open("rb") as handle:
            database_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
        report = {
            "schema_version": MATERIAL_AUDIT_SCHEMA_VERSION,
            "source": {
                "kind": "explicit_query_only_sqlite",
                "database_sha256": database_sha256,
                "tables_before": before,
                "tables_after": after,
                "query_only": True,
                "source_database_mutated": before != after,
            },
            "safety_contract": {
                "writes_formal_knowledge": False,
                "creates_review_records": False,
                "changes_agent_reply": False,
                "can_change_can_send": False,
                "material_name_proves_safety": False,
            },
            "summary": {
                "reviewed_product_count": len(reviewed_products),
                **dict(sorted(counts.items())),
                **entry_summary,
            },
            "review_bundles": bundles,
            "query_policy_profiles": list(MATERIAL_QUERY_POLICIES),
            "human_reply_contract": {
                "supported_first": "先回答已经有合格证据的材质构成或部位。",
                "claim_separation": "材质、安全、气味、清洁、防潮、入口风险和认证分别判断，不整句打包转人工。",
                "targeted_gap": "只对缺证据的子问题说明还缺什么，并提出一个必要的定向核验动作。",
                "no_system_jargon": "客服文案不出现 evidence、gate、fact_type、系统暂不支持等内部词。",
                "no_unsupported_promise": "没有实际报告或媒体 block 时，不承诺发送检测报告、图片或视频。",
            },
            "material_value_distribution": [
                {"value": value, "product_count": count}
                for value, count in material_values.most_common()
            ],
            "product_review_candidates": rows,
        }
        if report["source"]["source_database_mutated"]:
            raise MaterialKnowledgeAuditError("source_database_mutation_detected")
        return report
    finally:
        connection.close()
