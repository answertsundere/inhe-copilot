import sqlite3
import time

from app.agent.nodes.build_response import build_response
from app.agent.nodes.detect_intent import detect_intent
from app.agent.nodes.reply_relevance_guard import reply_relevance_guard
from app.agent.nodes.response_strategy_router import _compute_tool_lists


def test_stock_followup_uses_conversation_history():
    result = detect_intent({
        "customer_message": "还能发不？",
        "normalized_message": "还能发不？",
        "copilot_context": {
            "conversation_history": [{"role": "customer", "text": "这款现在有货吗？"}],
        },
        "trace_steps": [],
    })
    assert result["intent"] == "stock_query"


def test_multi_question_guard_keeps_safety_answer_and_adds_shipping_boundary():
    result = reply_relevance_guard({
        "customer_message": "这个安全吗，今天能发吗？",
        "normalized_message": "这个安全吗，今天能发吗？",
        "intent": "material_safety",
        "suggested_reply": "亲，安全信息需要按已确认的商品资料核实。",
        "trace_steps": [],
    })
    assert "发货部分" in result["suggested_reply"]
    assert "仓库" in result["suggested_reply"]


def test_multi_question_guard_replaces_irrelevant_answer_with_all_boundaries():
    result = reply_relevance_guard({
        "customer_message": "这个安全吗，今天能发吗？",
        "normalized_message": "这个安全吗，今天能发吗？",
        "intent": "material_safety",
        "suggested_reply": "亲，这款商品可以用湿布擦拭。",
        "trace_steps": [],
    })
    reply = result["suggested_reply"]
    assert "材质和安全部分" in reply
    assert "发货部分" in reply


def test_aftersales_followup_does_not_invent_missing_parts_for_wrong_item():
    result = build_response({
        "customer_message": "发错了，我想退，怎么弄？",
        "normalized_message": "发错了，我想退，怎么弄？",
        "suggested_reply": "亲，我先核对订单和实物。",
        "decision_fusion": {"final_intent": "wrong_item"},
        "risk_level": "medium",
        "trace_steps": [],
    })
    reply = result["suggested_reply"]
    assert "发错商品" in reply
    assert "还少配件" not in reply
    assert "少件/缺配件" not in reply


def test_wrong_item_and_return_are_both_detected():
    result = reply_relevance_guard({
        "customer_message": "发错了，我想退，怎么弄？",
        "normalized_message": "发错了，我想退，怎么弄？",
        "intent": "aftersales",
        "suggested_reply": "亲，发错商品需要核对订单和实物。",
        "trace_steps": [],
    })
    assert "退货部分" in result["suggested_reply"]


def test_aftersales_with_identifier_requires_jst_lookup():
    allowed, required, forbidden = _compute_tool_lists({
        "intent": "aftersales",
        "slots": {
            "identifier_type": "platform_trade_id",
            "platform_trade_id": "6926666820903533935",
        },
    }, "aftersales", True)
    assert "jst_lookup_outbound_tool" in required
    assert "jst_lookup_outbound_tool" in allowed
    assert "jst_lookup_outbound_tool" not in forbidden


def test_trace_repository_fails_fast_when_sqlite_is_locked(tmp_path, monkeypatch):
    from app.tracing import repository

    old_engine = repository._engine
    if old_engine is not None:
        old_engine.dispose()
    monkeypatch.setattr(repository, "TRACE_DB_PATH", str(tmp_path / "locked_trace.db"))
    monkeypatch.setattr(repository, "_engine", None)
    monkeypatch.setattr(repository, "_SessionLocal", None)
    repository.init_trace_tables()

    locker = sqlite3.connect(repository.TRACE_DB_PATH, timeout=0.1)
    try:
        locker.execute("BEGIN IMMEDIATE")
        started = time.perf_counter()
        repository.save_trace_run({
            "trace_id": "tr_locked",
            "request_id": "req_locked",
            "message_id": "msg_locked",
            "conversation_id": "conv_locked",
            "source": "test",
            "scenario": "",
            "status": "running",
            "started_at": "2026-06-13T00:00:00+00:00",
        })
        elapsed = time.perf_counter() - started
    finally:
        locker.rollback()
        locker.close()
        if repository._engine is not None:
            repository._engine.dispose()
        repository._engine = None
        repository._SessionLocal = None
        repository.TRACE_DB_PATH = str(tmp_path / "reset.db")

    assert elapsed < 1.0
