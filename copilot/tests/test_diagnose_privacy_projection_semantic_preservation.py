from app.services.canonical_conversation_turn_service import (
    project_value_for_external_model,
)
from scripts.diagnose_privacy_projection_semantic_preservation import (
    _marker_summary,
    _projection_qualification,
)


def test_projection_qualification_preserves_semantics_and_redacts_private_data():
    result = _projection_qualification(repeats=3)

    assert result["semantic_preservation"]["rate"] == 1
    assert result["privacy_redaction"]["rate"] == 1
    assert result["false_address_redaction_count"] == 0
    assert result["privacy_leakage_count"] == 0
    assert result["stability_rate"] == 1
    assert result["model_call_count"] == 0
    assert result["retry_count"] == 0
    assert result["repair_count"] == 0


def test_marker_summary_distinguishes_address_markers_from_other_redactions():
    result = _marker_summary(
        "[PRODUCT_ID_REDACTED:83a9f8ffa8f4] [ADDRESS_REDACTED]"
    )

    assert result["count"] == 2
    assert result["address_count"] == 1


def test_structured_projection_is_semantically_stable_when_field_order_changes():
    payload = {
        "product_title": "客厅卧室收纳凳",
        "fact": "主体材质为PP，宽80厘米",
        "buyer_id": "buyer-private-001",
        "order_id": "ORDER-PRIVATE-001",
    }

    projected = project_value_for_external_model(payload)
    reversed_projected = project_value_for_external_model(
        dict(reversed(list(payload.items())))
    )

    assert projected == reversed_projected
