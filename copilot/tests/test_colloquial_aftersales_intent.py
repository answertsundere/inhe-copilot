import pytest

from app.agent.nodes.detect_intent import detect_intent
from app.agent.nodes.parallel_understanding import _intent_classifier
from app.services.aftersales_intent_service import classify_colloquial_aftersales


@pytest.mark.parametrize(
    ("message", "subtype"),
    [
        ("这个还能配吗？", "replacement_request"),
        ("少了这个咋办？", "missing_item"),
        ("能单独给我来一个吗？", "replacement_request"),
        ("这个配件没有啊", "missing_item"),
        ("图上这个能补发不？", "replacement_request"),
        ("少了一个螺丝", "missing_item"),
        ("没有收到配件", "missing_item"),
        ("这个坏了能换一个吗？", "damaged_item"),
        ("发错了能重新发吗？", "wrong_item"),
        ("缺一块板子", "missing_item"),
    ],
)
def test_colloquial_aftersales_semantic_classification(message, subtype):
    result = classify_colloquial_aftersales(message)
    assert result["matched"] is True
    assert result["subtype"] == subtype


@pytest.mark.parametrize(
    "message",
    [
        "这个还能配吗？",
        "少了这个咋办？",
        "能单独给我来一个吗？",
        "这个配件没有啊",
        "图上这个能补发不？",
        "少了一个螺丝",
        "没有收到配件",
        "这个坏了能换一个吗？",
        "发错了能重新发吗？",
        "缺一块板子",
    ],
)
def test_colloquial_aftersales_reaches_legacy_and_parallel_routes(message):
    state = {"customer_message": message, "normalized_message": message, "trace_steps": []}
    legacy = detect_intent(state)
    parallel = _intent_classifier(state)

    assert legacy["intent"] == "aftersales"
    assert parallel["primary_intent"] in {"missing_item", "damaged_item", "wrong_item"}


@pytest.mark.parametrize(
    "message",
    [
        "这个配件是什么材质？",
        "安装需要几个螺丝？",
        "这个板子多厚？",
    ],
)
def test_product_questions_are_not_promoted_to_aftersales(message):
    assert classify_colloquial_aftersales(message) == {}
