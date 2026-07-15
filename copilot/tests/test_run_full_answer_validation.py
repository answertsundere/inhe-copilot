import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_full_answer_validation.py"
    spec = importlib.util.spec_from_file_location("formal_answer_validation", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_evaluator_rejects_duplicate_evidence_and_unsafe_high_risk_delivery():
    result = _module().evaluate_response(
        {
            "case_id": "case-1",
            "query_fact_type": "material_safety",
            "expected": {"must_handoff": True, "high_risk_claims": ["material_safety"]},
        },
        {
            "can_send": True,
            "requires_human_review": False,
            "sendable_reply": "unsafe",
            "suggested_reply": "draft for the supervisor",
            "selected_evidence": [{"evidence_uid": "same"}, {"evidence_uid": "same"}],
        },
    )
    assert set(result["issues"]) == {
        "selected_evidence_duplicate", "unsafe_auto_send", "unsupported_high_risk_claim",
    }
    assert result["suggested_reply"] == "draft for the supervisor"
    assert result["selected_evidence"] == [
        {"evidence_uid": "same", "source": "", "evidence_role": "", "fact_type": "", "attribute_key": ""},
        {"evidence_uid": "same", "source": "", "evidence_role": "", "fact_type": "", "attribute_key": ""},
    ]


def test_evaluator_rejects_appearance_media_for_dimension_delivery():
    result = _module().evaluate_response(
        {"case_id": "case-2", "query_fact_type": "dimensions"},
        {"reply_blocks": [{"type": "image", "asset_type": "sku_image", "media_purpose": "appearance_image"}]},
    )
    assert result["issues"] == ["media_role_mismatch"]
