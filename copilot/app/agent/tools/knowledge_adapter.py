"""
知识库 / SOP / 话术模板 / 物流政策 查询工具适配器
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class KnowledgeAdapter:
    """知识库查询适配器"""

    def __init__(
        self,
        knowledge_repo=None,
        sop_repo=None,
        reply_template_repo=None,
        file_knowledge_repo=None,
    ):
        self._knowledge_repo = knowledge_repo
        self._sop_repo = sop_repo
        self._reply_template_repo = reply_template_repo
        self._file_knowledge_repo = file_knowledge_repo

    def search_knowledge(self, message: str, limit: int = 3) -> list:
        if self._file_knowledge_repo is None:
            return []
        entries = self._file_knowledge_repo.search(message, limit=limit)
        return [
            {"title": e["title"], "category": e["category"], "content": e["content"][:500]}
            for e in entries
        ]

    def search_sop(self, message: str, intent: str, limit: int = 2) -> list:
        if self._sop_repo is None:
            return []
        entries = self._sop_repo.search(message, intent=intent, limit=limit)
        if not entries:
            entries = self._sop_repo.get_by_intent(intent)[:limit]
        return [
            {
                "id": s["id"],
                "scenario": s["scenario"],
                "steps": s.get("steps", [])[:5],
                "forbidden_claims": s.get("forbidden_claims", []),
                "escalation_triggers": s.get("escalation_triggers", []),
                "reply_style": s.get("suggested_reply_style", ""),
            }
            for s in entries
        ]

    def search_templates(self, message: str, intent: str, limit: int = 2) -> list:
        if self._reply_template_repo is None:
            return []
        entries = self._reply_template_repo.search(message, intent=intent, limit=limit)
        if not entries:
            entries = self._reply_template_repo.get_by_intent(intent, limit=limit)
        return [
            {
                "id": t["id"],
                "scenario": t["scenario"],
                "template": t["template"][:300],
                "forbidden_phrases": t.get("forbidden_phrases", []),
                "risk_level": t.get("risk_level", "low"),
            }
            for t in entries
        ]

    def match_shipping_policy(self, message: str, product_name: str = "") -> dict:
        """
        匹配物流政策，返回安全字段。
        """
        policy = {
            "default_courier": "",
            "eta_days_min": None,
            "eta_days_max": None,
            "note": "",
        }
        entries = self.search_knowledge(message, limit=3)
        if not entries and product_name:
            entries = self.search_knowledge(product_name, limit=3)

        for entry in entries:
            content = entry.get("content", "")
            if "中通" in content or "韵达" in content:
                policy["default_courier"] = "中通/韵达"
            if "德邦" in content or "安能" in content:
                policy["default_courier"] = "德邦/安能"
            if "48小时" in content:
                policy["note"] = "现货商品一般付款后48小时内发货（工作日）"
            if "2-3天" in content or "2~3天" in content:
                policy["eta_days_min"] = 2
                policy["eta_days_max"] = 3
            if "3-5天" in content or "3~5天" in content:
                policy["eta_days_min"] = 3
                policy["eta_days_max"] = 5
            if "5-7天" in content or "5~7天" in content:
                policy["eta_days_min"] = 5
                policy["eta_days_max"] = 7
        return policy
