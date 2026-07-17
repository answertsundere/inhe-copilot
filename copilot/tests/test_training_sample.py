"""
客服训练样本 API 测试
覆盖：创建、列表、详情、更新、base64 图片提取、附件上传
"""

from __future__ import annotations

import base64
import io
import json

from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_client(monkeypatch, tmp_path):
    import app.db as db_module
    from app.api import training_sample_routes
    from app.repositories import training_sample_repository
    from app.api.training_sample_routes import training_sample_bp
    from app.models.kb_tables import KBTrainingSample, KBTrainingSampleAttachment

    engine = create_engine(
        f"sqlite:///{tmp_path / 'training_sample.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(
        training_sample_repository, "SessionLocal", session_factory
    )
    db_module.Base.metadata.create_all(bind=engine)

    upload_dir = tmp_path / "training_sample_uploads"
    monkeypatch.setenv("COPILOT_TRAINING_SAMPLE_UPLOAD_DIR", str(upload_dir))

    app = Flask(__name__)
    app.register_blueprint(training_sample_bp, url_prefix="/api/kb")
    return app.test_client(), session_factory


def _create_sample(client, **overrides):
    payload = {
        "customer_quote": "这个婴儿床能不能睡到5岁？",
        "full_context": "客户问：这个婴儿床能不能睡到5岁？\n客服答：建议3岁。",
        "product_title": "实木婴儿床",
        "sku": "BED001",
        "order_no": "ORDER001",
        "question_type": "年龄适配",
        "difficulty_reason": "知识库没有",
        "csr_actual_reply": "可以睡到3岁",
        "correct_answer": "建议睡到3岁，5岁需换床",
        "risk_level": "中",
        "auto_reply_type": "需人工确认",
        "review_status": "待处理",
    }
    payload.update(overrides)
    return client.post("/api/kb/training-samples", json=payload)


def test_create_training_sample_success(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    res = _create_sample(client)
    assert res.status_code == 201
    body = res.get_json()
    assert body["id"]
    assert body["data"]["customer_quote"] == "这个婴儿床能不能睡到5岁？"
    assert body["data"]["review_status"] == "待处理"


def test_create_requires_customer_quote(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    res = _create_sample(client, customer_quote="")
    assert res.status_code == 400
    assert "客户原话" in res.get_json()["error"]


def test_list_training_samples(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    _create_sample(client)
    _create_sample(
        client,
        customer_quote="怎么安装？",
        full_context="客户问：怎么安装？",
        question_type="安装",
        product_title="婴儿床护栏",
    )

    res = client.get("/api/kb/training-samples")
    assert res.status_code == 200
    body = res.get_json()
    assert body["total"] == 2

    res = client.get("/api/kb/training-samples?question_type=安装")
    assert res.get_json()["total"] == 1

    res = client.get("/api/kb/training-samples?keyword=能不能睡到")
    assert res.get_json()["total"] == 1


def test_list_training_samples_uses_bounded_summary_and_detail_keeps_rich_content(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    rich_quote = "<p>客户问题</p><img src=\"data:image/png;base64," + ("a" * 5000) + "\">"
    full_context = "完整上下文" * 1000
    sample_id = _create_sample(
        client,
        customer_quote=rich_quote,
        full_context=full_context,
        csr_actual_reply="客服原回复" * 1000,
        correct_answer="标准答案" * 1000,
    ).get_json()["id"]

    list_body = client.get("/api/kb/training-samples").get_json()
    item = list_body["items"][0]
    assert item["id"] == sample_id
    assert item["customer_quote_preview"] == "客户问题"
    assert "customer_quote" not in item
    assert "full_context" not in item
    assert "csr_actual_reply" not in item
    assert "correct_answer" not in item
    assert "attachments" not in item
    assert "eval_contract" not in item
    assert len(json.dumps(list_body, ensure_ascii=False)) < 3000

    detail = client.get(f"/api/kb/training-samples/{sample_id}").get_json()
    assert detail["full_context"] == full_context
    assert detail["customer_quote"].startswith("<p>客户问题</p>")


def test_get_training_sample_detail(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    sample_id = _create_sample(client).get_json()["id"]

    res = client.get(f"/api/kb/training-samples/{sample_id}")
    assert res.status_code == 200
    body = res.get_json()
    assert body["id"] == sample_id
    assert body["sku"] == "BED001"


def test_update_training_sample(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    sample_id = _create_sample(client).get_json()["id"]

    res = client.patch(
        f"/api/kb/training-samples/{sample_id}",
        json={
            "review_status": "已确认",
            "correct_answer": "最终标准答案",
            "owner": "主管A",
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["review_status"] == "已确认"
    assert body["owner"] == "主管A"


def test_extract_base64_image_on_create(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    image_bytes = b"fake image bytes"
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    html = f'<p>客户问题<img src="data:image/png;base64,{b64}"></p>'

    res = _create_sample(client, customer_quote=html)
    assert res.status_code == 201
    body = res.get_json()
    sample_id = body["id"]

    # base64 应被替换为附件 URL
    assert "/ask/api/kb/training-samples/" in body["data"]["customer_quote"]
    assert "data:image/png;base64" not in body["data"]["customer_quote"]
    assert len(body["data"]["attachments"]) == 1
    assert body["data"]["attachments"][0]["field_name"] == "customer_quote"


def test_upload_attachment(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    sample_id = _create_sample(client).get_json()["id"]

    data = {
        "file": (io.BytesIO(b"fake image bytes"), "screenshot.png", "image/png"),
        "field_name": "full_context",
    }
    res = client.post(
        f"/api/kb/training-samples/{sample_id}/attachments",
        data=data,
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["field_name"] == "full_context"


def test_upload_rejects_non_image(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    sample_id = _create_sample(client).get_json()["id"]

    data = {
        "file": (io.BytesIO(b"not image"), "doc.pdf", "application/pdf"),
    }
    res = client.post(
        f"/api/kb/training-samples/{sample_id}/attachments",
        data=data,
        content_type="multipart/form-data",
    )
    assert res.status_code == 400


def test_get_attachment(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    sample_id = _create_sample(client).get_json()["id"]

    data = {
        "file": (io.BytesIO(b"fake image bytes"), "screenshot.png", "image/png"),
    }
    att = client.post(
        f"/api/kb/training-samples/{sample_id}/attachments",
        data=data,
        content_type="multipart/form-data",
    ).get_json()

    res = client.get(f"/api/kb/training-samples/{sample_id}/attachments/{att['id']}")
    assert res.status_code == 200
    assert res.mimetype == "image/png"


def test_delete_attachment(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path)
    sample_id = _create_sample(client).get_json()["id"]

    data = {
        "file": (io.BytesIO(b"fake image bytes"), "screenshot.png", "image/png"),
    }
    att = client.post(
        f"/api/kb/training-samples/{sample_id}/attachments",
        data=data,
        content_type="multipart/form-data",
    ).get_json()

    res = client.delete(f"/api/kb/training-samples/{sample_id}/attachments/{att['id']}")
    assert res.status_code == 200
    assert res.get_json()["deleted"] is True
