from app.services.final_answer_auditor import audit_final_answer


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        return _FakeResponse(self.content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    api_key = "test-key"
    model = "test-model"

    def __init__(self, content):
        self.client = type("Client", (), {"chat": _FakeChat(content)})()


def test_final_answer_auditor_uses_llm_semantic_judge(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["semantic_mismatch"], "reason": "客户问气味，但回复只讲防潮和材质，没有回答气味。"}'
        ),
    )
    response = {
        "intent": "product_question",
        "suggested_reply": "亲～这款主要采用冷轧钢管和环保PP材质，长期潮湿环境下可能有生锈风险。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "material"},
    }

    audited = audit_final_answer(response, customer_message="材质有气味吗")

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["final_answer_audit"]["mode"] == "llm_semantic_consistency_with_hard_safety"
    assert "llm:semantic_mismatch" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_llm_blocks_space_question_answered_as_load(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["answered_space_fit_as_load_capacity"], "reason": "客户问空间是否放得下，回复却只回答承重。"}'
        ),
    )
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff5e\u8fd9\u6b3e\u5355\u5c42\u5747\u5300\u627f\u91cd\u7ea615-30kg\uff0c\u653e\u4e66\u7c4d\u73a9\u5177\u90fd\u591f\u7528\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "space_fit"},
    }

    audited = audit_final_answer(response, customer_message="\u5367\u5ba4\u7a7a\u95f4\u6bd4\u8f83\u5c0f\uff0c\u8fd9\u4e2a\u653e\u7684\u4e0b\u5417")

    assert audited["final_answer_audit"]["passed"] is False
    assert "llm:answered_space_fit_as_load_capacity" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_blocks_pinch_answered_as_battery():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，您问的是「九号防夹滑门收纳柜」的小零件/电池安全，我先帮您核对。",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "pinch_safety",
            "query_fact_type_label": "夹手/结构安全",
        },
    }

    audited = audit_final_answer(
        response,
        customer_message="家里有两岁宝宝，这个会不会夹手或者有安全隐患？",
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert "pinch_safety_answered_as_small_parts_battery" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True
    assert "夹手" in audited["suggested_reply"]
    assert "小零件/电池安全" not in audited["suggested_reply"]


def test_final_answer_auditor_allows_matching_pinch_handoff():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，您担心的是「九号防夹滑门收纳柜」滑门会不会夹手对吗？我先帮您按对应款式核实清楚。",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "pinch_safety"},
    }

    audited = audit_final_answer(
        response,
        customer_message="家里有两岁宝宝，这个会不会夹手或者有安全隐患？",
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert audited["suggested_reply"] == response["suggested_reply"]


def test_final_answer_auditor_blocks_pinch_answered_as_generic_material():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，您问的材质和安全点我先按这款商品帮您再核实一下。",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "pinch_safety"},
    }

    audited = audit_final_answer(
        response,
        customer_message="家里有两岁宝宝，这个会不会夹手或者有安全隐患？",
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert "夹手" in audited["suggested_reply"]
    assert "材质和安全点" not in audited["suggested_reply"]


def test_final_answer_auditor_blocks_internal_language():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，系统里目前没有这款商品的已审核资料，我先转人工。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "material"},
    }

    audited = audit_final_answer(response, customer_message="这个材质安全吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert "internal_system_language" in audited["final_answer_audit"]["issues"]
    assert "系统里" not in audited["suggested_reply"]
    assert "已审核资料" not in audited["suggested_reply"]


def test_final_answer_auditor_rewrites_odor_internal_or_wrong_reply():
    response = {
        "intent": "odor_question",
        "product_name": "测试收纳柜",
        "suggested_reply": "亲，系统里没有这款商品的已审核资料，我不能凭感觉说有没有味道，先转人工。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "odor"},
    }

    audited = audit_final_answer(response, customer_message="产品有味道吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["requires_human_review"] is True
    assert "气味" in audited["suggested_reply"]
    assert "通风" in audited["suggested_reply"]
    assert "拍照" in audited["suggested_reply"] or "视频" in audited["suggested_reply"]
    assert "系统" not in audited["suggested_reply"]
    assert "资料库" not in audited["suggested_reply"]
    assert "凭感觉" not in audited["suggested_reply"]
    assert "绝对没有" not in audited["suggested_reply"]
    assert "核实" not in audited["suggested_reply"]
    assert "确认清楚" not in audited["suggested_reply"]
    assert "转人工" not in audited["suggested_reply"]

def test_final_answer_auditor_blocks_direct_answer_when_product_card_fact_missing():
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u662f\u53ef\u4ee5\u62c6\u5378\u7684\uff0c\u65e5\u5e38\u4f7f\u7528\u5f88\u65b9\u4fbf\u3002",
        "requires_human_review": False,
        "product_context_pack": {
            "evidence_pack": {
                "answerability": "missing_product_fact",
                "query_fact_type": "detachable",
                "missing_fields": ["detachable"],
                "matched_facts": [],
            }
        },
        "evidence_debug": {"query_fact_type": "detachable"},
    }

    audited = audit_final_answer(response, customer_message="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417")

    assert audited["final_answer_audit"]["passed"] is False
    assert "product_card_missing_fact_answered_as_direct" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_allows_handoff_when_product_card_fact_missing():
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u4e2a\u62c6\u88c5\u7ec6\u8282\u6211\u5148\u5e2e\u60a8\u6838\u5b9e\u6e05\u695a\uff0c\u60a8\u7a0d\u7b49\u4e00\u4e0b\u3002",
        "requires_human_review": True,
        "product_context_pack": {
            "evidence_pack": {
                "answerability": "missing_product_fact",
                "query_fact_type": "detachable",
                "missing_fields": ["detachable"],
                "matched_facts": [],
            }
        },
        "evidence_debug": {"query_fact_type": "detachable"},
    }

    audited = audit_final_answer(response, customer_message="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417")

    assert audited["final_answer_audit"]["passed"] is True


def test_final_answer_auditor_blocks_visual_question_answered_as_load_capacity():
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff5e\u8fd9\u6b3e\u5355\u5c42\u5747\u5300\u627f\u91cd\u7ea615-30kg\uff0c\u653e\u4e66\u7c4d\u73a9\u5177\u90fd\u591f\u7528\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "visual_asset"},
    }

    audited = audit_final_answer(response, customer_message="\u6709\u6ca1\u6709\u56fe\u7247\u770b\u4e00\u4e0b")

    assert audited["final_answer_audit"]["passed"] is False
    assert any("visual_asset" in issue for issue in audited["final_answer_audit"]["issues"])
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_blocks_age_question_answered_as_load_capacity():
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff5e\u8fd9\u6b3e\u5355\u5c42\u5747\u5300\u627f\u91cd\u7ea615-30kg\uff0c\u6750\u8d28\u6bd4\u8f83\u7ed3\u5b9e\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "age_range"},
    }

    audited = audit_final_answer(response, customer_message="\u8fd9\u4e2a\u9002\u5408\u4e00\u5c81\u5b9d\u5b9d\u5417\uff1f")

    assert audited["final_answer_audit"]["passed"] is False
    assert any("age_range" in issue for issue in audited["final_answer_audit"]["issues"])
    assert "\u9002\u5408" in audited["suggested_reply"]
    assert "\u5b9d\u5b9d" in audited["suggested_reply"]
    assert "\u4e00\u5b9a\u9002\u5408" not in audited["suggested_reply"]


def test_final_answer_auditor_does_not_use_non_exact_generic_rule_as_correction():
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff0c\u6211\u5728\u7684\uff0c\u60a8\u53ef\u4ee5\u76f4\u63a5\u8bf4\u9047\u5230\u7684\u95ee\u9898\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "dimensions"},
        "context_used": {
            "product_context_pack": {
                "generic_rules": [{
                    "rule_key": "media_supported_install_size_parts_v1",
                    "fact_type": "media_reference",
                    "risk_level": "low",
                    "auto_reply_allowed": True,
                    "reply_template": "\u8fd9\u4e2a\u7ec6\u8282\u53ef\u4ee5\u53c2\u8003\u6211\u4e0b\u9762\u53d1\u60a8\u7684\u56fe\u7247\u6216\u89c6\u9891\u3002",
                    "score": 9.0,
                }],
            }
        },
    }

    audited = audit_final_answer(
        response,
        customer_message="\u53ef\u4ee5\u76f4\u63a5\u544a\u8bc9\u6211\u4f60\u4eec\u4ea7\u54c1\u7684\u5927\u5c0f\u5417",
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["requires_human_review"] is True
    assert audited["final_answer_audit"].get("correction_source") != "generic_service_rule"
    assert "\u4e0b\u9762\u53d1\u60a8\u7684\u56fe\u7247\u6216\u89c6\u9891" not in audited["suggested_reply"]
