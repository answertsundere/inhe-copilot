"""One authoritative post-graph pipeline for every analysis entry point."""

from __future__ import annotations

import os
import re
import time
from collections.abc import MutableMapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


PIPELINE_VERSION = "analysis-pipeline-v1"
PIPELINE_COMPOSER_ENTRY_DIAGNOSTICS_SCHEMA = (
    "analysis-pipeline-composer-entry-diagnostics/v1"
)
PIPELINE_COMPOSER_ENTRY_DIAGNOSTICS_OWNER = "analysis_pipeline"
_FORMAL_DECISION_FIELDS = (
    "suggested_reply",
    "draft_reply",
    "sendable_reply",
    "can_send",
    "requires_human_review",
    "reply_status",
    "block_reasons",
    "recommended_assets",
    "reply_blocks",
    "reply_delivery",
    "final_answer_audit",
    "final_semantic_fit_audit",
)
_IMAGE_MARKER_RE = re.compile(r"\[\s*图片\d*\s*\]")
_TEXT_PRODUCT_QUESTION_TERMS = (
    "吗", "呢", "怎么", "如何", "可以", "能不能", "是不是", "有没有", "会不会",
    "可拆", "拆卸", "安装", "组装", "材质", "承重", "尺寸", "清洗", "防潮",
)
_VISUAL_FACT_TYPES = {"installation", "detachable", "dimensions", "space_fit", "accessories", "packaging"}
_SERVICE_OR_ORDER_FACT_TYPES = {
    "aftersales_policy",
    "gift_policy",
    "invoice_policy",
    "logistics",
    "order_status",
    "price_protection",
    "promotion_policy",
    "return_pickup",
    "stock_shipping",
    "after_sales",
    "aftersales",
}
_VISUAL_TERMS = (
    "图片", "照片", "实物图", "商品图", "尺寸图", "视频", "安装图", "安装视频",
    "配件图", "打包图", "说明书",
)
_MEDIA_PROMISE_TERMS = (
    "发安装视频", "发视频", "发图", "图片发您", "参考我下面发您的图片或视频",
    "下面发您的图片或视频", "图片/视频资料", "图片或视频",
)


def _diagnostic_alias(value: Any, *, prefix: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    from app.services.formal_knowledge_database_guard_service import (
        formal_kb_audit_hmac_key,
    )
    from app.services.high_quality_long_conversation_review_service import (
        stable_evaluation_alias,
    )

    secret = formal_kb_audit_hmac_key()
    if not secret:
        raise ValueError("diagnostic_alias_key_required")
    return stable_evaluation_alias(
        prefix,
        text,
        alias_secret=secret,
    )


def _composer_entry_diagnostic_base(
    sink: MutableMapping[str, Any] | None,
) -> dict[str, Any]:
    request_alias = ""
    case_alias = ""
    diagnostics_error_code = ""
    if isinstance(sink, MutableMapping):
        try:
            request_alias = _diagnostic_alias(
                sink.get("request_alias"),
                prefix="request",
            )
            case_alias = _diagnostic_alias(
                sink.get("case_alias"),
                prefix="case",
            )
        except Exception:
            request_alias = ""
            case_alias = ""
            diagnostics_error_code = "diagnostic_alias_unavailable"
    return {
        "schema_version": PIPELINE_COMPOSER_ENTRY_DIAGNOSTICS_SCHEMA,
        "owner": PIPELINE_COMPOSER_ENTRY_DIAGNOSTICS_OWNER,
        "request_alias": request_alias,
        "case_alias": case_alias,
        "pipeline_entered": False,
        "pipeline_completed": False,
        "graph_completed": False,
        "response_shape_valid": False,
        "understanding_status": "not_observed",
        "authoritative_customer_goal_count": 0,
        "requested_claim_count": 0,
        "claim_resolution_count": 0,
        "selected_evidence_count": 0,
        "admitted_evidence_count": 0,
        "trusted_domain_pack_status": "not_observed",
        "formal_evidence_convergence_enabled": False,
        "model_first_answer_composer_enabled": False,
        "bounded_inference_shadow_enabled": False,
        "minimal_context_attempted": False,
        "minimal_context_completed": False,
        "renderable_customer_goal_count": 0,
        "composer_service_available": False,
        "composer_service_check_status": "not_checked",
        "composer_entry_eligible": False,
        "composer_invocation_attempted": False,
        "composer_invocation_completed": False,
        "exact_reason_code": "pipeline_not_started",
        "downstream_stage": "not_started",
        "diagnostics_error_code": diagnostics_error_code,
        "pipeline_elapsed_ms": 0,
        "used_for_final_reply": False,
        "used_as_evidence": False,
        "can_change_can_send": False,
        "can_change_model_call_count": False,
    }


def _initialize_composer_entry_diagnostics(
    sink: MutableMapping[str, Any] | None,
) -> None:
    if not isinstance(sink, MutableMapping):
        return
    try:
        value = _composer_entry_diagnostic_base(sink)
        sink.clear()
        sink.update(value)
    except Exception:
        return


def _update_composer_entry_diagnostics(
    sink: MutableMapping[str, Any] | None,
    **values: Any,
) -> None:
    if not isinstance(sink, MutableMapping):
        return
    try:
        prepared = deepcopy(values)
        if "exact_reason_code" in prepared:
            current_reason = str(
                sink.get("exact_reason_code") or ""
            )
            if current_reason not in {
                "",
                "pipeline_not_started",
                "pipeline_entered",
                "composer_invocation_attempted",
            }:
                prepared.pop("exact_reason_code", None)
        sink.update(prepared)
    except Exception:
        try:
            sink["diagnostics_error_code"] = (
                "diagnostics_sink_update_failed"
            )
        except Exception:
            return


def _composer_entry_diagnostic_reason(
    sink: MutableMapping[str, Any] | None,
) -> str:
    if not isinstance(sink, MutableMapping):
        return ""
    try:
        return str(sink.get("exact_reason_code") or "")
    except Exception:
        return ""


def _composer_entry_diagnostic_flag(
    sink: MutableMapping[str, Any] | None,
    key: str,
) -> bool:
    if not isinstance(sink, MutableMapping):
        return False
    try:
        return sink.get(key) is True
    except Exception:
        return False


def _diagnostic_rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


@dataclass(frozen=True)
class AnalysisPipelineRequest:
    customer_message: str
    reply_service: Any
    order_id: str = ""
    tracking_no: str = ""
    conversation_id: str = "default"
    product_name: str = ""
    product_candidates: list[dict[str, Any]] = field(default_factory=list)
    copilot_context: dict[str, Any] = field(default_factory=dict)
    image_attachments: list[dict[str, Any]] = field(default_factory=list)
    source: str = "api"
    scenario: str = ""
    delivery_message: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    trusted_answer_eligibility_context: dict[str, Any] = field(
        default_factory=dict
    )
    composer_entry_diagnostics_sink: MutableMapping[str, Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    composer_privacy_diagnostics_sink: MutableMapping[str, Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )


class AnalysisPipelineService:
    """Run graph, delivery preparation, final response, shadow, then persistence."""

    def run(self, request: AnalysisPipelineRequest) -> dict[str, Any]:
        from app.services.analysis_execution_service import execute_analysis

        sink = (
            request.composer_entry_diagnostics_sink
            if isinstance(
                request.composer_entry_diagnostics_sink,
                MutableMapping,
            )
            else None
        )
        started = time.perf_counter() if sink is not None else None
        if sink is not None:
            _initialize_composer_entry_diagnostics(sink)
            _update_composer_entry_diagnostics(
                sink,
                pipeline_entered=True,
                downstream_stage="canonical_input",
                exact_reason_code="pipeline_entered",
            )
        try:
            try:
                prepared = self._prepare_request(request)
            except Exception as exc:
                from app.services.canonical_conversation_turn_service import ConversationContextContractError
                if isinstance(exc, ConversationContextContractError):
                    if sink is not None:
                        _update_composer_entry_diagnostics(
                            sink,
                            pipeline_completed=True,
                            exact_reason_code="canonical_conversation_invalid",
                            downstream_stage="canonical_input_blocked",
                        )
                    return self._invalid_conversation_context_response(
                        request,
                        exc.reason,
                    )
                if sink is not None:
                    _update_composer_entry_diagnostics(
                        sink,
                        exact_reason_code="pipeline_prepare_failed",
                        downstream_stage="canonical_input_failed",
                    )
                raise
            readiness = self._knowledge_readiness_for_request(prepared)
            if readiness is not None and not readiness["ready"]:
                if sink is not None:
                    _update_composer_entry_diagnostics(
                        sink,
                        pipeline_completed=True,
                        exact_reason_code="runtime_knowledge_not_ready",
                        downstream_stage="runtime_readiness_blocked",
                    )
                return self._runtime_not_ready_response(prepared, readiness)

            def complete_graph_response(
                graph_response: dict[str, Any],
            ) -> dict[str, Any]:
                if sink is not None:
                    _update_composer_entry_diagnostics(
                        sink,
                        graph_completed=True,
                        response_shape_valid=isinstance(graph_response, dict),
                        downstream_stage="graph_completed",
                        **(
                            {}
                            if isinstance(graph_response, dict)
                            else {
                                "exact_reason_code": (
                                    "graph_response_shape_invalid"
                                )
                            }
                        ),
                    )
                try:
                    return self._complete_response(graph_response, prepared)
                except Exception:
                    if sink is not None:
                        _update_composer_entry_diagnostics(
                            sink,
                            exact_reason_code="pipeline_post_processor_failed",
                            downstream_stage="pipeline_post_processor_failed",
                        )
                    raise

            try:
                response = execute_analysis(
                    reply_service=prepared.reply_service,
                    customer_message=prepared.customer_message,
                    order_id=prepared.order_id,
                    tracking_no=prepared.tracking_no,
                    conversation_id=prepared.conversation_id,
                    product_name=prepared.product_name,
                    product_candidates=prepared.product_candidates,
                    copilot_context=prepared.copilot_context,
                    image_attachments=prepared.image_attachments,
                    source=prepared.source,
                    scenario=prepared.scenario,
                    final_orchestration=False,
                    response_post_processor=complete_graph_response,
                )
            except Exception:
                if (
                    sink is not None
                    and _composer_entry_diagnostic_reason(sink)
                    != "pipeline_post_processor_failed"
                ):
                    _update_composer_entry_diagnostics(
                        sink,
                        exact_reason_code="graph_execution_failed",
                        downstream_stage="graph_execution_failed",
                    )
                raise
            if sink is not None:
                if not _composer_entry_diagnostic_flag(
                    sink,
                    "graph_completed",
                ):
                    _update_composer_entry_diagnostics(
                        sink,
                        exact_reason_code="graph_completion_not_observed",
                        downstream_stage="graph_completion_unknown",
                    )
                _update_composer_entry_diagnostics(
                    sink,
                    pipeline_completed=True,
                    downstream_stage="pipeline_completed",
                )
            return response
        finally:
            if sink is not None and started is not None:
                _update_composer_entry_diagnostics(
                    sink,
                    pipeline_elapsed_ms=max(
                        0,
                        int((time.perf_counter() - started) * 1000),
                    ),
                )

    @staticmethod
    def _knowledge_readiness_for_request(request: AnalysisPipelineRequest) -> dict[str, Any] | None:
        context = request.copilot_context or {}
        has_product_scope = bool(
            request.product_name
            or request.product_candidates
            or any(context.get(key) for key in ("product_id", "i_id", "sku_code", "product_name", "product_candidates"))
        )
        if not has_product_scope:
            return None
        query_fact_type = AnalysisPipelineService._request_query_fact_type(request)
        if query_fact_type in _SERVICE_OR_ORDER_FACT_TYPES:
            return None
        from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService

        return RuntimeKnowledgeReadinessService().inspect()

    @staticmethod
    def _request_query_fact_type(request: AnalysisPipelineRequest) -> str:
        """Reuse the existing turn-understanding contract before readiness gating."""
        context = request.copilot_context or {}
        understanding = context.get("turn_understanding") or {}
        explicit = (
            context.get("query_fact_type")
            or context.get("benchmark_query_fact_type")
            or understanding.get("effective_query_fact_type")
            or understanding.get("query_fact_type")
            or understanding.get("expected_query_fact_type")
        )
        if explicit:
            return str(explicit).strip()

        from app.services.fact_type_service import classify_query_fact_type

        classified = classify_query_fact_type(request.customer_message)
        return str(classified.get("query_fact_type") or "").strip()

    @staticmethod
    def _runtime_not_ready_response(
        request: AnalysisPipelineRequest,
        readiness: dict[str, Any],
    ) -> dict[str, Any]:
        reasons = list(readiness.get("reasons") or ["knowledge_db_unavailable"])
        stages = list((request.copilot_context or {}).get("analysis_pipeline_input_stages") or [])
        stages.append({"stage": "runtime_readiness", "status": "blocked", "reasons": reasons})
        pipeline = {
            "version": PIPELINE_VERSION,
            "stages": stages,
            "final_orchestration_completed": False,
            "capabilities": dict(request.capabilities or {}),
        }
        return {
            "suggested_reply": "",
            "draft_reply": "",
            "sendable_reply": "",
            "can_send": False,
            "requires_human_review": True,
            "reply_status": "needs_human_review",
            "reply_blocks": [],
            "reply_delivery": {"mode": "blocked", "auto_send_ready": False, "reason": "runtime_not_ready"},
            "recommended_assets": [],
            "block_reasons": ["runtime_not_ready", *reasons],
            "trace_response_stage": "pre_final",
            "final_response_pipeline_version": "",
            "analysis_pipeline": pipeline,
            "evidence_debug": {
                "runtime_not_ready": True,
                "knowledge_db_unavailable": reasons,
                "runtime_readiness": readiness,
                "analysis_pipeline": pipeline,
            },
            "trace_steps": [{
                "node": "analysis_pipeline",
                "status": "blocked",
                "summary": "knowledge runtime readiness blocked product-scoped analysis",
                "reasons": reasons,
            }],
        }

    def _prepare_request(self, request: AnalysisPipelineRequest) -> AnalysisPipelineRequest:
        context = dict(request.copilot_context or {})
        from app.services.canonical_conversation_turn_service import (
            ConversationContextContractError,
            is_strict_evaluation_source,
            normalize_trusted_answer_eligibility_owner_context,
            normalize_conversation_turns,
        )

        context.pop("_answer_eligibility_owner_context", None)
        public_understanding = context.pop("turn_understanding", None)
        if isinstance(public_understanding, dict):
            removed = sorted(str(key) for key in public_understanding)
            if removed:
                context.setdefault("pipeline_diagnostics", []).append({
                    "stage": "canonical_input",
                    "type": "public_turn_understanding_removed",
                    "fields": removed,
                })
        raw_trusted_context = request.trusted_answer_eligibility_context
        raw_trusted_context = (
            raw_trusted_context
            if isinstance(raw_trusted_context, dict)
            else {}
        )
        normalized_owner_context = (
            normalize_trusted_answer_eligibility_owner_context(
                raw_trusted_context
            )
        )
        invalid_owner_reason = ""
        if raw_trusted_context and not normalized_owner_context:
            invalid_owner_reason = (
                "answer_eligibility_owner_context_invalid"
            )
            owner_source = "server_configuration"
            domain_selector: dict[str, Any] = {}
        elif normalized_owner_context:
            owner_source = str(
                normalized_owner_context.get("source") or ""
            )
            domain_selector = dict(
                normalized_owner_context.get("domain_policy_context")
                or {}
            )
        else:
            owner_source = "server_configuration"
            configured_domain_policy_id = str(
                os.getenv("COPILOT_DOMAIN_POLICY_ID", "")
            ).strip()
            domain_selector = (
                {
                    "catalog_metadata": {
                        "domain_policy_id": configured_domain_policy_id,
                    },
                }
                if configured_domain_policy_id
                else {}
            )
        from app.repositories.file_policy_repository import (
            FilePolicyRepository,
        )

        trusted_domain_policy_context = (
            FilePolicyRepository().build_trusted_domain_policy_context(
                domain_selector,
                selection_source=owner_source,
                invalid_reason=invalid_owner_reason,
            )
        )
        trusted_eligibility_context = {
            "schema_version": "answer-eligibility-owner-context/v1",
            "source": owner_source,
            "owner": "analysis_pipeline",
            "provenance": {
                "boundary": "analysis_pipeline_internal",
            },
            "domain_policy_context": trusted_domain_policy_context,
        }
        reference_status = normalized_owner_context.get(
            "conversation_reference_status"
        )
        if isinstance(reference_status, dict):
            trusted_eligibility_context[
                "conversation_reference_status"
            ] = dict(reference_status)
        context["_answer_eligibility_owner_context"] = (
            trusted_eligibility_context
        )
        strict_context = is_strict_evaluation_source(request.source, context)
        upstream_diagnostics = context.get("conversation_context_contract")
        upstream_diagnostics = dict(upstream_diagnostics) if isinstance(upstream_diagnostics, dict) else {}
        upstream_status = str(upstream_diagnostics.get("status") or "").strip().lower()
        upstream_reason = str(upstream_diagnostics.get("original_reason") or upstream_diagnostics.get("reason") or "").strip()
        if strict_context and upstream_status in {"degraded", "invalid"}:
            raise ConversationContextContractError(upstream_reason or "conversation_context_upstream_invalid")
        turns, turn_diagnostics = normalize_conversation_turns(
            context.get("conversation_history"), strict=strict_context,
        )
        if upstream_status in {"degraded", "invalid"}:
            turn_diagnostics = {
                **upstream_diagnostics,
                "status": upstream_status,
                "reason": upstream_reason,
                "original_reason": upstream_reason,
                "upstream_status": upstream_status,
                "pipeline_revalidation_status": turn_diagnostics.get("status"),
                "degraded_context": upstream_status == "degraded",
            }
        context["conversation_history"] = turns
        context["conversation_context_contract"] = turn_diagnostics
        attachments = [dict(item) for item in (request.image_attachments or []) if isinstance(item, dict)]
        stages: list[dict[str, Any]] = [{
            "stage": "canonical_input",
            "status": "completed",
            "source": request.source,
            "conversation_turn_count": len(turns),
            "conversation_context_status": turn_diagnostics["status"],
        }]
        if attachments:
            context["has_image_attachment"] = True
            if self._skip_image_vlm(request, context):
                context["image_analysis_skipped"] = "text_product_question_with_known_context"
                for attachment in attachments:
                    attachment.setdefault("vlm_analysis", {
                        "source": "customer_image_metadata",
                        "skipped": True,
                        "reason": "text_product_question_with_known_context",
                    })
                stages.append({"stage": "image_context", "status": "skipped", "reason": context["image_analysis_skipped"]})
            else:
                try:
                    from app.services.customer_image_vlm_service import analyze_customer_images

                    image_analysis = analyze_customer_images(attachments)
                    if image_analysis:
                        context["image_analysis"] = image_analysis
                        for index, analysis in enumerate(image_analysis):
                            if index < len(attachments) and analysis.get("summary") and not attachments[index].get("description"):
                                attachments[index]["description"] = analysis["summary"]
                            if index < len(attachments):
                                attachments[index]["vlm_analysis"] = analysis
                    stages.append({"stage": "image_context", "status": "completed", "count": len(image_analysis or [])})
                except Exception as exc:
                    context.setdefault("pipeline_diagnostics", []).append({
                        "stage": "image_context", "type": type(exc).__name__, "message": str(exc),
                    })
                    stages.append({"stage": "image_context", "status": "degraded", "reason": type(exc).__name__})
        context["analysis_pipeline_input_stages"] = stages
        return AnalysisPipelineRequest(
            **{**request.__dict__, "copilot_context": context, "image_attachments": attachments}
        )

    @staticmethod
    def _invalid_conversation_context_response(request: AnalysisPipelineRequest, reason: str) -> dict[str, Any]:
        pipeline = {
            "version": PIPELINE_VERSION,
            "stages": [{"stage": "canonical_input", "status": "blocked", "reason": reason, "source": request.source}],
            "final_orchestration_completed": False,
            "capabilities": dict(request.capabilities or {}),
        }
        return {
            "error": "invalid_conversation_context", "error_reason": reason,
            "suggested_reply": "", "draft_reply": "", "sendable_reply": "",
            "can_send": False, "requires_human_review": True, "reply_status": "needs_human_review",
            "block_reasons": ["invalid_conversation_context", reason], "recommended_assets": [], "reply_blocks": [],
            "reply_delivery": {"mode": "blocked", "auto_send_ready": False, "reason": "invalid_conversation_context"},
            "analysis_pipeline": pipeline,
            "evidence_debug": {"conversation_context_contract": {"status": "blocked", "reason": reason}, "analysis_pipeline": pipeline},
            "trace_steps": [{"node": "analysis_pipeline", "status": "blocked", "summary": "invalid canonical conversation context", "reason": reason}],
        }

    @staticmethod
    def _composer_entry_observation(
        response: dict[str, Any],
        request: AnalysisPipelineRequest,
    ) -> dict[str, Any]:
        debug = (
            response.get("evidence_debug")
            if isinstance(response.get("evidence_debug"), dict)
            else {}
        )
        understanding = response.get("turn_understanding")
        if not isinstance(understanding, dict):
            understanding = debug.get("turn_understanding")
        understanding = (
            understanding if isinstance(understanding, dict) else {}
        )
        minimal = response.get("minimal_decision_context")
        if not isinstance(minimal, dict):
            minimal = debug.get("minimal_decision_context")
        minimal = minimal if isinstance(minimal, dict) else {}
        requested_claims = _diagnostic_rows(
            minimal.get("requested_claims")
        ) or _diagnostic_rows(understanding.get("requested_claims"))
        selected_evidence = _diagnostic_rows(
            response.get("selected_evidence")
        ) or _diagnostic_rows(debug.get("selected_evidence"))
        admitted_evidence = _diagnostic_rows(
            minimal.get("admitted_evidence")
            or minimal.get("admitted_direct_facts")
        )
        trusted_pack = minimal.get("trusted_domain_policy_context")
        if not isinstance(trusted_pack, dict):
            owner_context = (request.copilot_context or {}).get(
                "_answer_eligibility_owner_context"
            )
            owner_context = (
                owner_context if isinstance(owner_context, dict) else {}
            )
            trusted_pack = owner_context.get("domain_policy_context")
        trusted_pack = trusted_pack if isinstance(trusted_pack, dict) else {}
        trusted_status = str(trusted_pack.get("status") or "").strip().lower()
        if trusted_status not in {
            "selected",
            "loaded",
            "missing",
            "invalid",
            "blocked",
            "not_selected",
        }:
            trusted_status = "unknown" if trusted_pack else "not_observed"
        return {
            "understanding_status": AnalysisPipelineService
            ._turn_understanding_verdict(response)["status"],
            "authoritative_customer_goal_count": len([
                item
                for item in _diagnostic_rows(
                    understanding.get("customer_goals")
                )
                if str(item.get("goal_kind") or "customer_goal")
                == "customer_goal"
            ]),
            "requested_claim_count": len(requested_claims),
            "claim_resolution_count": len(
                _diagnostic_rows(minimal.get("claim_resolutions"))
            ),
            "selected_evidence_count": len(selected_evidence),
            "admitted_evidence_count": len(admitted_evidence),
            "trusted_domain_pack_status": trusted_status,
            "minimal_context_completed": bool(minimal),
        }

    @classmethod
    def _update_composer_entry_observation(
        cls,
        response: dict[str, Any],
        request: AnalysisPipelineRequest,
    ) -> None:
        sink = request.composer_entry_diagnostics_sink
        if not isinstance(sink, MutableMapping):
            return
        _update_composer_entry_diagnostics(
            sink,
            **cls._composer_entry_observation(response, request),
        )

    def _complete_response(
        self,
        response: dict[str, Any],
        request: AnalysisPipelineRequest,
    ) -> dict[str, Any]:
        response = dict(response or {})
        stages = list((request.copilot_context or {}).get("analysis_pipeline_input_stages") or [])
        stages.append({"stage": "graph_execution", "status": "completed"})
        identity = self._identity(request)
        for key in ("product_id", "i_id", "sku_code"):
            if identity.get(key) not in (None, ""):
                response.setdefault(key, identity[key])

        understanding_verdict = self._turn_understanding_verdict(response)
        diagnostics_enabled = isinstance(
            request.composer_entry_diagnostics_sink,
            MutableMapping,
        )
        if diagnostics_enabled:
            self._update_composer_entry_observation(response, request)
        understanding_restricted = understanding_verdict["status"] in {
            "invalid",
            "degraded",
        }
        understanding_invalid = understanding_verdict["status"] == "invalid"
        if understanding_restricted:
            if diagnostics_enabled:
                _update_composer_entry_diagnostics(
                    request.composer_entry_diagnostics_sink,
                    composer_entry_eligible=False,
                    exact_reason_code="turn_understanding_not_authoritative",
                    downstream_stage="turn_understanding_boundary",
                )
            response = self._apply_invalid_understanding_boundary(
                response,
                understanding_verdict,
                clear_candidate_reply=understanding_invalid,
            )
            stages.extend([
                {
                    "stage": "media_delivery",
                    "status": "blocked",
                    "reason": "turn_understanding_not_authoritative",
                },
                {
                    "stage": "model_first_answer_composer",
                    "status": "blocked",
                    "reason": "turn_understanding_not_authoritative",
                    "used_for_final_reply": False,
                },
            ])
        else:
            response, media_stage = self._apply_media_delivery(
                response,
                request,
                identity,
            )
            stages.append(media_stage)

            response, composer_stage = self._apply_model_first_answer_composer(
                response,
                request,
            )
            stages.append(composer_stage)

        final_completed = False
        try:
            from app.services.final_response_orchestrator import orchestrate_final_response

            response = orchestrate_final_response(
                response,
                customer_message=request.delivery_message or request.customer_message,
                copilot_context=request.copilot_context,
            )
            if understanding_restricted:
                response = self._apply_invalid_understanding_boundary(
                    response,
                    understanding_verdict,
                    clear_candidate_reply=False,
                )
            elif self._env_enabled("COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED"):
                response = self._force_model_first_review_boundary(response)
            final_completed = True
            stages.append({"stage": "final_response_orchestration", "status": "completed"})
        except Exception as exc:
            from app.services.analysis_execution_service import apply_pre_final_response_safety

            response.setdefault("evidence_debug", {})["analysis_pipeline_final_error"] = {
                "type": type(exc).__name__, "message": str(exc),
            }
            response = apply_pre_final_response_safety(
                response,
                "final_orchestration_failed",
            )
            stages.append({"stage": "final_response_orchestration", "status": "failed", "reason": type(exc).__name__})

        response, shadow_stages = self._attach_shadow_layers(response, request, identity)
        stages.extend(shadow_stages)
        pipeline = {
            "version": PIPELINE_VERSION,
            "stages": stages,
            "final_orchestration_completed": final_completed,
            "capabilities": dict(request.capabilities or {}),
        }
        response["analysis_pipeline"] = pipeline
        response.setdefault("execution_debug", {})["analysis_pipeline"] = pipeline
        response.setdefault("evidence_debug", {})["analysis_pipeline"] = pipeline
        response.setdefault("trace_steps", []).append({
            "node": "analysis_pipeline",
            "status": "completed" if final_completed else "degraded",
            "summary": "graph, media delivery, final response, shadow; persistence follows in AnalysisExecutionService",
            "stages": stages,
        })
        return response

    @staticmethod
    def _turn_understanding_verdict(
        response: dict[str, Any],
    ) -> dict[str, Any]:
        debug = (
            response.get("evidence_debug")
            if isinstance(response.get("evidence_debug"), dict)
            else {}
        )
        understanding = response.get("turn_understanding")
        if not isinstance(understanding, dict):
            understanding = debug.get("turn_understanding")
        understanding = (
            understanding if isinstance(understanding, dict) else {}
        )
        status = str(
            understanding.get("goal_understanding_status") or ""
        ).strip().lower()
        if status not in {"valid", "degraded", "invalid"}:
            status = "unknown"
        diagnostics = understanding.get(
            "goal_understanding_diagnostics"
        )
        reasons = list(dict.fromkeys(
            str(reason).strip()
            for reason in (
                diagnostics if isinstance(diagnostics, list) else []
            )
            if str(reason or "").strip()
        ))
        if status in {"invalid", "degraded"} and not reasons:
            reasons = ["turn_understanding_not_authoritative"]
        return {
            "status": status,
            "reason_codes": reasons,
            "source_stage": "turn_understanding",
        }

    @classmethod
    def _apply_invalid_understanding_boundary(
        cls,
        response: dict[str, Any],
        verdict: dict[str, Any],
        *,
        clear_candidate_reply: bool,
    ) -> dict[str, Any]:
        response = dict(response or {})
        reason_codes = list(verdict.get("reason_codes") or [])
        earliest_reason = (
            str(reason_codes[0]).strip()
            if reason_codes
            else "turn_understanding_not_authoritative"
        )
        if clear_candidate_reply:
            response["suggested_reply"] = ""
        response["draft_reply"] = ""
        response["sendable_reply"] = ""
        response["can_send"] = False
        response["requires_human_review"] = True
        response["reply_status"] = "needs_human_review"
        response["recommended_assets"] = []
        response["recommended_assets_meta"] = {
            "priority_types": [],
            "has_unapproved": False,
            "source": "turn_understanding_boundary",
        }
        response["reply_blocks"] = (
            []
            if clear_candidate_reply
            else [
                {
                    **block,
                    "send_mode": "manual",
                }
                for block in (response.get("reply_blocks") or [])
                if isinstance(block, dict)
                and block.get("type") == "text"
                and str(block.get("content") or "").strip()
            ]
        )
        response["reply_delivery"] = {
            "mode": "blocked",
            "auto_send_ready": False,
            "reason": "turn_understanding_not_authoritative",
        }
        response["reason_for_review"] = cls._append_reason(
            str(response.get("reason_for_review") or ""),
            "turn_understanding_not_authoritative",
        )
        block_reasons = response.get("block_reasons")
        block_reasons = (
            list(block_reasons)
            if isinstance(block_reasons, list)
            else []
        )
        response["block_reasons"] = list(dict.fromkeys([
            *block_reasons,
            "turn_understanding_not_authoritative",
            earliest_reason,
        ]))
        diagnostics = {
            "status": verdict.get("status"),
            "reason_codes": reason_codes,
            "earliest_reason_code": earliest_reason,
            "requested_claims": [],
            "selected_evidence_diagnostic_only": True,
            "used_for_final_reply": False,
            "can_change_can_send": False,
        }
        response["turn_understanding_boundary"] = diagnostics
        response.setdefault("evidence_debug", {})[
            "turn_understanding_boundary"
        ] = diagnostics
        return response

    def _apply_model_first_answer_composer(
        self,
        response: dict[str, Any],
        request: AnalysisPipelineRequest,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        entry_sink = request.composer_entry_diagnostics_sink
        entry_diagnostics_enabled = isinstance(
            entry_sink,
            MutableMapping,
        )
        composer_enabled = self._env_enabled(
            "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED"
        )
        convergence_enabled = self._env_enabled(
            "COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED"
        )
        if entry_diagnostics_enabled:
            _update_composer_entry_diagnostics(
                entry_sink,
                formal_evidence_convergence_enabled=convergence_enabled,
                model_first_answer_composer_enabled=composer_enabled,
                bounded_inference_shadow_enabled=self._env_enabled(
                    "COPILOT_BOUNDED_INFERENCE_SHADOW_ENABLED"
                ),
                downstream_stage="composer_entry_gate",
            )
            self._update_composer_entry_observation(response, request)
        if not composer_enabled:
            if entry_diagnostics_enabled:
                _update_composer_entry_diagnostics(
                    entry_sink,
                    composer_entry_eligible=False,
                    exact_reason_code="composer_feature_disabled",
                    downstream_stage="composer_skipped",
                )
            return response, {
                "stage": "model_first_answer_composer",
                "status": "disabled",
            }

        response = dict(response or {})
        response["can_send"] = False
        response["sendable_reply"] = ""
        response["requires_human_review"] = True
        response["reply_status"] = "needs_human_review"
        response["reason_for_review"] = self._append_reason(
            str(response.get("reason_for_review") or ""),
            "model_first_candidate_review_only",
        )
        if not convergence_enabled:
            if entry_diagnostics_enabled:
                _update_composer_entry_diagnostics(
                    entry_sink,
                    composer_entry_eligible=False,
                    exact_reason_code="formal_evidence_convergence_disabled",
                    downstream_stage="composer_blocked",
                )
            diagnostics = {
                "version": "model-first-answer-composer-v1",
                "status": "provider_blocked",
                "rejection_reason": "formal_evidence_convergence_disabled",
                "used_for_final_reply": False,
                "can_change_can_send": False,
                "requires_human_review": True,
                "can_send": False,
            }
            response["model_first_answer_composer"] = diagnostics
            response.setdefault("evidence_debug", {})[
                "model_first_answer_composer"
            ] = diagnostics
            return response, {
                "stage": "model_first_answer_composer",
                "status": "blocked",
                "reason": "formal_evidence_convergence_disabled",
            }

        try:
            try:
                from app.services.model_first_answer_composer_service import (
                    ModelFirstAnswerComposerService,
                )
            except Exception:
                if entry_diagnostics_enabled:
                    _update_composer_entry_diagnostics(
                        entry_sink,
                        composer_service_available=False,
                        composer_service_check_status="unavailable",
                        composer_entry_eligible=False,
                        exact_reason_code="composer_service_unavailable",
                        downstream_stage="composer_import_failed",
                    )
                raise

            if entry_diagnostics_enabled:
                minimal_context = (
                    ModelFirstAnswerComposerService._minimal_context(
                        response
                    )
                )
                _update_composer_entry_diagnostics(
                    entry_sink,
                    composer_service_available=True,
                    composer_service_check_status="available",
                    composer_entry_eligible=True,
                    composer_invocation_attempted=True,
                    minimal_context_attempted=True,
                    minimal_context_completed=bool(minimal_context),
                    exact_reason_code="composer_invocation_attempted",
                    downstream_stage="composer_invocation",
                )
            response, diagnostics = ModelFirstAnswerComposerService().compose(
                response,
                customer_message=request.delivery_message or request.customer_message,
                copilot_context=request.copilot_context,
                privacy_diagnostics_sink=(
                    request.composer_privacy_diagnostics_sink
                ),
            )
            eligibility = diagnostics.get("input_eligibility")
            eligibility = (
                eligibility if isinstance(eligibility, dict) else {}
            )
            rejection_reason = str(
                diagnostics.get("rejection_reason") or ""
            ).strip()
            if entry_diagnostics_enabled:
                _update_composer_entry_diagnostics(
                    entry_sink,
                    composer_invocation_completed=True,
                    renderable_customer_goal_count=int(
                        eligibility.get(
                            "renderable_customer_goal_count"
                        )
                        or 0
                    ),
                    exact_reason_code=(
                        rejection_reason
                        or "composer_invocation_completed"
                    ),
                    downstream_stage=(
                        "composer_completed"
                        if diagnostics.get("status") == "accepted"
                        else "composer_blocked"
                    ),
                )
                self._update_composer_entry_observation(response, request)
            response["can_send"] = False
            response["sendable_reply"] = ""
            response["requires_human_review"] = True
            response["reply_status"] = "needs_human_review"
            response["reason_for_review"] = self._append_reason(
                str(response.get("reason_for_review") or ""),
                "model_first_candidate_review_only",
            )
            response["model_first_answer_composer"] = diagnostics
            response.setdefault("evidence_debug", {})[
                "model_first_answer_composer"
            ] = diagnostics
            accepted = diagnostics.get("status") == "accepted"
            return response, {
                "stage": "model_first_answer_composer",
                "status": "completed" if accepted else "blocked",
                "reason": diagnostics.get("rejection_reason") or "",
                "used_for_final_reply": bool(
                    diagnostics.get("used_for_final_reply")
                ),
            }
        except Exception as exc:
            if (
                entry_diagnostics_enabled
                and _composer_entry_diagnostic_reason(entry_sink)
                != "composer_service_unavailable"
            ):
                _update_composer_entry_diagnostics(
                    entry_sink,
                    composer_invocation_completed=False,
                    exact_reason_code="composer_invocation_failed",
                    downstream_stage="composer_failed",
                )
            response.setdefault("evidence_debug", {})[
                "model_first_answer_composer_error"
            ] = {"type": type(exc).__name__}
            return response, {
                "stage": "model_first_answer_composer",
                "status": "degraded",
                "reason": type(exc).__name__,
            }

    def _apply_media_delivery(
        self,
        response: dict[str, Any],
        request: AnalysisPipelineRequest,
        identity: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            from app.services.media_asset_service import (
                build_reply_blocks,
                recommend_for_analyze_response,
                select_delivery_assets,
            )

            delivery_enabled = bool((request.capabilities or {}).get("media_delivery", True))
            message = request.delivery_message or request.customer_message
            recommendation = recommend_for_analyze_response(
                response,
                customer_message=message,
                product_name=identity["product_name"] or None,
                i_id=identity["i_id"] or None,
                sku_code=identity["sku_code"] or None,
                product_id=identity["product_id"],
            )
            fact_type = str(
                response.get("query_fact_type")
                or (response.get("evidence_debug") or {}).get("query_fact_type")
                or ""
            )
            if not fact_type and str(response.get("intent") or "") in {"image_attachment", "product_question"}:
                fact_type = "appearance"
            assets = self._pack_media_assets(response, message, identity)
            if assets:
                recommendation = {
                    "recommended_assets": assets,
                    "priority_types": [item.get("asset_type", "") for item in assets if item.get("asset_type")],
                    "has_unapproved": False,
                    "source": "product_context_pack",
                }
            allow_delivery = delivery_enabled and self._is_visual_media_question(message, response)
            candidate_source = str(recommendation.get("source") or "media_asset_service")
            response["recommended_assets"] = (
                select_delivery_assets(
                    recommendation.get("recommended_assets") or [],
                    max_assets=1,
                    query_fact_type=fact_type,
                    product_identity=identity,
                )
                if allow_delivery else []
            )
            for asset in response["recommended_assets"]:
                asset["delivery_candidate_source"] = candidate_source
            response["suggested_reply"] = self._sanitize_media_promise(
                str(response.get("suggested_reply") or ""), response["recommended_assets"]
            )
            response["suggested_reply"] = self._align_media_promise(
                str(response.get("suggested_reply") or ""), response["recommended_assets"]
            )
            response["recommended_assets_meta"] = {
                "priority_types": recommendation.get("priority_types", []),
                "has_unapproved": recommendation.get("has_unapproved", False),
                "source": recommendation.get("source", "media_asset_service"),
            }
            response.update(build_reply_blocks(
                response.get("suggested_reply", ""),
                response["recommended_assets"],
                requires_human_review=bool(response.get("requires_human_review")),
                query_fact_type=fact_type,
                product_identity=identity,
            ))
            attached = [
                block for block in response.get("reply_blocks") or []
                if isinstance(block, dict) and block.get("type") in {"image", "video"}
            ]
            response.setdefault("evidence_debug", {})["media_delivery_contract"] = {
                "candidate_source": candidate_source,
                "candidate_count": len(recommendation.get("recommended_assets") or []),
                "eligible_asset_count": len(response["recommended_assets"]),
                "actual_attached_media_count": len(attached),
                "attached_media": [
                    {
                        "type": block.get("type"),
                        "asset_type": block.get("asset_type"),
                        "delivery_candidate_source": block.get("delivery_candidate_source"),
                        "review_status": block.get("status"),
                        "review_approved": str(block.get("status") or "").lower() == "approved",
                        "usable_for_agent": block.get("usable_for_agent") in {True, 1},
                        "identity_present": bool(block.get("product_id") or block.get("i_id") or block.get("sku_code")),
                        "identity_matched": True,
                        "role_matched": True,
                    }
                    for block in attached
                ],
            }
            return response, {"stage": "media_delivery", "status": "completed", "attached_media_count": len(attached)}
        except Exception as exc:
            response["recommended_assets"] = []
            response["recommended_assets_meta"] = {"priority_types": [], "has_unapproved": False}
            response["reply_blocks"] = ([{"type": "text", "content": response.get("suggested_reply", ""), "send_mode": "auto_when_platform_connected"}] if response.get("suggested_reply") else [])
            response["reply_delivery"] = {
                "mode": "blocks", "auto_send_ready": False, "reason": "media_block_build_failed",
            }
            response.setdefault("evidence_debug", {})["analysis_pipeline_media_error"] = {
                "type": type(exc).__name__, "message": str(exc),
            }
            return response, {"stage": "media_delivery", "status": "degraded", "reason": type(exc).__name__}

    def _attach_shadow_layers(
        self,
        response: dict[str, Any],
        request: AnalysisPipelineRequest,
        identity: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        stages: list[dict[str, Any]] = []
        if self._env_enabled("COPILOT_ANSWER_MEMORY_SHADOW_ENABLED"):
            try:
                from app.services.answer_memory_adapter_service import AnswerMemoryAdapterService

                response, stage = self._run_shadow_stage(
                    response,
                    "answer_memory_shadow",
                    lambda shadow_response: AnswerMemoryAdapterService().attach_shadow_guidance(
                        shadow_response,
                        customer_message=request.delivery_message or request.customer_message,
                        product_i_id=identity["i_id"],
                        sku_code=identity["sku_code"],
                        product_title=identity["product_name"],
                        copilot_context=request.copilot_context,
                    ),
                )
                stages.append(stage)
            except Exception as exc:
                response.setdefault("evidence_debug", {})["answer_memory_guidance_error"] = str(exc)
                stages.append({"stage": "answer_memory_shadow", "status": "degraded", "reason": type(exc).__name__})
        else:
            stages.append({"stage": "answer_memory_shadow", "status": "disabled"})

        if self._env_enabled("COPILOT_GROUNDED_REASONING_SHADOW_ENABLED"):
            try:
                from app.services.grounded_reasoning_draft_service import GroundedReasoningDraftService

                response, stage = self._run_shadow_stage(
                    response,
                    "grounded_reasoning_shadow",
                    lambda shadow_response: GroundedReasoningDraftService().attach_shadow_draft(
                        shadow_response,
                        customer_message=request.delivery_message or request.customer_message,
                        product_identity=identity,
                        answer_memory_guidance=shadow_response.get("answer_memory_guidance") if isinstance(shadow_response.get("answer_memory_guidance"), dict) else {},
                    ),
                )
                stages.append(stage)
            except Exception as exc:
                response.setdefault("evidence_debug", {})["grounded_reasoning_draft_error"] = str(exc)
                stages.append({"stage": "grounded_reasoning_shadow", "status": "degraded", "reason": type(exc).__name__})
        else:
            stages.append({"stage": "grounded_reasoning_shadow", "status": "disabled"})

        if self._env_enabled("COPILOT_LLM_DECISION_SHADOW_ENABLED"):
            try:
                from app.services.agent_decision_proposal_service import AgentDecisionProposalService

                response, stage = self._run_shadow_stage(
                    response,
                    "llm_decision_shadow",
                    lambda shadow_response: AgentDecisionProposalService().attach_shadow_decision(
                        shadow_response,
                        customer_message=request.delivery_message or request.customer_message,
                        product_identity=identity,
                        copilot_context=request.copilot_context,
                    ),
                )
                stages.append(stage)
            except Exception as exc:
                response.setdefault("evidence_debug", {})["llm_decision_shadow_error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                stages.append({"stage": "llm_decision_shadow", "status": "degraded", "reason": type(exc).__name__})
        else:
            from app.services.strict_decision_provider_service import StrictDecisionProviderService

            provider = StrictDecisionProviderService()
            metadata = provider.metadata()
            reason = provider.config.capability_status()
            if reason == "configured" and not provider.ready_for_shadow():
                reason = "provider_not_qualified"
            response.setdefault("evidence_debug", {})["llm_decision_shadow_status"] = {
                "shadow_only": True,
                "status": "disabled",
                "reason": reason,
                "provider": metadata,
                "used_for_final_reply": False,
                "can_change_can_send": False,
            }
            stages.append({"stage": "llm_decision_shadow", "status": "disabled", "reason": reason})

        stages.append({
            "stage": "evidence_action_shadow",
            "status": "disabled",
            "reason": "paused_not_qualified",
            "used_for_final_reply": False,
            "can_change_can_send": False,
        })
        return response, stages

    @staticmethod
    def _run_shadow_stage(
        response: dict[str, Any],
        stage_name: str,
        attach,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        baseline = {
            field: deepcopy(response.get(field))
            for field in _FORMAL_DECISION_FIELDS
        }
        updated = attach(deepcopy(response))
        if not isinstance(updated, dict):
            raise TypeError(f"{stage_name} must return a dict")

        changed_fields = [
            field for field, value in baseline.items()
            if updated.get(field) != value
        ]
        if not changed_fields:
            return updated, {"stage": stage_name, "status": "completed"}

        for field in changed_fields:
            updated[field] = deepcopy(baseline[field])
        updated.setdefault("evidence_debug", {}).setdefault(
            "shadow_contract_violation", []
        ).append({"stage": stage_name, "fields": changed_fields})
        return updated, {
            "stage": stage_name,
            "status": "contract_violation",
            "fields": changed_fields,
        }

    @staticmethod
    def _env_enabled(name: str) -> bool:
        return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _append_reason(existing: str, reason: str) -> str:
        values = [item for item in (existing.strip(), reason.strip()) if item]
        return "; ".join(dict.fromkeys(values))

    @staticmethod
    def _force_model_first_review_boundary(
        response: dict[str, Any],
    ) -> dict[str, Any]:
        response["can_send"] = False
        response["sendable_reply"] = ""
        response["requires_human_review"] = True
        response["reply_status"] = "needs_human_review"
        reasons = [
            str(item)
            for item in response.get("block_reasons") or []
            if str(item)
        ]
        if "model_first_candidate_review_only" not in reasons:
            reasons.append("model_first_candidate_review_only")
        response["block_reasons"] = reasons
        for block in response.get("reply_blocks") or []:
            if isinstance(block, dict) and block.get("type") in {"image", "video"}:
                block["send_mode"] = "manual"
        delivery = response.get("reply_delivery")
        if isinstance(delivery, dict):
            delivery["auto_send_ready"] = False
            delivery["reason"] = "model_first_candidate_review_only"
        response.setdefault("evidence_debug", {})[
            "model_first_candidate_delivery_boundary"
        ] = {
            "can_send": False,
            "requires_human_review": True,
            "reason": "model_first_candidate_review_only",
        }
        return response

    @staticmethod
    def _identity(request: AnalysisPipelineRequest) -> dict[str, Any]:
        context = request.copilot_context or {}
        identity: dict[str, Any] = {
            "product_name": request.product_name or context.get("display_product_name") or context.get("product_name") or "",
            "sku_code": context.get("sku_code") or "",
            "i_id": context.get("i_id") or "",
            "product_id": None,
        }
        candidates = request.product_candidates or context.get("product_candidates") or []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            value = str(candidate.get("value") or "").strip()
            kind = str(candidate.get("type") or "").lower()
            if not value:
                continue
            if "product_id" in kind and identity["product_id"] is None:
                try:
                    identity["product_id"] = int(value)
                except ValueError:
                    pass
            elif ("sku" in kind or "i_id" in kind) and not identity["sku_code"]:
                identity["sku_code"] = value
                identity["i_id"] = identity["i_id"] or value
            elif ("product_name" in kind or kind.endswith("name")) and not identity["product_name"]:
                identity["product_name"] = value
        return identity

    @staticmethod
    def _skip_image_vlm(request: AnalysisPipelineRequest, context: dict[str, Any]) -> bool:
        text = _IMAGE_MARKER_RE.sub("", request.customer_message or "").strip()
        has_text_question = bool(text and any(term in text for term in _TEXT_PRODUCT_QUESTION_TERMS))
        has_context = bool(
            request.product_name or request.product_candidates or request.order_id or request.tracking_no
            or context.get("product_name") or context.get("product_candidates") or context.get("order_id")
            or context.get("platform_order_id") or context.get("platform_trade_id") or context.get("tracking_no")
        )
        return has_text_question and has_context

    @staticmethod
    def _is_visual_media_question(message: str, response: dict[str, Any]) -> bool:
        debug = response.get("evidence_debug") or {}
        semantic_query = debug.get("semantic_query") or response.get("semantic_query") or {}
        if isinstance(semantic_query, dict) and semantic_query.get("needs_visual_asset"):
            return True
        if str(debug.get("query_fact_type") or "").strip() in _VISUAL_FACT_TYPES:
            return True
        if str(response.get("intent") or "").strip() == "image_attachment":
            return True
        text = _IMAGE_MARKER_RE.sub("", message or "")
        return any(term in text for term in _VISUAL_TERMS)

    @staticmethod
    def _pack_media_assets(
        response: dict[str, Any],
        message: str,
        product_identity: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not AnalysisPipelineService._is_visual_media_question(message, response):
            return []
        from app.services.media_asset_service import is_delivery_media_asset_eligible

        context_used = response.get("context_used") or {}
        pack = context_used.get("product_context_pack") or response.get("product_context_pack") or {}
        fact_type = str((response.get("evidence_debug") or {}).get("query_fact_type") or "")
        assets = list(pack.get("recommended_assets") or [])
        if assets:
            return [
                item for item in assets
                if isinstance(item, dict) and is_delivery_media_asset_eligible(
                    item,
                    query_fact_type=fact_type,
                    product_identity=product_identity,
                )
            ]
        media_assets = pack.get("media_assets") or []
        if fact_type in {"installation", "detachable"}:
            assets = [item for item in media_assets if str(item.get("asset_type") or "").startswith("install") or str(item.get("media_purpose") or "").startswith("install")]
        elif fact_type in {"dimensions", "space_fit"}:
            assets = [
                item for item in media_assets
                if isinstance(item, dict) and is_delivery_media_asset_eligible(
                    item,
                    query_fact_type=fact_type,
                    product_identity=product_identity,
                )
            ]
        elif fact_type in {"accessories", "packaging"}:
            assets = [item for item in media_assets if str(item.get("asset_type") or "") in {"sku_image", "pack_guide_image", "size_chart_image"} or str(item.get("media_purpose") or "") in {"appearance_image", "packing_list_image", "size_chart_image"}]
        else:
            assets = [item for item in media_assets if str(item.get("asset_type") or "") in {"sku_image", "install_video", "pack_guide_image", "size_chart_image"}]
        return assets[:1]

    @staticmethod
    def _sanitize_media_promise(reply: str, assets: list[dict[str, Any]]) -> str:
        if assets or not reply or not any(term in reply for term in _MEDIA_PROMISE_TERMS):
            return reply
        safe_line = "如果您安装或核对过程中卡在具体步骤，可以把卡住的位置或页面截图发我，我这边按已有说明帮您核对。"
        cleaned: list[str] = []
        inserted = False
        for line in reply.splitlines():
            if not any(term in line for term in _MEDIA_PROMISE_TERMS):
                cleaned.append(line)
                continue
            stripped = line
            for term in _MEDIA_PROMISE_TERMS:
                stripped = stripped.replace(term, "")
            stripped = stripped.strip(" ，,。.；;！？!?:：、~～")
            if stripped:
                cleaned.append(stripped)
            elif not inserted:
                cleaned.append(safe_line)
                inserted = True
        return "\n".join(cleaned).strip() or safe_line

    @staticmethod
    def _align_media_promise(reply: str, assets: list[dict[str, Any]]) -> str:
        asset_types = {str(asset.get("asset_type") or "") for asset in assets}
        if "install_video" in asset_types and "安装视频" in reply:
            return reply.replace(
                "如果需要安装视频，可以联系客服，我们发给您参考",
                "我把安装视频一起发您参考。",
            )
        return reply
