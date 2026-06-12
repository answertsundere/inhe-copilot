"""
话术模板仓库 - 从 reply_templates.json 加载
"""

import json
import os
from typing import Optional

from app.config import KNOWLEDGE_DIR


class ReplyTemplateRepository:
    """话术模板仓库"""

    def __init__(self, knowledge_dir: str = ""):
        self._templates = []
        self._by_id = {}
        self._by_intent = {}
        self._loaded = False
        self._knowledge_dir = knowledge_dir or KNOWLEDGE_DIR

    def load(self):
        """加载 reply_templates.json"""
        path = os.path.join(self._knowledge_dir, "reply_templates.json")
        if not os.path.exists(path):
            self._loaded = True
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._loaded = True
            return

        self._templates = data.get("templates", [])
        for t in self._templates:
            tid = t.get("id")
            if tid:
                self._by_id[tid] = t
            intent = t.get("intent", "general")
            self._by_intent.setdefault(intent, []).append(t)

        self._loaded = True

    def count(self) -> int:
        return len(self._templates)

    def get_by_id(self, template_id: str) -> Optional[dict]:
        return self._by_id.get(template_id)

    def get_by_intent(self, intent: str, limit: int = 5) -> list:
        return self._by_intent.get(intent, [])[:limit]

    def search(self, query: str, intent: str = "", risk_level: str = "", limit: int = 5) -> list:
        """关键词搜索话术模板"""
        if not self._templates:
            return []

        query_lower = query.lower()
        scored = []

        for t in self._templates:
            # intent 过滤
            if intent and t.get("intent") != intent:
                continue
            # risk_level 过滤
            if risk_level and t.get("risk_level") != risk_level:
                continue

            score = 0
            scenario = (t.get("scenario") or "").lower()
            template_text = (t.get("template") or "").lower()
            tags = " ".join(t.get("tags", [])).lower()

            if query_lower in scenario or scenario in query_lower:
                score += 10
            if query_lower in template_text:
                score += 5
            if query_lower in tags:
                score += 3
            # 关键词匹配
            for kw in query_lower.split():
                if kw in scenario:
                    score += 2
                if kw in template_text:
                    score += 1

            if score > 0:
                scored.append((score, t))

        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored[:limit]]
