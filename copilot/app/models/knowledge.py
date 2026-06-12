"""
知识库数据模型
"""

from dataclasses import dataclass


@dataclass
class KnowledgeEntry:
    """知识条目"""
    title: str = ""
    category: str = ""       # shipping / refund / product / complaint
    content: str = ""
    source_file: str = ""
