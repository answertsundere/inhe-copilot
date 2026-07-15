from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "web" / "templates" / "real_test_panel.html"


def test_shadow_preview_is_read_only_and_surfaces_provider_status():
    content = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="decisionShadowPreview"' in content
    assert 'id="decisionShadowPreviewBody"' in content
    assert "supervisor_candidate_preview" in content
    assert "主管预览" in content
    assert "仅供主管核对，不会自动发送" in content
    assert "候选模型状态" in content
    assert "llm_decision_shadow_status" in content
    assert "provider_not_qualified" in content
    assert "renderDecisionShadowPreview(data)" in content


def test_shadow_preview_keeps_the_formal_reply_panel_separate():
    content = TEMPLATE.read_text(encoding="utf-8")
    start = content.index("function renderDecisionShadowPreview")
    shadow_function = content[start:]

    assert "officialReply" not in shadow_function
    assert "suggested_reply =" not in shadow_function
    assert "shortUid" not in shadow_function
