"""Build a read-only positive evaluation set for Grounded Reasoning.

The generated scenarios are explicitly synthetic contract fixtures.  They do
not create, publish, or modify product knowledge.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _direct_fact(
    *,
    fact_type: str,
    attribute_key: str,
    value: str,
    identity: dict[str, str],
) -> dict[str, Any]:
    return {
        "evidence_role": "product_fact_direct",
        "fact_type": fact_type,
        "attribute_key": attribute_key,
        "value": value,
        "direct_answer_allowed": True,
        "gate_status": "allowed",
        "review_status": "reviewed",
        **identity,
    }


def _scenario(
    *,
    scenario_uid: str,
    customer_message: str,
    query_fact_type: str,
    reasoning_tier: str,
    selected_evidence: list[dict[str, Any]],
    expected_fact_keys: list[str] | None = None,
    expected_rejection_reasons: list[str] | None = None,
    expected_draft_terms: list[str] | None = None,
    allowed_inferences: list[str] | None = None,
    forbidden_claims: list[str] | None = None,
    must_handoff: bool = False,
    notes: str = "",
    product_identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "scenario_uid": scenario_uid,
        "source": "synthetic_fixture",
        "customer_message": customer_message,
        "query_fact_type": query_fact_type,
        "product_identity": product_identity or {"i_id": "EVAL-IID-01", "sku_code": "EVAL-SKU-01"},
        "selected_evidence": selected_evidence,
        "product_context_pack": {},
        "answer_memory_guidance": {
            "reference_only": True,
            "action_hints": ["先围绕当前问题组织处理动作。"],
        },
        "reasoning_tier": reasoning_tier,
        "expected_fact_keys": expected_fact_keys or [],
        "expected_rejection_reasons": expected_rejection_reasons or [],
        "expected_draft_terms": expected_draft_terms or [],
        "allowed_inferences": allowed_inferences or [],
        "forbidden_claims": forbidden_claims or [],
        "must_handoff": must_handoff,
        "notes": notes,
    }


def build_synthetic_eval_set() -> list[dict[str, Any]]:
    """Return deterministic fixtures for admission and draft-composition checks."""
    identity = {"i_id": "EVAL-IID-01", "sku_code": "EVAL-SKU-01"}
    direct = lambda fact_type, key, value: _direct_fact(
        fact_type=fact_type,
        attribute_key=key,
        value=value,
        identity=identity,
    )
    scenarios: list[dict[str, Any]] = []

    # L0: one reviewed, direct, scoped fact should be admitted and surfaced.
    l0_cases = [
        ("material", "材质是什么？", "material", "主体材质为工程塑料", "主体材质"),
        ("dimensions", "宽度是多少？", "width", "宽度为80cm", "宽度"),
        ("dimensions", "高度是多少？", "height", "高度为120cm", "高度"),
        ("dimensions", "长度是多少？", "length", "长度为60cm", "长度"),
        ("gross_weight", "包装毛重是多少？", "gross_weight", "包装毛重为1.2kg", "包装毛重"),
        ("load_capacity", "承重是多少？", "load_capacity", "标注承重为20kg", "承重"),
        ("structure", "一共有几层？", "layer_count", "共有三层收纳空间", "三层"),
        ("installation", "安装步骤在哪里看？", "installation_manual", "说明书包含安装步骤和孔位说明", "安装步骤"),
        ("accessory_availability", "配件清单里有什么？", "accessory_list", "包装内含固定配件", "固定配件"),
        ("structure_function", "侧板可以调节吗？", "side_panel", "侧板支持位置调节", "侧板"),
        ("certification_report", "有没有检测资料？", "certificate_reference", "已审核检测资料编号为TEST-001", "检测资料"),
        ("installation", "说明书有没有孔位提示？", "hole_position", "说明书标注了孔位顺序", "孔位"),
    ]
    for index, (fact_type, message, key, value, term) in enumerate(l0_cases, start=1):
        scenarios.append(
            _scenario(
                scenario_uid=f"synthetic-l0-{index:02d}",
                customer_message=message,
                query_fact_type=fact_type,
                reasoning_tier="L0",
                selected_evidence=[direct(fact_type, key, value)],
                expected_fact_keys=[key],
                expected_draft_terms=[term],
                notes="Reviewed direct product fact.",
            )
        )

    # L1: same product and compatible attributes can be considered together.
    l1_cases = [
        ("dimensions", "放在这里尺寸合适吗？", [("width", "宽度为80cm"), ("height", "高度为120cm")], ["width", "height"]),
        ("dimensions", "深度和长度分别多少？", [("depth", "深度为35cm"), ("length", "长度为60cm")], ["depth", "length"]),
        ("installation", "安装时先看哪一步？", [("installation_manual", "说明书列出安装步骤"), ("hole_position", "说明书标注孔位顺序")], ["installation_manual", "hole_position"]),
        ("installation", "配件位置怎么确认？", [("accessory_position", "说明书标出配件位置"), ("installation_manual", "说明书包含安装步骤")], ["accessory_position", "installation_manual"]),
        ("structure", "层数和分区怎么安排？", [("layer_count", "共有三层收纳空间"), ("partition_count", "内部有两个分区")], ["layer_count", "partition_count"]),
        ("accessory_availability", "固定配件和备用件都有吗？", [("accessory_list", "包装内含固定配件"), ("spare_part", "包装内含备用连接件")], ["accessory_list", "spare_part"]),
        ("structure_function", "侧板和隔层都能调整吗？", [("side_panel", "侧板支持位置调节"), ("shelf_position", "隔层支持位置调节")], ["side_panel", "shelf_position"]),
        ("gross_weight", "运输重量怎么参考？", [("gross_weight", "包装毛重为1kg"), ("shipping_weight", "物流参考重量为1000g")], ["gross_weight", "shipping_weight"]),
    ]
    for index, (fact_type, message, facts, keys) in enumerate(l1_cases, start=1):
        scenarios.append(
            _scenario(
                scenario_uid=f"synthetic-l1-{index:02d}",
                customer_message=message,
                query_fact_type=fact_type,
                reasoning_tier="L1",
                selected_evidence=[direct(fact_type, key, value) for key, value in facts],
                expected_fact_keys=keys,
                allowed_inferences=["May combine compatible facts from the same scoped product."],
                notes="Low-risk same-product combination.",
            )
        )

    # L2: the draft may explain limits, but it must remain fact-bound.
    l2_cases = [
        ("installation", "螺丝拧紧后还松怎么办？", "installation_step", "说明书要求按孔位顺序锁紧", "孔位顺序"),
        ("structure_function", "这两个位置怎么调？", "adjustment", "侧板支持位置调节", "侧板"),
        ("placement_scene", "摆放前要注意什么？", "placement_note", "建议按页面尺寸预留摆放空间", "摆放空间"),
        ("accessory_usage", "这个配件应该装在哪？", "accessory_position", "说明书标出配件位置", "配件位置"),
        ("structure", "这个结构怎么搭配使用？", "structure_note", "共有三层收纳空间", "三层"),
    ]
    for index, (fact_type, message, key, value, term) in enumerate(l2_cases, start=1):
        scenarios.append(
            _scenario(
                scenario_uid=f"synthetic-l2-{index:02d}",
                customer_message=message,
                query_fact_type=fact_type,
                reasoning_tier="L2",
                selected_evidence=[direct(fact_type, key, value)],
                expected_fact_keys=[key],
                expected_draft_terms=[term],
                allowed_inferences=["State the verified setup condition without expanding to safety or order commitments."],
                notes="Conditioned, low-risk explanation only.",
            )
        )

    # L3: high-risk claims without direct evidence must remain review-only.
    l3_controls = [
        ("age_range", "两岁孩子能用吗？", "适合两岁", "child suitability requires review"),
        ("child_safety", "会不会夹手？", "绝对安全", "child safety requires review"),
        ("material_safety", "会不会有毒？", "无毒", "material safety requires review"),
        ("certification_report", "有检测报告吗？", "有检测报告", "certificate requires review"),
        ("load_capacity", "承重能保证吗？", "保证承重", "load capacity requires review"),
    ]
    for index, (fact_type, message, forbidden, note) in enumerate(l3_controls, start=1):
        scenarios.append(
            _scenario(
                scenario_uid=f"synthetic-l3-risk-{index:02d}",
                customer_message=message,
                query_fact_type=fact_type,
                reasoning_tier="L3",
                selected_evidence=[],
                forbidden_claims=[forbidden],
                must_handoff=True,
                notes=note,
            )
        )

    # Rejection controls verify the admission boundary without changing it.
    rejected_controls = [
        ("identity-mismatch", "gross_weight", "重量是多少？", {**direct("gross_weight", "gross_weight", "包装毛重为2kg"), "i_id": "OTHER-IID"}, "product_identity_mismatch"),
        ("identity-namespace", "gross_weight", "重量是多少？", {**{k: v for k, v in direct("gross_weight", "gross_weight", "包装毛重为2kg").items() if k != "i_id"}, "sku_code": "OTHER-SKU"}, "product_identity_namespace_missing"),
        ("pending", "material", "材质是什么？", {**direct("material", "material", "主体材质为工程塑料"), "review_status": "pending_review"}, "unreviewed_fact"),
        ("reference", "installation", "有安装说明吗？", {**direct("installation", "installation_manual", "说明书包含安装步骤"), "reference_only": True}, "reference_only"),
        ("service-action", "installation", "有安装说明吗？", {**direct("installation", "installation_manual", "请联系人工协助"), "evidence_role": "service_action"}, "ineligible_role_or_gate"),
        ("media-reference", "installation", "有安装视频吗？", {**direct("installation", "installation_video", "安装视频可参考"), "evidence_role": "media_reference"}, "ineligible_role_or_gate"),
        ("conflict", "gross_weight", "包装毛重是多少？", [direct("gross_weight", "gross_weight", "包装毛重为1kg"), direct("gross_weight", "gross_weight", "包装毛重为2kg")], "conflicting_evidence"),
    ]
    for index, (kind, fact_type, message, evidence, reason) in enumerate(rejected_controls, start=1):
        selected = evidence if isinstance(evidence, list) else [evidence]
        scenarios.append(
            _scenario(
                scenario_uid=f"synthetic-l3-reject-{index:02d}",
                customer_message=message,
                query_fact_type=fact_type,
                reasoning_tier="L3",
                selected_evidence=selected,
                expected_rejection_reasons=[reason],
                must_handoff=True,
                product_identity={"i_id": "EVAL-IID-01"} if kind == "identity-namespace" else None,
                notes=f"Admission rejection control: {kind}.",
            )
        )
    return scenarios


def inventory_formal_knowledge() -> dict[str, int | str]:
    """Read current formal knowledge availability without initializing or changing DB state."""
    try:
        from app.db import SessionLocal
        from app.models.kb_tables import KBProduct, KBQA

        db = SessionLocal()
        try:
            product_count = db.query(KBProduct).filter(KBProduct.status.in_(("reviewed", "published", "approved"))).count()
            faq_count = db.query(KBQA).filter(KBQA.status.in_(("reviewed", "published", "approved"))).count()
        finally:
            db.close()
        return {
            "mode": "read_only",
            "reviewed_or_published_product_count": product_count,
            "reviewed_or_published_faq_count": faq_count,
        }
    except Exception as exc:  # The builder must remain usable without a local DB.
        return {"mode": "unavailable", "error_type": type(exc).__name__}


def build_eval_payload() -> dict[str, Any]:
    scenarios = build_synthetic_eval_set()
    return {
        "schema_version": "grounded-reasoning-positive-eval-v1",
        "source": "synthetic_fixture",
        "real_knowledge_inventory": inventory_formal_knowledge(),
        "scenario_count": len(scenarios),
        "reasoning_tier_counts": dict(sorted(Counter(item["reasoning_tier"] for item in scenarios).items())),
        "scenarios": scenarios,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a read-only Grounded Reasoning positive eval set.")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_eval_payload()
    # ASCII JSON keeps Windows PowerShell 5's default Get-Content decoding safe.
    output.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "scenarios"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
