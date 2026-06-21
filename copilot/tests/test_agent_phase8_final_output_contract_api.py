from __future__ import annotations

import json
import os
import re
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


PHASE8_SKU = "PHASE8_CONTRACT_SKU"
PHASE8_I_ID = "PHASE8_CONTRACT_PRODUCT"
PHASE8_PRODUCT_NAME = "\u6d4b\u8bd5\u513f\u7ae5\u6536\u7eb3\u67b6"

_FORBIDDEN_TEXT = (
    "\u627f\u91cd/\u5bb9\u91cf:",
    "\u5c3a\u5bf8:",
    "\u6750\u8d28:",
    "score:",
    "fact_type",
    "query_fact_type",
    "evidence_debug",
    "RAG",
    "\u77e5\u8bc6\u5e93",
    "\u7cfb\u7edf\u68c0\u7d22",
)
_UNSUPPORTED_MEDIA_CLAIMS = (
    "\u4e0b\u9762\u53d1\u56fe",
    "\u53d1\u89c6\u9891\u7ed9\u60a8",
    "\u56fe\u7247\u53d1\u60a8",
)
_RAW_FIELD_RE = re.compile(r"[\u4e00-\u9fffA-Za-z_/]{1,16}\s*[:：]\s*[-+]?\d+(?:\.\d+)?")


@pytest.fixture()
def phase8_api(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBProductActivityRule, KBQA  # noqa: F401
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)

    saved_key = os.environ.get("COPILOT_LLM_API_KEY", "")
    os.environ["COPILOT_LLM_API_KEY"] = ""
    os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tempfile.gettempdir(), "phase8_feedback.jsonl")
    os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tempfile.gettempdir(), "phase8_review.jsonl")

    _seed_phase8_product(session_factory)

    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    try:
        yield app.test_client()
    finally:
        os.environ["COPILOT_LLM_API_KEY"] = saved_key


def _seed_phase8_product(session_factory) -> None:
    from app.models.kb_tables import KBProduct

    db = session_factory()
    try:
        db.add(KBProduct(
            i_id=PHASE8_I_ID,
            product_name=PHASE8_PRODUCT_NAME,
            sku_list_json=json.dumps([{"sku_code": PHASE8_SKU}], ensure_ascii=False),
            specs_json=json.dumps({
                "material": "\u73af\u4fddPP/\u51b7\u8f67\u94a2\u7ba1",
                "load_capacity": "\u627f\u91cd/\u5bb9\u91cf: 8.58",
                "size": "",
                "certification_report": "",
            }, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()


def _analyze(client, message: str) -> dict:
    resp = client.post("/api/analyze", json={
        "message": message,
        "sku_code": PHASE8_SKU,
        "conversation_id": "phase8_contract_" + str(abs(hash(message))),
    })
    assert resp.status_code == 200
    assert resp.is_json
    return resp.get_json()


def _assert_final_output_contract(data: dict, *, message: str) -> None:
    reply = data.get("suggested_reply") or ""
    assert isinstance(reply, str) and reply.strip(), message
    for term in _FORBIDDEN_TEXT:
        assert term not in reply, f"{message}: forbidden term {term} in {reply}"
    assert not _RAW_FIELD_RE.search(reply), f"{message}: raw field shape in {reply}"
    trace = data.get("answer_trace") or (data.get("evidence_debug") or {}).get("answer_trace") or {}
    selected_assets = trace.get("selected_assets") or data.get("selected_assets") or []
    if not selected_assets:
        for claim in _UNSUPPORTED_MEDIA_CLAIMS:
            assert claim not in reply, f"{message}: unsupported media claim in {reply}"
    assert "final_quality_pass" in trace, message
    assert trace.get("final_quality_pass") is True or data.get("requires_human_review") is True
    compiler = trace.get("semantic_compiler_result") or {}
    assert "post_compiler_validation" in compiler, message
    assert compiler.get("final_text_passed") is True, message


@pytest.mark.parametrize("message", [
    "\u8fd9\u4e2a\u9002\u5408\u653e\u5b9d\u5b9d\u73a9\u5177\u5417\uff1f\u7a33\u4e0d\u7a33\uff1f",
    "\u80fd\u4e0d\u80fd\u653e\u5c0f\u670b\u53cb\u7684\u4e1c\u897f\uff1f",
    "\u653e\u73a9\u5177\u4f1a\u4e0d\u4f1a\u6643\uff1f",
    "\u5b69\u5b50\u78b0\u5230\u4f1a\u4e0d\u4f1a\u5012\uff1f",
    "\u513f\u7ae5\u623f\u53ef\u4ee5\u653e\u5417\uff1f",
    "\u653e\u7ed8\u672c\u4f1a\u4e0d\u4f1a\u538b\u584c\uff1f",
    "\u5367\u5ba4\u7a7a\u95f4\u5c0f\u80fd\u653e\u5417\uff1f",
    "\u8fd9\u4e2a\u5c3a\u5bf8\u591a\u5927\uff1f",
    "\u6709\u6ca1\u6709\u5b89\u88c5\u89c6\u9891\uff1f",
    "\u6709\u68c0\u6d4b\u62a5\u544a\u5417\uff1f",
])
def test_phase8_final_output_contract_api(phase8_api, message):
    data = _analyze(phase8_api, message)
    _assert_final_output_contract(data, message=message)

    reply = data["suggested_reply"]
    trace = data.get("answer_trace") or {}
    fact_type = trace.get("query_fact_type") or data.get("query_fact_type")
    if "\u5c3a\u5bf8" in message:
        assert fact_type in {"dimensions", "visual_asset"}
        assert "\u627f\u91cd" not in reply or "\u5c3a\u5bf8" in reply
    if "\u68c0\u6d4b\u62a5\u544a" in message:
        assert fact_type == "certification_report"
        assert "\u6750\u8d28" not in reply or "\u62a5\u544a" in reply or "\u8bc1\u4e66" in reply
    if "\u7a7a\u95f4\u5c0f" in message:
        assert fact_type == "space_fit"
        assert "\u627f\u91cd" not in reply or "\u7a7a\u95f4" in reply
    if "\u5b89\u88c5\u89c6\u9891" in message:
        assert "\u53d1\u89c6\u9891\u7ed9\u60a8" not in reply
