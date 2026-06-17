from app.services.customer_reply_polisher import polish_customer_reply


def test_polisher_removes_internal_material_safety_process_language():
    response = {
        "suggested_reply": (
            "亲～\n"
            "🌿 宝宝用的东西您关心材质和安全很正常，我先按当前商品「九号防夹滑门收纳柜」帮您核实一下准确说法。\n"
            "🌿 材质和防潮说明这类信息我不先凭感觉判断，避免给您说错。\n"
            "👉 麻烦您稍等一下，我这边确认清楚后再回复您。\n"
            "如果您手边有商品页面的材质说明截图，也可以一起发来，我这边会一起对照核实。"
        )
    }

    polished = polish_customer_reply(
        response,
        customer_message="这个材质安全吗？会不会容易受潮？",
    )
    reply = polished["suggested_reply"]

    assert "九号防夹滑门收纳柜" in reply
    assert "材质" in reply
    assert "准确说法" not in reply
    assert "凭感觉" not in reply
    assert "避免给您说错" not in reply
    assert "系统里" not in reply
    assert "资料库" not in reply
    assert polished["customer_reply_polish"]["applied"] is True


def test_polisher_keeps_business_decision_but_softens_handoff():
    response = {
        "suggested_reply": (
            "亲，您担心的是「九号防夹滑门收纳柜」会不会夹手、家里宝宝使用是否安全对吗？\n"
            "这个点我先帮您按对应款式核实清楚，避免不同款式结构说错影响您判断。\n"
            "麻烦您稍等一下，我确认清楚后再按准确说法回复您。"
        )
    }

    polished = polish_customer_reply(response, customer_message="家里有宝宝，会不会夹手？")
    reply = polished["suggested_reply"]

    assert "夹手" in reply
    assert "九号防夹滑门收纳柜" in reply
    assert "准确说法" not in reply
    assert "凭感觉" not in reply
    assert "您稍等一下" in reply


def test_polisher_redacts_internal_system_terms():
    response = {
        "suggested_reply": "亲，系统里目前没有这款商品的已审核资料，知识库暂时没有可直接引用的说明，我先转人工。",
    }

    polished = polish_customer_reply(response, customer_message="这个能拆吗？")
    reply = polished["suggested_reply"]

    assert "系统里" not in reply
    assert "知识库" not in reply
    assert "已审核资料" not in reply
    assert "可直接引用" not in reply
