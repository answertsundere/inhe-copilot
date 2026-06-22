"""Central tool policy definitions.

These policies describe when a tool may run. They are not customer reply
strategy and should be evaluated against structured agent context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


POLICY_VERSION = "tool-policy-v1"

READ_ONLY_LOW_RISK = "read_only_low_risk"
READ_ONLY_SENSITIVE = "read_only_sensitive"
WRITE_OR_SIDE_EFFECT = "write_or_side_effect"


@dataclass(frozen=True)
class ToolPolicy:
    tool_name: str
    risk_level: str
    allowed_intents: tuple[str, ...] = ()
    allowed_fact_types: tuple[str, ...] = ()
    required_entities: tuple[str, ...] = ()
    denied_when: tuple[str, ...] = ()
    timeout_ms: int = 3000
    max_calls_per_request: int = 1
    audit_required: bool = True
    pii_allowed: bool = False
    evidence_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "risk_level": self.risk_level,
            "allowed_intents": list(self.allowed_intents),
            "allowed_fact_types": list(self.allowed_fact_types),
            "required_entities": list(self.required_entities),
            "denied_when": list(self.denied_when),
            "timeout_ms": self.timeout_ms,
            "max_calls_per_request": self.max_calls_per_request,
            "audit_required": self.audit_required,
            "pii_allowed": self.pii_allowed,
            "evidence_required": self.evidence_required,
        }


ORDER_INTENTS = (
    "logistics_eta",
    "logistics_trace",
    "delivery_not_received",
    "shipping",
    "logistics",
    "aftersales",
)

PRODUCT_INTENTS = (
    "product_question",
    "installation",
    "cleaning_care",
    "stock_query",
    "complaint",
    "aftersales",
)

MEDIA_FACT_TYPES = (
    "visual_asset",
    "installation",
    "accessories",
    "packaging",
    "dimensions",
    "space_fit",
    "detachable",
    "certification_report",
)

ACTIVITY_FACT_TYPES = ("promotion_policy", "price_protection", "gift_policy")


TOOL_POLICIES: dict[str, ToolPolicy] = {
    "jst_lookup_order_tool": ToolPolicy(
        tool_name="jst_lookup_order_tool",
        risk_level=READ_ONLY_SENSITIVE,
        allowed_intents=ORDER_INTENTS,
        required_entities=("order_entity",),
        timeout_ms=3000,
        pii_allowed=True,
        evidence_required=True,
    ),
    "jst_lookup_outbound_tool": ToolPolicy(
        tool_name="jst_lookup_outbound_tool",
        risk_level=READ_ONLY_SENSITIVE,
        allowed_intents=("logistics_eta", "logistics_trace", "delivery_not_received"),
        required_entities=("order_entity",),
        timeout_ms=3000,
        pii_allowed=True,
        evidence_required=True,
    ),
    "jst_lookup_tracking_tool": ToolPolicy(
        tool_name="jst_lookup_tracking_tool",
        risk_level=READ_ONLY_SENSITIVE,
        allowed_intents=("logistics_eta", "logistics_trace", "delivery_not_received", "logistics"),
        required_entities=("tracking_entity",),
        timeout_ms=3000,
        pii_allowed=True,
        evidence_required=True,
    ),
    "rag_search_tool": ToolPolicy(
        tool_name="rag_search_tool",
        risk_level=READ_ONLY_LOW_RISK,
        allowed_intents=PRODUCT_INTENTS + ORDER_INTENTS,
        required_entities=("product_or_query",),
        timeout_ms=2000,
        evidence_required=True,
    ),
    "product_resolver_tool": ToolPolicy(
        tool_name="product_resolver_tool",
        risk_level=READ_ONLY_LOW_RISK,
        allowed_intents=PRODUCT_INTENTS + ORDER_INTENTS,
        required_entities=("message",),
        timeout_ms=1000,
    ),
    "sop_lookup_tool": ToolPolicy(
        tool_name="sop_lookup_tool",
        risk_level=READ_ONLY_LOW_RISK,
        allowed_intents=("complaint", "aftersales", "delivery_not_received"),
        required_entities=("message",),
        timeout_ms=1000,
        audit_required=True,
        evidence_required=True,
    ),
    "template_select_tool": ToolPolicy(
        tool_name="template_select_tool",
        risk_level=READ_ONLY_LOW_RISK,
        allowed_intents=(),
        required_entities=("message",),
        timeout_ms=500,
    ),
    "media_asset_recommend_tool": ToolPolicy(
        tool_name="media_asset_recommend_tool",
        risk_level=READ_ONLY_LOW_RISK,
        allowed_intents=PRODUCT_INTENTS,
        allowed_fact_types=MEDIA_FACT_TYPES,
        required_entities=("product_entity",),
        timeout_ms=1000,
        evidence_required=True,
    ),
    "activity_rule_lookup_tool": ToolPolicy(
        tool_name="activity_rule_lookup_tool",
        risk_level=READ_ONLY_SENSITIVE,
        allowed_intents=("stock_query", "product_question"),
        allowed_fact_types=ACTIVITY_FACT_TYPES,
        required_entities=("product_entity",),
        timeout_ms=1000,
        evidence_required=True,
    ),
    "send_message_tool": ToolPolicy(
        tool_name="send_message_tool",
        risk_level=WRITE_OR_SIDE_EFFECT,
        allowed_intents=(),
        denied_when=("write_tool_not_enabled",),
        timeout_ms=3000,
        max_calls_per_request=0,
        audit_required=True,
        pii_allowed=True,
    ),
}


def get_tool_policy(tool_name: str) -> ToolPolicy:
    name = str(tool_name or "")
    if name in TOOL_POLICIES:
        return TOOL_POLICIES[name]

    write_markers = ("send", "update", "write", "publish", "refresh", "delete", "create")
    if any(marker in name.lower() for marker in write_markers):
        return ToolPolicy(
            tool_name=name,
            risk_level=WRITE_OR_SIDE_EFFECT,
            denied_when=("unknown_write_tool_policy",),
            max_calls_per_request=0,
            audit_required=True,
        )

    return ToolPolicy(
        tool_name=name,
        risk_level=READ_ONLY_LOW_RISK,
        audit_required=True,
    )


def all_tool_policies() -> dict[str, ToolPolicy]:
    return dict(TOOL_POLICIES)
