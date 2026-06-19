from app.services.answer_composition_service import compose_customer_reply
from app.services.final_answer_auditor import audit_final_answer


def _grouping(*fact_types: str) -> dict:
    return {
        "groups": [],
        "coverage": {"required_fact_types": list(fact_types)},
    }


def _compose(fact_type: str, *, evidence=None, secondary=None, assets=None, message="请帮我看一下") -> dict:
    secondary = secondary or []
    required = [fact_type, *secondary]
    return compose_customer_reply(
        customer_message=message,
        base_reply="",
        query_understanding={
            "query_fact_type": fact_type,
            "secondary_fact_types": secondary,
            "required_fact_types": required,
        },
        evidence_grouping=_grouping(*required),
        selected_evidence=evidence or [],
        selected_assets=assets or [],
        product_name="",
        risk_level="low",
        intent="product_question",
        identity_context={},
    )


def test_material_similar_evidence_is_deduped_and_merged_naturally():
    evidence = [
        {
            "entry_id": "e1",
            "chunk_id": "c1",
            "fact_type": "material",
            "source_type": "product_facts",
            "chunk_text": "主要采用冷轧钢管/环保PP/无纺布等材质，金属部分经过防锈喷涂处理，具备一定防潮能力。",
            "selected": True,
        },
        {
            "entry_id": "e2",
            "chunk_id": "c2",
            "fact_type": "material",
            "source_type": "product_facts",
            "chunk_text": "主要采用冷轧钢管、环保PP和无纺布等材质；金属部分经过防锈喷涂处理，具备一定防潮能力。潮湿环境下建议放在干燥通风处，避免长期积水。",
            "selected": True,
        },
    ]

    result = _compose(
        "material",
        evidence=evidence,
        message="宝宝能用吗，会不会容易受潮？",
    )
    reply = result["composed_reply"]
    trace = result["composition_trace"]

    assert reply.count("冷轧钢") == 1
    assert reply.count("环保PP") == 1
    assert "防潮" in reply
    assert "干燥通风" in reply
    assert "绝对安全" not in reply
    assert "0甲醛" not in reply
    assert "完全无害" not in reply
    assert trace["evidence_dedup"]["before_count"] == 2
    assert trace["evidence_dedup"]["after_count"] == 1
    assert trace["evidence_dedup"]["removed_count"] == 1


def test_dimensions_without_asset_but_with_text_fact_answers_text_first():
    result = _compose(
        "dimensions",
        evidence=[{
            "entry_id": "dim-1",
            "chunk_id": "dim-c1",
            "fact_type": "dimensions",
            "source_type": "product_facts",
            "chunk_text": "页面标注尺寸为长80cm、宽35cm、高120cm。",
            "selected": True,
        }],
        message="尺寸多大，有没有图？",
    )
    reply = result["composed_reply"]

    assert "长80cm" in reply
    assert "宽35cm" in reply
    assert "高120cm" in reply
    assert "下面发" not in reply
    assert "确认清楚后再回复" not in reply


def test_dimensions_without_asset_or_text_uses_dimension_specific_fallback():
    result = _compose("dimensions", message="尺寸多大，有没有图？")
    reply = result["composed_reply"]

    assert "尺寸图" in reply
    assert "页面标注" in reply
    assert "预留空间" in reply
    assert "下面发" not in reply
    assert "确认清楚后再回复" not in reply


def test_installation_without_video_gives_basic_steps_without_off_topic_facts():
    result = _compose("installation", message="怎么安装，有视频吗？")
    reply = result["composed_reply"]

    assert "安装" in reply
    assert "说明书" in reply
    assert "安装视频" in reply
    assert "下面发" not in reply
    assert "材质" not in reply
    assert "防潮" not in reply
    assert "承重" not in reply


def test_certification_without_report_can_use_material_only_as_secondary():
    result = _compose(
        "certification_report",
        secondary=["material"],
        evidence=[{
            "entry_id": "mat-1",
            "chunk_id": "mat-c1",
            "fact_type": "material",
            "source_type": "product_facts",
            "chunk_text": "主要采用冷轧钢管、环保PP和无纺布等材质。",
            "selected": True,
        }],
        message="有没有检测报告，安全吗？",
    )
    reply = result["composed_reply"]
    trace = result["composition_trace"]

    assert "检测报告" in reply
    assert "没有看到对应报告" in reply
    assert "冷轧钢管" in reply
    assert "有检测报告" not in reply
    assert "已通过检测" not in reply
    assert "绝对安全" not in reply
    assert "certification_report" in trace["needs_followup_fact_types"]
    assert "material" in trace["evidence_answered_fact_types"]


def test_visual_asset_positive_path_records_asset_trace():
    result = _compose(
        "visual_asset",
        secondary=["dimensions"],
        assets=[{
            "asset_id": "asset-size-1",
            "asset_type": "size_image",
            "asset_title": "尺寸图",
            "asset_url": "https://example.com/size.png",
            "source_type": "product_media",
        }],
        message="尺寸多大，有没有图？",
    )
    reply = result["composed_reply"]
    trace = result["composition_trace"]

    assert "图片" in reply
    assert "参考" in reply
    assert trace["asset_evidence_used"]["visual_asset"][0]["asset_type"] == "size_image"


def test_final_auditor_blocks_unsupported_certification_claim():
    response = {
        "intent": "product_question",
        "query_fact_type": "certification_report",
        "suggested_reply": "亲亲，这款有检测报告，已经通过检测，可以放心使用。",
        "evidence_debug": {
            "query_fact_type": "certification_report",
            "answer_trace": {
                "query_fact_type": "certification_report",
                "required_fact_types": ["certification_report"],
                "trace_contract_broken": False,
            },
        },
    }

    audited = audit_final_answer(response, customer_message="有没有检测报告，安全吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert "unsupported_certification_report_claim" in audited["final_answer_audit"]["issues"]


def test_final_auditor_blocks_material_question_answered_as_load_capacity():
    response = {
        "intent": "product_question",
        "query_fact_type": "material",
        "suggested_reply": "亲亲，这款承重/容量是2.65，日常放东西没问题。",
        "evidence_debug": {"query_fact_type": "material"},
    }

    audited = audit_final_answer(response, customer_message="这个材质安全吗？会不会容易受潮？")

    assert audited["final_answer_audit"]["passed"] is False
    assert any(issue.startswith("wrong_topic:material") for issue in audited["final_answer_audit"]["issues"])
