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
STAGES = [
    "canonical_input",
    "graph_execution",
    "media_delivery",
    "final_response_orchestration",
    "answer_memory_shadow",
    "grounded_reasoning_shadow",
    "final_persistence",
]


def diagnose(project_root: Path) -> dict:
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
    return {
        "pipeline_version": "analysis-pipeline-v1",
        "stages": STAGES,
        "entrypoints": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    report = diagnose(project_root)
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
