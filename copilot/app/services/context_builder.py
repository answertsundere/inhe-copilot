"""
上下文组装服务 - 查询订单、物流、退款、售后、商品、库存、知识库、产品知识卡、话术模板、SOP、数据质量
"""

import logging

from app.repositories.json_order_repository import JsonOrderRepository
from app.repositories.json_product_repository import JsonProductRepository
from app.repositories.file_knowledge_repository import FileKnowledgeRepository
from app.repositories.product_knowledge_repository import ProductKnowledgeRepository
from app.repositories.reply_template_repository import ReplyTemplateRepository
from app.repositories.sop_repository import SOPRepository
from app.services.skill_router import SkillRouter
from app.services.data_quality_service import DataQualityService

logger = logging.getLogger(__name__)


class ContextBuilder:
    """上下文组装器"""

    def __init__(
        self,
        order_repo: JsonOrderRepository,
        product_repo: JsonProductRepository,
        knowledge_repo: FileKnowledgeRepository,
        product_knowledge_repo: ProductKnowledgeRepository = None,
        reply_template_repo: ReplyTemplateRepository = None,
        sop_repo: SOPRepository = None,
        skill_router: SkillRouter = None,
        data_quality_service: DataQualityService = None,
    ):
        self.order_repo = order_repo
        self.product_repo = product_repo
        self.knowledge_repo = knowledge_repo
        self.product_knowledge_repo = product_knowledge_repo
        self.reply_template_repo = reply_template_repo
        self.sop_repo = sop_repo
        self.skill_router = skill_router or SkillRouter()
        self.data_quality_service = data_quality_service

    def build(
        self,
        customer_message: str,
        order_id: str = "",
    ) -> dict:
        """
        构建业务上下文。
        """
        context = {}

        # 订单相关上下文
        if order_id:
            order = self.order_repo.get_order(order_id)
            if order:
                context["order"] = self._format_order(order)
                for key, repo_method in [
                    ("logistics", self.order_repo.get_logistics),
                    ("refund", self.order_repo.get_refunds),
                    ("aftersale", self.order_repo.get_aftersale),
                ]:
                    data = repo_method(order_id)
                    if data:
                        context[key] = data

                # 订单中的商品信息 + 库存
                products = []
                for item in order.get("items", []):
                    sku_info = self.product_repo.get_sku(item.get("sku_id", ""))
                    if sku_info:
                        products.append(sku_info)
                        inv = self.product_repo.get_inventory(item.get("sku_id", ""))
                        if inv:
                            context.setdefault("inventory", []).extend(inv)
                if products:
                    context["products"] = products

        # 通用知识库上下文（shipping.md, refund.md 等）
        knowledge_entries = self.knowledge_repo.search(customer_message, limit=3)
        if knowledge_entries:
            context["knowledge"] = [
                {"title": e["title"], "category": e["category"], "content": e["content"][:500]}
                for e in knowledge_entries
            ]

        # 产品知识卡上下文（从 product_cards.json）
        pk_entries = []
        pk_warnings = []
        if self.product_knowledge_repo and self.product_knowledge_repo.count() > 0:
            pk_entries = self._search_product_knowledge(customer_message, context)
            if pk_entries:
                context["product_knowledge"] = pk_entries
                # 数据质量检查
                for pk in pk_entries:
                    level = pk.get("agent_level", "L0")
                    if level in ("L0", "L1"):
                        pk_warnings.append(f"产品[{pk.get('name', '?')}]知识完整度低({level})，请勿对参数做确定性承诺")

        # Skill 路由
        risk_hint = "low"  # 默认，ReplyService 会覆盖
        skill_route = self.skill_router.route(customer_message, risk_level=risk_hint, context=context)
        context["skill_route"] = skill_route

        # SOP 场景
        sop_entries = []
        if self.sop_repo and self.sop_repo.count() > 0:
            sop_entries = self.sop_repo.search(customer_message, intent=skill_route["skill"], limit=2)
            if not sop_entries:
                sop_entries = self.sop_repo.get_by_intent(skill_route["skill"])[:2]
            if sop_entries:
                context["sop_scenarios"] = [
                    {"id": s["id"], "scenario": s["scenario"], "steps": s.get("steps", [])[:5],
                     "forbidden_claims": s.get("forbidden_claims", []),
                     "escalation_triggers": s.get("escalation_triggers", []),
                     "reply_style": s.get("suggested_reply_style", "")}
                    for s in sop_entries
                ]

        # 话术模板
        template_entries = []
        if self.reply_template_repo and self.reply_template_repo.count() > 0:
            template_entries = self.reply_template_repo.search(
                customer_message, intent=skill_route["skill"], limit=2
            )
            if not template_entries:
                template_entries = self.reply_template_repo.get_by_intent(skill_route["skill"], limit=2)
            if template_entries:
                context["reply_templates"] = [
                    {"id": t["id"], "scenario": t["scenario"], "template": t["template"][:300],
                     "forbidden_phrases": t.get("forbidden_phrases", []),
                     "risk_level": t.get("risk_level", "low")}
                    for t in template_entries
                ]

        # 数据质量警告
        if pk_warnings:
            context["data_quality_warnings"] = pk_warnings

        return context

    def _search_product_knowledge(self, customer_message: str, context: dict) -> list:
        """从产品知识库搜索相关知识"""
        repo = self.product_knowledge_repo
        results = []

        # 1. 如果订单中有 SKU/i_id，直接查询
        for product in context.get("products", []):
            sku_id = product.get("sku_id")
            i_id = product.get("i_id")
            card = None
            if i_id:
                card = repo.get_by_i_id(i_id)
            if not card and sku_id:
                card = repo.get_by_sku_id(sku_id)
            if card:
                results.append(repo.get_summary(card))

        # 2. 关键词搜索（补充）
        if len(results) < 3:
            searched = repo.search(customer_message, limit=3)
            existing_iids = {r.get("i_id") for r in results}
            for card in searched:
                if card.get("i_id") not in existing_iids:
                    results.append(repo.get_summary(card))

        return results[:3]  # 最多 3 条，避免 prompt 过长

    def _format_order(self, order: dict) -> dict:
        """格式化订单信息（去除隐私字段）"""
        return {
            "o_id": order.get("o_id"),
            "shop_name": order.get("shop_name"),
            "status": order.get("status"),
            "shop_status": order.get("shop_status"),
            "amount": order.get("amount"),
            "pay_amount": order.get("pay_amount"),
            "created": order.get("created"),
            "pay_date": order.get("pay_date"),
            "send_date": order.get("send_date"),
            "sign_time": order.get("sign_time"),
            "logistics_company": order.get("logistics_company"),
            "l_id": order.get("l_id"),
            "buyer_message": order.get("buyer_message"),
            "remark": order.get("remark"),
            "items": order.get("items", []),
        }

    def build_context_summary(self, context: dict) -> dict:
        """构建上下文摘要（给前端用，不含隐私）"""
        product_knowledge = context.get("product_knowledge", [])
        # 去除产品知识中的隐私字段
        safe_pk = []
        for pk in product_knowledge:
            safe_pk.append({
                k: v for k, v in pk.items()
                if k not in ("buyer_id", "receiver_name", "receiver_phone",
                             "receiver_address", "receiver_state", "receiver_city")
            })

        summary = {
            "has_order": "order" in context,
            "has_logistics": "logistics" in context,
            "has_refund": bool(context.get("refund")),
            "has_aftersale": bool(context.get("aftersale")),
            "has_inventory": bool(context.get("inventory")),
            "knowledge_count": len(context.get("knowledge", [])),
            "product_knowledge_count": len(product_knowledge),
            "product_knowledge": safe_pk,
            "skill_route": context.get("skill_route", {}),
            "sop_count": len(context.get("sop_scenarios", [])),
            "template_count": len(context.get("reply_templates", [])),
            "data_quality_warnings": context.get("data_quality_warnings", []),
            "data_source": context.get("data_source", ""),
            "tracking_no": context.get("tracking_no", ""),
            "tracking_state": context.get("tracking_state", ""),
            "tracking_courier": context.get("tracking_courier", ""),
            "tracking_data_count": len(context.get("tracking_data", [])),
        }

        # 补充数据来源信息
        sources = []
        if context.get("live_order"):
            sources.append("live_jst")
        elif "order" in context:
            sources.append("local_order")
        if product_knowledge:
            sources.append("product_knowledge")
        if context.get("knowledge"):
            sources.append("knowledge_base")
        if not sources:
            sources.append("fallback")
        summary["sources"] = sources

        # 补充订单状态摘要（不含隐私）
        order = context.get("order")
        if order:
            summary["order_status"] = order.get("status", "")
            summary["order_courier"] = order.get("logistics_company", "")
            summary["order_tracking_no"] = order.get("l_id", "")
            items = order.get("items", [])
            if items:
                summary["order_items"] = [
                    {"name": i.get("name", ""), "sku_id": i.get("sku_id", "")}
                    for i in items[:3]
                ]

        return summary
