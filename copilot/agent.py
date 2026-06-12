"""
[已废弃] 旧 Agent 模块 - 仅为参考保留。

逻辑已拆分到新架构:
    - app/services/risk_service.py     - 风险检测
    - app/services/context_builder.py  - 上下文组装
    - app/services/output_guard.py     - 输出安全检查
    - app/services/reply_service.py    - 主编排
    - app/llm/client.py               - LLM 调用
    - app/llm/prompts.py              - Prompt 模板
    - app/llm/schemas.py              - Schema 校验

新入口:
    - Web 服务: python run_web.py
    - 命令行:   python run_cli.py
"""

import warnings

warnings.warn(
    "agent.py (旧) 已废弃，逻辑已迁移至 app/services/ 和 app/llm/。",
    DeprecationWarning,
    stacklevel=2,
)

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 代理到新架构：保持旧调用兼容
from app.services.reply_service import format_suggestion


def analyze_message(customer_message, order_id=None, extra_info=None):
    """兼容旧调用 - 代理到新 ReplyService"""
    from app.main import get_reply_service
    service = get_reply_service()
    result = service.analyze(customer_message, order_id=order_id or "")
    return result.to_dict()


def build_context(customer_message, order_id=None, extra_info=None):
    """兼容旧调用 - 代理到新 ContextBuilder"""
    from app.main import get_order_repo, get_product_repo, get_knowledge_repo
    from app.services.context_builder import ContextBuilder
    order_repo = get_order_repo()
    product_repo = get_product_repo()
    knowledge_repo = get_knowledge_repo()
    builder = ContextBuilder(order_repo, product_repo, knowledge_repo)
    return builder.build(customer_message, order_id or "")


def detect_risk(customer_message):
    """兼容旧调用 - 代理到新 RiskService"""
    from app.main import get_risk_service
    service = get_risk_service()
    return service.detect_risk(customer_message)
