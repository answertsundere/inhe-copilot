from app.services.evidence_rerank_service import _evidence_key, rerank_evidence


def _ev(fact_type, text, *, origin="product_facts", source_type="product_facts", score=1):
    return {
        "entry_id": f"{origin}-{fact_type}-{abs(hash(text))}",
        "source_type": source_type,
        "evidence_origin": origin,
        "fact_type": fact_type,
        "evidence_fact_type": fact_type,
        "chunk_text": text,
        "score": score,
        "rerank_score": score,
    }


def _asset(asset_type, fact_type, *, url="https://example.test/a.jpg", status="approved", usable=True):
    return {
        "asset_id": f"asset-{asset_type}",
        "id": f"asset-{asset_type}",
        "asset_type": asset_type,
        "asset_title": asset_type,
        "asset_url": url,
        "source_type": "product_media",
        "evidence_origin": "product_media",
        "fact_type": fact_type,
        "evidence_fact_type": fact_type,
        "status": status,
        "usable_for_agent": usable,
    }


def _keys(items):
    return {_evidence_key(item) for item in items}


def _trace_states(result):
    states = {}
    for row in result["rerank_trace"]:
        key = row.get("rerank_key") or row.get("evidence_id")
        states.setdefault(key, set()).add(bool(row.get("selected")))
    return states


def test_dimensions_question_selects_dimensions_not_load_capacity():
    result = rerank_evidence(
        retrieved_evidence=[
            _ev("load_capacity", "承重/容量: 8.58", score=99),
            _ev("dimensions", "长宽高 120*40*80cm", score=1),
        ],
        query_fact_type="dimensions",
        required_fact_types=["dimensions"],
    )

    assert result["primary_fact_type"] == "dimensions"
    assert result["selected_evidence"][0]["evidence_fact_type"] == "dimensions"
    assert all(item["role"] != "direct_answer" for item in result["rejected_evidence"] if item["evidence_fact_type"] == "load_capacity")
    assert any(item["reject_reason"] for item in result["rejected_evidence"])


def test_space_fit_rejects_load_capacity_as_direct_evidence():
    result = rerank_evidence(
        retrieved_evidence=[
            _ev("load_capacity", "单层承重 20kg", score=99),
            _ev("dimensions", "宽度 60cm，进深 35cm", score=1),
            _ev("placement_scene", "卧室建议预留开合空间", score=1),
        ],
        query_fact_type="space_fit",
        required_fact_types=["space_fit"],
    )

    selected_types = [item["evidence_fact_type"] for item in result["selected_evidence"]]
    assert selected_types[0] in {"dimensions", "placement_scene"}
    assert "load_capacity" not in selected_types[:1]


def test_certification_report_cannot_use_material_as_direct_evidence():
    result = rerank_evidence(
        retrieved_evidence=[_ev("material", "环保PP，冷轧钢管")],
        query_fact_type="certification_report",
        required_fact_types=["certification_report"],
    )

    assert not result["selected_evidence"]
    assert result["rejected_evidence"][0]["reject_reason"] == "certification_requires_report_evidence"


def test_certificate_image_can_support_certification_report():
    result = rerank_evidence(
        product_context_pack={"media_evidence": [_asset("certificate_image", "certification_report")]},
        query_fact_type="certification_report",
        required_fact_types=["certification_report"],
    )

    assert result["selected_evidence"][0]["role"] == "direct_answer"
    assert result["selected_evidence"][0]["asset_type"] == "certificate_image"
    assert result["selected_assets"][0]["asset_type"] == "certificate_image"


def test_install_video_beats_installation_text_for_media_answer():
    result = rerank_evidence(
        retrieved_evidence=[_ev("installation", "先核对配件，再按说明书安装", score=20)],
        product_context_pack={"media_evidence": [_asset("install_video", "installation")]},
        query_fact_type="installation",
        required_fact_types=["installation"],
    )

    assert result["selected_evidence"][0]["asset_type"] == "install_video"
    assert result["selected_assets"][0]["asset_type"] == "install_video"


def test_unsendable_install_video_is_rejected():
    result = rerank_evidence(
        product_context_pack={"media_evidence": [_asset("install_video", "installation", url="")]},
        query_fact_type="installation",
        required_fact_types=["installation"],
    )

    assert not result["selected_assets"]
    assert result["rejected_evidence"][0]["reject_reason"] == "media_not_sendable"


def test_product_card_beats_generic_rule_for_detachable():
    result = rerank_evidence(
        product_context_pack={
            "product_card_evidence": [_ev("detachable", "商品卡片：不可拆卸", origin="product_card", score=1)],
            "generic_rules": [_ev("detachable", "通用规则：多数可以拆卸", origin="generic_rules", source_type="generic_rules", score=99)],
        },
        query_fact_type="detachable",
        required_fact_types=["detachable"],
    )

    assert result["selected_evidence"][0]["evidence_origin"] == "product_card"
    assert any(item["evidence_origin"] == "generic_rules" for item in result["rejected_evidence"])


def test_stability_uses_load_capacity_only_as_supporting_evidence():
    result = rerank_evidence(
        retrieved_evidence=[
            _ev("load_capacity", "承重/容量: 8.58", score=99),
            _ev("stability", "放在平整地面，重物建议放下层", score=1),
        ],
        query_fact_type="stability",
        required_fact_types=["stability"],
    )

    roles = {item["evidence_fact_type"]: item["role"] for item in result["selected_evidence"]}
    assert roles["stability"] == "direct_answer"
    assert roles["load_capacity"] == "supporting_evidence"
    assert result["rerank_trace"]
    assert result["evidence_origin_by_fact_type"]


def test_selected_and_rejected_do_not_overlap_for_evidence_without_ids():
    result = rerank_evidence(
        retrieved_evidence=[
            {"fact_type": "dimensions", "fact": "长宽高 120*40*80cm", "score": 1},
            {"fact_type": "load_capacity", "fact": "承重/容量: 8.58", "score": 99},
        ],
        product_context_pack={},
        query_fact_type="dimensions",
        required_fact_types=["dimensions"],
    )

    assert any(item["evidence_fact_type"] == "dimensions" for item in result["selected_evidence"])
    assert not (_keys(result["selected_evidence"]) & _keys(result["rejected_evidence"]))
    selected_dimension_keys = {
        _evidence_key(item)
        for item in result["selected_evidence"]
        if item["evidence_fact_type"] == "dimensions"
    }
    rejected_dimension_keys = {
        _evidence_key(item)
        for item in result["rejected_evidence"]
        if item["evidence_fact_type"] == "dimensions"
    }
    assert not (selected_dimension_keys & rejected_dimension_keys)


def test_supporting_evidence_selected_once_and_not_rejected_without_ids():
    result = rerank_evidence(
        retrieved_evidence=[
            {"fact_type": "stability", "fact": "放在平整地面，重物建议放下层", "score": 1},
            {"fact_type": "load_capacity", "fact": "承重/容量: 8.58", "score": 99},
        ],
        product_context_pack={},
        query_fact_type="stability",
        required_fact_types=["stability"],
    )

    roles = {item["evidence_fact_type"]: item["role"] for item in result["selected_evidence"]}
    assert roles["stability"] == "direct_answer"
    assert roles["load_capacity"] == "supporting_evidence"
    assert not (_keys(result["selected_evidence"]) & _keys(result["rejected_evidence"]))
    assert all(len(states) == 1 for states in _trace_states(result).values())
    assert all(row["reject_reason"] == "" for row in result["rerank_trace"] if row["selected"])


def test_evidence_key_is_stable_after_dict_copy_without_ids():
    ev = {"fact_type": "dimensions", "fact": "长宽高 120*40*80cm"}
    ev_copy = {**ev}

    assert _evidence_key(ev) == _evidence_key(ev_copy)


def test_real_entry_id_still_dedupes_duplicate_evidence():
    result = rerank_evidence(
        retrieved_evidence=[
            {"entry_id": "E1", "fact_type": "dimensions", "fact": "长宽高 120*40*80cm", "score": 1},
            {"entry_id": "E1", "fact_type": "dimensions", "fact": "长宽高 120*40*80cm", "score": 99},
        ],
        product_context_pack={},
        query_fact_type="dimensions",
        required_fact_types=["dimensions"],
    )

    selected_and_rejected = result["selected_evidence"] + result["rejected_evidence"]
    assert len([item for item in selected_and_rejected if item.get("entry_id") == "E1"]) == 1
    assert len([row for row in result["rerank_trace"] if row.get("entry_id") == "E1"]) == 1
