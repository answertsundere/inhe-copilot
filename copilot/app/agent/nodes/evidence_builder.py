"""
evidence_builder 节点 - 收集所有来源的证据并分层
输出分层证据 + 兼容字段

fact_review_status 设计:
- knowledge_chunks.metadata_json 中的 fact_review_status: pending/verified/rejected/needs_update
- entry_status == "draft" 的知识条目，其 product_facts/faq 中包含高风险字段时，
  标记为 unverified_fact，在 evidence_debug 中体现。
- 高风险字段: 材质/承重/尺寸/适用年龄/洗涤/填充/防水/机洗/实木/食品级/无毒/重量

Knowledge Evidence Quality Gate (Phase 2.5):
- 新增 metadata: fact_source, fact_confidence, evidence_allowed_for_direct_answer
- unverified 高风险商品事实 → evidence_allowed_for_direct_answer=False
- real_cases/feedback_records → 不作为强事实依据
"""

import os
import time

from app.agent.nodes.evidence_filter_node import SOURCE_TYPE_CONFIDENCE
from app.services.evidence_quality_gate import (
    HIGH_RISK_FACT_FIELDS as GATE_RISK_FIELDS,
    VERIFIED_STATUSES as GATE_VERIFIED,
    WEAK_SOURCE_TYPES as GATE_WEAK_SOURCES,
)
from app.services.evidence_fact_gate_service import evaluate_evidence_item, sanitize_risky_convenience_claim
from app.services.product_structured_evidence_service import (
    build_product_spec_evidence_candidates,
    material_direct_answer_block_reason,
    structured_field_source_kind,
)
from app.services.fact_type_service import infer_evidence_fact_type, is_strict_fact_type
from app.services.product_context_pack_service import (
    match_authoritative_requested_fact_type,
)
from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    build_minimal_decision_context,
    canonical_selected_evidence,
)
from app.services.claim_resolution_service import expand_claim_dependencies
from app.agent.tools.registry import build_tool_requirement_status
from app.repositories.file_policy_repository import FilePolicyRepository
from app.services.canonical_conversation_turn_service import (
    canonical_conversation_reference_status,
    normalize_trusted_answer_eligibility_owner_context,
)

# 高风险商品事实字段 — 包含这些字段的知识条目需要 fact review
HIGH_RISK_FACT_FIELDS = (
    "材质", "承重", "尺寸", "适用年龄", "洗涤", "填充", "防水", "机洗",
    "实木", "食品级", "无毒", "重量", "承重", "材质说明", "填充物",
    "洗涤方式", "是否食品级", "是否3C", "是否无毒无味", "是否实木",
    "是否绝对安全", "是否可机洗",
)

PRODUCT_PROFILE_FACT_TYPES = {
    "",
    "material",
    "certification_report",
    "load_capacity",
    "stability",
    "dimensions",
    "age_range",
    "cleaning_care",
    "odor",
    "installation",
    "detachable",
    "variant_compare",
    "stock_shipping",
    "pinch_safety",
    "safety_small_parts",
}

CONTEXT_CATEGORY_COMPATIBILITY = (
    (("绘本", "书本", "书籍", "图书"), ("书架", "绘本架", "书柜", "收纳架", "收纳柜", "置物架", "储物", "架", "柜")),
    (("水龙头", "洗手", "洗脸", "洗漱"), ("水龙头", "延长器", "洗手", "洗漱")),
)


def _compact_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            text = _compact_value(v)
            if text:
                parts.append(f"{k}: {text}")
        return "；".join(parts)
    return str(value).strip()


# Retrieval metadata may carry formal attribution.  Keep the allowlist narrow
# so opaque metadata never becomes answerable evidence.
_FORMAL_EVIDENCE_PROTOCOL_FIELDS = (
    "evidence_uid",
    "evidence_id",
    "origin_evidence_key",
    "chunk_id",
    "entry_id",
    "fact_type",
    "evidence_fact_type",
    "fact_review_status",
    "attribute_key",
    "canonical_attribute_key",
    "subject_scope",
    "product_scope",
    "sku_scope",
    "i_id",
    "sku_code",
    "source_table",
    "source_id",
    "protocol_source_type",
)


def _formal_evidence_protocol(item: dict) -> dict:
    metadata = item.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        field: item.get(field) if item.get(field) is not None else metadata.get(field)
        for field in _FORMAL_EVIDENCE_PROTOCOL_FIELDS
        if item.get(field) is not None or field in metadata
    }


def _has_odor_signal(text: str) -> bool:
    return any(term in str(text or "") for term in (
        "\u6c14\u5473",
        "\u5473\u9053",
        "\u6709\u5473",
        "\u65e0\u5473",
        "\u65e0\u5f02\u5473",
        "\u65e0\u6bd2\u65e0\u5473",
        "\u5f02\u5473",
        "\u523a\u9f3b",
        "\u6563\u5473",
        "\u901a\u98ce",
    ))


def _context_product_category_mismatch(message: str, product_name: str) -> str:
    msg = message or ""
    name = product_name or ""
    if not msg or not name:
        return ""
    for cues, compatible_terms in CONTEXT_CATEGORY_COMPATIBILITY:
        if any(cue in msg for cue in cues) and not any(term in name for term in compatible_terms):
            return next(cue for cue in cues if cue in msg)
    return ""


def _identity_values(state: dict) -> dict:
    identity = state.get("order_product_identity") or {}
    slots = state.get("slots") or {}
    sku = (
        slots.get("sku_code")
        or identity.get("sku_id")
        or identity.get("internal_sku_code")
        or state.get("sku_code")
        or ""
    )
    i_id = (
        identity.get("i_id")
        or identity.get("internal_product_code")
        or state.get("i_id")
        or ""
    )
    product_name = (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or identity.get("internal_product_name")
        or state.get("product_name")
        or ""
    )
    return {"sku": str(sku or "").strip(), "i_id": str(i_id or "").strip(), "product_name": str(product_name or "").strip()}


def _find_kb_product(state: dict):
    values = _identity_values(state)
    sku = values["sku"]
    i_id = values["i_id"]
    product_name = values["product_name"]
    if not (sku or i_id or product_name):
        return None

    try:
        from app.db import SessionLocal
        from app.models.kb_tables import KBProduct
    except Exception:
        return None

    db = SessionLocal()
    try:
        try:
            if i_id:
                product = db.query(KBProduct).filter(KBProduct.i_id == i_id).first()
                if product:
                    return product.to_dict(detail=True)

            products = db.query(KBProduct).all()
            for product in products:
                if sku and (sku == product.i_id or sku.startswith(product.i_id) or product.i_id.startswith(sku)):
                    return product.to_dict(detail=True)
                if sku and sku in str(product.get_sku_list()):
                    return product.to_dict(detail=True)

            if product_name:
                for product in products:
                    name = product.product_name or ""
                    if name and (name in product_name or product_name in name):
                        return product.to_dict(detail=True)
        except Exception:
            return None
    finally:
        db.close()
    return None


def _find_product_card(state: dict) -> dict | None:
    values = _identity_values(state)
    sku = values["sku"]
    i_id = values["i_id"]
    product_name = values["product_name"]
    if not (sku or i_id or product_name):
        return None
    try:
        from app.main import _init_repos, get_product_knowledge_repo
        _init_repos()
        repo = get_product_knowledge_repo()
    except Exception:
        return None

    card = None
    if sku:
        card = repo.get_by_sku_id(sku)
    if not card and i_id:
        card = repo.get_by_i_id(i_id)
    if not card and sku:
        # Many platform SKU codes start with the internal product code, e.g. YH06K53B05S13 -> YH06K53.
        for n in (7, 8, 6):
            if len(sku) > n:
                card = repo.get_by_i_id(sku[:n])
                if card:
                    break
    if not card and product_name:
        results = repo.search(product_name, limit=1)
        if results:
            card = results[0]
    if not card:
        return None
    summary = repo.get_summary(card)
    summary["source_card_name"] = card.get("product_name", "")
    return summary


def _profile_fact_text(profile: dict, query_fact_type: str, msg: str, source: str = "") -> tuple[str, list[str]]:
    specs = profile.get("specs") or {}
    missing = []
    parts = []

    def add(label: str, *keys: str) -> bool:
        for key in keys:
            value = profile.get(key)
            if value in (None, "", [], {}):
                value = specs.get(key)
            text = _compact_value(value)
            if text:
                parts.append(f"{label}: {text}")
                return True
        missing.append(label)
        return False

    if query_fact_type == "installation":
        add("安装方式", "install_method", "安装方式", "installation", "组装方式")
        add("配件清单", "accessories", "配件清单", "parts", "配件")
    elif query_fact_type == "detachable":
        if add("拆卸/拆装", "detachable", "可拆", "可拆卸", "拆卸", "拆装"):
            add("尺寸", "size", "尺寸")
    elif query_fact_type == "odor":
        before = len(parts)
        add("气味说明", "odor_note", "odor", "气味", "味道", "异味", "散味")
        has_odor_fact = len(parts) > before
        material = ""
        for key in ("material", "材质", "材料", "材质说明"):
            material = _compact_value(profile.get(key) if profile.get(key) not in (None, "", [], {}) else specs.get(key))
            if material:
                break
        if material and (has_odor_fact or _has_odor_signal(material)):
            parts.append(f"材质: {material}")
    elif query_fact_type == "cleaning_care":
        add("清洁保养", "cleaning_care", "cleaning", "maintenance", "清洗", "清洁", "保养")
    elif query_fact_type == "moisture_resistance":
        add("防潮/存放", "moisture", "防潮", "是否防潮", "storage", "保养")
    elif query_fact_type in {
        "material_safety", "bite_or_toxicity", "certification_report",
        "food_grade", "non_toxic_claim",
    }:
        # High-risk claims need their own direct field. Composition is appended
        # separately as a declared supporting claim and cannot change this type.
        missing.append(query_fact_type)
    elif query_fact_type == "load_capacity":
        if source == "product_cards":
            # product card / JST 主数据里的 weight 多数是商品自重，不能冒充承重。
            add("承重/容量", "load_capacity", "承重/容量", "承重")
        else:
            # KBProduct 等来源：weight 是商品自重，不能冒充承重，只认 load_capacity
            add("承重/容量", "load_capacity", "承重/容量", "承重")
    elif query_fact_type == "dimensions":
        add("尺寸", "size", "尺寸")
    elif query_fact_type == "age_range":
        add("适用年龄", "age_range", "适用年龄")
    elif query_fact_type in ("variant_compare",):
        add("款式差异", "variant_compare", "款式差异", "difference", "差异")
    else:
        material_query = query_fact_type in ("material", "safety", "moisture") or any(
        word in (msg or "") for word in ("材质", "材料", "安全", "受潮", "防潮", "有毒", "味道")
        )
        if material_query:
            add("材质", "material", "材质", "材料", "材质说明")
            add("防潮/存放", "moisture", "防潮", "是否防潮", "storage", "保养", "物流属性")
        else:
            add("材质", "material", "材质", "材料", "材质说明")
            add("尺寸", "size", "尺寸")
            # `weight` is a product/package mass field.  It must never be
            # relabelled as load capacity when understanding is unavailable.
            add("商品重量", "weight", "商品重量", "重量")
            add("承重/容量", "load_capacity", "承重/容量", "承重")
            add("适用年龄", "age_range", "适用年龄")
            add("配件清单", "accessories", "配件清单")
            add("安装方式", "install_method", "安装方式")

    parts = [p for p in parts if not p.endswith(": -")]
    if not parts:
        return "", missing
    return "；".join(parts), missing


def _append_product_profile_evidence(state: dict, product_facts: list, verified_facts: list, unknowns: list, sources: list) -> None:
    values = _identity_values(state)
    if not (values["sku"] or values["i_id"] or values["product_name"]):
        return

    query_fact_type = state.get("query_fact_type", "")
    if query_fact_type not in PRODUCT_PROFILE_FACT_TYPES:
        unknowns.append({
            "fact": f"当前问题类型为 {query_fact_type}，商品资料库仅作为商品身份背景，不用于直接回答",
            "source": values["sku"] or values["i_id"] or values["product_name"],
            "source_type": "product_profile_lookup",
            "confidence": "medium",
            "scope": "product",
            "reference_only": True,
        })
        return

    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    mismatch_cue = _context_product_category_mismatch(msg, values["product_name"])
    if mismatch_cue:
        unknowns.append({
            "fact": f"客户问题提到「{mismatch_cue}」，但当前商品「{values['product_name']}」品类不一致，商品资料库仅作为背景，不能直接回答参数",
            "source": values["sku"] or values["i_id"] or values["product_name"],
            "source_type": "product_profile_lookup",
            "confidence": "medium",
            "scope": "product",
            "reference_only": True,
            "product_category_mismatch": True,
        })
        return
    found_sources = []

    kb_product = _find_kb_product(state)
    if kb_product:
        fact_text, missing = _profile_fact_text(kb_product, query_fact_type, msg)
        protocol_profile = dict(kb_product)
        protocol_profile.setdefault("product_id", kb_product.get("id"))
        protocols = build_product_spec_evidence_candidates(
            protocol_profile,
            requested_fact_type=query_fact_type,
        )
        protocol = protocols[0] if protocols else {}
        found_sources.append("kb_product")
        material_reason = material_direct_answer_block_reason(kb_product) if query_fact_type == "material" else ""
        if fact_text and not material_reason:
            fact = {
                "fact": fact_text,
                "source": kb_product.get("i_id", "") or values["sku"] or values["product_name"],
                "source_type": "product_facts",
                "confidence": "high" if kb_product.get("status") == "published" else "medium",
                "scope": "product",
                "entry_status": kb_product.get("status", "unknown"),
                "fact_review_status": "published" if kb_product.get("status") == "published" else "draft_unverified",
                "evidence_fact_type": query_fact_type,
                "fact_type": query_fact_type,
                # A broad fact type is not an attribute slot. Composite size
                # fields remain unslotted until a structured width/height/etc.
                # key is available.
                "attribute_key": "material" if query_fact_type == "material" else "",
                "product_profile_source": "kb_product",
                "material_provenance": structured_field_source_kind(kb_product, "material") if query_fact_type == "material" else "",
                "evidence_allowed_for_direct_answer": kb_product.get("status") == "published",
                "direct_answer_allowed": kb_product.get("status") == "published",
                "i_id": kb_product.get("i_id", ""),
                "evidence_id": protocol.get("evidence_id", ""),
                "source_table": protocol.get("source_table", "kb_product"),
                "source_id": protocol.get("source_id", str(kb_product.get("id") or kb_product.get("product_id") or "")),
                "source_field_keys": protocol.get("source_field_keys", []),
            }
            product_facts.append(fact)
            verified_facts.append(fact)
            sources.append("product_facts")
        elif material_reason:
            unknowns.append({
                "fact": "material field requires verified provenance before direct use",
                "source": kb_product.get("i_id", "") or values["sku"] or values["product_name"],
                "source_type": "product_profile_lookup",
                "confidence": "high",
                "scope": "product",
                "product_profile_source": "kb_product",
                "material_admission_reason": material_reason,
                "reference_only": True,
            })
        elif missing:
            unknowns.append({
                "fact": f"已按当前商品查询商品资料库，但缺少字段: {'、'.join(missing)}",
                "source": kb_product.get("i_id", "") or values["sku"] or values["product_name"],
                "source_type": "product_profile_lookup",
                "confidence": "high",
                "scope": "product",
                "product_profile_source": "kb_product",
            })

    card = _find_product_card(state)
    if card:
        found_sources.append("product_cards")
        fact_text, missing = _profile_fact_text(card, query_fact_type, msg, source="product_cards")
        material_reason = material_direct_answer_block_reason(card) if query_fact_type == "material" else ""
        if fact_text and not material_reason and not any(f.get("product_profile_source") == "kb_product" for f in product_facts):
            fact = {
                "fact": fact_text,
                "source": card.get("i_id", "") or values["sku"] or values["product_name"],
                "source_type": "product_facts",
                "confidence": "medium",
                "scope": "product",
                "entry_status": "published",
                "fact_review_status": "published",
                "evidence_fact_type": query_fact_type,
                "fact_type": query_fact_type,
                "attribute_key": "material" if query_fact_type == "material" else query_fact_type,
                "product_profile_source": "product_cards",
                "material_provenance": structured_field_source_kind(card, "material") if query_fact_type == "material" else "",
                "evidence_allowed_for_direct_answer": True,
                "direct_answer_allowed": True,
                "i_id": card.get("i_id", ""),
            }
            product_facts.append(fact)
            verified_facts.append(fact)
            sources.append("product_facts")
        elif material_reason and not kb_product:
            unknowns.append({
                "fact": "material field requires verified provenance before direct use",
                "source": card.get("i_id", "") or values["sku"] or values["product_name"],
                "source_type": "product_profile_lookup",
                "confidence": "medium",
                "scope": "product",
                "product_profile_source": "product_cards",
                "material_admission_reason": material_reason,
                "reference_only": True,
            })
        elif missing and not kb_product:
            unknowns.append({
                "fact": f"已按当前商品查询商品卡片，但缺少字段: {'、'.join(missing)}",
                "source": card.get("i_id", "") or values["sku"] or values["product_name"],
                "source_type": "product_profile_lookup",
                "confidence": "medium",
                "scope": "product",
                "product_profile_source": "product_cards",
            })

    if not found_sources:
        unknowns.append({
            "fact": "已按当前商品名称/SKU查询商品资料库，但没有找到对应商品主资料",
            "source": values["sku"] or values["i_id"] or values["product_name"],
            "source_type": "product_profile_lookup",
            "confidence": "low",
            "scope": "product",
        })


def _detect_high_risk_fields(text: str) -> list:
    """检测文本中包含的高风险商品事实字段"""
    found = []
    for field in HIGH_RISK_FACT_FIELDS:
        if field in text:
            found.append(field)
    return found


def _enrich_evidence_item(base: dict, text: str, entry_status: str,
                           fact_review_status: str, source_type: str) -> dict:
    """
    Phase 2.5: 为证据项添加 Knowledge Evidence Quality Gate 字段。
    - fact_source: 从 chunk metadata 推断
    - fact_confidence: 使用已有的 confidence
    - evidence_allowed_for_direct_answer: 根据审核状态判定
    """
    risk_fields = _detect_high_risk_fields(text)
    is_weak = source_type in GATE_WEAK_SOURCES
    is_unverified = (
        entry_status == "draft"
        or (entry_status != "published" and fact_review_status in ("pending", "needs_update", "rejected"))
        or (not fact_review_status and entry_status != "published")
    )

    if risk_fields:
        base["high_risk_fields"] = risk_fields
        base["high_risk_fact_fields"] = risk_fields

    if is_unverified and risk_fields:
        base["unverified_fact"] = True
        base["evidence_allowed_for_direct_answer"] = False
    elif is_weak:
        base["evidence_allowed_for_direct_answer"] = False
    else:
        base["evidence_allowed_for_direct_answer"] = True

    return base


def _formal_evidence_convergence_enabled() -> bool:
    return str(os.getenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


def _formal_product_identity(state: dict) -> dict:
    slots = state.get("slots") if isinstance(state.get("slots"), dict) else {}
    identity = state.get("order_product_identity") if isinstance(state.get("order_product_identity"), dict) else {}
    return {
        "sku_code": str(slots.get("sku_code") or identity.get("sku_code") or identity.get("sku_id") or state.get("sku_code") or "").strip(),
        "i_id": str(identity.get("i_id") or identity.get("internal_product_code") or state.get("i_id") or "").strip(),
        "product_name": str(state.get("matched_product_name") or identity.get("matched_product_name") or state.get("product_name") or "").strip(),
    }


def _formal_understanding(state: dict) -> dict:
    understanding = state.get("turn_understanding") if isinstance(state.get("turn_understanding"), dict) else {}
    result = dict(understanding)
    status = str(
        result.get("goal_understanding_status") or ""
    ).strip().lower()
    if status in {"invalid", "degraded"}:
        result["requested_claims"] = []
        diagnostics = result.get("goal_understanding_diagnostics")
        result["goal_understanding_diagnostics"] = list(dict.fromkeys(
            str(reason).strip()
            for reason in (
                diagnostics if isinstance(diagnostics, list) else []
            )
            if str(reason or "").strip()
        ))
        return result
    claims = result.get("requested_claims") if isinstance(result.get("requested_claims"), list) else []
    if not claims:
        fact_types = [state.get("query_fact_type"), *(state.get("secondary_fact_types") or [])]
        result["requested_claims"] = [
            {
                "goal_kind": "compatibility_claim",
                "claim_type": str(fact_type).strip(),
                "question": state.get(
                    "normalized_message",
                    state.get("customer_message", ""),
                ),
                "eligibility_source": "query_fact_type_fallback",
                "customer_goal_eligible": False,
            }
            for fact_type in fact_types
            if str(fact_type or "").strip()
        ]
        if result["requested_claims"]:
            current_status = str(
                result.get("goal_understanding_status") or ""
            ).strip().lower()
            if current_status not in {"invalid", "degraded"}:
                result["goal_understanding_status"] = "degraded"
            diagnostics = result.get("goal_understanding_diagnostics")
            diagnostics = list(diagnostics) if isinstance(diagnostics, list) else []
            diagnostics.append("query_fact_type_compatibility_fallback")
            result["goal_understanding_diagnostics"] = list(dict.fromkeys(
                str(reason).strip()
                for reason in diagnostics
                if str(reason or "").strip()
            ))
    result["requested_claims"] = expand_claim_dependencies(
        result.get("requested_claims") if isinstance(result.get("requested_claims"), list) else []
    )
    return result


def _append_formal_supporting_profile_evidence(
    state: dict,
    product_facts: list[dict],
    verified_facts: list[dict],
    unknowns: list[dict],
    sources: list[str],
) -> None:
    """Reuse structured-product admission for declared supporting material claims.

    This is enabled only with formal evidence convergence.  It does not derive
    a high-risk conclusion from material; it makes the already reviewed
    composition field available as a separately resolved claim.
    """
    claims = _formal_understanding(state).get("requested_claims") or []
    if not any(str(item.get("claim_type") or "") == "material_composition" for item in claims if isinstance(item, dict)):
        return
    if str(state.get("query_fact_type") or "") in {"material", "material_composition"}:
        return
    supporting_state = dict(state)
    supporting_state["query_fact_type"] = "material"
    # The support lookup is for the structured composition field only.  Do not
    # let wording for the parent safety/care claim select extra profile fields.
    supporting_state["normalized_message"] = ""
    supporting_state["customer_message"] = ""
    _append_product_profile_evidence(
        supporting_state,
        product_facts,
        verified_facts,
        unknowns,
        sources,
    )


def _formal_evidence_convergence(
    state: dict,
    *,
    product_facts: list[dict],
    policy_facts: list[dict],
    faq_evidence: list[dict],
    order_facts: list[dict] | None = None,
    logistics_facts: list[dict] | None = None,
) -> dict:
    """Converge already-gated evidence through the shared admission service."""
    if not _formal_evidence_convergence_enabled():
        return {}
    candidates = [
        *(state.get("knowledge_evidence") or []),
        *(state.get("filtered_evidence") or []),
        *(order_facts or []),
        *(logistics_facts or []),
        *product_facts,
        *policy_facts,
        *faq_evidence,
    ]
    response = {
        "product_context_pack": state.get("product_context_pack") or {},
        "selected_evidence": state.get("selected_evidence") or [],
        "formal_evidence_candidates": candidates,
        "tool_results": state.get("tool_results") or {},
    }
    identity = _formal_product_identity(state)
    copilot_context = (
        state.get("copilot_context")
        if isinstance(state.get("copilot_context"), dict)
        else {}
    )
    owner_context = normalize_trusted_answer_eligibility_owner_context(
        copilot_context.get("_answer_eligibility_owner_context")
    )
    trusted_domain_policy_context = owner_context.get(
        "domain_policy_context"
    )
    trusted_domain_policy_context = (
        trusted_domain_policy_context
        if isinstance(trusted_domain_policy_context, dict)
        else {}
    )
    domain_policy_pack = FilePolicyRepository().resolve_domain_policy_pack(
        trusted_domain_policy_context
    )
    admitted = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity=identity,
        understanding=_formal_understanding(state),
        current_customer_message=str(
            state.get("normalized_message", state.get("customer_message", ""))
            or ""
        ),
        answer_eligibility_inputs={
            "domain_policy_pack": domain_policy_pack,
            "trusted_domain_policy_context": (
                trusted_domain_policy_context
            ),
            "conversation_reference_status": canonical_conversation_reference_status(
                owner_context
            ),
            "tool_requirement_status": build_tool_requirement_status(
                state.get("required_tools"),
                state.get("tool_results"),
            ),
        },
    )
    selected = canonical_selected_evidence(admitted)
    minimal_context = build_minimal_decision_context(
        admitted,
        customer_message=str(state.get("normalized_message", state.get("customer_message", "")) or ""),
        conversation_summary=state.get("conversation_context_summary") if isinstance(state.get("conversation_context_summary"), dict) else {},
        conversation_turns=(
            copilot_context.get("conversation_history", [])
            if isinstance(copilot_context.get("conversation_history"), list)
            else []
        ),
        channel_capabilities=copilot_context.get("channel_capabilities", {}),
        allowed_read_only_tools=[
            str(item.get("tool_name") or "")
            for item in state.get("tool_plan", [])
            if isinstance(item, dict) and str(item.get("tool_name") or "")
        ],
    )
    from app.services.agent_decision_proposal_service import build_supervisor_partial_answer_preview

    preview = build_supervisor_partial_answer_preview(
        minimal_context,
        provider_status="not_qualified",
    )
    return {
        "selected_evidence": selected,
        "admitted_answer_context": admitted,
        "minimal_decision_context": minimal_context,
        "supervisor_candidate_preview": preview,
        "formal_evidence_convergence": admitted.get("evidence_convergence") or {},
    }


def evidence_builder(state: dict) -> dict:
    """构建证据链（分层版）"""
    t0 = time.time()

    # 分层证据
    order_facts = []
    logistics_facts = []
    product_facts = []
    policy_facts = []
    sop_evidence = []
    template_evidence = []
    faq_evidence = []

    # 兼容字段
    verified_facts = []
    estimated_facts = []
    unknowns = []
    conflicts = []
    sources = []

    # 1. 订单事实（聚水潭 - 区分普通订单 vs 销售出库）
    live_order = state.get("live_order")
    if live_order:
        used_endpoint = state.get("used_endpoint", "")
        is_outbound = "out/simple" in used_endpoint or "outbound" in used_endpoint
        source_label = "jst_sales_out" if is_outbound else "jst_order"
        fact = {
            "fact": f"聚水潭查到订单 {live_order.get('o_id', '')}, 状态 {live_order.get('status', '')}",
            # Sales-out fields are internal operational provenance.  The
            # Composer may use only this customer-safe meaning; an outbound
            # row proves shipment, not carrier pickup or a live transit node.
            "customer_text": (
                "订单已发出。"
                if is_outbound
                else ""
            ),
            "source": live_order.get("o_id", ""),
            "source_type": source_label,
            "confidence": "high",
            "scope": "order",
            "endpoint": used_endpoint,
            "evidence_role": "operational_fact_direct",
            "fact_type": "stock_shipping",
            "claim_types_supported": ["stock_shipping"],
            "fact_review_status": "verified",
            "gate_status": "allowed",
            "direct_answer_allowed": True,
            "operational_scope": "order",
            "tool_execution_status": "completed",
            "read_only": True,
        }
        order_facts.append(fact)
        verified_facts.append(fact)
        sources.append(source_label)

    # 2. 订单事实（本地）
    local_order = state.get("order")
    if local_order and not live_order:
        fact = {
            "fact": f"本地查到订单 {local_order.get('o_id', '')}, 状态 {local_order.get('status', '')}",
            "source": local_order.get("o_id", ""),
            "source_type": "local_order",
            "confidence": "medium",
            "scope": "order",
        }
        order_facts.append(fact)
        verified_facts.append(fact)
        sources.append("local_order")

    # 3. 物流事实（聚水潭 - 区分订单来源 vs 销售出库来源）
    logistics_trace = state.get("logistics_trace")
    if logistics_trace and logistics_trace.get("status") not in ("no_trace", "api_failed", ""):
        carrier = logistics_trace.get("carrier", "") or logistics_trace.get("logistics_company", "")
        tracking_no = logistics_trace.get("tracking_no", "")
        send_date = logistics_trace.get("send_date", "")
        order_status = logistics_trace.get("order_status", "")
        status = logistics_trace.get("status", "")
        is_outbound = "out/simple" in state.get("used_endpoint", "")
        source_label = "jst_sales_out_logistics" if is_outbound else "jst_logistics"
        # Tracking identity remains server-side provenance. It must not enter
        # customer-answerable prose where privacy projection would expose an
        # internal redaction marker to the Composer.
        fact_parts = [
            f"聚水潭物流信息: 承运商 {carrier}"
            if carrier
            else "聚水潭物流信息"
        ]
        if send_date:
            fact_parts.append(f"发货时间 {send_date}")
        if order_status:
            fact_parts.append(f"订单状态 {order_status}")
        elif status:
            fact_parts.append(f"物流状态 {status}")
        latest = logistics_trace.get("latest", {})
        latest_time = str(latest.get("time", "")) if latest else ""
        latest_context = str(latest.get("context", "")) if latest else ""
        latest_duplicates_shipped_boundary = bool(
            send_date
            and latest_time == str(send_date)
            and latest_context in {"已发出", "包裹已发出"}
        )
        if latest and not latest_duplicates_shipped_boundary:
            fact_parts.append(f"最新 {latest.get('time', '')} {latest.get('context', '')}")
        if is_outbound:
            carrier_clause = f"，由{carrier}承运" if carrier else ""
            customer_text = (
                f"订单已发出{carrier_clause}；"
                "目前未有中转、派送或签收轨迹，暂时无法确认包裹当前位置。"
            )
        else:
            customer_text = ""
        fact = {
            "fact": ", ".join(fact_parts),
            "customer_text": customer_text,
            "source": tracking_no,
            "source_type": source_label,
            "confidence": "medium" if logistics_trace.get("low_confidence") else "high",
            "scope": "logistics",
            "evidence_boundary": "已发出" if send_date and not logistics_trace.get("sign_time") else ("已签收" if logistics_trace.get("is_delivered") else "状态未知"),
            "latest_trace_available": bool(
                not is_outbound
                and latest
                and not latest_duplicates_shipped_boundary
            ),
            "evidence_role": "operational_fact_direct",
            "fact_type": "stock_shipping",
            "claim_types_supported": ["stock_shipping"],
            "fact_review_status": "verified",
            "gate_status": "allowed",
            "direct_answer_allowed": True,
            "operational_scope": "logistics",
            "tool_execution_status": "completed",
            "read_only": True,
        }
        logistics_facts.append(fact)
        verified_facts.append(fact)
        sources.append(source_label)
    elif logistics_trace and logistics_trace.get("status") == "no_trace":
        tracking_no = logistics_trace.get("tracking_no", "")
        unknowns.append({
            "fact": f"聚水潭暂未返回完整物流信息: {tracking_no}",
            "source": tracking_no,
            "source_type": "jst_logistics",
            "confidence": "low",
            "scope": "logistics",
        })
        sources.append("jst_logistics")

    # 4. 商品事实（商品映射）
    product_name = state.get("matched_product_name", "")
    if product_name:
        fact = {
            "fact": f"匹配到商品: {product_name}",
            "source": product_name,
            "source_type": "product_mapping",
            "confidence": "medium",
            "scope": "product",
        }
        product_facts.append(fact)
        estimated_facts.append(fact)
        sources.append("product_mapping")

    _append_product_profile_evidence(state, product_facts, verified_facts, unknowns, sources)
    if _formal_evidence_convergence_enabled():
        _append_formal_supporting_profile_evidence(
            state,
            product_facts,
            verified_facts,
            unknowns,
            sources,
        )

    # 5. 物流政策（旧字段兼容）
    policy = state.get("shipping_policy", {})
    if policy:
        fact = {
            "fact": f"物流政策: 默认{policy.get('default_courier', '')}, 时效{policy.get('eta_days_min', '')}-{policy.get('eta_days_max', '')}天",
            "source": "shipping_policy",
            "source_type": "shipping_policy",
            "confidence": "medium",
            "scope": "policy",
        }
        policy_facts.append(fact)
        estimated_facts.append(fact)
        sources.append("shipping_policy")

    # 6. 冲突检测
    order_status = state.get("order_status", "")
    if order_status in ("unpaid", "canceled", "refunded") and logistics_trace:
        conflicts.append({
            "fact": f"订单状态为{order_status}但存在物流轨迹",
            "source": "order_vs_logistics",
            "source_type": "conflict",
            "confidence": "high",
            "scope": "conflict",
        })

    # 7. 无订单时的未知
    slots = state.get("slots", {})
    if not live_order and not local_order and not logistics_trace:
        if slots.get("order_id"):
            unknowns.append({
                "fact": f"提供订单号 {slots['order_id']} 但未查到订单",
                "source": slots["order_id"],
                "source_type": "unknown",
                "confidence": "low",
                "scope": "order",
            })

    # 8. 知识库 RAG 证据（分层处理 + fact_review_status）
    knowledge_evidence = state.get("knowledge_evidence", [])
    has_product_fact_from_rag = False
    unverified_fact_fields = []  # 未审核的高风险字段列表
    query_fact_type = state.get("query_fact_type", "")

    for ke in knowledge_evidence:
        st = ke.get("source_type", "")
        text = ke.get("chunk_text", "")
        confidence = ke.get("confidence", "low")
        ref_only = ke.get("reference_only", False)
        entry_status = ke.get("entry_status", "unknown")
        fact_review_status = ke.get("fact_review_status", "")
        source_sheet = ke.get("source_sheet", "")
        row_number = ke.get("row_number", 0)
        evidence_fact_type = ke.get("evidence_fact_type") or infer_evidence_fact_type(ke)
        odor_material_bridge = bool(
            query_fact_type == "odor"
            and evidence_fact_type == "material"
            and _has_odor_signal(text)
        )
        if odor_material_bridge:
            evidence_fact_type = "odor"
        matched_requested_fact_type = match_authoritative_requested_fact_type(
            state,
            evidence_fact_type,
            query_fact_type,
        )
        gate_query_fact_type = (
            evidence_fact_type
            if matched_requested_fact_type
            else query_fact_type
        )
        wrong_fact_type = bool(query_fact_type and not matched_requested_fact_type)

        # 检测高风险字段
        risk_fields = _detect_high_risk_fields(text)
        # 只有明确 draft 或明确未审核状态才算 unverified；published entry 不受空 fact_review_status 影响
        is_unverified = (
            entry_status == "draft"
            or (entry_status != "published" and fact_review_status in ("pending", "needs_update", "rejected"))
        )

        # 如果是高风险字段 + 未审核，标记为 unverified
        if risk_fields and is_unverified and st in ("product_facts", "faq"):
            for f in risk_fields:
                if f not in unverified_fact_fields:
                    unverified_fact_fields.append(f)

        base = {
            "fact": text,
            "source": "knowledge_base",
            "source_type": st,
            "confidence": confidence,
            "reference_only": ref_only,
            "entry_status": entry_status,
            "fact_review_status": fact_review_status if fact_review_status else ("draft_unverified" if is_unverified else "published"),
            "source_sheet": source_sheet,
            "row_number": row_number,
            "matched_entry_id": ke.get("entry_id"),
            "entry_id": ke.get("entry_id"),
            "chunk_id": ke.get("chunk_id"),
            "matched_title": ke.get("title", ""),
            "query_fact_type": gate_query_fact_type,
            "primary_query_fact_type": query_fact_type,
            "matched_requested_fact_type": matched_requested_fact_type,
            "evidence_fact_type": evidence_fact_type,
            "evidence_allowed_for_exact_answer": ke.get("evidence_allowed_for_exact_answer", True),
            "material_provenance": ke.get("material_provenance", ""),
        }
        base.update(_formal_evidence_protocol(ke))
        base = _enrich_evidence_item(base, text, entry_status, fact_review_status, st)
        if ke.get("evidence_allowed_for_direct_answer") is False and not odor_material_bridge:
            base["evidence_allowed_for_direct_answer"] = False
        if st == "faq" and ke.get("evidence_allowed_for_exact_answer") is False and not odor_material_bridge:
            base["evidence_allowed_for_direct_answer"] = False
        if odor_material_bridge:
            base["evidence_allowed_for_direct_answer"] = True
            base["evidence_allowed_for_exact_answer"] = True
            base["mismatch_reason"] = ""
        if wrong_fact_type:
            base["evidence_allowed_for_direct_answer"] = False
            base["evidence_allowed_for_exact_answer"] = False
            base["mismatch_reason"] = base.get("mismatch_reason") or "wrong_fact_type"
            if is_strict_fact_type(query_fact_type):
                base["reference_only"] = True

        if st == "product_facts":
            has_product_fact_from_rag = True
            pf = {**base, "scope": "product"}
            product_facts.append(pf)
            verified_facts.append(pf)
            sources.append("product_facts")
        elif st == "shipping_policy":
            pf = {**base, "scope": "policy"}
            policy_facts.append(pf)
            estimated_facts.append(pf)
            sources.append("shipping_policy")
        elif st == "aftersales_policy":
            pf = {**base, "scope": "policy"}
            policy_facts.append(pf)
            estimated_facts.append(pf)
            sources.append("aftersales_policy")
        elif st == "installation_guide":
            pf = {**base, "scope": "installation"}
            product_facts.append(pf)  # 安装指南也归入 product 辅助
            estimated_facts.append(pf)
            sources.append("installation_guide")
        elif st == "faq":
            pf = {**base, "scope": "knowledge", "confidence": "low"}
            faq_evidence.append(pf)
            estimated_facts.append(pf)
            sources.append("faq")
        elif st == "response_templates":
            pf = {**base, "scope": "template", "confidence": "low"}
            template_evidence.append(pf)
            estimated_facts.append(pf)
            sources.append("response_templates")
        elif st == "high_risk_sop":
            pf = {**base, "scope": "sop", "reference_only": True}
            sop_evidence.append(pf)
            estimated_facts.append(pf)
            sources.append("high_risk_sop")
        elif st == "forbidden_rules":
            conflicts.append({
                "fact": text,
                "source": "knowledge_base",
                "source_type": "forbidden_rules",
                "confidence": "high",
                "scope": "guard",
            })
            sources.append("forbidden_rules")

    # 9. RAG 未知检测
    intent = state.get("intent", "general")
    if intent in ("product_question", "product_consult") and not has_product_fact_from_rag and not faq_evidence and not product_name:
        unknowns.append({
            "fact": "咨询商品参数但未匹配到 product_facts",
            "source": "rag",
            "source_type": "unknown",
            "confidence": "low",
            "scope": "product",
        })

    # 10. 从 tool_results 补充证据（工具注册层产出的结果）
    tool_results = state.get("tool_results", {})
    for tool_name, tool_output in tool_results.items():
        if not isinstance(tool_output, dict) or tool_output.get("error"):
            continue

        if tool_name == "jst_lookup_outbound_tool" and tool_output.get("found"):
            # outbound 工具结果 → 订单事实 + 物流事实
            if not any(f.get("source_type") == "jst_sales_out" for f in order_facts):
                fact = {
                    "fact": f"销售出库查到订单 {tool_output.get('o_id', '')}, 状态 {tool_output.get('status', '')}",
                    "source": tool_output.get("o_id", ""),
                    "source_type": "jst_sales_out",
                    "confidence": "high",
                    "scope": "order",
                    "endpoint": tool_output.get("endpoint", ""),
                }
                order_facts.append(fact)
                verified_facts.append(fact)
                sources.append("jst_sales_out")

        elif tool_name == "sop_lookup_tool" and tool_output.get("sops"):
            for sop in tool_output["sops"]:
                sop_evidence.append({
                    "fact": f"SOP: {sop.get('scenario', '')}",
                    "source": "sop_lookup_tool",
                    "source_type": "high_risk_sop",
                    "confidence": "high",
                    "scope": "sop",
                    "reference_only": True,
                })
                sources.append("high_risk_sop")

        elif tool_name == "template_select_tool" and tool_output.get("templates"):
            for tmpl in tool_output["templates"]:
                template_evidence.append({
                    "fact": tmpl.get("template", ""),
                    "source": "template_select_tool",
                    "source_type": "response_templates",
                    "confidence": "medium",
                    "scope": "template",
                })
                sources.append("response_templates")

        elif tool_name == "rag_search_tool" and tool_output.get("chunks"):
            # RAG 工具结果 → 按 source_type 分层，等价于 evidence_filter_node 逻辑
            existing_ke_chunk_ids = {
                ke.get("chunk_id") for ke in state.get("knowledge_evidence", [])
                if isinstance(ke, dict) and ke.get("chunk_id")
            }
            existing_ke_entry_ids = {
                ke.get("entry_id") for ke in state.get("knowledge_evidence", [])
                if isinstance(ke, dict) and ke.get("entry_id") and not ke.get("chunk_id")
            }
            for chunk in tool_output["chunks"]:
                st = chunk.get("source_type", "")
                text = chunk.get("chunk_text", "")
                if not text:
                    continue
                # 与 knowledge_evidence 去重：同一条 chunk 不重复计入
                _chunk_id = chunk.get("chunk_id", "")
                _entry_id = chunk.get("entry_id", "")
                if _chunk_id and _chunk_id in existing_ke_chunk_ids:
                    continue
                if not _chunk_id and _entry_id and _entry_id in existing_ke_entry_ids:
                    continue
                entry_status = chunk.get("entry_status", "unknown")
                score = chunk.get("score", 0)
                risk_fields = _detect_high_risk_fields(text)
                is_unverified = (
                    entry_status == "draft"
                    or (entry_status != "published" and chunk.get("fact_review_status", "") in ("pending", "needs_update", "rejected"))
                )

                # Phase 2.5: 追踪未审核高风险字段
                if risk_fields and is_unverified and st in ("product_facts", "faq"):
                    for f in risk_fields:
                        if f not in unverified_fact_fields:
                            unverified_fact_fields.append(f)

                confidence = SOURCE_TYPE_CONFIDENCE.get(st, "low") if st in SOURCE_TYPE_CONFIDENCE else "low"
                meta = chunk.get("metadata", {})
                evidence_fact_type = chunk.get("evidence_fact_type") or chunk.get("fact_type") or infer_evidence_fact_type(chunk)
                odor_material_bridge = bool(
                    query_fact_type == "odor"
                    and evidence_fact_type == "material"
                    and _has_odor_signal(text)
                )
                if odor_material_bridge:
                    evidence_fact_type = "odor"
                matched_requested_fact_type = match_authoritative_requested_fact_type(
                    state,
                    evidence_fact_type,
                    query_fact_type,
                )
                gate_query_fact_type = (
                    evidence_fact_type
                    if matched_requested_fact_type
                    else query_fact_type
                )
                _sanitized = False
                if query_fact_type == "installation" and evidence_fact_type == "installation":
                    _new_text, _did = sanitize_risky_convenience_claim(text)
                    if _did:
                        text = _new_text
                        _sanitized = True
                wrong_fact_type = bool(query_fact_type and not matched_requested_fact_type)
                ref_only = not meta.get("auto_reply_allowed", True)
                if chunk.get("evidence_allowed_for_direct_answer") is False and not odor_material_bridge:
                    ref_only = True
                if wrong_fact_type and is_strict_fact_type(query_fact_type):
                    ref_only = True

                base = {
                    "fact": text,
                    "source": "knowledge_base",
                    "source_type": st,
                    "confidence": confidence,
                    "reference_only": ref_only,
                    "entry_status": entry_status,
                    "fact_review_status": chunk.get("fact_review_status", ""),
                    "source_sheet": chunk.get("source_sheet", ""),
                    "row_number": chunk.get("row_number", 0),
                    "score": score,
                    "text_score": chunk.get("text_score", 0),
                    "vector_score": chunk.get("vector_score", 0),
                    "scope_score": chunk.get("scope_score", 0),
                    "source_confidence": chunk.get("source_confidence", confidence),
                    "rerank_score": chunk.get("rerank_score", score),
                    "mismatch_reason": chunk.get("mismatch_reason", ""),
                    "scope_match": chunk.get("scope_score", 0) >= 0,
                    "query_fact_type": gate_query_fact_type,
                    "primary_query_fact_type": query_fact_type,
                    "matched_requested_fact_type": matched_requested_fact_type,
                    "evidence_fact_type": evidence_fact_type,
                    "material_provenance": chunk.get("material_provenance", ""),
                    "evidence_allowed_for_exact_answer": chunk.get(
                        "evidence_allowed_for_exact_answer",
                        not chunk.get("mismatch_reason", ""),
                    ),
                    "entry_id": chunk.get("entry_id"),
                    "matched_entry_id": chunk.get("entry_id"),
                    "matched_title": chunk.get("title", ""),
                    "title": chunk.get("title", ""),
                    "chunk_id": chunk.get("chunk_id", ""),
                }
                base.update(_formal_evidence_protocol(chunk))
                base = _enrich_evidence_item(
                    base, text, entry_status,
                    chunk.get("fact_review_status", ""), st,
                )
                if chunk.get("evidence_allowed_for_direct_answer") is False and not odor_material_bridge:
                    base["evidence_allowed_for_direct_answer"] = False
                if st == "faq" and chunk.get("evidence_allowed_for_exact_answer") is False and not odor_material_bridge:
                    base["evidence_allowed_for_direct_answer"] = False
                if wrong_fact_type:
                    base["evidence_allowed_for_direct_answer"] = False
                    base["evidence_allowed_for_exact_answer"] = False
                    base["mismatch_reason"] = base.get("mismatch_reason") or "wrong_fact_type"
                if odor_material_bridge:
                    base["reference_only"] = False
                    base["evidence_allowed_for_direct_answer"] = True
                    base["evidence_allowed_for_exact_answer"] = True
                    base["mismatch_reason"] = ""

                # 统一证据门控：gate_status / gate_reasons / direct_answer_allowed
                base["query_fact_type"] = gate_query_fact_type
                base["evidence_fact_type"] = evidence_fact_type
                _gate = evaluate_evidence_item(base, state)
                base["gate_status"] = _gate["gate_status"]
                base["gate_reasons"] = _gate["gate_reasons"]
                base["direct_answer_allowed"] = _gate["direct_answer_allowed"]
                base["evidence_allowed_for_exact_answer"] = _gate["evidence_allowed_for_exact_answer"]
                if not _gate["direct_answer_allowed"]:
                    base["evidence_allowed_for_direct_answer"] = False
                    if _gate["reference_only"]:
                        base["reference_only"] = True
                if _sanitized:
                    base["sanitization_applied"] = True

                if st == "product_facts":
                    has_product_fact_from_rag = True
                    pf = {**base, "scope": "product"}
                    product_facts.append(pf)
                    verified_facts.append(pf)
                    sources.append("product_facts")
                elif st == "shipping_policy":
                    pf = {**base, "scope": "policy"}
                    policy_facts.append(pf)
                    estimated_facts.append(pf)
                    sources.append("shipping_policy")
                elif st == "aftersales_policy":
                    pf = {**base, "scope": "policy"}
                    policy_facts.append(pf)
                    estimated_facts.append(pf)
                    sources.append("aftersales_policy")
                elif st == "installation_guide":
                    pf = {**base, "scope": "installation"}
                    product_facts.append(pf)
                    estimated_facts.append(pf)
                    sources.append("installation_guide")
                elif st == "faq":
                    pf = {**base, "scope": "knowledge"}
                    faq_evidence.append(pf)
                    estimated_facts.append(pf)
                    sources.append("faq")
                elif st == "high_risk_sop":
                    pf = {**base, "scope": "sop", "reference_only": True}
                    sop_evidence.append(pf)
                    estimated_facts.append(pf)
                    sources.append("high_risk_sop")
                elif st == "forbidden_rules":
                    conflicts.append({
                        "fact": text,
                        "source": "knowledge_base",
                        "source_type": "forbidden_rules",
                        "confidence": "high",
                        "scope": "guard",
                    })
                    sources.append("forbidden_rules")

        elif tool_name == "product_resolver_tool":
            if tool_output.get("matched_product_name") and not product_name:
                pname = tool_output["matched_product_name"]
                product_facts.append({
                    "fact": f"匹配到商品: {pname}",
                    "source": pname,
                    "source_type": "product_mapping",
                    "confidence": "medium",
                    "scope": "product",
                })
                sources.append("product_mapping")

    evidence = {
        # 分层证据
        "order_facts": order_facts,
        "logistics_facts": logistics_facts,
        "product_facts": product_facts,
        "policy_facts": policy_facts,
        "sop_evidence": sop_evidence,
        "template_evidence": template_evidence,
        "faq_evidence": faq_evidence,
        # 兼容字段
        "verified_facts": verified_facts,
        "estimated_facts": estimated_facts,
        "unknowns": unknowns,
        "conflicts": conflicts,
        "evidence_sources": list(set(sources)),
        "unverified_fact_fields": unverified_fact_fields,
    }

    # 兼容：将 RAG 检索到的 FAQ 和产品事实同步到 knowledge 列表，供 generate_reply 使用
    knowledge = []
    for pf in product_facts:
        if pf.get("source_type") == "product_facts" and pf.get("fact"):
            knowledge.append({"title": "产品信息", "content": pf["fact"]})
    for faq in faq_evidence:
        if faq.get("fact"):
            knowledge.append({"title": "常见问题", "content": faq["fact"]})
    for tmpl in template_evidence:
        if tmpl.get("fact"):
            knowledge.append({"title": "话术模板", "content": tmpl["fact"]})

    duration_ms = int((time.time() - t0) * 1000)
    trace = {
        "node": "evidence_builder",
        "status": "success",
        "duration_ms": duration_ms,
        "cache_hit": False,
        "summary": f"证据分层: 订单{len(order_facts)} 物流{len(logistics_facts)} 商品{len(product_facts)} 政策{len(policy_facts)} SOP{len(sop_evidence)} 模板{len(template_evidence)} FAQ{len(faq_evidence)} 未知{len(unknowns)} 冲突{len(conflicts)}",
    }

    convergence = _formal_evidence_convergence(
        state,
        order_facts=order_facts,
        logistics_facts=logistics_facts,
        product_facts=product_facts,
        policy_facts=policy_facts,
        faq_evidence=faq_evidence,
    )
    if convergence:
        trace["formal_selected_evidence_count"] = len(convergence["selected_evidence"])
        trace["formal_evidence_convergence_enabled"] = True

    return {
        "evidence": evidence,
        "knowledge": knowledge,
        "trace_steps": state.get("trace_steps", []) + [trace],
        **convergence,
    }
