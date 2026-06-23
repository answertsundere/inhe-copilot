import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import Base
from app.models.eval_tables import EvalCase, EvalConversationTurn
from app.services.eval_sanitizer_service import sanitize_text
from app.services.real_conversation_import_service import (
    collect_real_conversation_samples,
    write_samples_to_db,
)


def _patch_test_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    return session_factory


def test_real_conversation_sanitizer_redacts_sensitive_values():
    raw = (
        "手机 13812345678，订单 123456789012345，地址 浙江省杭州市西湖区文三路99号，"
        "微信 wx_test001，https://demo.oss-cn-hangzhou.aliyuncs.com/a.jpg?Expires=1&Signature=abc&OSSAccessKeyId=key，"
        "api_key=secret-value data:image/png;base64," + "a" * 120
    )

    cleaned = sanitize_text(raw)

    assert "13812345678" not in cleaned
    assert "123456789012345" not in cleaned
    assert "文三路99号" not in cleaned
    assert "wx_test001" not in cleaned
    assert "Signature=abc" not in cleaned
    assert "OSSAccessKeyId" not in cleaned
    assert "secret-value" not in cleaned
    assert "data:image/png;base64" not in cleaned
    assert "[PHONE_REDACTED]" in cleaned
    assert "[SIGNED_URL_REDACTED:" in cleaned


def test_import_real_conversation_dry_run_collects_without_writing(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    payload = {
        "conversation_id": "conv-1",
        "platform": "tb",
        "shop_name": "test shop",
        "messages": [
            {"speaker": "买家", "text": "这个怎么安装？手机号13812345678"},
            {"speaker": "客服", "text": "您先看安装说明"},
            {"speaker": "买家", "text": "有视频吗"},
            {"speaker": "客服", "text": "可以发您视频"},
            {"speaker": "买家", "text": "订单123456789012345到哪了"},
            {"speaker": "客服", "text": "我帮您查询"},
        ],
    }
    (source / "chat.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    samples = collect_real_conversation_samples(str(source), limit=50, min_turns=6)

    assert len(samples) == 1
    assert samples[0].turns[0].speaker == "buyer"
    assert "13812345678" not in samples[0].turns[0].sanitized_text
    db = session_factory()
    try:
        assert db.query(EvalCase).count() == 0
        assert db.query(EvalConversationTurn).count() == 0
    finally:
        db.close()


def test_import_real_conversation_apply_writes_sanitized_cases(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "chat.txt").write_text(
        "\n".join([
            "买家: 材质安全吗，电话13812345678",
            "客服: 以页面和检测资料为准",
            "买家: 会不会受潮",
            "客服: 建议保持干燥",
            "买家: 怎么安装",
            "客服: 可以按说明书安装",
        ]),
        encoding="utf-8",
    )

    samples = collect_real_conversation_samples(str(source), limit=50, min_turns=6)
    stats = write_samples_to_db(samples)

    assert stats["cases_created"] == 1
    assert stats["turns_created"] == 6
    db = session_factory()
    try:
        case = db.query(EvalCase).one()
        turns = db.query(EvalConversationTurn).order_by(EvalConversationTurn.turn_index).all()
        assert case.source_type == "real_conversation"
        assert "13812345678" not in case.message
        assert turns[0].reference_human_reply == "以页面和检测资料为准"
        assert all("13812345678" not in turn.sanitized_text for turn in turns)
    finally:
        db.close()
