"""
数据质量服务 - 聚合 product_cards.json、data_quality_report.md、missing_info_tasks.csv
"""

import csv
import json
import logging
import os
from collections import Counter

from app.config import KNOWLEDGE_DIR

logger = logging.getLogger(__name__)


def _default_data_dir() -> str:
    """返回 product_knowledge 目录（在 KNOWLEDGE_DIR 的父目录下）"""
    base = os.path.dirname(KNOWLEDGE_DIR)
    return os.path.join(base, "product_knowledge")


class DataQualityService:
    """数据质量中心"""

    def __init__(self, knowledge_dir: str = "", data_dir: str = ""):
        self._knowledge_dir = knowledge_dir or KNOWLEDGE_DIR
        self._data_dir = data_dir or _default_data_dir()
        self._cards = []
        self._missing_tasks = []
        self._loaded = False

    def load(self):
        """加载数据"""
        self._load_cards()
        self._load_missing_tasks()
        self._loaded = True

    def _load_cards(self):
        path = os.path.join(self._data_dir, "product_cards.json")
        if not os.path.exists(path):
            # 尝试知识库目录
            alt = os.path.join(self._knowledge_dir, "product_cards.json")
            if os.path.exists(alt):
                path = alt
            else:
                logger.info("product_cards.json 不存在，数据质量服务降级为空")
                return

        try:
            with open(path, "r", encoding="utf-8") as f:
                self._cards = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取 product_cards.json 失败: %s", e)

    def _load_missing_tasks(self):
        path = os.path.join(self._data_dir, "missing_info_tasks.csv")
        if not os.path.exists(path):
            return

        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                self._missing_tasks = list(reader)
        except Exception as e:
            logger.warning("读取 missing_info_tasks.csv 失败: %s", e)

    # ---- 对外接口 ----

    def get_quality_summary(self) -> dict:
        """全局数据质量摘要"""
        if not self._loaded:
            self.load()

        if not self._cards:
            return {
                "product_count": 0,
                "sku_count": 0,
                "level_distribution": {},
                "missing_field_summary": {},
                "agent_usable_distribution": {},
                "avg_completeness_score": 0,
                "warning": "product_cards.json 未加载",
            }

        levels = Counter()
        agent_levels = Counter()
        missing_fields = Counter()
        sku_count = 0
        scores = []

        for c in self._cards:
            levels[c.get("agent_usable_level", "L0")] += 1
            agent_levels[c.get("review_status", "未知")] += 1
            sku_count += c.get("sku_summary", {}).get("sku_count", 0)
            scores.append(c.get("completeness_score", 0))
            for mf in c.get("missing_fields", []):
                missing_fields[mf] += 1

        return {
            "product_count": len(self._cards),
            "sku_count": sku_count,
            "level_distribution": dict(levels),
            "missing_field_summary": dict(missing_fields.most_common(20)),
            "agent_usable_distribution": dict(agent_levels),
            "avg_completeness_score": round(sum(scores) / len(scores), 1) if scores else 0,
        }

    def get_missing_info(self, limit: int = 100) -> list:
        """缺失信息任务列表"""
        if not self._loaded:
            self.load()
        return self._missing_tasks[:limit]

    def get_product_quality(self, i_id: str) -> dict:
        """单个商品的数据质量"""
        if not self._loaded:
            self.load()

        for c in self._cards:
            if str(c.get("i_id")) == str(i_id):
                return {
                    "i_id": c.get("i_id"),
                    "product_name": c.get("product_name"),
                    "completeness_score": c.get("completeness_score"),
                    "agent_usable_level": c.get("agent_usable_level"),
                    "review_status": c.get("review_status"),
                    "missing_fields": c.get("missing_fields", []),
                    "data_quality_warnings": c.get("data_quality_warnings", []),
                    "sku_count": c.get("sku_summary", {}).get("sku_count", 0),
                }

        return {
            "i_id": i_id,
            "product_name": None,
            "completeness_score": 0,
            "agent_usable_level": "L0",
            "review_status": "未找到",
            "missing_fields": [],
            "data_quality_warnings": ["商品未在知识库中找到"],
            "sku_count": 0,
        }
