import pytest


def _run_post_processor(kwargs, response):
    post_processor = kwargs.get("response_post_processor")
    return post_processor(response) if callable(post_processor) else response


@pytest.fixture()
def client():
    import app.models.kb_tables  # noqa: F401
    from app.db import init_db
    from app.main import create_app

    init_db()
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_analyze_final_output_polishes_after_media_stage(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    def fake_execute_analysis(**kwargs):
        return _run_post_processor(kwargs, {
            "intent": "material_safety",
            "suggested_reply": (
                "亲～\n"
                "宝宝用的东西您关心材质和安全很正常，我先按当前商品「九号防夹滑门收纳柜」帮您核实一下准确说法。\n"
                "材质和防潮说明这类信息我不先凭感觉判断，避免给您说错。"
            ),
            "requires_human_review": True,
            "context_used": {
                "conversation_context_summary": {
                    "confirmed_product": "九号防夹滑门收纳柜",
                }
            },
            "evidence_debug": {"query_fact_type": "material"},
        })

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)

    response = client.post("/api/analyze", json={
        "message": "这个材质安全吗？会不会容易受潮？",
        "product_name": "九号防夹滑门收纳柜",
        "conversation_id": "pytest_final_output_contract",
    })

    assert response.status_code == 200
    data = response.get_json()
    reply = data["suggested_reply"]
    assert "九号防夹滑门收纳柜" in reply
    assert "准确说法" not in reply
    assert "凭感觉" not in reply
    assert "系统里" not in reply
    assert data["customer_reply_polish"]["applied"] is True
    assert data["reply_blocks"][0]["type"] == "text"


def test_analyze_uses_product_pack_media_as_send_blocks(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    def fake_execute_analysis(**kwargs):
        return _run_post_processor(kwargs, {
            "intent": "installation",
            "suggested_reply": "亲～安装视频我一起发您参考。",
            "requires_human_review": False,
            "context_used": {
                "product_context_pack": {
                    "recommended_assets": [{
                        "asset_id": 12,
                        "asset_type": "install_video",
                        "asset_title": "安装视频",
                        "asset_url": "https://example.com/install.mp4",
                        "product_name": "一号喂养柜",
                        "send_mode": "auto_when_platform_connected",
                    }]
                },
                "conversation_context_summary": {
                    "confirmed_product": "一号喂养柜",
                },
            },
            "evidence_debug": {"query_fact_type": "installation"},
        })

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)

    response = client.post("/api/analyze", json={
        "message": "这个怎么安装？有视频吗？",
        "product_name": "一号喂养柜",
        "conversation_id": "pytest_pack_media_blocks",
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data["recommended_assets"][0]["asset_type"] == "install_video"
    assert [block["type"] for block in data["reply_blocks"]] == ["text", "video"]
    assert data["reply_delivery"]["auto_send_ready"] is False
    assert data["reply_delivery"]["reason"] == "final_sendable_contract_blocked"
    assert data["reply_blocks"][1]["send_mode"] == "auto_when_platform_connected"


def test_analyze_allows_identity_matched_size_media_as_send_blocks(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    def fake_execute_analysis(**kwargs):
        return _run_post_processor(kwargs, {
            "intent": "product_question",
            "suggested_reply": "Please measure width, depth and height, then compare with the size image.",
            "requires_human_review": False,
            "context_used": {
                "product_context_pack": {
                    "recommended_assets": [{
                        "asset_id": 14,
                            "asset_type": "size_image",
                            "asset_title": "Dimension reference",
                            "asset_url": "https://example.com/size-marked.png",
                            "product_name": "Test product",
                            "i_id": "IID-A",
                        "auto_send_level": "auto",
                    }]
                },
                "conversation_context_summary": {
                    "confirmed_product": "Test product",
                },
            },
            "evidence_debug": {"query_fact_type": "space_fit"},
        })

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)

    response = client.post("/api/analyze", json={
        "message": "small bedroom, can it fit?",
        "product_name": "Test product",
        "copilot_context": {"i_id": "IID-A"},
        "conversation_id": "pytest_pack_media_space_fit",
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data["recommended_assets"][0]["asset_type"] == "size_image"
    assert [block["type"] for block in data["reply_blocks"]] == ["text", "image"]
    assert data["reply_delivery"]["auto_send_ready"] is True


def test_analyze_blocks_space_fit_plain_sku_image_auto_send(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    def fake_execute_analysis(**kwargs):
        return _run_post_processor(kwargs, {
            "intent": "product_question",
            "suggested_reply": "Please compare with the product image.",
            "requires_human_review": False,
            "context_used": {
                "product_context_pack": {
                    "recommended_assets": [{
                        "asset_id": 15,
                        "asset_type": "sku_image",
                        "asset_title": "Product appearance image",
                        "asset_url": "https://example.com/product.png",
                        "product_name": "Test product",
                        "auto_send_level": "auto",
                    }]
                },
                "conversation_context_summary": {
                    "confirmed_product": "Test product",
                },
            },
            "evidence_debug": {"query_fact_type": "space_fit"},
        })

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)

    response = client.post("/api/analyze", json={
        "message": "small bedroom, can it fit?",
        "product_name": "Test product",
        "conversation_id": "pytest_plain_sku_image_space_fit",
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data["recommended_assets"] == []
    assert data["reply_delivery"]["auto_send_ready"] is False
    assert data["can_send"] is False
    assert data["requires_human_review"] is True


def test_analyze_keeps_pack_media_preview_only_when_review_required(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    def fake_execute_analysis(**kwargs):
        return _run_post_processor(kwargs, {
            "intent": "material_safety",
            "suggested_reply": "亲～这个我帮您确认后回复。",
            "requires_human_review": True,
            "context_used": {
                "product_context_pack": {
                    "recommended_assets": [{
                        "asset_id": 13,
                        "asset_type": "size_image",
                        "asset_title": "尺寸图",
                        "asset_url": "https://example.com/size.png",
                        "product_name": "测试商品",
                    }]
                },
                "conversation_context_summary": {
                    "confirmed_product": "测试商品",
                },
            },
            "evidence_debug": {"query_fact_type": "material"},
        })

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)

    response = client.post("/api/analyze", json={
        "message": "这个安全吗？",
        "product_name": "测试商品",
        "conversation_id": "pytest_pack_media_review",
    })

    assert response.status_code == 200
    data = response.get_json()
    assert [block["type"] for block in data["reply_blocks"]] == ["text"]
    assert data["reply_delivery"]["auto_send_ready"] is False
    assert data["recommended_assets"] == []
