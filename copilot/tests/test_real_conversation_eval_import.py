import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import Base
from app.models.eval_tables import EvalCase, EvalConversationTurn
from app.services.eval_sanitizer_service import sanitize_text
from app.services.real_conversation_import_service import (
    collect_real_conversation_samples,
    iter_conversation_files,
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


def test_import_real_conversation_stores_structured_context_in_metadata(tmp_path, monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    payload = {
        "conversation_id": "conv-context-1",
        "messages": [
            {
                "speaker": "system",
                "text": "当前用户来自 商品详情页 https://item.taobao.com/item.htm?id=123456789&spm=a1",
                "product_name": "儿童书架收纳柜",
            },
            {
                "speaker": "buyer",
                "text": "这个视频和我买的不一样",
                "media_url": "https://demo.oss-cn-hangzhou.aliyuncs.com/install.mp4?Expires=1&Signature=abc",
            },
            {
                "speaker": "service",
                "text": "我帮您核对",
            },
            {
                "speaker": "buyer",
                "text": "订单号 123456789012345 到哪了",
            },
        ],
    }
    (source / "chat.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    samples = collect_real_conversation_samples(str(source), limit=50, min_turns=1)
    stats = write_samples_to_db(samples)

    assert stats["cases_created"] == 1
    db = session_factory()
    try:
        case = db.query(EvalCase).one()
        turns = db.query(EvalConversationTurn).order_by(EvalConversationTurn.turn_index).all()
        case_context = case.get_metadata()["real_context"]
        buyer_context = turns[1].get_metadata()["real_context"]
        order_context = turns[3].get_metadata()["real_context"]

        assert case_context["conversation_type"] == "mixed"
        assert buyer_context["source_page"] == "product_detail"
        assert buyer_context["product"]["item_id"] == "123456789"
        assert buyer_context["media"]["video_urls"] == ["https://demo.oss-cn-hangzhou.aliyuncs.com/install.mp4"]
        assert order_context["order"]["order_id_hash"]
        assert "123456789012345" not in str(order_context)
        assert "Signature=abc" not in str(buyer_context)
    finally:
        db.close()


def test_real_conversation_import_skips_report_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "duplicate_report.txt").write_text(
        "\n".join([
            "今日重复对话排查报告",
            "买家:unknown 客服:英禾旗舰店:宇航 时间:2026-05-19 08:08:00+08:00 → 5 个会话",
            "发现 20 组同一分钟内同买家+客服的重复会话",
        ]),
        encoding="utf-8",
    )

    assert iter_conversation_files(str(source)) == []
    assert collect_real_conversation_samples(str(source), limit=50, min_turns=1) == []


def test_import_real_conversation_reads_chat_xlsx(tmp_path):
    import openpyxl

    source = tmp_path / "source"
    chat_dir = source / "聊天记录"
    chat_dir.mkdir(parents=True)
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "聊天记录"
    worksheet.append([
        "抓取时间", "会话ID", "说话时间", "说话类型", "说话人", "买家昵称", "店铺昵称",
        "消息类型", "是否客户有效意图", "一句话意图", "消息内容", "图片链接", "接口URL", "原始数据",
    ])
    worksheet.append(["2026-06-24", "conv-1", "2026-06-23 10:00:00", "客户", "tb_user", "tb_user", "英禾旗舰店", "文本", "是", "", "这个材质安全吗", "", "", ""])
    worksheet.append(["2026-06-24", "conv-1", "2026-06-23 10:00:02", "客服", "英禾旗舰店:宇航", "tb_user", "英禾旗舰店", "文本", "否", "", "亲亲，我们帮您核实", "", "", ""])
    worksheet.append(["2026-06-24", "conv-1", "2026-06-23 10:00:04", "客户", "tb_user", "tb_user", "英禾旗舰店", "文本", "是", "", "有没有味道", "", "", ""])
    workbook.save(chat_dir / "chat.xlsx")

    samples = collect_real_conversation_samples(str(source), limit=50, min_turns=3)

    assert len(samples) == 1
    assert samples[0].source_file.endswith("chat.xlsx")
    assert [turn.speaker for turn in samples[0].turns] == ["buyer", "service", "buyer"]
    assert samples[0].turns[0].sanitized_text == "这个材质安全吗"
    assert samples[0].turns[0].reference_human_reply == "亲亲，我们帮您核实"


def test_import_real_conversation_keeps_order_cards_and_acknowledgements_as_context(tmp_path):
    import openpyxl

    source = tmp_path / "source"
    chat_dir = source / "聊天记录"
    chat_dir.mkdir(parents=True)
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "聊天记录"
    worksheet.append([
        "抓取时间", "会话ID", "说话时间", "说话人类型", "说话人", "买家昵称", "店铺昵称",
        "消息类型", "是否客户有效意图", "一句话意图", "消息内容", "图片链接", "接口URL", "原始数据",
    ])
    worksheet.append(["2026-06-24", "conv-1", "2026-06-23 10:00:00", "客户", "tb_user", "tb_user", "英禾旗舰店", "文本", "否", "", "订单号:123456789012345678 共1件商品,合计￥141.00 交易时间:2026-06-18 20:17:56", "", "", ""])
    worksheet.append(["2026-06-24", "conv-1", "2026-06-23 10:00:01", "客户", "tb_user", "tb_user", "英禾旗舰店", "文本", "否", "", "好的", "", "", ""])
    worksheet.append(["2026-06-24", "conv-1", "2026-06-23 10:00:02", "客户", "tb_user", "tb_user", "英禾旗舰店", "文本", "是", "", "安装视频给我发一个", "", "", ""])
    workbook.save(chat_dir / "chat.xlsx")

    samples = collect_real_conversation_samples(str(source), limit=50, min_turns=1)

    assert len(samples) == 1
    assert [turn.speaker for turn in samples[0].turns] == ["context", "context", "buyer"]
    assert sum(1 for turn in samples[0].turns if turn.speaker == "buyer") == 1
    assert samples[0].turns[-1].sanitized_text == "安装视频给我发一个"
