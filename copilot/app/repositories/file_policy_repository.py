"""
文件规则仓库 - 从 YAML 文件加载规则
"""

import os
import re
import yaml
from .base import PolicyRepositoryBase
from app.config import RULES_DIR


class FilePolicyRepository(PolicyRepositoryBase):
    """从 YAML 文件加载的规则仓库"""

    def __init__(self, rules_dir: str | None = None):
        self._rules_dir = rules_dir or RULES_DIR
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
        path = os.path.join(self._rules_dir, filename)
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
        path = os.path.join(self._rules_dir, "forbidden_claims.yaml")
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

    def resolve_domain_policy_pack(self, context: dict | None) -> dict:
        """Load a domain policy only from explicit structured metadata."""
        context = context if isinstance(context, dict) else {}
        candidates = [
            (context.get("tenant_metadata") or {}).get("domain_policy_id")
            if isinstance(context.get("tenant_metadata"), dict) else None,
            (context.get("store_metadata") or {}).get("domain_policy_id")
            if isinstance(context.get("store_metadata"), dict) else None,
            (context.get("catalog_metadata") or {}).get("domain_policy_id")
            if isinstance(context.get("catalog_metadata"), dict) else None,
        ]
        selected = sorted({
            str(value).strip()
            for value in candidates
            if str(value or "").strip()
        })
        if not selected:
            return self._domain_policy_result(
                status="missing",
                reason="domain_policy_id_missing",
            )
        if len(selected) != 1:
            return self._domain_policy_result(
                status="invalid",
                reason="domain_policy_id_conflict",
            )
        domain_id = selected[0]
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", domain_id):
            return self._domain_policy_result(
                status="invalid",
                domain_id=domain_id,
                reason="domain_policy_id_invalid",
            )

        path = os.path.join(
            self._rules_dir,
            "domain_policy_packs",
            f"{domain_id}.yaml",
        )
        if not os.path.isfile(path):
            return self._domain_policy_result(
                status="missing",
                domain_id=domain_id,
                reason="domain_policy_pack_missing",
            )
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError):
            return self._domain_policy_result(
                status="invalid",
                domain_id=domain_id,
                reason="domain_policy_pack_unreadable",
            )
        reason = self._validate_domain_policy_pack(
            data,
            expected_domain_id=domain_id,
        )
        if reason:
            return self._domain_policy_result(
                status="invalid",
                domain_id=domain_id,
                reason=reason,
            )
        return {
            "schema_version": "domain-policy-pack/v1",
            "domain_id": domain_id,
            "version": str(data["version"]).strip(),
            "status": "loaded",
            "reason_codes": [],
            "claim_policies": {
                str(key): dict(value)
                for key, value in sorted(data["claim_policies"].items())
            },
            "bounded_inference_policies": [
                dict(value)
                for value in sorted(
                    data.get("bounded_inference_policies") or [],
                    key=lambda item: str(
                        item.get("policy_intent_ref") or ""
                    ),
                )
            ],
        }

    @staticmethod
    def _domain_policy_result(
        *,
        status: str,
        reason: str,
        domain_id: str = "",
    ) -> dict:
        return {
            "schema_version": "domain-policy-pack/v1",
            "domain_id": domain_id,
            "version": "",
            "status": status,
            "reason_codes": [reason],
            "claim_policies": {},
            "bounded_inference_policies": [],
        }

    @staticmethod
    def _validate_domain_policy_pack(
        data: object,
        *,
        expected_domain_id: str,
    ) -> str:
        if not isinstance(data, dict):
            return "domain_policy_pack_not_object"
        if data.get("schema_version") != "domain-policy-pack/v1":
            return "domain_policy_schema_invalid"
        required_top_level = {
            "schema_version",
            "domain_id",
            "version",
            "claim_policies",
        }
        allowed_top_level = {
            *required_top_level,
            "bounded_inference_policies",
        }
        if (
            not required_top_level.issubset(data)
            or not set(data).issubset(allowed_top_level)
        ):
            return "domain_policy_top_level_schema_invalid"
        if str(data.get("domain_id") or "").strip() != expected_domain_id:
            return "domain_policy_identity_mismatch"
        version = str(data.get("version") or "").strip()
        if not version:
            return "domain_policy_version_missing"
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            return "domain_policy_version_invalid"
        policies = data.get("claim_policies")
        if not isinstance(policies, dict) or not policies:
            return "domain_policy_claim_policies_missing"
        allowed_keys = {
            "risk_level",
            "direct_fact_fast_path_allowed",
            "bounded_inference_policy",
            "freshness_requirement",
        }
        for claim_type, policy in policies.items():
            if not isinstance(claim_type, str) or not claim_type.strip():
                return "domain_policy_claim_type_invalid"
            if not isinstance(policy, dict) or set(policy) != allowed_keys:
                return "domain_policy_claim_policy_schema_invalid"
            if policy.get("risk_level") not in {
                "low",
                "medium",
                "high",
                "prohibited",
            }:
                return "domain_policy_risk_level_invalid"
            if not isinstance(policy.get("direct_fact_fast_path_allowed"), bool):
                return "domain_policy_direct_permission_invalid"
            if policy.get("bounded_inference_policy") not in {
                "none",
                "allowed",
                "review_required",
                "prohibited",
            }:
                return "domain_policy_inference_policy_invalid"
            if policy.get("freshness_requirement") not in {
                "static",
                "live",
                "action",
            }:
                return "domain_policy_freshness_invalid"
        inference_policies = data.get("bounded_inference_policies", [])
        if not isinstance(inference_policies, list):
            return "domain_policy_bounded_inference_policies_invalid"
        policy_intent_refs: set[str] = set()
        inference_keys = {
            "policy_intent_ref",
            "goal_family",
            "intent_kind",
            "premise_fact_families",
            "required_context_capabilities",
            "allowed_scope",
            "required_qualifiers",
            "prohibited_claim_families",
            "review_only",
        }
        identifier_pattern = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}")
        for policy in inference_policies:
            if not isinstance(policy, dict) or set(policy) != inference_keys:
                return "domain_policy_bounded_inference_schema_invalid"
            policy_intent_ref = str(
                policy.get("policy_intent_ref") or ""
            ).strip()
            if (
                not identifier_pattern.fullmatch(policy_intent_ref)
                or policy_intent_ref in policy_intent_refs
            ):
                return "domain_policy_policy_intent_ref_invalid"
            policy_intent_refs.add(policy_intent_ref)
            if not identifier_pattern.fullmatch(
                str(policy.get("goal_family") or "")
            ):
                return "domain_policy_goal_family_invalid"
            if policy.get("intent_kind") not in {
                "practical_guidance",
                "absolute_guarantee",
                "test_standard_request",
                "warranty_or_liability_request",
            }:
                return "domain_policy_intent_kind_invalid"
            for key in (
                "premise_fact_families",
                "required_context_capabilities",
                "required_qualifiers",
                "prohibited_claim_families",
            ):
                values = policy.get(key)
                if (
                    not isinstance(values, list)
                    or not values
                    or len(values) != len(set(values))
                    or any(
                        not isinstance(value, str)
                        or not identifier_pattern.fullmatch(value)
                        for value in values
                    )
                ):
                    return "domain_policy_bounded_inference_values_invalid"
            if not identifier_pattern.fullmatch(
                str(policy.get("allowed_scope") or "")
            ):
                return "domain_policy_bounded_inference_scope_invalid"
            if policy.get("review_only") is not True:
                return "domain_policy_bounded_inference_review_only_required"
        return ""
