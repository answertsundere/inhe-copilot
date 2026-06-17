"""回归测试：证据相关性 / 模糊问题处理。

验证：
- 模糊问题不能拿任意商品字段回答。
- 问题事实类型与命中证据事实类型必须匹配。
- 前端可依赖的 evidence_sufficient / answer_relevance_passed / direct_answer_supported
  / missing_required_fact_fields / needs_clarification 字段已正确输出。
"""

import json
import pytest

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _analyze(client, message):
    payload = {
        "message": message,
        "conversation_id": f"evidence_relevance_{hash(message) & 0xFFFFFFFF}",
        "product_candidates": [
            {
                "value": "一号小熊床护栏",
                "type": "product_candidate",
                "source": "manual",
                "verified": True,
            }
        ],
        "copilot_context": {
            "source": "manual",
            "product_candidates": [
                {
                    "value": "一号小熊床护栏",
                    "type": "product_candidate",
                    "source": "manual",
                    "verified": True,
                }
            ],
        },
    }
    resp = client.post(
        "/ask/api/analyze",
        data=json.dumps(payload, ensure_ascii=False),
        content_type="application/json",
    )
    assert resp.status_code == 200
    return resp.get_json()


def test_case_a_vague_question(client):
    """Case A: 模糊问题不能拿商品字段回答，必须追问图片/具体情况。"""
    data = _analyze(client, "帮我看下是什么情况")
    dbg = data.get("evidence_debug", {})

    assert data.get("intent") == "needs_clarification"
    assert data.get("requires_human_review") is True
    assert data.get("needs_clarification") is True or dbg.get("needs_clarification") is True
    assert dbg.get("evidence_sufficient") is False
    assert dbg.get("answer_relevance_passed") is False
    assert dbg.get("direct_answer_supported") is False
    assert "具体问题/图片/异常位置" in (dbg.get("missing_required_fact_fields") or [])

    reply = data.get("suggested_reply", "")
    assert "照片" in reply or "具体情况" in reply or "截图" in reply
    assert "承重" not in reply
    assert "材质" not in reply


def test_case_b_load_capacity_missing_evidence_escalates(client):
    """Case B: 明确承重问题，但当前商品没有承重证据，不能编造数值。"""
    data = _analyze(client, "这个可以承重多少？")
    dbg = data.get("evidence_debug", {})

    assert data.get("intent") == "product_question"
    assert dbg.get("query_fact_type") == "load_capacity"
    assert dbg.get("evidence_sufficient") is False
    assert dbg.get("answer_relevance_passed") is False
    assert dbg.get("direct_answer_supported") is True

    reply = data.get("suggested_reply", "")
    assert "承重" in reply
    assert "多少斤" not in reply
    assert "多少kg" not in reply


def test_case_c_material_safety_uses_material_evidence(client):
    """Case C: 材质问题有材质证据时，必须用材质证据，不能串到承重/安装。"""
    data = _analyze(client, "这个材质安全吗？")
    dbg = data.get("evidence_debug", {})

    assert data.get("intent") == "material_safety"
    assert dbg.get("query_fact_type") == "material"
    assert dbg.get("evidence_sufficient") is True
    assert dbg.get("answer_relevance_passed") is True

    reply = data.get("suggested_reply", "")
    assert "HDPE" in reply or "PP" in reply
    assert "承重" not in reply
    assert "安装" not in reply


def test_case_d_installation_uses_installation_evidence(client):
    """Case D: 安装问题有安装证据时，可直接回答，且不能串到承重。"""
    data = _analyze(client, "这个怎么安装？")
    dbg = data.get("evidence_debug", {})

    assert data.get("intent") == "installation"
    assert dbg.get("query_fact_type") == "installation"
    assert dbg.get("evidence_sufficient") is True
    assert dbg.get("answer_relevance_passed") is True

    reply = data.get("suggested_reply", "")
    assert "承重" not in reply
    assert "安装" in reply or "组装" in reply
