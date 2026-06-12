"""
文件规则仓库 - 从 YAML 文件加载规则
"""

import os
import yaml
from .base import PolicyRepositoryBase
from app.config import RULES_DIR


class FilePolicyRepository(PolicyRepositoryBase):
    """从 YAML 文件加载的规则仓库"""

    def __init__(self):
        self._forbidden_claims = []
        self._risk_keywords = {}
        self._reply_policies = []
        self._platform_rules = []
        self._escalation_rules = []
        self._qa_checklist = []
        self._loaded = False

    def load(self):
        """加载所有规则文件"""
        # 加载禁止承诺
        self._forbidden_claims = self._load_yaml_list(
            "forbidden_claims.yaml", "forbidden_claims"
        )

        # 加载风险关键词
        risk_data = self._load_yaml("risk_keywords.yaml")
        if risk_data and "risk_keywords" in risk_data:
            self._risk_keywords = risk_data["risk_keywords"]
        else:
            self._risk_keywords = {"high": [], "medium": [], "low": []}

        # 加载回复策略
        policy_data = self._load_yaml("reply_policies.yaml")
        if policy_data and "policies" in policy_data:
            self._reply_policies = policy_data["policies"]
        else:
            self._reply_policies = []

        # 加载平台规则
        pr_data = self._load_yaml("platform_rules.yaml")
        if pr_data and "rules" in pr_data:
            self._platform_rules = pr_data["rules"]
        else:
            self._platform_rules = []

        # 加载升级规则
        er_data = self._load_yaml("escalation_rules.yaml")
        if er_data and "rules" in er_data:
            self._escalation_rules = er_data["rules"]
        else:
            self._escalation_rules = []

        # 加载质检清单
        qa_data = self._load_yaml("qa_checklist.yaml")
        if qa_data and "checklist" in qa_data:
            self._qa_checklist = qa_data["checklist"]
        else:
            self._qa_checklist = []

        self._loaded = True

    def _load_yaml(self, filename: str) -> dict:
        """加载 YAML 文件"""
        path = os.path.join(RULES_DIR, filename)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_yaml_list(self, filename: str, key: str) -> list:
        """加载 YAML 列表"""
        data = self._load_yaml(filename)
        if isinstance(data, dict):
            items = data.get(key, [])
            # 提取 phrase 字段（如果是对象列表）
            if items and isinstance(items[0], dict):
                return [item.get("phrase", "") for item in items if item.get("phrase")]
            return items
        return []

    def get_forbidden_claims(self) -> list:
        """获取禁止承诺列表（纯字符串列表）"""
        return list(self._forbidden_claims)

    def get_forbidden_claims_detailed(self) -> list:
        """获取禁止承诺详细列表（含分类和原因）"""
        path = os.path.join(RULES_DIR, "forbidden_claims.yaml")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("forbidden_claims", [])

    def get_risk_keywords(self) -> dict:
        """获取风险关键词"""
        return dict(self._risk_keywords)

    def get_reply_policies(self) -> list:
        """获取回复策略"""
        return list(self._reply_policies)

    def get_platform_rules(self) -> list:
        """获取平台规则"""
        return list(self._platform_rules)

    def get_escalation_rules(self) -> list:
        """获取升级规则"""
        return list(self._escalation_rules)

    def get_qa_checklist(self) -> list:
        """获取质检清单"""
        return list(self._qa_checklist)
