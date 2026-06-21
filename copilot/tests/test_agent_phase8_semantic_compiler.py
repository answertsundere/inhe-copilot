from app.services.answer_trace_service import attach_answer_trace
from app.services.final_response_orchestrator import orchestrate_final_response
from app.services.semantic_compiler_service import (
    compile_customer_response,
    semantic_compiler_issues,
    validate_final_output_contract,
)


def _response(
    *,
    reply: str,
    query_fact_type: str,
    required_fact_types: list[str] | None = None,
    evidence: list[dict] | None = None,
    selected_assets: list[dict] | None = None,
) -> dict:
    required = required_fact_types or [query_fact_type]
    return {
        "suggested_reply": reply,
        "query_fact_type": query_fact_type,
        "required_fact_types": required,
        "selected_assets": selected_assets or [],
        "evidence_debug": {
            "query_fact_type": query_fact_type,
            "required_fact_types": required,
            "selected_evidence": evidence or [],
            "evidence_grouping": {"coverage": {"required_fact_types": required}},
        },
    }


def test_semantic_compiler_rerenders_current_bad_shape_from_blocks():
    response = _response(
        reply="亲～ 关于这款商品：承重/容量: 8.58。",
        query_fact_type="load_capacity",
        evidence=[
            {
                "source_type": "product_facts",
                "fact_type": "load_capacity",
                "evidence_fact_type": "load_capacity",
                "entry_id": "load-1",
                "fact": "承重/容量: 8.58",
            }
        ],
    )

    compiled = compile_customer_response(response, customer_message="这个适合放宝宝玩具吗？稳不稳？")

    assert compiled["semantic_compiler_result"]["renderer_used"] is True
    assert compiled["semantic_compiler_result"]["blocked_raw_text"]
    assert "承重/容量:" not in compiled["suggested_reply"]
    assert "适合" in compiled["suggested_reply"]
    assert any(term in compiled["suggested_reply"] for term in ("下层", "均匀", "更稳", "平整"))
    assert compiled["final_quality_pass"] is True


def test_semantic_compiler_rejects_question_answer_mismatch_shapes():
    dimensions_response = _response(
        reply="亲亲，这款承重不错，重一点可以放下层。",
        query_fact_type="dimensions",
        evidence=[],
    )
    issues = semantic_compiler_issues(
        dimensions_response["suggested_reply"],
        response=dimensions_response,
        customer_message="这个尺寸多大？",
    )
    assert "missing_answer:dimensions" in issues
    assert any(issue.startswith("off_topic:dimensions") for issue in issues)

    scene_response = _response(
        reply="亲亲，这款主要是 PP 材质，日常注意防潮。",
        query_fact_type="placement_scene",
        evidence=[],
    )
    issues = semantic_compiler_issues(
        scene_response["suggested_reply"],
        response=scene_response,
        customer_message="卧室能不能放？",
    )
    assert "missing_answer:placement_scene" in issues

    report_response = _response(
        reply="亲亲，这款是 PP 材质，宝宝用的东西谨慎一点。",
        query_fact_type="certification_report",
        evidence=[
            {
                "source_type": "product_facts",
                "fact_type": "material",
                "evidence_fact_type": "material",
                "fact": "材质: PP",
            }
        ],
    )
    issues = semantic_compiler_issues(
        report_response["suggested_reply"],
        response=report_response,
        customer_message="有检测报告吗？",
    )
    assert "missing_answer:certification_report" in issues
    assert "off_topic:certification_report_answered_as_material" in issues


def test_semantic_compiler_blocks_unsupported_install_video_claim():
    response = _response(
        reply="亲亲，下面发安装视频给您参考。",
        query_fact_type="installation",
        evidence=[],
        selected_assets=[],
    )

    compiled = compile_customer_response(response, customer_message="有没有安装视频？")

    assert "下面发" not in compiled["suggested_reply"]
    assert "目前没有可直接发送的安装视频" in compiled["suggested_reply"]
    assert compiled["semantic_compiler_result"]["renderer_used"] is True


def test_post_compiler_validation_blocks_late_text_pollution():
    response = _response(
        reply="亲亲，尺寸可以先按页面标注参考，您也可以把预留空间发我核对。",
        query_fact_type="dimensions",
        evidence=[],
    )
    compiled = compile_customer_response(response, customer_message="这个尺寸多大？")
    assert compiled["final_quality_pass"] is True

    compiled["suggested_reply"] = "尺寸: 2.65"
    final = validate_final_output_contract(compiled, customer_message="这个尺寸多大？")
    compiler = final["semantic_compiler_result"]

    assert "尺寸: 2.65" not in final["suggested_reply"]
    assert compiler["post_compiler_validation"]["fallback_used"] is True
    assert compiler["blocked_raw_text"] == "尺寸: 2.65"
    assert compiler["final_text_passed"] is True
    assert final["final_quality_pass"] is True


def test_certification_report_block_does_not_treat_mislabeled_load_fact_as_report():
    response = _response(
        reply="亲亲，这个有检测报告，承重/容量: 2.65。",
        query_fact_type="certification_report",
        evidence=[
            {
                "source_type": "product_facts",
                "fact_type": "certification_report",
                "evidence_fact_type": "certification_report",
                "entry_id": "dirty-cert-1",
                "fact": "承重/容量: 2.65",
            }
        ],
    )

    compiled = compile_customer_response(response, customer_message="有检测报告吗？")

    assert "承重/容量:" not in compiled["suggested_reply"]
    assert "有检测报告" not in compiled["suggested_reply"]
    assert "可以参考对应报告素材" not in compiled["suggested_reply"]
    assert "不能直接替您下检测结论" in compiled["suggested_reply"]


def test_orchestrator_trace_records_blocks_renderer_and_compiler_result(monkeypatch):
    monkeypatch.setattr("app.config.COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    monkeypatch.setattr("app.config.COPILOT_FINAL_POLISH_LLM_ENABLED", False)
    response = _response(
        reply="亲亲，关于这款：承重/容量: 8.58",
        query_fact_type="load_capacity",
        evidence=[
            {
                "source_type": "product_facts",
                "fact_type": "load_capacity",
                "evidence_fact_type": "load_capacity",
                "entry_id": "load-1",
                "fact": "承重/容量: 8.58",
            }
        ],
    )

    final = orchestrate_final_response(
        response,
        customer_message="放书会不会压塌？",
        copilot_context={},
    )
    final = attach_answer_trace(final, customer_message="放书会不会压塌？")
    trace = final["answer_trace"]

    assert "承重/容量:" not in final["suggested_reply"]
    assert trace["answer_blocks"]
    assert trace["semantic_compiler_result"]["passed"] is True
    assert trace["renderer_used"] is True
    assert trace["blocked_raw_text"]
    assert trace["final_quality_pass"] is True
    assert trace["reject_reason"] == []
