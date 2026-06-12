"""LLM-first fact type classifier for customer product/policy questions."""

from __future__ import annotations

import json
import logging
from typing import Any

from app import config
from app.llm.client import get_llm_client
from app.services.fact_type_service import FACT_TYPE_LABELS, classify_query_fact_type

logger = logging.getLogger(__name__)


ALLOWED_FACT_TYPES = set(FACT_TYPE_LABELS)


SYSTEM_PROMPT = """你是 INHE 客服 Copilot 的“问题事实类型”语义分类器。
你只判断客户当前真正想问的事实字段，不生成客服回复，不做事实回答。

请结合客户消息、系统已识别意图、侧边栏商品名/sku/订单上下文，输出 JSON。

可选 fact_type:
- material: 材质、用料、环保材料、安全材料
- certification_report: 检测报告、认证、3C、食品级、甲醛
- load_capacity: 承重、能放多重、承载能力
- stability: 稳定性、防倾倒、会不会倒、宝宝扶靠是否安全、绝对不会倒这类安全承诺
- dimensions: 尺寸、长宽高、占地
- age_range: 适用年龄、适合多大宝宝
- cleaning_care: 清洁、清洗、擦拭、保养
- odor: 气味、异味、刺鼻、散味
- installation: 安装、组装、配件、说明书
- variant_compare: 基础款/升级款/不同款式差异
- stock_shipping: 库存、今天能否发货、什么时候发
- invoice_policy: 发票、电子发票、抬头、税号
- price_protection: 价保、保价、买贵、降价
- promotion_policy: 优惠、活动、券、满减
- gift_policy: 赠品、漏发赠品
- safety_small_parts: 小零件、电池、误吞、夹手、宝宝受伤
- aftersales_policy: 退换货、补发、破损、少件、售后政策

判断原则:
1. 按语义判断，不要只按关键词匹配。
2. 多个问题时，选择最高风险或最需要证据门控的 fact_type，并在 secondary_fact_types 写其他类型。
3. “绝对、安全保证、一定不会”等承诺型表达要识别为 high risk，但 fact_type 仍按实际问题归类。
4. 如果无法判断，fact_type 为空字符串，confidence 低于 0.4。

输出 JSON schema:
{
  "query_fact_type": "",
  "confidence": 0.0,
  "risk_hint": "low|medium|high",
  "secondary_fact_types": [],
  "reason": "简短中文理由"
}
"""


def classify_query_fact_type_llm_first(state: dict[str, Any]) -> dict[str, Any]:
    """Classify query fact type using LLM first, deterministic fallback second."""
    message = state.get("normalized_message", state.get("customer_message", "")) or ""
    intent = state.get("intent", "general") or "general"

    if config.COPILOT_FACT_TYPE_LLM_ENABLED:
        llm_result = _classify_with_llm(state, message, intent)
        if llm_result:
            return llm_result

    fallback = classify_query_fact_type(message, intent)
    fallback["source"] = "rule_fallback" if config.COPILOT_FACT_TYPE_LLM_ENABLED else fallback.get("source", "rule")
    fallback["fallback_reason"] = fallback.get("fallback_reason", "llm_unavailable_or_invalid")
    return fallback


def _classify_with_llm(state: dict[str, Any], message: str, intent: str) -> dict[str, Any] | None:
    client = get_llm_client()
    if not client.api_key:
        return None

    payload = {
        "customer_message": message,
        "intent": intent,
        "risk_level": state.get("risk_level", ""),
        "product_name": state.get("product_name", ""),
        "resolved_product": state.get("resolved_product", {}),
        "product_candidates": state.get("product_candidates", [])[:5],
        "order_id_present": bool(state.get("order_id") or state.get("platform_order_id")),
        "conversation_context_summary": state.get("conversation_context_summary", {}),
    }

    try:
        response = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=260,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)
        return _sanitize_llm_result(parsed)
    except Exception as exc:
        logger.warning("LLM fact type classifier failed, using fallback: %s", exc)
        return None


def _sanitize_llm_result(data: dict[str, Any]) -> dict[str, Any] | None:
    fact_type = str(data.get("query_fact_type") or data.get("fact_type") or "").strip()
    if fact_type and fact_type not in ALLOWED_FACT_TYPES:
        fact_type = ""

    try:
        confidence = float(data.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    if not fact_type and confidence >= 0.4:
        confidence = 0.3

    risk_hint = str(data.get("risk_hint") or data.get("risk_level") or "").strip().lower()
    if risk_hint not in {"low", "medium", "high"}:
        risk_hint = ""
    if fact_type in {"stability", "safety_small_parts", "certification_report", "age_range"} and not risk_hint:
        risk_hint = "high"

    secondary = data.get("secondary_fact_types") or []
    if not isinstance(secondary, list):
        secondary = []
    secondary = [str(x) for x in secondary if str(x) in ALLOWED_FACT_TYPES and str(x) != fact_type]

    return {
        "query_fact_type": fact_type,
        "query_fact_type_label": FACT_TYPE_LABELS.get(fact_type, fact_type),
        "confidence": confidence,
        "matched_terms": [],
        "source": "llm",
        "reason": str(data.get("reason", ""))[:200],
        "risk_hint": risk_hint,
        "secondary_fact_types": secondary[:5],
    }
