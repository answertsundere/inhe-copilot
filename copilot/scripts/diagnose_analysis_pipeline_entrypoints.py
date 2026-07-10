"""Read-only audit of formal AnalysisPipeline adoption across entry points."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ENTRYPOINTS = {
    "/api/analyze": "app/api/analyze_routes.py",
    "/api/copilot/context": "app/api/copilot_routes.py",
    "agent_benchmark": "app/services/agent_benchmark_runner_service.py",
    "real_conversation_replay": "app/services/real_conversation_replay_service.py",
}
REQUIRED_RUNTIME_STAGES = {
    "canonical_input",
    "graph_execution",
    "media_delivery",
    "final_response_orchestration",
    "answer_memory_shadow",
    "grounded_reasoning_shadow",
}


def _runtime_observation(runtime_response: object | None) -> dict:
    responses: list[dict] = []
    if isinstance(runtime_response, dict):
        if isinstance(runtime_response.get("analysis_pipeline"), dict):
            responses = [runtime_response]
        elif isinstance(runtime_response.get("responses"), list):
            responses = [item for item in runtime_response["responses"] if isinstance(item, dict)]
    elif isinstance(runtime_response, list):
        responses = [item for item in runtime_response if isinstance(item, dict)]

    observed_stages: set[str] = set()
    final_persistence_claimed_by_pipeline = False
    for response in responses:
        pipeline = response.get("analysis_pipeline") or {}
        for stage in pipeline.get("stages") or []:
            if isinstance(stage, dict) and stage.get("stage"):
                stage_name = str(stage["stage"])
                observed_stages.add(stage_name)
                final_persistence_claimed_by_pipeline |= stage_name == "final_persistence"

    return {
        "available": bool(responses),
        "response_count": len(responses),
        "observed_stages": sorted(observed_stages),
        "missing_required_runtime_stages": sorted(
            REQUIRED_RUNTIME_STAGES - observed_stages
        ),
        "final_persistence_claimed_by_pipeline": final_persistence_claimed_by_pipeline,
    }


def diagnose(project_root: Path, runtime_response: object | None = None) -> dict:
    results = {}
    for name, relative_path in ENTRYPOINTS.items():
        text = (project_root / relative_path).read_text(encoding="utf-8")
        results[name] = {
            "path": relative_path,
            "uses_analysis_pipeline": "AnalysisPipelineService" in text,
            "route_level_final_orchestration": "orchestrate_final_response" in text,
            "route_level_media_selection": "recommend_for_analyze_response" in text,
            "direct_execute_analysis": "execute_analysis(" in text,
        }
    execution_source = (project_root / "app/services/analysis_execution_service.py").read_text(encoding="utf-8")
    return {
        "pipeline_version": "analysis-pipeline-v1",
        "source_code_adoption": results,
        "runtime_observation": _runtime_observation(runtime_response),
        "persistence_contract": {
            "owner": "AnalysisExecutionService",
            "post_processor_before_persistence": "response_post_processor" in execution_source,
            "pipeline_claims_final_persistence": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--runtime-response-json")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    runtime_response = None
    if args.runtime_response_json:
        runtime_response = json.loads(
            Path(args.runtime_response_json).read_text(encoding="utf-8")
        )
    report = diagnose(project_root, runtime_response=runtime_response)
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
