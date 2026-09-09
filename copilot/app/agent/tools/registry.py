"""
ToolRegistry — 工具注册中心

全局单例，所有工具在此注册。
提供按名称查找、按意图过滤、生成 LLM tool 列表等能力。
"""

import logging
import re
from typing import Optional

from app.agent.tools.base import ToolSpec

logger = logging.getLogger(__name__)


def _looks_like_sku(value: str) -> bool:
    value = str(value or "").strip()
    return bool(re.search(r"[A-Z]{2}\d{2}K\d{2}", value, re.IGNORECASE) or re.search(r"[A-Z0-9]+B\d+S\d+", value, re.IGNORECASE))


class ToolRegistry:
    """工具注册中心（全局单例）"""

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec):
        """注册工具"""
        if tool.name in self._tools:
            logger.warning("工具 %s 已存在，将被覆盖", tool.name)
        self._tools[tool.name] = tool
        logger.debug("注册工具: %s", tool.name)

    def get(self, name: str) -> Optional[ToolSpec]:
        """按名称获取工具"""
        return self._tools.get(name)

    def get_all(self) -> dict[str, ToolSpec]:
        """获取所有已注册工具"""
        return dict(self._tools)

    def get_for_intent(self, intent: str, risk_level: str = "low") -> list[ToolSpec]:
        """获取当前 intent + risk_level 下允许的工具列表"""
        return [
            t for t in self._tools.values()
            if t.is_allowed(intent, risk_level)
        ]

    def get_tool_metas(self, names: list[str] = None) -> list[dict]:
        """获取工具元数据列表（供 LLM tool 描述用）。
        names 为 None 时返回全部。
        """
        if names is None:
            return [t.to_meta() for t in self._tools.values()]
        return [
            self._tools[n].to_meta()
            for n in names if n in self._tools
        ]

    def validate_tool_names(self, names: list[str]) -> tuple[list[str], list[str]]:
        """校验工具名列表，返回 (valid, invalid)"""
        valid = [n for n in names if n in self._tools]
        invalid = [n for n in names if n not in self._tools]
        return valid, invalid

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


# 全局单例
def build_tool_requirement_status(
    required_tools: list[str] | None,
    tool_results: dict | None,
    *,
    registry: ToolRegistry | None = None,
) -> dict:
    """Project router requirements and executor completion without name heuristics."""
    registry = registry or get_tool_registry()
    required = sorted({
        str(name).strip()
        for name in required_tools or []
        if str(name or "").strip()
    })
    results = tool_results if isinstance(tool_results, dict) else {}
    completed = [
        name
        for name in required
        if name in results and not _tool_result_failed(results.get(name))
    ]
    base = {
        "required_tool_refs": required,
        "completed_tool_refs": completed,
        "source_stage": "tool_router_and_executor",
        "reason_codes": [],
    }
    if not required:
        return {**base, "status": "not_required"}

    specs = {name: registry.get(name) for name in required}
    if any(spec is None for spec in specs.values()):
        return {
            **base,
            "status": "unknown",
            "reason_codes": ["required_tool_not_registered"],
        }
    freshness = {
        name: str(spec.freshness_class or "unknown").strip().lower()
        for name, spec in specs.items()
        if spec is not None
    }
    if any(value not in {"static", "live", "action"} for value in freshness.values()):
        return {
            **base,
            "status": "unknown",
            "reason_codes": ["tool_freshness_unknown"],
        }
    if "action" in freshness.values():
        return {
            **base,
            "status": "action_tool_required",
            "reason_codes": ["side_effect_authorization_required"],
        }

    failed = [
        name
        for name in required
        if name in results and _tool_result_failed(results.get(name))
    ]
    missing = [name for name in required if name not in results]
    live = [name for name in required if freshness[name] == "live"]
    if live:
        if failed:
            return {
                **base,
                "status": "live_tool_failed",
                "reason_codes": ["required_live_tool_failed"],
            }
        if missing:
            return {
                **base,
                "status": "live_tool_required",
                "reason_codes": ["required_live_tool_pending"],
            }
        return {**base, "status": "live_tool_completed"}

    if failed or missing:
        return {
            **base,
            "status": "unknown",
            "reason_codes": ["required_static_tool_incomplete"],
        }
    return {**base, "status": "static_knowledge_completed"}


def _tool_result_failed(value: object) -> bool:
    if not isinstance(value, dict):
        return True
    if value.get("timed_out") is True:
        return True
    if str(value.get("status") or "").strip().lower() in {
        "failed",
        "error",
        "timeout",
        "not_found",
    }:
        return True
    return bool(
        value.get("error")
        or value.get("error_code")
        or value.get("safe_fallback_reason")
    )


_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取全局工具注册中心"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_default_tools(_registry)
    return _registry


def reset_tool_registry():
    """重置注册中心（测试用）"""
    global _registry
    _registry = None


def _register_default_tools(registry: ToolRegistry):
    """注册默认工具集"""
    from app.agent.tools.schemas import (
        JST_ORDER_INPUT, JST_ORDER_OUTPUT,
        JST_OUTBOUND_INPUT, JST_OUTBOUND_OUTPUT,
        JST_TRACKING_INPUT, JST_TRACKING_OUTPUT,
        RAG_SEARCH_INPUT, RAG_SEARCH_OUTPUT,
        PRODUCT_RESOLVER_INPUT, PRODUCT_RESOLVER_OUTPUT,
        SOP_LOOKUP_INPUT, SOP_LOOKUP_OUTPUT,
        TEMPLATE_SELECT_INPUT, TEMPLATE_SELECT_OUTPUT,
    )

    # ---- 1. jst_lookup_order_tool ----
    registry.register(ToolSpec(
        name="jst_lookup_order_tool",
        freshness_class="live",
        description="按聚水潭内部订单号(o_id)或平台订单号(so_id)查询订单状态、物流信息",
        input_schema=JST_ORDER_INPUT,
        output_schema=JST_ORDER_OUTPUT,
        allowed_intents=["logistics_eta", "logistics_trace", "delivery_not_received", "aftersales"],
        timeout_ms=3000,
        read_only=True,
        can_create_fact_types=["order_facts", "logistics_facts"],
        handler=_handle_jst_lookup_order,
    ))

    # ---- 2. jst_lookup_outbound_tool ----
    registry.register(ToolSpec(
        name="jst_lookup_outbound_tool",
        freshness_class="live",
        description="按外部交易单号/平台交易号(outer_so_id)查询销售出库记录，获取发货状态、快递公司、快递单号",
        input_schema=JST_OUTBOUND_INPUT,
        output_schema=JST_OUTBOUND_OUTPUT,
        allowed_intents=["logistics_eta", "logistics_trace", "delivery_not_received"],
        timeout_ms=3000,
        read_only=True,
        can_create_fact_types=["order_facts", "logistics_facts"],
        handler=_handle_jst_lookup_outbound,
    ))

    # ---- 3. jst_lookup_tracking_tool ----
    registry.register(ToolSpec(
        name="jst_lookup_tracking_tool",
        freshness_class="live",
        description="按快递单号查询物流轨迹和关联订单（扫描最近7天物流记录）",
        input_schema=JST_TRACKING_INPUT,
        output_schema=JST_TRACKING_OUTPUT,
        allowed_intents=["logistics_eta", "logistics_trace", "delivery_not_received"],
        timeout_ms=3000,
        read_only=True,
        can_create_fact_types=["logistics_facts"],
        handler=_handle_jst_lookup_tracking,
    ))

    # ---- 4. rag_search_tool ----
    registry.register(ToolSpec(
        name="rag_search_tool",
        freshness_class="static",
        description="从知识库检索相关知识分片（FAQ、产品信息、物流政策、售后政策等）",
        input_schema=RAG_SEARCH_INPUT,
        output_schema=RAG_SEARCH_OUTPUT,
        allowed_intents=[],  # 所有意图都可以用
        timeout_ms=2000,
        read_only=True,
        can_create_fact_types=["policy_facts", "product_facts", "faq_evidence"],
        handler=_handle_rag_search,
    ))

    # ---- 5. product_resolver_tool ----
    registry.register(ToolSpec(
        name="product_resolver_tool",
        freshness_class="static",
        description="从客户消息中识别商品名称，返回匹配的商品候选",
        input_schema=PRODUCT_RESOLVER_INPUT,
        output_schema=PRODUCT_RESOLVER_OUTPUT,
        allowed_intents=["product_question", "installation", "logistics_eta", "logistics_trace"],
        timeout_ms=1000,
        read_only=True,
        can_create_fact_types=["product_facts"],
        handler=_handle_product_resolver,
    ))

    # ---- 6. sop_lookup_tool ----
    registry.register(ToolSpec(
        name="sop_lookup_tool",
        freshness_class="static",
        description="检索高风险SOP和禁止承诺规则，用于投诉、赔偿等高风险场景",
        input_schema=SOP_LOOKUP_INPUT,
        output_schema=SOP_LOOKUP_OUTPUT,
        allowed_intents=["complaint", "aftersales", "delivery_not_received"],
        timeout_ms=1000,
        read_only=True,
        can_create_fact_types=["sop_evidence"],
        requires_human_review=True,
        handler=_handle_sop_lookup,
    ))

    # ---- 7. template_select_tool ----
    registry.register(ToolSpec(
        name="template_select_tool",
        freshness_class="static",
        description="根据意图和场景选择合适的话术模板",
        input_schema=TEMPLATE_SELECT_INPUT,
        output_schema=TEMPLATE_SELECT_OUTPUT,
        allowed_intents=[],  # 所有意图都可以用
        timeout_ms=500,
        read_only=True,
        can_create_fact_types=["template_evidence"],
        handler=_handle_template_select,
    ))


# ========== 工具 handler 实现 ==========
# 每个 handler: (inputs: dict, state: dict) -> dict
# 内部调用现有函数，不重写底层逻辑。


def _trusted_jst_shop_scope(inputs: dict, state: dict) -> dict:
    """Return channel-provided shop routing metadata without deriving identity."""
    context = state.get("copilot_context", {}) or {}
    scope = {}
    for key in ("shop_id", "shop_name"):
        value = str(context.get(key) or inputs.get(key) or "").strip()
        if value:
            scope[key] = value
    return scope

def _handle_jst_lookup_order(inputs: dict, state: dict) -> dict:
    """调用 lookup_order_by_order_id 或 lookup_order_by_platform_order_id"""
    from app.integrations.jst.live_query import (
        lookup_order_by_order_id, lookup_order_by_platform_order_id, lookup_order_by_identifier,
    )

    identifier = inputs.get("identifier", "")
    identifier_type = inputs.get("identifier_type", "internal_order_id")

    result = lookup_order_by_identifier(
        identifier,
        identifier_type,
        **_trusted_jst_shop_scope(inputs, state),
    )
    if result.get("found"):
        data = result["data"]
        return {
            "found": True,
            "o_id": data.get("o_id", ""),
            "so_id": data.get("so_id", ""),
            "outer_so_id": data.get("outer_so_id", ""),
            "status": data.get("status", ""),
            "logistics_company": data.get("logistics_company", ""),
            "l_id": data.get("l_id", ""),
            "send_date": data.get("send_date", ""),
            "sign_time": data.get("sign_time", ""),
            "items": data.get("items", []),
            "endpoint": result.get("endpoint", ""),
            "duration_ms": result.get("duration_ms", 0),
        }
    return {
        "found": False,
        "endpoint": result.get("endpoint", ""),
        "duration_ms": result.get("duration_ms", 0),
        "query_type": result.get("query_type", ""),
        "attempted_paths": result.get("attempted_paths", []),
        "error_code": result.get("error_code"),
        "safe_fallback_reason": result.get("safe_fallback_reason", ""),
    }


def _handle_jst_lookup_outbound(inputs: dict, state: dict) -> dict:
    """调用 lookup_outbound_by_so_id"""
    from app.integrations.jst.live_query import lookup_order_by_identifier

    outer_so_id = inputs.get("outer_so_id", "")
    result = lookup_order_by_identifier(
        outer_so_id,
        "platform_trade_id",
        **_trusted_jst_shop_scope(inputs, state),
    )
    if result.get("found"):
        data = result["data"]
        return {
            "found": True,
            "o_id": data.get("o_id", ""),
            "status": data.get("status", ""),
            "logistics_company": data.get("logistics_company", ""),
            "l_id": data.get("l_id", ""),
            "send_date": data.get("send_date", ""),
            "sign_time": data.get("sign_time", ""),
            "items": data.get("items", []),
            "endpoint": result.get("endpoint", ""),
            "duration_ms": result.get("duration_ms", 0),
        }
    return {
        "found": False,
        "endpoint": result.get("endpoint", ""),
        "duration_ms": result.get("duration_ms", 0),
        "query_type": result.get("query_type", ""),
        "attempted_paths": result.get("attempted_paths", []),
        "error_code": result.get("error_code"),
        "safe_fallback_reason": result.get("safe_fallback_reason", ""),
    }


def _handle_jst_lookup_tracking(inputs: dict, state: dict) -> dict:
    """调用 lookup_logistics_by_tracking_no"""
    from app.integrations.jst.live_query import lookup_order_by_identifier

    tracking_no = inputs.get("tracking_no", "")
    result = lookup_order_by_identifier(tracking_no, "tracking_no")
    if result.get("found"):
        data = result["data"]
        return {
            "found": True,
            "o_id": data.get("o_id", ""),
            "logistics_company": data.get("logistics_company", ""),
            "l_id": data.get("l_id", ""),
            "send_date": data.get("send_date", ""),
            "sign_time": data.get("sign_time", ""),
            "items": data.get("items", []),
            "endpoint": result.get("endpoint", ""),
            "duration_ms": result.get("duration_ms", 0),
        }
    return {
        "found": False,
        "endpoint": result.get("endpoint", ""),
        "duration_ms": result.get("duration_ms", 0),
        "query_type": result.get("query_type", ""),
        "attempted_paths": result.get("attempted_paths", []),
        "error_code": result.get("error_code"),
        "safe_fallback_reason": result.get("safe_fallback_reason", ""),
    }


def _handle_rag_search(inputs: dict, state: dict) -> dict:
    """通过 RetrieverFactory 调用检索，失败时降级文本检索。"""
    try:
        from app.retrieval.retriever_factory import get_retriever
        from app.services.metrics_service import get_metrics_service

        query = inputs.get("query", "")
        source_types = inputs.get("source_types") or state.get("allowed_source_types", [])
        intent = inputs.get("intent") or state.get("intent", "")
        product_scope = inputs.get("product_scope") or []
        slots = state.get("slots", {}) or {}
        identity = state.get("order_product_identity") or {}
        product_name = (
            inputs.get("product_name")
            or state.get("matched_product_name")
            or identity.get("matched_product_name")
            or slots.get("product_name", "")
        )
        input_sku = inputs.get("sku_name") or ""
        fact_type = inputs.get("fact_type") or state.get("query_fact_type", "")
        slot_sku = slots.get("sku_name") or slots.get("sku_code") or ""
        sku_name = (
            input_sku if _looks_like_sku(input_sku)
            else slot_sku if _looks_like_sku(slot_sku)
            else identity.get("sku_id")
            or identity.get("i_id")
            or input_sku
            or slot_sku
        )
        if _looks_like_sku(sku_name):
            sku_name = str(sku_name).strip().upper()
        if identity.get("matched_product_name") and identity["matched_product_name"] not in product_scope:
            product_scope = [identity["matched_product_name"], *product_scope]
        for value in identity.get("candidates", []) or []:
            if isinstance(value, dict):
                candidate_text = str(
                    value.get("matched_product_name")
                    or value.get("product_name")
                    or value.get("name")
                    or value.get("title")
                    or value.get("value")
                    or ""
                ).strip()
            else:
                candidate_text = str(value or "").strip()
            if candidate_text and candidate_text not in product_scope:
                product_scope.append(candidate_text)

        debug = {
            "query": query,
            "source_types": source_types,
            "product_scope": product_scope,
            "sku_scope": [sku_name] if sku_name else [],
            "product_name": product_name,
            "sku_name": sku_name,
            "fact_type": fact_type,
        }

        if not source_types:
            return {
                "chunks": [],
                "count": 0,
                "retrieval_mode": "skipped_no_source_types",
                "debug": debug,
            }

        get_metrics_service().increment("rag_retrieval_count")
        retrieval_mode = "retriever_hybrid"

        # 使用 RetrieverFactory
        retriever = get_retriever()
        results = retriever.retrieve(
            query=query,
            source_types=source_types,
            product_scope=product_scope if product_scope else None,
            sku_scope=[sku_name] if sku_name else None,
            fact_type=fact_type,
            top_k=5,
            min_score=0.1,
            sku_name=sku_name,
            product_name=product_name,
        )

        if not results:
            # 降级：尝试包含 draft
            retrieval_mode = "retriever_draft_fallback"
            try:
                from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
                results = KnowledgeChunkRepository.search_hybrid(
                    query=query,
                    source_types=source_types,
                    intent="",
                    product_scope=product_scope if product_scope else None,
                    sku_scope=[sku_name] if sku_name else None,
                    fact_type=fact_type,
                    top_k=5,
                    min_score=0.1,
                    include_draft=True,
                    product_name=product_name,
                    sku_name=sku_name,
                )
            except Exception:
                results = []

        if not results:
            get_metrics_service().increment("rag_no_evidence_count")

        # Mark draft entries as unverified
        for r in results:
            if r.get("entry_status") == "draft":
                r["fact_review_status"] = r.get("fact_review_status") or "draft_unverified"
                r["evidence_allowed_for_direct_answer"] = False

        return {
            "chunks": results,
            "count": len(results),
            "retrieval_mode": retrieval_mode,
            "debug": debug,
        }
    except Exception as e:
        logger.warning("RAG 搜索失败: %s", e)
        return {"chunks": [], "count": 0, "error": str(e)}


def _handle_product_resolver(inputs: dict, state: dict) -> dict:
    """调用 resolve_product_identity 的核心逻辑。
    优先使用 state 中已解析的商品身份，避免重复匹配。"""
    # Check if product identity is already resolved from upstream
    identity = state.get("order_product_identity") or {}
    matched_name = state.get("matched_product_name", "")
    if identity.get("status") == "resolved" and (identity.get("matched_product_name") or matched_name):
        resolved_name = identity.get("matched_product_name") or matched_name
        candidates = identity.get("candidates", [])
        if resolved_name and resolved_name not in candidates:
            candidates = [resolved_name] + list(candidates)
        return {
            "matched_product_name": resolved_name,
            "candidates": candidates or [resolved_name],
            "need_clarification": False,
            "source": identity.get("source", "state_identity"),
            "sku_id": identity.get("sku_id", ""),
            "i_id": identity.get("i_id", ""),
        }

    from app.agent.nodes.resolve_product_identity import _match_products_from_message

    message = inputs.get("message", "")
    candidates = _match_products_from_message(message)

    if len(candidates) == 1:
        return {
            "matched_product_name": candidates[0],
            "candidates": candidates,
            "need_clarification": False,
        }
    if len(candidates) > 1:
        return {
            "matched_product_name": "",
            "candidates": candidates,
            "need_clarification": True,
        }
    return {
        "matched_product_name": "",
        "candidates": [],
        "need_clarification": False,
    }


def _handle_sop_lookup(inputs: dict, state: dict) -> dict:
    """检索 SOP 和禁止承诺"""
    try:
        from app.main import get_policy_repo, get_sop_repo
        policy_repo = get_policy_repo()
        sop_repo = get_sop_repo()

        message = inputs.get("message", "")
        intent = inputs.get("intent") or state.get("intent", "complaint")

        sops = []
        if sop_repo:
            entries = sop_repo.search(message, intent=intent, limit=2)
            if not entries:
                entries = sop_repo.get_by_intent(intent)[:2]
            sops = [
                {
                    "id": s.get("id", ""),
                    "scenario": s.get("scenario", ""),
                    "steps": s.get("steps", [])[:5],
                    "forbidden_claims": s.get("forbidden_claims", []),
                    "reply_style": s.get("suggested_reply_style", ""),
                }
                for s in entries
            ]

        forbidden = policy_repo.get_forbidden_claims() if policy_repo else []

        return {
            "sops": sops,
            "forbidden_claims": forbidden[:10],
        }
    except Exception as e:
        logger.warning("SOP 查询失败: %s", e)
        return {"sops": [], "forbidden_claims": [], "error": str(e)}


def _handle_template_select(inputs: dict, state: dict) -> dict:
    """选择话术模板"""
    try:
        from app.main import get_reply_template_repo
        template_repo = get_reply_template_repo()

        message = inputs.get("message", "")
        intent = inputs.get("intent") or state.get("intent", "general")

        templates = []
        if template_repo:
            entries = template_repo.search(message, intent=intent, limit=2)
            if not entries:
                entries = template_repo.get_by_intent(intent, limit=2)
            templates = [
                {
                    "id": t.get("id", ""),
                    "scenario": t.get("scenario", ""),
                    "template": t.get("template", "")[:300],
                }
                for t in entries
            ]

        return {"templates": templates}
    except Exception as e:
        logger.warning("模板选择失败: %s", e)
        return {"templates": [], "error": str(e)}
