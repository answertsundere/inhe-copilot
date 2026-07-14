"""One authoritative post-graph pipeline for every analysis entry point."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


PIPELINE_VERSION = "analysis-pipeline-v1"
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
_VISUAL_TERMS = (
    "图片", "照片", "实物图", "商品图", "尺寸图", "视频", "安装图", "安装视频",
    "配件图", "打包图", "说明书",
)
_MEDIA_PROMISE_TERMS = (
    "发安装视频", "发视频", "发图", "图片发您", "参考我下面发您的图片或视频",
    "下面发您的图片或视频", "图片/视频资料", "图片或视频",
)


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


class AnalysisPipelineService:
    """Run graph, delivery preparation, final response, shadow, then persistence."""

    def run(self, request: AnalysisPipelineRequest) -> dict[str, Any]:
        from app.services.analysis_execution_service import execute_analysis

        prepared = self._prepare_request(request)
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
            response_post_processor=lambda graph_response: self._complete_response(
                graph_response, prepared
            ),
        )

        return response

    def _prepare_request(self, request: AnalysisPipelineRequest) -> AnalysisPipelineRequest:
        context = dict(request.copilot_context or {})
        attachments = [dict(item) for item in (request.image_attachments or []) if isinstance(item, dict)]
        stages: list[dict[str, Any]] = [{
            "stage": "canonical_input",
            "status": "completed",
            "source": request.source,
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

    def _complete_response(
        self,
        response: dict[str, Any],
        request: AnalysisPipelineRequest,
    ) -> dict[str, Any]:
        response = dict(response or {})
        stages = list((request.copilot_context or {}).get("analysis_pipeline_input_stages") or [])
        stages.append({"stage": "graph_execution", "status": "completed"})
        identity = self._identity(request)

        response, media_stage = self._apply_media_delivery(response, request, identity)
        stages.append(media_stage)

        final_completed = False
        try:
            from app.services.final_response_orchestrator import orchestrate_final_response

            response = orchestrate_final_response(
                response,
                customer_message=request.delivery_message or request.customer_message,
                copilot_context=request.copilot_context,
            )
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
            assets = self._pack_media_assets(response, message)
            if assets:
                recommendation = {
                    "recommended_assets": assets,
                    "priority_types": [item.get("asset_type", "") for item in assets if item.get("asset_type")],
                    "has_unapproved": False,
                    "source": "product_context_pack",
                }
            allow_delivery = delivery_enabled and self._is_visual_media_question(message, response)
            response["recommended_assets"] = (
                select_delivery_assets(recommendation.get("recommended_assets") or [], max_assets=1)
                if allow_delivery else []
            )
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
            ))
            return response, {"stage": "media_delivery", "status": "completed", "attached_media_count": sum(1 for block in response.get("reply_blocks") or [] if block.get("type") in {"image", "video"})}
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
    def _pack_media_assets(response: dict[str, Any], message: str) -> list[dict[str, Any]]:
        if not AnalysisPipelineService._is_visual_media_question(message, response):
            return []
        context_used = response.get("context_used") or {}
        pack = context_used.get("product_context_pack") or response.get("product_context_pack") or {}
        assets = list(pack.get("recommended_assets") or [])
        if assets:
            return assets
        fact_type = str((response.get("evidence_debug") or {}).get("query_fact_type") or "")
        media_assets = pack.get("media_assets") or []
        if fact_type in {"installation", "detachable"}:
            assets = [item for item in media_assets if str(item.get("asset_type") or "").startswith("install") or str(item.get("media_purpose") or "").startswith("install")]
        elif fact_type in {"dimensions", "space_fit", "accessories", "packaging"}:
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
