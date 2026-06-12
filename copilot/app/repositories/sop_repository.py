"""
SOP 场景仓库 - 从 sop_scenarios.yaml 加载
"""

import os
import yaml
from typing import Optional

from app.config import KNOWLEDGE_DIR


class SOPRepository:
    """SOP 场景仓库"""

    def __init__(self, knowledge_dir: str = ""):
        self._scenarios = []
        self._by_id = {}
        self._by_intent = {}
        self._loaded = False
        self._knowledge_dir = knowledge_dir or KNOWLEDGE_DIR

    def load(self):
        """加载 sop_scenarios.yaml"""
        path = os.path.join(self._knowledge_dir, "sop_scenarios.yaml")
        if not os.path.exists(path):
            self._loaded = True
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            self._loaded = True
            return

        raw_scenarios = data.get("scenarios", [])
        self._scenarios = []
        for s in raw_scenarios:
            # 数据清洗：过滤掉 scenario 为空或 steps 包含元数据的 bad SOP
            scenario = s.get("scenario", "")
            if not scenario or not isinstance(scenario, str):
                continue
            steps = s.get("steps", [])
            steps_text = " ".join(str(step) for step in steps)
            bad_markers = ["Codex", ".py", "markdown", "```", "POST /api", "GET /api"]
            if any(marker in steps_text for marker in bad_markers):
                continue
            self._scenarios.append(s)
            sid = s.get("id")
            if sid:
                self._by_id[sid] = s
            intent = s.get("intent", "general")
            self._by_intent.setdefault(intent, []).append(s)

        self._loaded = True

    def count(self) -> int:
        return len(self._scenarios)

    def get_by_id(self, scenario_id: str) -> Optional[dict]:
        return self._by_id.get(scenario_id)

    def get_by_intent(self, intent: str) -> list:
        return self._by_intent.get(intent, [])

    def search(self, query: str, intent: str = "", limit: int = 5) -> list:
        """关键词搜索 SOP"""
        if not self._scenarios:
            return []

        query_lower = query.lower()
        scored = []

        for s in self._scenarios:
            if intent and s.get("intent") != intent:
                continue

            score = 0
            scenario = (s.get("scenario") or "").lower()
            steps_text = " ".join(s.get("steps", [])).lower()

            if query_lower in scenario or scenario in query_lower:
                score += 10
            if query_lower in steps_text:
                score += 5
            for kw in query_lower.split():
                if kw in scenario:
                    score += 3
                if kw in steps_text:
                    score += 1

            if score > 0:
                scored.append((score, s))

        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:limit]]
