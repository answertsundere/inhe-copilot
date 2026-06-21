from app.services.answer_blocks_service import (
    build_answer_blocks,
    raw_field_leakage_issues,
    validate_customer_text,
)
from app.services.customer_answer_renderer import render_customer_answer
from app.services.fact_type_service import classify_query_fact_type
from app.services.semantic_compiler_service import semantic_compiler_issues


def _load_capacity_response(message: str) -> dict:
    return {
        "suggested_reply": "亲亲，关于这款：承重/容量: 8.58",
        "query_fact_type": "load_capacity",
        "required_fact_types": ["load_capacity"],
        "evidence_debug": {
            "query_fact_type": "load_capacity",
            "required_fact_types": ["load_capacity"],
            "selected_evidence": [
                {
                    "source_type": "product_facts",
                    "fact_type": "load_capacity",
                    "evidence_fact_type": "load_capacity",
                    "entry_id": "fact-load-1",
                    "fact": "承重/容量: 8.58",
                },
                {
                    "source_type": "product_facts",
                    "fact_type": "stability",
                    "evidence_fact_type": "stability",
                    "entry_id": "fact-structure-1",
                    "fact": "放置时建议保持地面平整，重物放下层更稳。",
                },
            ],
        },
    }


def test_raw_field_leakage_contract_blocks_common_field_shapes():
    for text in ["承重/容量: 8.58", "尺寸: 2.65", "材质: PP", "score: 0.88"]:
        assert raw_field_leakage_issues(text), text
        assert validate_customer_text(text), text


def test_answer_blocks_render_stability_without_exposing_raw_field():
    response = _load_capacity_response("放绘本稳吗？")

    result = build_answer_blocks(response, customer_message="放绘本稳吗？")
    rendered = render_customer_answer(result["answer_blocks"], customer_message="放绘本稳吗？")

    assert rendered["passed"] is True
    reply = rendered["rendered_text"]
    assert "承重/容量:" not in reply
    assert "8.58" not in reply or "页面有承重相关标注" in reply
    assert "绘本" in reply
    assert any(term in reply for term in ("下层", "均匀", "更稳", "平整"))
    assert not validate_customer_text(reply)


def test_stability_variants_do_not_render_database_field_values():
    messages = [
        "放绘本稳吗？",
        "放客厅杂物会不会晃？",
        "能不能放小朋友的东西？",
        "放书会不会压塌？",
    ]

    for message in messages:
        response = _load_capacity_response(message)
        blocks = build_answer_blocks(response, customer_message=message)["answer_blocks"]
        reply = render_customer_answer(blocks, customer_message=message)["rendered_text"]

        assert "承重/容量:" not in reply
        assert not semantic_compiler_issues(reply, response=response, customer_message=message, answer_blocks=blocks)
        assert any(term in reply for term in ("适合", "建议", "下层", "更稳", "平整"))


def test_phase8_variant_intents_classify_to_customer_question_shape():
    assert classify_query_fact_type("\u653e\u5ba2\u5385\u6742\u7269\u4f1a\u4e0d\u4f1a\u6643\uff1f")["query_fact_type"] == "stability"
    assert classify_query_fact_type("\u5367\u5ba4\u7a7a\u95f4\u5c0f\u80fd\u653e\u5417\uff1f")["query_fact_type"] == "space_fit"
    usage_cases = {
        "\u80fd\u4e0d\u80fd\u653e\u5c0f\u670b\u53cb\u7684\u4e1c\u897f\uff1f": "stability",
        "\u53ef\u4ee5\u653e\u5b69\u5b50\u7684\u73a9\u5177\u5417\uff1f": "stability",
        "\u80fd\u653e\u5b9d\u5b9d\u7528\u54c1\u5417\uff1f": "stability",
        "\u9002\u5408\u653e\u513f\u7ae5\u7528\u54c1\u5417\uff1f": "stability",
        "\u653e\u7ed8\u672c\u7a33\u5417\uff1f": "stability",
        "\u653e\u4e66\u4f1a\u4e0d\u4f1a\u538b\u584c\uff1f": "load_capacity",
    }
    for message, expected in usage_cases.items():
        assert classify_query_fact_type(message)["query_fact_type"] == expected

    scene_cases = {
        "\u5367\u5ba4\u80fd\u4e0d\u80fd\u653e\uff1f": {"placement_scene", "space_fit"},
        "\u536b\u751f\u95f4\u80fd\u4e0d\u80fd\u653e\uff1f": {"placement_scene", "material"},
        "\u9633\u53f0\u80fd\u4e0d\u80fd\u653e\uff1f": {"placement_scene"},
    }
    for message, expected_types in scene_cases.items():
        fact_type = classify_query_fact_type(message)["query_fact_type"]
        assert fact_type in expected_types
        assert fact_type != "stability"

    space_cases = {
        "\u5367\u5ba4\u7a7a\u95f4\u5c0f\u80fd\u653e\u5417\uff1f": "space_fit",
        "5\u5e73\u65b9\u591f\u4e0d\u591f\u653e\uff1f": "space_fit",
        "\u8fd9\u4e2a\u5c3a\u5bf8\u591a\u5927\uff1f": "dimensions",
    }
    for message, expected in space_cases.items():
        assert classify_query_fact_type(message)["query_fact_type"] == expected


def test_legal_answers_pass_renderer_contracts():
    response = {
        "query_fact_type": "load_capacity",
        "required_fact_types": ["load_capacity"],
        "evidence_debug": {"query_fact_type": "load_capacity"},
    }
    legal = "亲亲，这款适合放绘本、玩具和日用品，重一点的东西建议放在下层，整体会更稳一些。"
    assert not semantic_compiler_issues(legal, response=response, customer_message="放绘本稳吗？")

    dimensions = {
        "query_fact_type": "dimensions",
        "required_fact_types": ["dimensions"],
        "evidence_debug": {"query_fact_type": "dimensions"},
    }
    legal_dimensions = "亲亲，尺寸可以先按页面标注参考：长宽高约 60cm、30cm、80cm，您也可以把预留空间发我核对。"
    assert not semantic_compiler_issues(legal_dimensions, response=dimensions, customer_message="这个尺寸多大？")

    install = {
        "query_fact_type": "installation",
        "required_fact_types": ["installation"],
        "evidence_debug": {"query_fact_type": "installation"},
    }
    legal_install = "亲亲，安装一般先核对配件，再按说明书从主体框架开始装；目前没有可直接发送的安装视频。"
    assert not semantic_compiler_issues(legal_install, response=install, customer_message="有没有安装视频？")

    with_asset = {
        "query_fact_type": "visual_asset",
        "required_fact_types": ["visual_asset"],
        "selected_assets": [{"asset_id": "asset-1", "asset_type": "image", "asset_url": "https://example.test/a.jpg"}],
        "evidence_debug": {"query_fact_type": "visual_asset"},
    }
    legal_media = "亲亲，我把对应图片发您参考，具体细节以页面标注为准。"
    assert not semantic_compiler_issues(legal_media, response=with_asset, customer_message="有没有图？")
