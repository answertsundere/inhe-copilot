"""Reply relevance guard regression tests."""

from app.agent.nodes.reply_relevance_guard import reply_relevance_guard


def _run(message: str, reply: str, **state_overrides) -> dict:
    state = {
        "customer_message": message,
        "normalized_message": message,
        "suggested_reply": reply,
        "trace_steps": [],
        "guard_warnings": [],
        "slots": {},
        "tool_results": {},
        **state_overrides,
    }
    return reply_relevance_guard(state)


def test_installation_video_cannot_answer_load_capacity():
    result = _run(
        "我要安装视频",
        "关于3号云屋收纳柜：承重/容量 8.58",
        matched_product_name="3号云屋收纳柜",
        intent="installation",
    )

    guard = result["reply_relevance_guard"]
    assert guard["passed"] is False
    assert guard["wrong_fact_type"] is True
    assert "承重" not in result["suggested_reply"]
    assert "容量" not in result["suggested_reply"]
    assert "安装" in result["suggested_reply"]


def test_book_capacity_cannot_use_faucet_product():
    result = _run(
        "可以放多少本绘本",
        "亲，这款商品的承重/容量是 0.15。",
        matched_product_name="1号快乐鲸鱼水龙头延长器",
        intent="product_question",
    )

    guard = result["reply_relevance_guard"]
    assert guard["passed"] is False
    assert guard["product_context_mismatch"] is True
    assert "0.15" not in result["suggested_reply"]
    assert "商品" in result["suggested_reply"]
    assert "不一致" in result["suggested_reply"] or "确认" in result["suggested_reply"]


def test_gift_missing_cannot_answer_material():
    result = _run(
        "页面说有赠品，我收到怎么没有？",
        "这款商品材质是PP，日常使用很方便。",
        intent="gift_missing",
    )

    guard = result["reply_relevance_guard"]
    assert guard["passed"] is False
    assert guard["wrong_fact_type"] is True
    assert "赠品" in result["suggested_reply"]
    assert "PP" not in result["suggested_reply"]


def test_invoice_question_rejects_vague_general_reply():
    result = _run(
        "这个订单可以开电子发票吗？",
        "亲，我帮您判断下一步怎么处理。",
        intent="invoice",
    )

    guard = result["reply_relevance_guard"]
    assert guard["passed"] is False
    assert "invoice" in guard["missed_questions"]
    assert "发票" in result["suggested_reply"] or "开票" in result["suggested_reply"]


def test_multi_question_reports_material_as_missed():
    result = _run(
        "帮我查快递到哪了，还有这个材质安全吗？",
        "亲，您的快递正在运输中，具体以物流更新为准。",
        intent="logistics_eta",
    )

    guard = result["reply_relevance_guard"]
    assert guard["passed"] is False
    assert "material_safety" in guard["missed_questions"]
    assert "材质" in result["suggested_reply"] or "安全" in result["suggested_reply"]


def test_presale_shipping_does_not_require_order_id():
    result = _run(
        "现在拍多久发货？",
        "麻烦您提供订单号，我帮您查询。",
        intent="stock_query",
    )

    guard = result["reply_relevance_guard"]
    assert guard["passed"] is False
    assert any("unnecessary_order" in issue for issue in guard["issues"])
    assert "订单号" not in result["suggested_reply"]
    assert "发货" in result["suggested_reply"]


def test_order_shipping_reply_does_not_leak_internal_fact_type():
    reply = "亲，您的订单当前状态为待发货，尚未发货，我们会尽快安排。"
    result = _run(
        "什么时候发货",
        reply,
        intent="logistics_eta",
        order_id="202501010003",
        slots={"order_id": "202501010003"},
        tool_results={"jst_lookup_order_tool": {"found": False}},
    )

    assert "stock_shipping" not in result["suggested_reply"]
    assert result["suggested_reply"] == reply


def test_absolute_child_safety_promise_is_blocked():
    result = _run(
        "你保证我孩子用了绝对不会出事吗？",
        "亲，保证绝对不会出事，一定安全。",
        intent="child_safety",
    )

    guard = result["reply_relevance_guard"]
    assert guard["passed"] is False
    assert any("unsafe_promise" in issue for issue in guard["issues"])
    assert "保证绝对不会" not in result["suggested_reply"]
    assert "一定安全" not in result["suggested_reply"]
    assert "不能" in result["suggested_reply"]


def test_negated_delivery_guarantee_is_not_blocked():
    reply = "亲，订单已发出，可以尝试申请快递拦截，但不能保证一定成功。"
    result = _run(
        "可以帮我拦截吗？",
        reply,
        intent="logistics_eta",
        order_id="6926666820903533935",
        slots={"platform_order_id": "6926666820903533935"},
        tool_results={"jst_lookup_outbound_tool": {"found": True}},
    )

    assert result["suggested_reply"] == reply
    assert not any(
        "unsafe_promise" in issue
        for issue in result["reply_relevance_guard"]["issues"]
    )


def test_internal_system_language_is_removed():
    result = _run(
        "这个是什么材质？",
        "系统里没有明确证据，Evidence Gate 没通过，我不能凭感觉猜。",
        intent="product_question",
    )

    assert result["reply_relevance_guard"]["passed"] is False
    assert "系统里没有明确证据" not in result["suggested_reply"]
    assert "Evidence Gate" not in result["suggested_reply"]
    assert "不能凭感觉猜" not in result["suggested_reply"]


def test_order_sensitive_question_requires_order_tool_execution():
    result = _run(
        "页面说有赠品，我收到怎么没有？",
        "亲，您的订单没有赠品。",
        intent="gift_missing",
        order_id="5116887975001001001",
        slots={"order_id": "5116887975001001001"},
        required_tools=["jst_lookup_outbound_tool"],
        tool_results={},
    )

    guard = result["reply_relevance_guard"]
    assert guard["passed"] is False
    assert any("order_tool_not_executed" in issue for issue in guard["issues"])
    assert "没有赠品" not in result["suggested_reply"]
    assert "订单信息" in result["suggested_reply"] or "核实" in result["suggested_reply"]


def test_good_installation_reply_passes_unchanged():
    reply = "亲，您需要的是3号云屋收纳柜的安装视频，我先帮您核对对应型号的安装资料。"
    result = _run(
        "我要安装视频",
        reply,
        matched_product_name="3号云屋收纳柜",
        intent="installation",
    )

    assert result["reply_relevance_guard"]["passed"] is True
    assert result["suggested_reply"] == reply


def test_guard_rewrites_at_most_once():
    first = _run(
        "我要安装视频",
        "承重/容量 8.58",
        intent="installation",
    )
    second = reply_relevance_guard({
        "customer_message": "我要安装视频",
        "normalized_message": "我要安装视频",
        "suggested_reply": "承重/容量 8.58",
        "reply_relevance_rewrite_count": first["reply_relevance_rewrite_count"],
        "trace_steps": first["trace_steps"],
        "guard_warnings": first["guard_warnings"],
    })

    assert first["reply_relevance_rewrite_count"] == 1
    assert second["reply_relevance_rewrite_count"] == 1
    assert second["suggested_reply"] == "承重/容量 8.58"


def test_relevance_rewrite_does_not_replace_business_answer_mode():
    result = _run(
        "可以放多少本绘本？",
        "承重/容量 0.15",
        intent="product_question",
        answer_mode="no_evidence_clarification",
        matched_product_name="1号快乐鲸鱼水龙头延长器",
    )

    assert "answer_mode" not in result
    assert result["generation_mode"] == "relevance_guard_fallback"


def test_graph_places_relevance_guard_before_build_response():
    from app.agent.graph import customer_service_graph

    graph = customer_service_graph.get_graph()
    edges = list(graph.edges)
    grounding_outgoing = [
        edge.target for edge in edges
        if edge.source == "post_generation_grounding_guard"
    ]
    relevance_outgoing = [
        edge.target for edge in edges
        if edge.source == "reply_relevance_guard"
    ]

    assert "reply_relevance_guard" in grounding_outgoing
    assert "build_response" in relevance_outgoing


def test_failed_relevance_guard_becomes_a_bad_case_candidate():
    from app.services.bad_case_service import should_auto_create_bad_case

    should_create, reason = should_auto_create_bad_case(
        execution_debug={
            "guards": [{
                "guard_name": "reply_relevance_guard",
                "passed": False,
            }],
        },
    )

    assert should_create is True
    assert reason == "reply_relevance_rewrite"
