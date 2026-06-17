from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_web_copilot_review_banner_uses_actual_reason():
    html = (ROOT / "web/templates/copilot_panel.html").read_text(encoding="utf-8")
    assert "humanReviewText" in html
    assert "data.reason_for_review || data.review_reason" in html
    assert "高风险消息，需人工复核" not in html


def test_desktop_message_keeps_review_reason():
    html = (ROOT / "desktop/pages/index.html").read_text(encoding="utf-8")
    assert "reason_for_review: data.reason_for_review || data.review_reason" in html
    assert "需人工复核</span>" in html


def test_real_test_panel_explains_low_risk_review():
    html = (ROOT / "web/templates/real_test_panel.html").read_text(encoding="utf-8")
    assert "需人工确认：${reviewReason}" in html
