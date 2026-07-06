from app.services.real_conversation_turn_understanding_service import (
    RealConversationTurnUnderstandingService,
    detect_reply_topics,
)


def _understand(message, **kwargs):
    return RealConversationTurnUnderstandingService().understand(message, **kwargs)


def test_receipt_and_installation_status_is_context_update_not_product_question():
    first = _understand("柜子我昨天收到已经装好了")
    variant = _understand("昨天收到了，已经装完了")

    for result in (first, variant):
        assert result["turn_actionability"] == "context_update"
        assert result["needs_rag"] is False
        assert result["should_score"] is True
        assert "dimensions" in result["forbidden_reply_topics"]
        assert "material" in result["forbidden_reply_topics"]


def test_acknowledgement_and_noise_are_not_scored_agent_turns():
    ack = _understand("好的")
    short = _understand("嗯")

    for result in (ack, short):
        assert result["turn_actionability"] == "acknowledgement"
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["should_score"] is False
        assert result["reply_strategy"] == "skip"


def test_deictic_followup_without_context_is_context_insufficient():
    result = _understand("这一块")

    assert result["turn_actionability"] == "deictic_followup"
    assert result["needs_agent_reply"] is False
    assert result["should_score"] is True
    assert result["skip_reason"] == "context_insufficient"


def test_short_context_dependent_questions_are_deictic_followups():
    for message in ("这样的床可以吗", "这种可以吗", "柜子的有吗"):
        result = _understand(message)
        assert result["turn_actionability"] == "deictic_followup"
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["should_score"] is True
        assert result["skip_reason"] == "context_insufficient"


def test_url_links_and_service_boilerplate_are_not_product_fact_questions():
    for message in (
        "https://item.taobao.com/item.htm?id=123456789",
        "https://img.alicdn.com/imgextra/demo.jpg",
        "您好~欢迎光临本小店，您看中哪些宝贝？",
        "客服已接入，请稍等",
    ):
        result = _understand(message)
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["should_score"] is False
        assert result["query_fact_type"] == ""


def test_non_question_media_reference_with_history_does_not_call_agent():
    for message in ("图里圈出来这块板", "图片这个位置", "红色圈出来背面那块板"):
        result = _understand(message, history=[{"speaker": "service", "text": "请看图"}])
        assert result["turn_actionability"] == "media_reference"
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["should_score"] is True
        assert result["skip_reason"] == "context_insufficient"
        assert result["query_fact_type"] == ""


def test_logistics_and_aftersales_short_questions_get_fact_type():
    cases = {
        "明天能到吗": "stock_shipping",
        "还没发出呢吧": "stock_shipping",
        "单号没给我呀": "stock_shipping",
        "怎么补偿": "aftersales",
        "残次品吗": "aftersales",
        "还没到一年呢": "aftersales",
        "这个断了": "aftersales",
        "板子裂了": "aftersales",
        "配件坏了怎么办": "aftersales",
        "收到的配件只有两个": "aftersales",
        "配件只有两个": "aftersales",
    }
    for message, fact_type in cases.items():
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == fact_type


def test_replay_high_frequency_service_and_product_terms_get_fact_type():
    cases = {
        "\u5e2e\u5fd9\u6539\u5730\u5740\u4e86\u5417": "order_assistance",
        "\u9001\u8d27\u4e0a\u95e8\u5417": "stock_shipping",
        "\u4ec0\u4e48\u5851\u6599": "material",
        "\u8d34\u7eb8\u8d34\u54ea\uff1f": "installation",
        "\u8fd9\u4e2a\u4e0d\u662f\u80cc\u80f6\u561b": "installation",
        "\u4f60\u4eec\u6709\u4e9b\u87ba\u5e3d\u6ed1\u7259\uff0c\u600e\u4e48\u529e": "aftersales",
        "\u8fd9\u4e24\u6b3e\u54ea\u4e2a\u627f\u653e\u7684\u6570\u91cf\u66f4\u591a": "variant_compare",
    }
    for message, fact_type in cases.items():
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == fact_type
    address_followup = _understand(
        "\u6211\u8fd9\u663e\u793a\u6ca1\u6539\u5462",
        history=[{"speaker": "buyer", "text": "\u5e2e\u5fd9\u6539\u5730\u5740\u4e86\u5417"}],
    )
    assert address_followup["turn_actionability"] == "actionable_question"
    assert address_followup["query_fact_type"] == "order_assistance"


def test_short_fragments_stay_contextual_after_fact_type_aliases():
    for message in ("\u8fd9\u4e2a\u5417", "\u4e24\u8fb9\u5462", "\u6211\u8054\u7cfb\uff1f"):
        result = _understand(message)
        assert result["query_fact_type"] == ""
        assert result["turn_actionability"] in {"deictic_followup", "noise", "actionable_question"}


def test_order_assistance_alias_does_not_steal_purchase_status_update():
    result = _understand("\u597d\u7684\uff0c\u9a6c\u4e0a\u4e0b\u5355")

    assert result["query_fact_type"] == ""
    assert result["turn_actionability"] == "noise"


def test_return_pickup_questions_are_aftersales_logistics_not_stock_shipping():
    for message in ("\u4e3a\u4ec0\u4e48\u6ca1\u6709\u4e0a\u95e8\u53d6\u4ef6", "\u9000\u8d27\u53d6\u4ef6\u600e\u4e48\u5b89\u6392", "\u5feb\u9012\u63fd\u6536\u4ec0\u4e48\u65f6\u5019\u6765"):
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == "return_pickup"
        assert result["needs_rag"] is False
        assert result["needs_tool"] is True


def test_return_pickup_does_not_steal_normal_delivery_tracking():
    for message in ("\u7269\u6d41\u5230\u54ea\u4e86", "\u4ec0\u4e48\u65f6\u5019\u53d1\u8d27", "\u8fd0\u5355\u53f7\u53d1\u6211\u4e00\u4e0b"):
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == "stock_shipping"


def test_short_deictic_dimension_needs_context_before_fact_type():
    without_context = _understand("这个多大")
    with_product_context = _understand("这个多大", product_hint="children cabinet")

    assert without_context["turn_actionability"] == "deictic_followup"
    assert without_context["needs_agent_reply"] is False
    assert without_context["skip_reason"] == "context_insufficient"
    assert without_context["query_fact_type"] == ""

    assert with_product_context["turn_actionability"] == "actionable_question"
    assert with_product_context["query_fact_type"] == "dimensions"


def test_preference_update_and_fragment_do_not_trigger_product_facts():
    preference = _understand("我要白色的")
    fragment = _understand("吗", history=[{"speaker": "service", "text": "您好"}])

    assert preference["turn_actionability"] == "context_update"
    assert preference["needs_rag"] is False
    assert "dimensions" in preference["forbidden_reply_topics"]

    assert fragment["turn_actionability"] == "deictic_followup"
    assert fragment["needs_agent_reply"] is False
    assert fragment["skip_reason"] == "context_insufficient"


def test_short_elliptical_followups_are_deictic_not_actionable_questions():
    for message in ("抽屉的也可以", "单门的", "7也行", "为什么", "为啥", "为何", "咋回事", "怎么回事"):
        result = _understand(message)
        assert result["turn_actionability"] == "deictic_followup"
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["should_score"] is True
        assert result["skip_reason"] == "context_insufficient"


def test_installation_video_and_dimension_questions_are_actionable():
    video = _understand("请发安装视频")
    size = _understand("最窄是什么尺寸")
    deictic_size = _understand("这个尺寸多少")
    install = _understand("这个怎么装")

    assert video["turn_actionability"] == "actionable_question"
    assert video["needs_rag"] is True
    assert video["query_fact_type"] == "installation"
    assert size["turn_actionability"] == "actionable_question"
    assert size["query_fact_type"] == "dimensions"
    assert deictic_size["turn_actionability"] == "actionable_question"
    assert deictic_size["query_fact_type"] == "dimensions"
    assert install["turn_actionability"] == "actionable_question"
    assert install["query_fact_type"] == "installation"


def test_structure_function_questions_are_not_space_or_scene_questions():
    cases = (
        "这个一边能放下来吗",
        "侧板可以翻下来吗",
        "护栏能不能放下",
        "三面围栏，想补第四面，这款能用吗",
        "这个护栏能补一面吗",
        "这个侧板能单独配吗",
        "这个配件能不能装这款",
    )
    for message in cases:
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == "structure_function"
        assert result["query_fact_type"] not in {"placement_scene", "space_fit", "dimensions"}


def test_structure_function_does_not_steal_scene_or_space_fit_questions():
    bedroom = _understand("这个放阳台可以吗")
    small_space = _understand("空间小能放下吗")
    cabinet = _understand("这个柜子能不能放阳台")
    bed = _understand("这个床能不能放下")

    assert bedroom["turn_actionability"] == "actionable_question"
    assert bedroom["query_fact_type"] == "placement_scene"
    assert small_space["turn_actionability"] == "actionable_question"
    assert small_space["query_fact_type"] == "space_fit"
    assert cabinet["turn_actionability"] == "actionable_question"
    assert cabinet["query_fact_type"] == "placement_scene"
    assert bed["turn_actionability"] == "actionable_question"
    assert bed["query_fact_type"] == "space_fit"


def test_can_only_becomes_actionable_with_business_action_or_question_marker():
    elliptical = _understand("抽屉的也可以")
    refund = _understand("可以退吗")
    deictic_refund = _understand("这个可以退吗")

    assert elliptical["turn_actionability"] == "deictic_followup"
    for result in (refund, deictic_refund):
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == "aftersales"


def test_aftersales_mismatch_beats_installation_or_media_terms():
    manual = _understand("发过来的说明书和物品不对")
    video = _understand("你发给我的这个视频和我买的不太一样啊")

    for result in (manual, video):
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == "aftersales"
        assert result["needs_rag"] is False


def test_promotion_questions_are_actionable_promotion_not_aftersales():
    for message in ("有没有福利", "有什么优惠", "晒图返多少"):
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == "promotion"
        assert result["needs_rag"] is True
        assert result.get("secondary_fact_types", []) == []


def test_aftersales_and_promotion_multi_intent_keeps_promotion_secondary():
    result = _understand("退货后晒图福利还给吗")

    assert result["turn_actionability"] == "actionable_question"
    assert result["query_fact_type"] == "aftersales"
    assert "promotion" in result.get("secondary_fact_types", [])


def test_accessory_component_usage_questions_are_actionable_installation_questions():
    for message in ("防倒器和这个双面贴干啥用的", "哪个是顶板", "螺丝装哪里", "有安全带吗", "有没有防倒器"):
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["needs_agent_reply"] is True
        assert result["needs_rag"] is True
        assert result["should_score"] is True
        assert result["query_fact_type"] in {"installation", "accessory_usage"}
        assert "accessory" in result["reason"]


def test_accessory_retention_updates_are_not_installation_questions():
    for message in ("配件里面的螺丝刀我留下了", "这个螺丝刀我还要用", "护栏后面还要用螺丝刀"):
        result = _understand(message, history=[{"speaker": "service", "text": "好的"}])
        assert result["turn_actionability"] == "context_update"
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["should_score"] is True
        assert result["query_fact_type"] == ""


def test_accessory_installation_and_missing_tool_questions_remain_actionable():
    cases = {
        "螺丝刀怎么用": {"installation"},
        "没有螺丝刀怎么办": {"installation", "aftersales"},
        "护栏怎么安装": {"installation"},
    }
    for message, allowed_fact_types in cases.items():
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] in allowed_fact_types


def test_price_negotiation_questions_are_actionable_promotion():
    for message in ("买两个能不能便宜点", "多买有优惠吗", "最低多少钱", "能少点吗", "有没有套餐价"):
        result = _understand(message)
        assert result["turn_actionability"] == "actionable_question"
        assert result["query_fact_type"] == "promotion"


def test_general_status_updates_do_not_call_agent():
    for message in ("好的，相当于收到好评返28", "收到后我再联系你", "昨天收到已经装好了"):
        result = _understand(message, history=[{"speaker": "service", "text": "好的"}])
        assert result["turn_actionability"] == "context_update"
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["skip_reason"] == "context_update_no_question"
        assert result["query_fact_type"] == ""


def test_aftersales_status_terms_remain_actionable():
    for message in ("我们没收到这个", "收到的底架是同一边的", "收到会不会有质量问题，是全新的吧"):
        result = _understand(message, history=[{"speaker": "service", "text": "您看下配件"}])
        assert result["turn_actionability"] == "actionable_question"
        assert result["needs_agent_reply"] is True
        assert result["query_fact_type"] == "aftersales"


def test_product_link_with_title_without_question_is_media_reference():
    for message in (
        "【淘宝】https://e.tb.cn/h.demo 英禾儿童书架落地置物架可移动书本收纳架",
        "https://item.taobao.com/item.htm?id=123456789 宝宝水杯沥干晾干支架",
    ):
        result = _understand(message)
        assert result["turn_actionability"] == "media_reference"
        assert result["needs_agent_reply"] is False
        assert result["needs_rag"] is False
        assert result["should_score"] is False
        assert result["query_fact_type"] == ""


def test_product_link_with_explicit_question_still_actionable():
    result = _understand("https://item.taobao.com/item.htm?id=123456789 这个适合几岁宝宝")

    assert result["turn_actionability"] == "actionable_question"
    assert result["query_fact_type"] == "age_range"


def test_reply_topic_detection_is_fact_type_based():
    topics = detect_reply_topics("您可以量一下宽深高，再对照尺寸图。承重以页面说明为准。")

    assert "dimensions" in topics
    assert "load_capacity" in topics


def test_replay_service_does_not_contain_mojibake_risk_terms():
    from pathlib import Path

    raw = Path("app/services/real_conversation_replay_service.py").read_text(encoding="utf-8")

    assert "锛" not in raw
    assert "鐭" not in raw
    assert "璧" not in raw
