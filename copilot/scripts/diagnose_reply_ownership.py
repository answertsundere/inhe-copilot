"""Trace reply ownership without persistence or evaluation-label exposure."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", "true")
os.environ.setdefault("COPILOT_DAILY_MEDIA_SYNC_ENABLED", "false")


_SYSTEM_TONE_TERMS = ("系统", "资料显示", "知识库", "转人工", "帮您核对", "确认后回复")
_ACTIVE_STAGES: list[dict[str, Any]] | None = None


def _reply(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("suggested_reply") or value.get("draft_reply") or "")


def _record(stage: str, before: str, after: str, metadata: dict[str, Any] | None = None) -> None:
    if _ACTIVE_STAGES is None:
        return
    _ACTIVE_STAGES.append({
        "stage": stage,
        "input_reply": before,
        "output_reply": after,
        "changed": before != after,
        "fact_change_assessment": "requires_claim_attribution_review" if before != after else "unchanged",
        "system_tone_terms_added": [
            term for term in _SYSTEM_TONE_TERMS if term in after and term not in before
        ],
        "question_added": ("？" in after or "?" in after) and ("？" not in before and "?" not in before),
        **dict(metadata or {}),
    })


def _wrap_response_function(
    owner: Any,
    name: str,
    stage: str,
) -> tuple[Any, str, Callable[..., Any]]:
    original = getattr(owner, name)

    def wrapped(response, *args, **kwargs):
        before = _reply(response)
        result = original(response, *args, **kwargs)
        output = result if isinstance(result, dict) else response
        metadata: dict[str, Any] = {}
        if stage == "final_answer_auditor":
            audit = (output or {}).get("final_answer_audit") or {}
            metadata = {
                "audit_passed": bool(audit.get("passed", True)),
                "fallback_used": bool(audit.get("fallback_used")),
                "issues": list(audit.get("issues") or []),
            }
        _record(stage, before, _reply(output), metadata)
        return result

    setattr(owner, name, wrapped)
    return owner, name, original


def _wrap_state_function(
    owner: Any,
    name: str,
    stage: str,
) -> tuple[Any, str, Callable[..., Any]]:
    original = getattr(owner, name)

    def wrapped(state, *args, **kwargs):
        before = _reply(state)
        result = original(state, *args, **kwargs)
        output = result if isinstance(result, dict) else state
        _record(stage, before, _reply(output))
        return result

    setattr(owner, name, wrapped)
    return owner, name, original


def _install_instrumentation() -> list[tuple[Any, str, Callable[..., Any]]]:
    import app.agent.nodes.build_response as build_response_module
    import app.agent.nodes.generate_reply as generate_reply_module
    import app.services.final_response_orchestrator as final_module

    patches = [
        _wrap_state_function(generate_reply_module, "generate_reply", "graph_generate_reply"),
        _wrap_state_function(build_response_module, "build_response", "build_response"),
        _wrap_response_function(final_module, "apply_no_evidence_reply_policy", "no_evidence_policy"),
        _wrap_response_function(final_module, "audit_final_answer", "final_answer_auditor"),
        _wrap_response_function(final_module, "polish_customer_reply", "customer_reply_polisher"),
        _wrap_response_function(final_module, "apply_semantic_fit_result", "semantic_fallback"),
        _wrap_response_function(final_module, "orchestrate_final_response", "final_orchestration"),
    ]

    style_original = build_response_module.beautify_customer_reply

    def wrapped_style(reply: str, state: dict | None = None) -> str:
        output = style_original(reply, state)
        _record("reply_style_service", str(reply or ""), str(output or ""))
        return output

    build_response_module.beautify_customer_reply = wrapped_style
    patches.append((build_response_module, "beautify_customer_reply", style_original))
    return patches


def _restore_instrumentation(patches: list[tuple[Any, str, Callable[..., Any]]]) -> None:
    for owner, name, original in reversed(patches):
        setattr(owner, name, original)


def _request_from_scenario(scenario: dict[str, Any], reply_service: Any):
    from app.services.analysis_pipeline_service import AnalysisPipelineRequest

    template = deepcopy(scenario.get("api_request_template") or {})
    context = dict(template.get("copilot_context") or {})
    history = template.get("conversation_history")
    if isinstance(history, list):
        context["conversation_history"] = history
    for key in ("i_id", "sku_code"):
        if template.get(key):
            context[key] = template[key]
    return AnalysisPipelineRequest(
        reply_service=reply_service,
        customer_message=str(template.get("message") or ""),
        order_id=str(template.get("order_id") or ""),
        conversation_id=str(template.get("conversation_id") or "phase-0.9a-diagnostic"),
        product_name=str(template.get("product_name") or ""),
        product_candidates=[
            {"type": key, "value": str(template[key])}
            for key in ("i_id", "sku_code")
            if template.get(key)
        ],
        copilot_context=context,
        source="development_diagnostic",
        delivery_message=str(template.get("message") or ""),
        capabilities={"media_delivery": True},
    )


def _run_without_persistence(service: Any, request: Any) -> dict[str, Any]:
    prepared = service._prepare_request(request)
    suggestion = prepared.reply_service.analyze(
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
    )
    response = suggestion.to_dict() if hasattr(suggestion, "to_dict") else dict(suggestion)
    return service._complete_response(response, prepared)


def build_report(dataset: dict[str, Any], *, limit: int) -> dict[str, Any]:
    global _ACTIVE_STAGES

    from app.main import get_reply_service
    from app.services.analysis_pipeline_service import AnalysisPipelineService

    reply_service = get_reply_service()
    reply_service._review_queue_service = None
    service = AnalysisPipelineService()
    scenarios = [
        item for item in dataset.get("scenarios") or []
        if isinstance(item, dict) and item.get("api_request_template")
    ][:limit]
    rows: list[dict[str, Any]] = []
    changes: Counter[str] = Counter()
    final_owners: Counter[str] = Counter()
    patches = _install_instrumentation()
    try:
        for scenario in scenarios:
            _ACTIVE_STAGES = []
            response = _run_without_persistence(
                service,
                _request_from_scenario(scenario, reply_service),
            )
            for item in _ACTIVE_STAGES:
                if item.get("changed"):
                    changes[str(item.get("stage"))] += 1
            changed = [item["stage"] for item in _ACTIVE_STAGES if item.get("changed")]
            final_owner = changed[-1] if changed else "graph_output_unchanged"
            final_owners[final_owner] += 1
            rows.append({
                "scenario_uid": scenario.get("scenario_uid"),
                "business_domain": scenario.get("business_domain"),
                "customer_message": (scenario.get("api_request_template") or {}).get("message"),
                "stages": list(_ACTIVE_STAGES),
                "final_reply": str(response.get("suggested_reply") or ""),
                "final_reply_owner": final_owner,
                "can_send": bool(response.get("can_send")),
                "requires_human_review": bool(response.get("requires_human_review")),
                "selected_evidence_count": len(response.get("selected_evidence") or []),
                "pipeline_version": (response.get("analysis_pipeline") or {}).get("version"),
            })
    finally:
        _ACTIVE_STAGES = None
        _restore_instrumentation(patches)

    return {
        "schema_version": "reply-ownership-diagnostic-v1",
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("dataset_version"),
        "dataset_status": "development_diagnostic",
        "accuracy_claim_allowed": False,
        "scenario_count": len(rows),
        "persistence_enabled": False,
        "formal_knowledge_query_only": True,
        "stage_change_counts": dict(sorted(changes.items())),
        "final_reply_owner_counts": dict(sorted(final_owners.items())),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    dataset = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = build_report(dataset, limit=max(1, args.limit))
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "scenario_count": report["scenario_count"],
        "stage_change_counts": report["stage_change_counts"],
        "final_reply_owner_counts": report["final_reply_owner_counts"],
        "json_output": str(output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
