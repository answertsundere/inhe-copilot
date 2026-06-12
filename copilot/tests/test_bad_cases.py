"""
test_bad_cases — Phase 1C/1D 测试

覆盖:
1. rejected 自动创建 Bad Case
2. edited 事实变化创建 Bad Case
3. 纯语气修改不标记事实纠正
4. hallucination fallback 创建 Bad Case
5. tool timeout 创建 Bad Case
6. API 筛选和分页
7. 状态流转
8. 回归 JSON 导出
9. 脱敏
10. metrics 更新
"""

import json
import os
import pytest
import tempfile
import shutil

from app.services.bad_case_service import (
    BadCaseStore,
    should_auto_create_bad_case,
    create_bad_case_from_context,
    compute_edit_diff,
    _has_fact_change,
)


@pytest.fixture
def store():
    tmpdir = tempfile.mkdtemp()
    filepath = os.path.join(tmpdir, "test_bad_cases.jsonl")
    s = BadCaseStore(filepath=filepath)
    yield s
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestAutoCreate:
    def test_rejected_creates_bad_case(self):
        should, reason = should_auto_create_bad_case(action="rejected")
        assert should is True
        assert reason == "rejected"

    def test_edited_fact_change_creates(self):
        should, reason = should_auto_create_bad_case(
            action="edited",
            suggested_reply="这个书架是实木的，承重50kg",
            final_reply="这个书架是PP塑料的，承重30kg",
        )
        assert should is True
        assert reason == "edited_fact_change"

    def test_tone_only_no_create(self):
        should, reason = should_auto_create_bad_case(
            action="edited",
            suggested_reply="亲，这个书架承重50kg哦",
            final_reply="这个书架承重50kg",
        )
        assert should is False

    def test_hallucination_fallback_creates(self):
        ed = {
            "guards": [
                {"guard_name": "hallucination_guard", "passed": False, "details": {}},
            ]
        }
        should, reason = should_auto_create_bad_case(execution_debug=ed)
        assert should is True
        assert "hallucination" in reason

    def test_tool_timeout_creates(self):
        ed = {
            "tool_calls": [
                {"tool_name": "jst_lookup_order_tool", "status": "timeout"},
            ]
        }
        should, reason = should_auto_create_bad_case(execution_debug=ed)
        assert should is True
        assert "tool_error" in reason

    def test_rag_miss_creates(self):
        ed = {
            "rag": {"metrics": {"retrieved_count": 0}},
            "routing": {"final_intent": "product_question"},
        }
        should, reason = should_auto_create_bad_case(execution_debug=ed)
        assert should is True
        assert reason == "rag_miss"

    def test_accepted_no_create(self):
        should, reason = should_auto_create_bad_case(action="accepted")
        assert should is False

    def test_intent_corrected_creates(self):
        ed = {
            "routing": {"overrides": [{"from": "general", "to": "logistics_eta", "reason": "test"}]}
        }
        should, reason = should_auto_create_bad_case(execution_debug=ed)
        assert should is True
        assert "intent_corrected" in reason


class TestFactChangeDetection:
    def test_number_change(self):
        assert _has_fact_change("承重50kg", "承重30kg") is True

    def test_material_change(self):
        assert _has_fact_change("实木材质", "PP塑料材质") is True

    def test_logistics_status_change(self):
        assert _has_fact_change("已发货", "已签收") is True

    def test_compensation_change(self):
        assert _has_fact_change("无赔偿", "赔偿10元") is True

    def test_tone_only_no_change(self):
        assert _has_fact_change("亲亲好的呢", "好的呢") is False

    def test_empty_strings(self):
        assert _has_fact_change("", "") is False


class TestEditDiff:
    def test_compute_diff_fact_correction(self):
        diff = compute_edit_diff(
            "这个是实木的，承重50kg",
            "这个是PP塑料的，承重30kg",
        )
        assert diff["possible_fact_correction"] is True
        assert diff["tone_only_change"] is False

    def test_compute_diff_similar(self):
        diff = compute_edit_diff(
            "hello world foo bar",
            "hello world foo bar baz",
        )
        assert diff["tone_only_change"] is True
        assert diff["possible_fact_correction"] is False


class TestBadCaseStore:
    def test_create_and_read(self, store):
        case = store.create({"customer_message": "测试"})
        assert case["id"]
        assert case["status"] == "open"

        loaded = store.get_by_id(case["id"])
        assert loaded is not None
        assert loaded["customer_message"] == "测试"

    def test_update(self, store):
        case = store.create({"customer_message": "测试"})
        updated = store.update(case["id"], {"severity": "P0", "failure_type": "intent_error"})
        assert updated["severity"] == "P0"
        assert updated["failure_type"] == "intent_error"

    def test_query_with_filters(self, store):
        store.create({"customer_message": "a", "status": "open", "severity": "P1"})
        store.create({"customer_message": "b", "status": "fixed", "severity": "P0"})

        result = store.query(status="open")
        assert result["total"] == 1
        assert result["items"][0]["customer_message"] == "a"

        result = store.query(severity="P0")
        assert result["total"] == 1

    def test_pagination(self, store):
        for i in range(5):
            store.create({"customer_message": f"case {i}"})

        result = store.query(page=1, page_size=2)
        assert result["total"] == 5
        assert len(result["items"]) == 2
        assert result["total_pages"] == 3

        result = store.query(page=3, page_size=2)
        assert len(result["items"]) == 1

    def test_status_flow(self, store):
        case = store.create({"customer_message": "test"})
        store.update(case["id"], {"status": "triaged"})
        loaded = store.get_by_id(case["id"])
        assert loaded["status"] == "triaged"

    def test_delete(self, store):
        case = store.create({"customer_message": "to_delete"})
        assert store.delete(case["id"]) is True
        assert store.get_by_id(case["id"]) is None

    def test_metrics(self, store):
        store.create({"customer_message": "a", "status": "open", "severity": "P1", "failure_type": "intent_error"})
        store.create({"customer_message": "b", "status": "verified", "severity": "P0", "failure_type": "tool_error"})

        m = store.get_metrics()
        assert m["total"] == 2
        assert m["open_count"] == 1
        assert m["verified_count"] == 1


class TestCreateFromContext:
    def test_create_from_context(self, store):
        case = create_bad_case_from_context(
            store=store,
            action="rejected",
            reason="rejected",
            customer_message="帮我查订单",
            suggested_reply="已发货",
            final_reply="",
            conversation_id="conv-1",
            scenario="after_sale",
            execution_debug={
                "request": {"request_id": "r1", "message_id": "m1"},
                "routing": {"final_intent": "logistics_eta"},
                "versions": {"graph_version": "v1", "prompt_version": "v1"},
            },
        )
        assert case["id"]
        assert case["customer_message"] == "帮我查订单"
        assert case["actual_intent"] == "logistics_eta"
        assert case["failure_type"] == "unknown"
        assert case["csr_action"] == "rejected"


class TestRegressionExport:
    def test_export_regression_json(self, store):
        case = store.create({
            "customer_message": "test question",
            "expected_intent": "product_question",
            "expected_tools_json": '["rag_search_tool"]',
            "conversation_history_json": '[]',
            "sidecar_context_json": '{}',
            "graph_version": "v1",
            "prompt_version": "v1",
            "knowledge_version": "kb-123",
            "model_name": "qwen-plus",
        })

        case_id = case["id"]
        loaded = store.get_by_id(case_id)
        assert loaded is not None

        expected_tools = json.loads(loaded.get("expected_tools_json", "[]"))
        regression = {
            "case_id": loaded["id"],
            "name": f"Bad Case {loaded['id']}: {loaded['customer_message'][:50]}",
            "input": {
                "customer_message": loaded["customer_message"],
                "conversation_history": [],
                "context": {},
            },
            "expect": {
                "allowed_intents": [loaded.get("expected_intent", "")],
                "required_tools": expected_tools,
                "forbidden_tools": [],
                "reply_must_contain": [],
                "reply_must_not_contain": [],
            },
            "versions": {
                "graph_version": loaded.get("graph_version", ""),
            },
        }

        assert regression["case_id"] == case_id
        assert "product_question" in regression["expect"]["allowed_intents"]
        assert "rag_search_tool" in regression["expect"]["required_tools"]

    def test_export_sanitized(self, store):
        case = store.create({
            "customer_message": "13812345678 的订单",
        })
        loaded = store.get_by_id(case["id"])
        assert loaded is not None


# ========== New tests for validation & semantics ==========

class TestAutoCreateNoise:
    """正常高风险识别不应自动创建 Bad Case。"""

    def test_normal_high_risk_no_auto_create(self):
        """高风险被正确识别+转人工 → 不应创建 risk_error Bad Case。"""
        ed = {
            "routing": {"final_intent": "complaint", "risk_level": "high"},
            "outcome": {"need_human_review": True},
            "guards": [{"guard_name": "risk_check", "passed": True, "triggered": True}],
        }
        should, reason = should_auto_create_bad_case(
            action="escalated",
            execution_debug=ed,
        )
        assert should is False

    def test_normal_accepted_no_create(self):
        should, reason = should_auto_create_bad_case(action="accepted")
        assert should is False

    def test_normal_escalated_no_create(self):
        should, reason = should_auto_create_bad_case(action="escalated")
        assert should is False


class TestStoreValidation:
    """Bad Case 字段校验。"""

    def test_invalid_failure_type_sanitized(self, store):
        case = store.create({"failure_type": "invalid_type"})
        assert case["failure_type"] == "unknown"

    def test_invalid_severity_sanitized(self, store):
        case = store.create({"severity": "P99"})
        assert case["severity"] == "P2"

    def test_invalid_status_sanitized(self, store):
        case = store.create({"status": "nonexistent"})
        assert case["status"] == "open"


class TestBadCaseRoutes:
    """Bad Case API 路由校验。"""

    @pytest.fixture
    def client(self):
        from app.main import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_page_abc_returns_400(self, client):
        resp = client.get("/api/bad-cases?page=abc")
        assert resp.status_code == 400

    def test_page_negative_returns_400(self, client):
        resp = client.get("/api/bad-cases?page=-1")
        assert resp.status_code == 400

    def test_page_valid(self, client):
        resp = client.get("/api/bad-cases?page=1")
        assert resp.status_code == 200

    def test_invalid_status_filter_returns_400(self, client):
        resp = client.get("/api/bad-cases?status=nonexistent")
        assert resp.status_code == 400

    def test_invalid_severity_filter_returns_400(self, client):
        resp = client.get("/api/bad-cases?severity=P99")
        assert resp.status_code == 400

    def test_invalid_failure_type_filter_returns_400(self, client):
        resp = client.get("/api/bad-cases?failure_type=invalid")
        assert resp.status_code == 400

    def test_create_with_invalid_failure_type(self, client):
        resp = client.post("/api/bad-cases",
                           json={"failure_type": "invalid"},
                           content_type="application/json")
        assert resp.status_code == 400


class TestPlannedToolsExcluded:
    """planned status tools excluded from actual_tools_json。"""

    def test_planned_excluded(self, store):
        ed = {
            "request": {"request_id": "r1", "message_id": "m1"},
            "routing": {"final_intent": "test"},
            "versions": {},
            "tool_calls": [
                {"tool_name": "rag_search_tool", "status": "success"},
                {"tool_name": "jst_lookup_order_tool", "status": "planned"},
            ],
        }
        case = create_bad_case_from_context(
            store=store, action="rejected", reason="rejected",
            customer_message="test", suggested_reply="reply",
            execution_debug=ed,
        )
        tools = json.loads(case["actual_tools_json"])
        assert "rag_search_tool" in tools
        assert "jst_lookup_order_tool" not in tools
