"""
文件规则仓库 - 从 YAML 文件加载规则
"""

import hashlib
import json
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
        if context.get("schema_version") == "trusted-domain-policy-context/v1":
            return self._resolve_trusted_domain_policy_context(context)
        return self._resolve_domain_policy_selector(context)

    def build_trusted_domain_policy_context(
        self,
        selector: dict | None,
        *,
        selection_source: str,
        invalid_reason: str = "",
    ) -> dict:
        """Resolve one trusted selector into a non-factual control projection."""
        selector = selector if isinstance(selector, dict) else {}
        if selection_source not in {
            "server_configuration",
            "verified_server_mapping",
            "evaluation_fixture",
        }:
            selection_source = "server_configuration"
            invalid_reason = (
                invalid_reason
                or "trusted_domain_policy_selection_source_invalid"
            )
        binding_summary = {
            "tenant": isinstance(selector.get("tenant_metadata"), dict),
            "store": isinstance(selector.get("store_metadata"), dict),
            "catalog": isinstance(selector.get("catalog_metadata"), dict),
        }
        if invalid_reason:
            pack = self._domain_policy_result(
                status="invalid",
                reason=invalid_reason,
            )
        else:
            pack = self._resolve_domain_policy_selector(selector)
        status = {
            "loaded": "selected",
            "missing": "missing",
            "invalid": "invalid",
        }.get(str(pack.get("status") or ""), "invalid")
        domain_id = str(pack.get("domain_id") or "")
        return {
            "schema_version": "trusted-domain-policy-context/v1",
            "status": status,
            "trusted_owner": "analysis_pipeline",
            "selection_source": selection_source,
            "pack_ref": (
                str(pack.get("pack_ref") or "")
                if status == "selected"
                else ""
            ),
            "pack_schema_version": (
                str(pack.get("schema_version") or "")
                if status == "selected"
                else ""
            ),
            "pack_content_sha256": (
                str(pack.get("pack_content_sha256") or "")
                if status == "selected"
                else ""
            ),
            "domain_ref": self._domain_ref(domain_id),
            "binding_summary": binding_summary,
            "provenance": {
                "boundary": "analysis_pipeline_internal",
                "selector_owner": "file_policy_repository",
            },
            "selected_at_stage": "canonical_input",
            "validation_reasons": sorted({
                str(reason).strip()
                for reason in pack.get("reason_codes") or []
                if str(reason or "").strip()
            }),
            "used_for_evidence": False,
            "used_for_fact_support": False,
            "can_change_can_send": False,
        }

    def _resolve_domain_policy_selector(self, context: dict) -> dict:
        selector_reason = self._domain_policy_selector_reason(context)
        if selector_reason:
            return self._domain_policy_result(
                status="invalid",
                reason=selector_reason,
            )
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
        content_sha256 = hashlib.sha256(
            json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        version = str(data["version"]).strip()
        return {
            "schema_version": "domain-policy-pack/v1",
            "domain_id": domain_id,
            "version": version,
            "pack_ref": f"domain-policy:{domain_id}@{version}",
            "pack_content_sha256": content_sha256,
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

    def _resolve_trusted_domain_policy_context(self, context: dict) -> dict:
        required = {
            "schema_version",
            "status",
            "trusted_owner",
            "selection_source",
            "pack_ref",
            "pack_schema_version",
            "pack_content_sha256",
            "domain_ref",
            "binding_summary",
            "provenance",
            "selected_at_stage",
            "validation_reasons",
            "used_for_evidence",
            "used_for_fact_support",
            "can_change_can_send",
        }
        if set(context) != required:
            return self._domain_policy_result(
                status="invalid",
                reason="trusted_domain_policy_context_schema_invalid",
            )
        if (
            context.get("trusted_owner") != "analysis_pipeline"
            or context.get("selection_source")
            not in {
                "server_configuration",
                "verified_server_mapping",
                "evaluation_fixture",
            }
            or context.get("provenance")
            != {
                "boundary": "analysis_pipeline_internal",
                "selector_owner": "file_policy_repository",
            }
            or context.get("selected_at_stage") != "canonical_input"
            or context.get("used_for_evidence") is not False
            or context.get("used_for_fact_support") is not False
            or context.get("can_change_can_send") is not False
        ):
            return self._domain_policy_result(
                status="invalid",
                reason="trusted_domain_policy_context_authority_invalid",
            )
        binding_summary = context.get("binding_summary")
        if (
            not isinstance(binding_summary, dict)
            or set(binding_summary) != {"tenant", "store", "catalog"}
            or any(not isinstance(value, bool) for value in binding_summary.values())
        ):
            return self._domain_policy_result(
                status="invalid",
                reason="trusted_domain_policy_binding_invalid",
            )
        domain_ref = context.get("domain_ref")
        if domain_ref and not re.fullmatch(
            r"domain-[0-9a-f]{20}",
            str(domain_ref),
        ):
            return self._domain_policy_result(
                status="invalid",
                reason="trusted_domain_policy_domain_ref_invalid",
            )
        reasons = context.get("validation_reasons")
        if (
            not isinstance(reasons, list)
            or reasons != sorted(set(reasons))
            or any(not isinstance(reason, str) or not reason for reason in reasons)
        ):
            return self._domain_policy_result(
                status="invalid",
                reason="trusted_domain_policy_reasons_invalid",
            )
        status = context.get("status")
        if status in {"missing", "invalid"}:
            if any(
                context.get(key)
                for key in (
                    "pack_ref",
                    "pack_schema_version",
                    "pack_content_sha256",
                )
            ):
                return self._domain_policy_result(
                    status="invalid",
                    reason="trusted_domain_policy_unselected_pack_present",
                )
            return self._domain_policy_result(
                status=status,
                reason=(
                    reasons[0]
                    if reasons
                    else f"trusted_domain_policy_context_{status}"
                ),
            )
        if status != "selected" or not any(binding_summary.values()):
            return self._domain_policy_result(
                status="invalid",
                reason="trusted_domain_policy_selection_invalid",
            )
        match = re.fullmatch(
            r"domain-policy:([a-z0-9][a-z0-9_-]{0,63})@(\d+\.\d+\.\d+)",
            str(context.get("pack_ref") or ""),
        )
        content_sha256 = str(context.get("pack_content_sha256") or "")
        if (
            match is None
            or context.get("pack_schema_version") != "domain-policy-pack/v1"
            or not re.fullmatch(r"[0-9a-f]{64}", content_sha256)
            or reasons
        ):
            return self._domain_policy_result(
                status="invalid",
                reason="trusted_domain_policy_selection_invalid",
            )
        domain_id, version = match.groups()
        if context.get("domain_ref") != self._domain_ref(domain_id):
            return self._domain_policy_result(
                status="invalid",
                domain_id=domain_id,
                reason="trusted_domain_policy_domain_ref_mismatch",
            )
        loaded = self._resolve_domain_policy_selector({
            "catalog_metadata": {"domain_policy_id": domain_id},
        })
        if loaded.get("status") != "loaded":
            return loaded
        if (
            loaded.get("version") != version
            or loaded.get("pack_ref") != context.get("pack_ref")
            or loaded.get("pack_content_sha256") != content_sha256
        ):
            return self._domain_policy_result(
                status="invalid",
                domain_id=domain_id,
                reason="trusted_domain_policy_pack_mismatch",
            )
        return loaded

    @staticmethod
    def _domain_policy_selector_reason(context: dict) -> str:
        if not context:
            return ""
        allowed = {"tenant_metadata", "store_metadata", "catalog_metadata"}
        if not set(context).issubset(allowed):
            return "domain_policy_selector_schema_invalid"
        for value in context.values():
            if (
                not isinstance(value, dict)
                or set(value) != {"domain_policy_id"}
                or not isinstance(value.get("domain_policy_id"), str)
            ):
                return "domain_policy_selector_schema_invalid"
        return ""

    @staticmethod
    def _domain_ref(domain_id: str) -> str:
        if not domain_id:
            return ""
        return "domain-" + hashlib.sha256(
            domain_id.encode("utf-8")
        ).hexdigest()[:20]

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
            "pack_ref": "",
            "pack_content_sha256": "",
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
            "allowed_conclusion_family",
            "allowed_variability_factor_families",
            "advice_mode",
            "maximum_risk_level",
            "required_qualifiers",
            "prohibited_claim_families",
            "review_only",
        }
        optional_inference_keys = {
            "canonical_claim_types",
            "unmapped_semantic_keys",
        }
        identifier_pattern = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}")
        for policy in inference_policies:
            if (
                not isinstance(policy, dict)
                or not inference_keys.issubset(policy)
                or not set(policy).issubset(
                    inference_keys | optional_inference_keys
                )
            ):
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
            premise_families = policy.get("premise_fact_families")
            if (
                not isinstance(premise_families, list)
                or len(premise_families) != len(set(premise_families))
                or any(
                    not isinstance(value, str)
                    or not identifier_pattern.fullmatch(value)
                    for value in premise_families
                )
                or (
                    not premise_families
                    and policy.get("advice_mode")
                    != "safety_handoff_required"
                )
            ):
                return "domain_policy_bounded_inference_values_invalid"
            variability_factors = policy.get(
                "allowed_variability_factor_families"
            )
            if (
                not isinstance(variability_factors, list)
                or len(variability_factors)
                != len(set(variability_factors))
                or any(
                    not isinstance(value, str)
                    or not identifier_pattern.fullmatch(value)
                    for value in variability_factors
                )
            ):
                return "domain_policy_bounded_inference_factors_invalid"
            if not identifier_pattern.fullmatch(
                str(policy.get("allowed_scope") or "")
            ):
                return "domain_policy_bounded_inference_scope_invalid"
            if not identifier_pattern.fullmatch(
                str(policy.get("allowed_conclusion_family") or "")
            ):
                return "domain_policy_bounded_inference_conclusion_invalid"
            if policy.get("advice_mode") not in {
                "none",
                "concise_care_only",
                "safety_handoff_required",
            }:
                return "domain_policy_bounded_inference_advice_invalid"
            if policy.get("maximum_risk_level") not in {"low", "medium"}:
                return "domain_policy_bounded_inference_risk_invalid"
            if policy.get("review_only") is not True:
                return "domain_policy_bounded_inference_review_only_required"
            canonical_claim_types = policy.get(
                "canonical_claim_types", []
            )
            if (
                not isinstance(canonical_claim_types, list)
                or len(canonical_claim_types)
                != len(set(canonical_claim_types))
                or any(
                    not isinstance(value, str)
                    or not identifier_pattern.fullmatch(value)
                    or value not in policies
                    for value in canonical_claim_types
                )
            ):
                return "domain_policy_canonical_claim_types_invalid"
            unmapped_semantic_keys = policy.get(
                "unmapped_semantic_keys", []
            )
            if (
                not isinstance(unmapped_semantic_keys, list)
                or len(unmapped_semantic_keys)
                != len(set(unmapped_semantic_keys))
                or any(
                    not isinstance(value, str)
                    or not identifier_pattern.fullmatch(value)
                    for value in unmapped_semantic_keys
                )
            ):
                return "domain_policy_unmapped_semantic_keys_invalid"
        return ""
