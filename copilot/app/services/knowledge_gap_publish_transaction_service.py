"""Standard transaction plans for knowledge gap publish queue handoff.

The plans are execution contracts for a future formal publisher. This module
does not write formal tables and always returns publish_enabled=False.
"""

from __future__ import annotations

from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


PLAN_VERSION = "v1"
PUBLISH_ENABLED = False
COMMON_PRECONDITIONS = [
    "fingerprint_locked",
    "approved_to_publish",
    "dry_run_passed",
    "pre_publish_retest_passed",
]


def _clean_dict(value: Any) -> dict[str, Any]:
    return sanitize_obj(value) if isinstance(value, dict) else {}


def _field_names(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [sanitize_text(key) for key in value if sanitize_text(key)]
    if isinstance(value, list):
        return [sanitize_text(item) for item in value if sanitize_text(item)]
    return []


def _first_text(*values: Any) -> str:
    for value in values:
        text = sanitize_text(value)
        if text:
            return text
    return ""


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    product_identity = payload.get("product_identity")
    result = dict(product_identity) if isinstance(product_identity, dict) else {}
    for source, target in [
        ("item_id", "item_id"),
        ("i_id", "item_id"),
        ("sku", "sku_code"),
        ("sku_code", "sku_code"),
        ("bind_to_sku", "sku_code"),
        ("bind_to_item_id", "item_id"),
        ("product_title", "product_title"),
    ]:
        if _first_text(payload.get(source)) and not _first_text(result.get(target)):
            result[target] = payload.get(source)
    return sanitize_obj(result)


def _rollback(strategy: str, reason: str) -> dict[str, str]:
    return {"strategy": sanitize_text(strategy), "reason": sanitize_text(reason)}


def _validate_step(step_id: str, *, match_key: str = "", fields: list[str] | None = None) -> dict[str, Any]:
    return sanitize_obj({
        "step_id": step_id,
        "operation": "validate",
        "target_table": None,
        "match_key": sanitize_text(match_key),
        "fields": fields or [],
        "preconditions": [],
        "rollback": _rollback("none", "validation step"),
    })


def _write_step(
    step_id: str,
    *,
    operation: str,
    target_table: str,
    match_key: str,
    fields: list[str],
    rollback_strategy: str = "manual_review_required",
    rollback_reason: str = "formal write disabled in MVP",
) -> dict[str, Any]:
    return sanitize_obj({
        "step_id": step_id,
        "operation": operation,
        "target_table": target_table,
        "match_key": sanitize_text(match_key),
        "fields": fields,
        "preconditions": COMMON_PRECONDITIONS,
        "rollback": _rollback(rollback_strategy, rollback_reason),
    })


def _capability(target: str, reason: str = "formal publish adapter not enabled") -> dict[str, Any]:
    return sanitize_obj({
        "target": sanitize_text(target),
        "supports_formal_publish": False,
        "supports_rollback": False,
        "publish_enabled": PUBLISH_ENABLED,
        "required_checks": COMMON_PRECONDITIONS,
        "reason": reason,
    })


class KnowledgeGapPublishTransactionService:
    def capabilities(self) -> dict[str, Any]:
        targets = {
            target: _capability(target)
            for target in [
                "product_profile",
                "kb_product",
                "kb_media_asset",
                "activity_rules",
                "aftersales_policy",
            ]
        }
        targets["context_extractor"] = _capability(
            "context_extractor",
            "engineering task cannot publish to knowledge store",
        )
        return sanitize_obj({
            "plan_version": PLAN_VERSION,
            "publish_enabled": PUBLISH_ENABLED,
            "writes_formal_tables": False,
            "targets": targets,
        })

    def build_plan(self, queue_item) -> dict[str, Any]:
        target = sanitize_text(getattr(queue_item, "publish_target", ""))
        payload = _clean_dict(queue_item.get_payload())
        steps: list[dict[str, Any]]
        block_reasons: list[str] = []
        warnings: list[str] = []
        capability = _capability(target)

        if target == "product_profile":
            steps = self._product_profile_steps(payload)
        elif target == "kb_product":
            steps = self._kb_product_steps(payload)
        elif target == "kb_media_asset":
            steps, block_reasons, capability = self._media_asset_steps(payload)
        elif target == "activity_rules":
            steps = self._activity_rules_steps(payload)
        elif target == "aftersales_policy":
            steps = self._aftersales_policy_steps(payload)
        elif target == "context_extractor":
            steps = [
                _validate_step("engineering_task_plan", match_key=sanitize_text(getattr(queue_item, "task_uid", "")))
            ]
            block_reasons = ["engineering task cannot publish to knowledge store"]
            capability = _capability(target, "engineering task cannot publish to knowledge store")
        else:
            steps = [_validate_step("validate_publish_target", match_key=target)]
            block_reasons = ["unsupported publish target"]
            capability = _capability(target, "unsupported publish target")

        plan = {
            "plan_version": PLAN_VERSION,
            "mode": "simulation",
            "writes_formal_tables": False,
            "publish_enabled": PUBLISH_ENABLED,
            "publish_target": target,
            "queue_uid": sanitize_text(getattr(queue_item, "queue_uid", "")),
            "payload_fingerprint": sanitize_text(getattr(queue_item, "payload_fingerprint", "")),
            "locked_payload_fingerprint": sanitize_text(getattr(queue_item, "locked_payload_fingerprint", "")),
            "requires_transaction": True,
            "requires_pre_publish_gate": True,
            "requires_post_publish_retest": True,
            "rollback_supported": False,
            "adapter_capability": capability,
            "steps": steps,
            "block_reasons": block_reasons,
            "warnings": warnings,
        }
        return sanitize_obj(plan)

    def validate_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        if sanitize_text(plan.get("plan_version")) != PLAN_VERSION:
            errors.append("plan_version must be v1")
        if sanitize_text(plan.get("mode")) != "simulation":
            errors.append("mode must be simulation")
        if plan.get("writes_formal_tables") is not False:
            errors.append("writes_formal_tables must be false")
        if plan.get("publish_enabled") is not False:
            errors.append("publish_enabled must be false")
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append("steps are required")
        else:
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    errors.append(f"step {index} must be an object")
                    continue
                if not sanitize_text(step.get("step_id")):
                    errors.append(f"step {index} missing step_id")
                if not sanitize_text(step.get("operation")):
                    errors.append(f"step {index} missing operation")
                if "rollback" not in step or not isinstance(step.get("rollback"), dict):
                    errors.append(f"step {index} missing rollback")
                elif not sanitize_text(step["rollback"].get("strategy")):
                    errors.append(f"step {index} missing rollback strategy")
        capability = plan.get("adapter_capability")
        if not isinstance(capability, dict):
            errors.append("adapter_capability is required")
        elif capability.get("supports_formal_publish") is not False:
            errors.append("adapter_capability.supports_formal_publish must be false")
        return sanitize_obj({
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
        })

    def _product_profile_steps(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        identity = _identity(payload)
        match_key = _first_text(identity.get("item_id"), identity.get("sku_code"), identity.get("product_title"))
        fields = _field_names(payload.get("fields"))
        return [
            _validate_step("validate_product_identity", match_key=match_key, fields=_field_names(identity)),
            _write_step(
                "upsert_product_profile",
                operation="upsert",
                target_table="kb_product",
                match_key=match_key,
                fields=fields,
            ),
        ]

    def _kb_product_steps(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        identity = _identity(payload)
        fields = [
            key for key in ["fact_type", "evidence_text", "source_reference"]
            if _first_text(payload.get(key))
        ]
        return [
            _validate_step("validate_fact_payload", match_key="product_identity + fact_type", fields=_field_names(identity)),
            _write_step(
                "upsert_product_fact",
                operation="create_or_update_fact",
                target_table="kb_product_facts",
                match_key="product_identity + fact_type",
                fields=fields,
            ),
        ]

    def _media_asset_steps(self, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
        asset_key = _first_text(payload.get("uploaded_asset_id"), payload.get("asset_url"))
        if not asset_key:
            return (
                [
                    _validate_step("validate_media_asset_request", match_key=_first_text(payload.get("bind_to_sku"))),
                    _write_step(
                        "create_media_upload_request",
                        operation="create_media_asset_request",
                        target_table="kb_media_asset_requests",
                        match_key=_first_text(payload.get("bind_to_sku")),
                        fields=_field_names(payload),
                    ),
                ],
                ["media asset missing uploaded_asset_id or asset_url"],
                _capability("kb_media_asset", "media asset upload is required before formal publish"),
            )
        return (
            [
                _validate_step("validate_media_asset", match_key=asset_key),
                _write_step(
                    "upsert_media_asset",
                    operation="upsert_media_asset",
                    target_table="kb_media_asset",
                    match_key=asset_key,
                    fields=[
                        key for key in [
                            "asset_type",
                            "media_purpose",
                            "bind_to_sku",
                            "uploaded_asset_id",
                            "asset_url",
                        ]
                        if _first_text(payload.get(key))
                    ],
                    rollback_strategy="remove_or_disable_asset_manual_review",
                ),
            ],
            [],
            _capability("kb_media_asset"),
        )

    def _activity_rules_steps(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        match_key = _first_text(payload.get("platform"), payload.get("promotion_scope"), payload.get("time_scope"))
        return [
            _validate_step("validate_activity_scope", match_key=match_key),
            _write_step(
                "upsert_activity_rule",
                operation="upsert_activity_rule",
                target_table="activity_rules",
                match_key=match_key,
                fields=[
                    key for key in ["platform", "time_scope", "promotion_scope", "rule_text"]
                    if payload.get(key) is not None
                ],
            ),
        ]

    def _aftersales_policy_steps(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        match_key = _first_text(payload.get("scenario"), payload.get("policy_code"))
        return [
            _validate_step("validate_policy_scope", match_key=match_key),
            _write_step(
                "upsert_aftersales_policy",
                operation="upsert_policy_rule",
                target_table="aftersales_policy",
                match_key=match_key,
                fields=[
                    key for key in [
                        "scenario",
                        "policy_text",
                        "required_customer_inputs",
                        "allowed_actions",
                        "escalation_boundary",
                    ]
                    if payload.get(key) is not None
                ],
            ),
        ]
