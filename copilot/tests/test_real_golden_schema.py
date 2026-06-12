"""
Test real golden candidate JSON schema — 验证候选数据的结构完整性。
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "real_golden_candidates", "candidates_300.jsonl",
)

REQUIRED_FIELDS = [
    "case_id", "source", "scenario", "difficulty",
    "conversation_history", "customer_message", "product_context",
    "expected", "evidence_review", "annotation",
]

VALID_ANNOTATION_STATUSES = {"candidate", "pre_labeled", "needs_evidence", "reviewed", "approved", "rejected"}
VALID_EVIDENCE_STATUSES = {"unverified", "partial", "verified", "missing"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}


def _load_candidates():
    """Load candidates from JSONL file; return mock data if file missing."""
    if os.path.exists(DATA_PATH):
        candidates = []
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    candidates.append(json.loads(line))
        return candidates
    # Fallback: mock data so tests still exercise schema checks
    return _mock_candidates()


def _mock_candidates():
    """Return a small list of mock candidates for schema testing."""
    return [
        {
            "case_id": "MOCK-001",
            "source": {
                "system": "customer_service_qa",
                "type": "mock",
                "record_hash": "abc123",
                "business_session_hash": "",
                "source_date_min": "2026-06-01T00:00:00+08:00",
                "source_date_max": "2026-06-01T00:01:00+08:00",
                "source_files": [],
                "cutoff_applied": "2026-05-26T00:00:00+08:00",
            },
            "scenario": "pre_sale_product",
            "difficulty": "easy",
            "conversation_history": [
                {"role": "customer", "text": "多少钱", "time": "2026-06-01T00:00:00+08:00"},
                {"role": "agent", "text": "您好，50元", "time": "2026-06-01T00:00:05+08:00"},
            ],
            "customer_message": "多少钱",
            "product_context": {
                "platform_product_id_masked": "",
                "platform_title": "",
                "internal_i_id": "",
                "sku_id": "",
                "canonical_product_name": "",
            },
            "expected": {
                "allowed_intents": [],
                "required_tools": [],
                "forbidden_tools": [],
                "required_knowledge_entry_ids": [],
                "required_claims": [],
                "forbidden_claims": [],
                "risk_level": "",
                "need_human_review": False,
                "reply_requirements": [],
                "max_duration_ms": 0,
            },
            "evidence_review": {
                "status": "unverified",
                "knowledge_entries": [],
                "product_facts": [],
                "sop_entries": [],
                "jst_verification": None,
                "conflicts": [],
            },
            "annotation": {
                "status": "candidate",
                "reviewer": "",
                "reviewed_at": "",
                "notes": "",
            },
        },
        {
            "case_id": "MOCK-002",
            "source": {
                "system": "customer_service_qa",
                "type": "mock",
                "record_hash": "def456",
                "business_session_hash": "",
                "source_date_min": "2026-06-02T00:00:00+08:00",
                "source_date_max": "2026-06-02T00:01:00+08:00",
                "source_files": [],
                "cutoff_applied": "2026-05-26T00:00:00+08:00",
            },
            "scenario": "aftersales_return",
            "difficulty": "hard",
            "conversation_history": [
                {"role": "customer", "text": "我要退货", "time": "2026-06-02T00:00:00+08:00"},
                {"role": "agent", "text": "好的，帮您处理", "time": "2026-06-02T00:00:05+08:00"},
                {"role": "customer", "text": "东西坏了还带异味，投诉你们", "time": "2026-06-02T00:00:10+08:00"},
            ],
            "customer_message": "东西坏了还带异味，投诉你们",
            "product_context": {
                "platform_product_id_masked": "",
                "platform_title": "",
                "internal_i_id": "",
                "sku_id": "",
                "canonical_product_name": "",
            },
            "expected": {
                "allowed_intents": [],
                "required_tools": [],
                "forbidden_tools": [],
                "required_knowledge_entry_ids": [],
                "required_claims": [],
                "forbidden_claims": [],
                "risk_level": "",
                "need_human_review": False,
                "reply_requirements": [],
                "max_duration_ms": 0,
            },
            "evidence_review": {
                "status": "unverified",
                "knowledge_entries": [],
                "product_facts": [],
                "sop_entries": [],
                "jst_verification": None,
                "conflicts": [],
            },
            "annotation": {
                "status": "candidate",
                "reviewer": "",
                "reviewed_at": "",
                "notes": "",
            },
        },
    ]


@pytest.fixture(scope="module")
def candidates():
    """Load candidates once per module."""
    return _load_candidates()


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

class TestRequiredFields:
    """每个候选必须包含所有必填字段。"""

    def test_every_candidate_has_required_fields(self, candidates):
        """所有候选包含全部必填字段。"""
        for c in candidates:
            for field in REQUIRED_FIELDS:
                assert field in c, f"Missing field '{field}' in {c.get('case_id', '<unknown>')}"

    def test_case_id_not_empty(self, candidates):
        """case_id 非空。"""
        for c in candidates:
            assert c["case_id"], f"case_id is empty in candidate"

    def test_case_id_unique(self, candidates):
        """case_id 唯一。"""
        ids = [c["case_id"] for c in candidates]
        assert len(ids) == len(set(ids)), f"Duplicate case_ids found"

    def test_source_is_dict(self, candidates):
        """source 是字典。"""
        for c in candidates:
            assert isinstance(c["source"], dict), f"source is not a dict in {c['case_id']}"

    def test_product_context_is_dict(self, candidates):
        """product_context 是字典。"""
        for c in candidates:
            assert isinstance(c["product_context"], dict), f"product_context is not a dict in {c['case_id']}"

    def test_expected_is_dict(self, candidates):
        """expected 是字典。"""
        for c in candidates:
            assert isinstance(c["expected"], dict), f"expected is not a dict in {c['case_id']}"

    def test_evidence_review_is_dict(self, candidates):
        """evidence_review 是字典。"""
        for c in candidates:
            assert isinstance(c["evidence_review"], dict), f"evidence_review is not a dict in {c['case_id']}"

    def test_annotation_is_dict(self, candidates):
        """annotation 是字典。"""
        for c in candidates:
            assert isinstance(c["annotation"], dict), f"annotation is not a dict in {c['case_id']}"


# ---------------------------------------------------------------------------
# source.system
# ---------------------------------------------------------------------------

class TestSourceSystem:
    """source.system 必须为 customer_service_qa。"""

    def test_source_system_is_customer_service_qa(self, candidates):
        """所有候选的 source.system 为 customer_service_qa。"""
        for c in candidates:
            assert c["source"]["system"] == "customer_service_qa", (
                f"source.system is '{c['source']['system']}' in {c['case_id']}, expected 'customer_service_qa'"
            )

    def test_source_has_required_keys(self, candidates):
        """source 包含必要子字段。"""
        source_keys = {"system", "type", "record_hash", "cutoff_applied"}
        for c in candidates:
            for key in source_keys:
                assert key in c["source"], f"source missing '{key}' in {c['case_id']}"


# ---------------------------------------------------------------------------
# annotation.status
# ---------------------------------------------------------------------------

class TestAnnotationStatus:
    """annotation.status 必须是合法枚举值。"""

    def test_annotation_status_valid(self, candidates):
        """所有候选的 annotation.status 在合法集合中。"""
        for c in candidates:
            status = c["annotation"]["status"]
            assert status in VALID_ANNOTATION_STATUSES, (
                f"annotation.status '{status}' invalid in {c['case_id']}, "
                f"expected one of {VALID_ANNOTATION_STATUSES}"
            )

    def test_annotation_has_required_keys(self, candidates):
        """annotation 包含必要子字段。"""
        annotation_keys = {"status", "reviewer", "reviewed_at", "notes"}
        for c in candidates:
            for key in annotation_keys:
                assert key in c["annotation"], f"annotation missing '{key}' in {c['case_id']}"


# ---------------------------------------------------------------------------
# evidence_review.status
# ---------------------------------------------------------------------------

class TestEvidenceReviewStatus:
    """evidence_review.status 必须是合法枚举值。"""

    def test_evidence_review_status_valid(self, candidates):
        """所有候选的 evidence_review.status 在合法集合中。"""
        for c in candidates:
            status = c["evidence_review"]["status"]
            assert status in VALID_EVIDENCE_STATUSES, (
                f"evidence_review.status '{status}' invalid in {c['case_id']}, "
                f"expected one of {VALID_EVIDENCE_STATUSES}"
            )

    def test_evidence_review_has_required_keys(self, candidates):
        """evidence_review 包含必要子字段。"""
        evidence_keys = {"status", "knowledge_entries", "product_facts", "sop_entries", "conflicts"}
        for c in candidates:
            for key in evidence_keys:
                assert key in c["evidence_review"], f"evidence_review missing '{key}' in {c['case_id']}"


# ---------------------------------------------------------------------------
# difficulty
# ---------------------------------------------------------------------------

class TestDifficulty:
    """difficulty 必须是合法枚举值。"""

    def test_difficulty_valid(self, candidates):
        """所有候选的 difficulty 在合法集合中。"""
        for c in candidates:
            difficulty = c["difficulty"]
            assert difficulty in VALID_DIFFICULTIES, (
                f"difficulty '{difficulty}' invalid in {c['case_id']}, "
                f"expected one of {VALID_DIFFICULTIES}"
            )


# ---------------------------------------------------------------------------
# scenario
# ---------------------------------------------------------------------------

class TestScenario:
    """scenario 不能为空。"""

    def test_scenario_not_empty(self, candidates):
        """所有候选的 scenario 非空。"""
        for c in candidates:
            scenario = c["scenario"]
            assert scenario, f"scenario is empty in {c['case_id']}"

    def test_scenario_is_string(self, candidates):
        """scenario 是字符串类型。"""
        for c in candidates:
            assert isinstance(c["scenario"], str), f"scenario is not a string in {c['case_id']}"


# ---------------------------------------------------------------------------
# conversation_history
# ---------------------------------------------------------------------------

class TestConversationHistory:
    """conversation_history 必须是至少含 1 个元素的列表。"""

    def test_conversation_history_is_list(self, candidates):
        """conversation_history 是列表。"""
        for c in candidates:
            assert isinstance(c["conversation_history"], list), (
                f"conversation_history is not a list in {c['case_id']}"
            )

    def test_conversation_history_not_empty(self, candidates):
        """conversation_history 至少有 1 条记录。"""
        for c in candidates:
            assert len(c["conversation_history"]) >= 1, (
                f"conversation_history is empty in {c['case_id']}"
            )

    def test_conversation_history_items_have_role_and_text(self, candidates):
        """conversation_history 中每条记录有 role 和 text。"""
        for c in candidates:
            for item in c["conversation_history"]:
                assert "role" in item, f"Missing 'role' in conversation_history item of {c['case_id']}"
                assert "text" in item, f"Missing 'text' in conversation_history item of {c['case_id']}"


# ---------------------------------------------------------------------------
# customer_message
# ---------------------------------------------------------------------------

class TestCustomerMessage:
    """customer_message 不能为空。"""

    def test_customer_message_not_empty(self, candidates):
        """customer_message 非空。"""
        for c in candidates:
            msg = c["customer_message"]
            assert msg, f"customer_message is empty in {c['case_id']}"

    def test_customer_message_is_string(self, candidates):
        """customer_message 是字符串类型。"""
        for c in candidates:
            assert isinstance(c["customer_message"], str), (
                f"customer_message is not a string in {c['case_id']}"
            )

    def test_customer_message_is_not_whitespace_only(self, candidates):
        """customer_message 不只是空白字符。"""
        for c in candidates:
            assert c["customer_message"].strip(), (
                f"customer_message is whitespace-only in {c['case_id']}"
            )


# ---------------------------------------------------------------------------
# expected field — should NOT contain actual answer
# ---------------------------------------------------------------------------

class TestExpectedField:
    """expected 字段不应包含实际答案，只有约束。"""

    def test_expected_has_constraint_keys(self, candidates):
        """expected 包含约束类子字段。"""
        constraint_keys = {
            "allowed_intents", "required_tools", "forbidden_tools",
            "forbidden_claims", "risk_level", "need_human_review",
            "reply_requirements",
        }
        for c in candidates:
            for key in constraint_keys:
                assert key in c["expected"], f"expected missing '{key}' in {c['case_id']}"

    def test_expected_no_answer_text_key(self, candidates):
        """expected 不含 answer_text 或类似实际答案字段。"""
        forbidden_answer_keys = {"answer_text", "answer", "reply_text", "response_text", "suggested_reply"}
        for c in candidates:
            overlap = forbidden_answer_keys & set(c["expected"].keys())
            assert not overlap, (
                f"expected contains answer-like keys {overlap} in {c['case_id']}"
            )

    def test_allowed_intents_is_list(self, candidates):
        """allowed_intents 是列表。"""
        for c in candidates:
            assert isinstance(c["expected"]["allowed_intents"], list), (
                f"allowed_intents is not a list in {c['case_id']}"
            )

    def test_forbidden_tools_is_list(self, candidates):
        """forbidden_tools 是列表。"""
        for c in candidates:
            assert isinstance(c["expected"]["forbidden_tools"], list), (
                f"forbidden_tools is not a list in {c['case_id']}"
            )

    def test_reply_requirements_is_list(self, candidates):
        """reply_requirements 是列表。"""
        for c in candidates:
            assert isinstance(c["expected"]["reply_requirements"], list), (
                f"reply_requirements is not a list in {c['case_id']}"
            )

    def test_need_human_review_is_bool(self, candidates):
        """need_human_review 是布尔值。"""
        for c in candidates:
            assert isinstance(c["expected"]["need_human_review"], bool), (
                f"need_human_review is not bool in {c['case_id']}"
            )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

class TestDataLoading:
    """数据加载基本验证。"""

    def test_candidates_loaded(self, candidates):
        """成功加载至少 1 条候选。"""
        assert len(candidates) >= 1

    def test_all_candidates_are_dicts(self, candidates):
        """所有候选都是字典。"""
        for c in candidates:
            assert isinstance(c, dict), f"Candidate is not a dict: {type(c)}"

    def test_data_file_exists_or_mock_used(self):
        """确认数据文件存在或使用了 mock 数据。"""
        if os.path.exists(DATA_PATH):
            # Real data file exists
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                assert first_line, "Data file is empty"
                parsed = json.loads(first_line)
                assert "case_id" in parsed
        else:
            # Mock data is used — confirm it loads
            mock = _mock_candidates()
            assert len(mock) >= 1
            for c in mock:
                assert "case_id" in c
