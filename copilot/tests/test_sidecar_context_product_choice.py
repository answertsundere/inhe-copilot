from __future__ import annotations

from app.services.sidecar_context_service import best_candidate_value


def test_best_candidate_prefers_full_product_title_over_count_id_and_short_vision():
    title = "英禾床围栏宝宝防摔婴儿床护栏儿童床边挡板一侧单面隔板便携式"

    assert best_candidate_value([
        {"value": "(1)", "type": "product_candidate", "source": "uia_sidebar", "confidence": 0.6},
        {"value": "985017262291", "type": "platform_product_id_candidate", "source": "uia_sidebar", "confidence": 0.7},
        {"value": title, "type": "product_candidate", "source": "uia_sidebar", "confidence": 0.92},
        {"value": "床", "source": "vision", "confidence": 0.9},
    ]) == title
