"""
ToolSpec — 工具元数据定义

每个工具注册一个 ToolSpec，描述名称、能力边界、安全约束。
ToolSpec 不执行任何逻辑，只做声明。
"""

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ToolSpec:
    """工具规格定义"""

    # 基本信息
    name: str
    description: str

    # Schema（纯 dict，不做运行时校验）
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    freshness_class: str = "unknown"

    # 安全边界
    allowed_intents: list = field(default_factory=list)        # 允许使用此工具的意图，空=不限
    allowed_risk_levels: list = field(default_factory=list)    # 允许的风险等级，空=不限
    forbidden_intents: list = field(default_factory=list)      # 禁止使用此工具的意图
    read_only: bool = True                                     # 是否只读
    can_create_fact_types: list = field(default_factory=list)  # 能产生的事实类型
    requires_human_review: bool = False                        # 使用此工具的结果是否需要人工复核

    # 执行配置
    timeout_ms: int = 3000                                     # 超时毫秒
    handler: Optional[Callable] = None                         # 实际执行函数 (inputs, state) -> dict

    def is_allowed(self, intent: str, risk_level: str) -> bool:
        """检查此工具在当前 intent + risk_level 下是否允许"""
        if self.forbidden_intents and intent in self.forbidden_intents:
            return False
        if self.allowed_intents and intent not in self.allowed_intents:
            return False
        if self.allowed_risk_levels and risk_level not in self.allowed_risk_levels:
            return False
        return True

    def to_meta(self) -> dict:
        """返回工具元数据（供 LLM tool 描述用）"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
