"""
文件知识库仓库 - 从 Markdown 文件加载知识
"""

import os
from .base import KnowledgeRepositoryBase
from app.config import KNOWLEDGE_DIR


class FileKnowledgeRepository(KnowledgeRepositoryBase):
    """从 Markdown 文件加载的知识库"""

    def __init__(self):
        self.entries = []  # List[KnowledgeEntry]
        self._loaded = False

    def load(self):
        """加载所有 Markdown 知识文件"""
        if not os.path.exists(KNOWLEDGE_DIR):
            self._loaded = True
            return

        for filename in os.listdir(KNOWLEDGE_DIR):
            if not filename.endswith(".md"):
                continue
            path = os.path.join(KNOWLEDGE_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            category = os.path.splitext(filename)[0]
            title = content.split("\n")[0].lstrip("# ").strip() if content else filename
            self.entries.append({
                "title": title,
                "category": category,
                "content": content,
                "source_file": filename,
            })
        self._loaded = True

    def search(self, query: str, category: str = "", limit: int = 5) -> list:
        """简单关键词搜索知识条目"""
        results = []
        query_lower = query.lower()
        for entry in self.entries:
            if category and entry["category"] != category:
                continue
            # 简单关键词匹配
            if query_lower in entry["content"].lower():
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def get_by_category(self, category: str) -> list:
        """按分类获取知识"""
        return [e for e in self.entries if e["category"] == category]

    def get_all(self) -> list:
        """获取所有知识条目"""
        return list(self.entries)
