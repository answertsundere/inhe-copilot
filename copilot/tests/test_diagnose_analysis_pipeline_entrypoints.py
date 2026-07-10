from __future__ import annotations

from pathlib import Path

from scripts.diagnose_analysis_pipeline_entrypoints import ENTRYPOINTS, STAGES, diagnose


def test_entrypoint_diagnostic_reports_pipeline_adoption():
    project_root = Path(__file__).resolve().parents[1]
    report = diagnose(project_root)

    assert report["pipeline_version"] == "analysis-pipeline-v1"
    assert report["stages"] == STAGES
    assert set(report["entrypoints"]) == set(ENTRYPOINTS)
    for details in report["entrypoints"].values():
        assert details["uses_analysis_pipeline"] is True
        assert details["route_level_final_orchestration"] is False
        assert details["route_level_media_selection"] is False
        assert details["direct_execute_analysis"] is False
