from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AnalyzerResult:
    name: str
    status: str = "success"
    duration_ms: int = 0
    confidence: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SafetyContract:
    forbidden_claims: list[str] = field(default_factory=list)
    requires_evidence_for: list[str] = field(default_factory=list)
    must_escalate_if: list[str] = field(default_factory=list)
    allowed_fact_sources: list[str] = field(default_factory=list)
    forbidden_reply_patterns: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParallelUnderstandingResult:
    intent_classifier: dict[str, Any] = field(default_factory=dict)
    risk_classifier: dict[str, Any] = field(default_factory=dict)
    slot_entity_extractor: dict[str, Any] = field(default_factory=dict)
    context_resolver: dict[str, Any] = field(default_factory=dict)
    customer_state_analyzer: dict[str, Any] = field(default_factory=dict)
    tool_need_predictor: dict[str, Any] = field(default_factory=dict)
    knowledge_scope_predictor: dict[str, Any] = field(default_factory=dict)
    safety_precheck: dict[str, Any] = field(default_factory=dict)
    analyzer_durations: dict[str, int] = field(default_factory=dict)
    overall_status: str = "success"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionFusionResult:
    final_intent: str = "general"
    secondary_intents: list[str] = field(default_factory=list)
    risk_level: str = "low"
    risk_reasons: list[str] = field(default_factory=list)
    need_human_review: bool = False
    answer_mode: str = ""
    reply_goal: str = ""
    required_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    allowed_source_types: list[str] = field(default_factory=list)
    forbidden_source_types: list[str] = field(default_factory=list)
    safety_contract: dict[str, Any] = field(default_factory=dict)
    customer_concern: str = ""
    missing_slots: list[str] = field(default_factory=list)
    fusion_reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "success"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
