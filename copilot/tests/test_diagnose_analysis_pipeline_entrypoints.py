from __future__ import annotations

from pathlib import Path

from scripts.diagnose_analysis_pipeline_entrypoints import ENTRYPOINTS, diagnose


def test_entrypoint_diagnostic_reports_pipeline_adoption():
    project_root = Path(__file__).resolve().parents[1]
    report = diagnose(project_root)

    assert report["pipeline_version"] == "analysis-pipeline-v1"
    assert set(report["source_code_adoption"]) == set(ENTRYPOINTS)
    for details in report["source_code_adoption"].values():
        assert details["uses_analysis_pipeline"] is True
        assert details["route_level_final_orchestration"] is False
        assert details["route_level_media_selection"] is False
        assert details["direct_execute_analysis"] is False
    assert report["runtime_observation"]["available"] is False
    assert report["persistence_contract"] == {
        "owner": "AnalysisExecutionService",
        "post_processor_before_persistence": True,
        "pipeline_claims_final_persistence": False,
    }


def test_entrypoint_diagnostic_reports_observed_runtime_stages():
    project_root = Path(__file__).resolve().parents[1]
    report = diagnose(project_root, runtime_response={
        "analysis_pipeline": {
            "stages": [
                {"stage": "canonical_input", "status": "completed"},
                {"stage": "graph_execution", "status": "completed"},
                {"stage": "media_delivery", "status": "completed"},
                {"stage": "final_response_orchestration", "status": "completed"},
                {"stage": "answer_memory_shadow", "status": "disabled"},
                {"stage": "grounded_reasoning_shadow", "status": "disabled"},
            ]
        }
    })

    runtime = report["runtime_observation"]
    assert runtime["available"] is True
    assert runtime["missing_required_runtime_stages"] == []
    assert runtime["final_persistence_claimed_by_pipeline"] is False
