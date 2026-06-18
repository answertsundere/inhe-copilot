"""
generate_logistics_reply 节点 - 专门处理物流场景的回复生成
根据 answer_type 生成不同回复
按场景区分 fallback 话术：
  - 场景A: 有物流单号但查不到完整轨迹
  - 场景B: 有订单且已发货但物流暂未同步
  - 场景C: 物流数据返回签收但证据不足
  - 场景D: 接口失败/超时
"""


def _get_order_items_text(order: dict) -> str:
    items = order.get("items", [])
    item_names = [i.get("name", "") for i in items if i.get("name")]
    return "、".join(item_names[:3]) if item_names else "您购买的商品"


def _fallback_tracking_no_only(tracking_no: str) -> str:
    """场景A: 有物流单号但聚水潭未查到关联订单"""
    return (
        f"亲，我帮您查了一下快递单号{tracking_no}，"
        f"暂未在系统中查到对应的物流信息。\n"
        f"麻烦您发一下订单号或订单截图，我帮您继续核实～"
    )


def _fallback_order_shipped_no_sync(order, l_id: str, courier: str) -> str:
    """场景B: 有订单且已发货但物流暂未同步"""
    items_text = _get_order_items_text(order) if order else "您的包裹"
    reply = f"亲，您的订单（{items_text}）已安排发货"
    if courier:
        reply += f"，由{courier}承运"
    if l_id:
        reply += f"，物流单号：{l_id}"
    reply += "。\n"
    reply += "物流信息可能需要1-2个工作日同步更新，请您耐心等待。"
    reply += "\n如有疑问欢迎随时联系我们哦～"
    return reply


def _fallback_low_confidence_signed(tracking_no: str, courier: str) -> str:
    """场景C: 物流数据返回签收但证据不足"""
    reply = "亲，我帮您查到的物流信息显示该包裹可能已送达，但暂无法确认具体签收状态。"
    if tracking_no:
        reply += f"\n物流单号：{tracking_no}。"
    reply += "\n您可以先看一下家人、门卫、前台、驿站、快递柜或门口附近是否代收/暂放。"
    reply += "\n我会继续帮您核实签收记录和派送情况；如果方便，也可以补充快递通知、取件码或派送电话，定位会更快。"
    reply += "\n如需进一步帮助，也可以提供更多信息，我来帮您跟进。"
    return reply


def _fallback_api_failed(tracking_no: str) -> str:
    """场景D: 接口失败/超时"""
    reply = "亲，抱歉，物流查询服务暂时不可用，我们正在加紧恢复中。"
    if tracking_no:
        reply += f"\n您的物流单号：{tracking_no}，建议您稍后再试或提供订单号让我帮您核实。"
    reply += "\n如需帮助欢迎随时联系我们哦～"
    return reply


def _is_address_change_request(msg: str) -> bool:
    return any(word in (msg or "") for word in (
        "\u6539\u5730\u5740",
        "\u6536\u8d27\u5730\u5740",
        "\u5730\u5740",
        "\u8f6c\u5bc4",
    ))


def _is_intercept_request(msg: str) -> bool:
    return any(word in (msg or "") for word in (
        "\u62e6\u622a",
        "\u62d2\u6536",
    ))


def _is_address_or_intercept_request(msg: str) -> bool:
    return _is_address_change_request(msg) or _is_intercept_request(msg)


def _has_product_safety_question(msg: str) -> bool:
    return any(word in (msg or "") for word in (
        "材质", "材料", "安全吗", "安全不", "受潮", "防潮", "甲醛", "检测报告", "有味道", "刺鼻",
    ))


def _is_pre_sale_shipping_query(msg: str) -> bool:
    msg = msg or ""
    presale_terms = ("多久发货", "几天发货", "什么时候发货", "今天能发", "今天发", "明天发", "拍下多久", "拍了多久", "下单多久")
    aftersale_terms = ("我的订单", "订单", "单号", "快递", "物流", "到哪", "到哪里", "没收到", "签收")
    return any(term in msg for term in presale_terms) and not any(term in msg for term in aftersale_terms)


def _is_order_logistics_query(msg: str) -> bool:
    msg = msg or ""
    order_terms = (
        "我的订单", "这个订单", "订单", "单号", "快递", "物流", "到哪",
        "到哪里", "没收到", "签收", "派送", "已发货", "发出了吗",
    )
    return any(term in msg for term in order_terms)


def _delivery_not_received_reply(state: dict, order: dict | None, order_id: str, tracking_no: str) -> str:
    trace = state.get("logistics_trace") or {}
    carrier = str(trace.get("carrier") or trace.get("logistics_company") or "").strip()
    trace_no = str(trace.get("tracking_no") or tracking_no or "").strip()
    known_context = bool(order or order_id or trace_no)

    reply = (
        "亲，非常抱歉给您带来不便，我理解您没收到包裹会着急。"
        "\n显示签收但您没有收到的话，我会帮您一起核实派送和签收记录。"
        "\n您可以先看一下家人、门卫、前台、驿站、快递柜或门口附近是否代收/暂放。"
    )
    if order:
        items_text = _get_order_items_text(order)
        reply += f"\n我这边会按这笔订单（{items_text}）继续核对。"
    elif known_context:
        prefix = f"{carrier} " if carrier else ""
        id_text = trace_no or order_id
        reply += f"\n我已收到当前订单/物流信息，会按 {prefix}{id_text} 继续核对。"
    else:
        reply += "\n麻烦您补充一下订单号或物流单号，我这边按号码帮您核实。"
    reply += "\n如果确认都没有收到，我这边会联系快递核实派送情况，并继续跟进处理。"
    return reply


def _known_product_name(state: dict) -> str:
    identity = state.get("order_product_identity") or {}
    return (
        state.get("matched_product_name")
        or identity.get("matched_product_name")
        or identity.get("internal_product_name")
        or ""
    )


def _usable_product_fact(state: dict) -> str:
    evidence = state.get("evidence") or {}
    for bucket in ("faq_evidence", "product_facts"):
        for item in evidence.get(bucket, []) or []:
            if item.get("source_type") == "product_mapping":
                continue
            fact = str(item.get("fact") or item.get("chunk_text") or item.get("content") or "").strip()
            if fact:
                return fact
    for item in state.get("filtered_evidence", []) or state.get("knowledge_evidence", []) or []:
        if item.get("source_type") == "product_mapping":
            continue
        fact = str(item.get("chunk_text") or item.get("fact") or item.get("content") or "").strip()
        if fact:
            return fact
    return ""


def _append_secondary_product_reply(reply: str, state: dict) -> str:
    msg = state.get("normalized_message", state.get("customer_message", "")) or ""
    product_name = _known_product_name(state)
    if not product_name or not _has_product_safety_question(msg):
        return reply

    fact = _usable_product_fact(state)
    if fact:
        product_part = f"另外关于「{product_name}」：{fact}"
    else:
        product_part = (
            f"另外关于「{product_name}」的材质安全和受潮问题，我已经先帮您对上商品，"
            "这个点我先帮您再核实一下准确说法，避免不同款式信息说错。"
            "麻烦您稍等一下，确认后我再给您准确答复。"
        )
    return f"{reply}\n{product_part}"


def _address_or_intercept_reply(msg: str, order: dict, order_status: str, courier: str, l_id: str, send_date: str) -> tuple[str, str]:
    items_text = _get_order_items_text(order) if order else "\u60a8\u7684\u5305\u88f9"
    shipped = order_status in ("shipped", "delivered", "partially_shipped") or bool(l_id or send_date)
    address_change = _is_address_change_request(msg)
    intercept = _is_intercept_request(msg)

    if shipped:
        reply = f"\u4eb2\uff0c\u5e2e\u60a8\u67e5\u5230\u8ba2\u5355\uff08{items_text}\uff09\u5df2\u7ecf\u53d1\u51fa"
        if courier:
            reply += f"\uff0c\u5feb\u9012\u662f{courier}"
        if l_id:
            reply += f"\uff0c\u5355\u53f7\u662f{l_id}"
        if send_date:
            reply += f"\uff0c\u53d1\u51fa\u65f6\u95f4\u662f{send_date}"
        reply += "\u3002"
        if address_change:
            reply += "\n\u5df2\u53d1\u51fa\u7684\u5305\u88f9\u4e0d\u80fd\u518d\u8d70\u4ed3\u5e93\u4fee\u6539\u5730\u5740\uff0c\u6211\u8fd9\u8fb9\u53ef\u4ee5\u5e2e\u60a8\u8054\u7cfb\u5feb\u9012\u5c1d\u8bd5\u6539\u5740\u6216\u62e6\u622a\u8f6c\u5bc4\uff0c\u4f46\u662f\u5feb\u9012\u9014\u4e2d\u5904\u7406\u4e0d\u80fd\u4fdd\u8bc1\u4e00\u5b9a\u6210\u529f\u3002"
        elif intercept:
            reply += "\n\u5df2\u53d1\u51fa\u540e\u4e0d\u80fd\u518d\u7531\u4ed3\u5e93\u5904\u7406\uff0c\u6211\u8fd9\u8fb9\u53ef\u4ee5\u5e2e\u60a8\u8054\u7cfb\u5feb\u9012\u5c1d\u8bd5\u62e6\u622a\uff0c\u4f46\u662f\u5df2\u5728\u9014\u7684\u5305\u88f9\u4e0d\u80fd\u4fdd\u8bc1\u4e00\u5b9a\u62e6\u622a\u6210\u529f\u3002"
        else:
            reply += "\n\u6211\u8fd9\u8fb9\u53ef\u4ee5\u5e2e\u60a8\u8054\u7cfb\u5feb\u9012\u5c1d\u8bd5\u5904\u7406\uff0c\u4f46\u662f\u5df2\u5728\u9014\u5305\u88f9\u4e0d\u80fd\u4fdd\u8bc1\u4e00\u5b9a\u6210\u529f\u3002"
        reply += "\n\u60a8\u628a\u9700\u8981\u4fee\u6539\u7684\u5b8c\u6574\u6536\u4ef6\u4fe1\u606f\u53d1\u6211\u4e00\u4e0b\uff0c\u6211\u9a6c\u4e0a\u5e2e\u60a8\u8ddf\u8fdb\uff1b\u5982\u679c\u62e6\u622a/\u6539\u5740\u4e0d\u6210\u529f\uff0c\u540e\u7eed\u53ef\u4ee5\u6839\u636e\u7269\u6d41\u60c5\u51b5\u914d\u5408\u62d2\u6536\u6216\u518d\u5904\u7406\u54e6\u3002"
        return reply, "shipped_address_or_intercept"

    reply = f"\u4eb2\uff0c\u5e2e\u60a8\u67e5\u5230\u8ba2\u5355\uff08{items_text}\uff09\u76ee\u524d\u8fd8\u6ca1\u6709\u53d1\u51fa\u3002"
    if address_change:
        reply += "\n\u8fd8\u672a\u53d1\u51fa\u7684\u8bdd\uff0c\u6211\u8fd9\u8fb9\u53ef\u4ee5\u5e2e\u60a8\u5907\u6ce8\u65b0\u5730\u5740\u5e76\u540c\u6b65\u4ed3\u5e93\uff0c\u4f46\u9700\u8981\u4ed3\u5e93\u5904\u7406\u524d\u786e\u8ba4\u6210\u529f\u540e\u624d\u7b97\u751f\u6548\u3002"
    elif intercept:
        reply += "\n\u8fd8\u672a\u53d1\u51fa\u7684\u8bdd\uff0c\u6211\u8fd9\u8fb9\u4f18\u5148\u5e2e\u60a8\u8054\u7cfb\u4ed3\u5e93\u5c1d\u8bd5\u505c\u6b62\u53d1\u8d27/\u62e6\u622a\u51fa\u5e93\uff0c\u4ee5\u4ed3\u5e93\u6700\u7ec8\u5904\u7406\u7ed3\u679c\u4e3a\u51c6\u3002"
    reply += "\n\u60a8\u5148\u628a\u9700\u8981\u4fee\u6539\u7684\u5b8c\u6574\u6536\u4ef6\u4fe1\u606f\u6216\u5904\u7406\u8981\u6c42\u53d1\u6211\uff0c\u6211\u9a6c\u4e0a\u5e2e\u60a8\u8ddf\u8fdb\u3002"
    return reply, "pending_address_or_intercept"


def generate_logistics_reply(state: dict) -> dict:
    """生成物流场景回复"""
    msg = state.get("normalized_message", state.get("customer_message", ""))
    order = state.get("live_order") or state.get("order")
    order_status = state.get("order_status", "")
    logistics_trace = state.get("logistics_trace")
    policy = state.get("shipping_policy", {})
    product_name = state.get("matched_product_name", "")
    slots = state.get("slots", {})
    order_id = slots.get("order_id", "")
    tracking_no = slots.get("tracking_no", "")
    need_clarification = state.get("need_clarification", False)
    clarification_question = state.get("clarification_question", "")
    evidence = state.get("evidence", {})
    conflicts = evidence.get("conflicts", [])

    # 有冲突时优先人工复核
    if conflicts:
        reply = (
            "亲，您的问题涉及一些需要核实的信息，"
            "为了确保准确回复，我需要将您的问题提交给专人进一步确认。"
            "请您稍等，我们会尽快给您答复。"
        )
        return {
            "suggested_reply": reply,
            "answer_type": "human_review",
            "requires_human_review": True,
            "review_reason": "证据冲突",
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "generate_logistics_reply",
                "status": "success",
                "duration_ms": 0,
                "cache_hit": False,
                "answer_type": "human_review",
                "summary": "检测到证据冲突，生成安全回复",
            }],
        }

    # ========== 需要追问 ==========
    if need_clarification and clarification_question:
        return {
            "suggested_reply": clarification_question,
            "answer_type": "clarification_needed",
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "generate_logistics_reply",
                "status": "success",
                "duration_ms": 0,
                "cache_hit": False,
                "answer_type": "clarification_needed",
                "summary": "需要追问商品信息",
            }],
        }

    # ========== 签收未收到场景 ==========
    intent = state.get("intent", "")
    if intent == "delivery_not_received":
        reply = _delivery_not_received_reply(state, order, order_id, tracking_no)
        return {
            "suggested_reply": reply,
            "answer_type": "human_review",
            "requires_human_review": True,
            "review_reason": "签收未收到，需人工跟进核实",
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "generate_logistics_reply",
                "status": "success",
                "duration_ms": 0,
                "cache_hit": False,
                "answer_type": "human_review",
                "summary": "签收未收到场景，安抚+引导核实+人工跟进",
            }],
        }

    # ========== 1. 有订单 ==========
    if order:
        items_text = _get_order_items_text(order)
        courier = order.get("logistics_company", "")
        l_id = order.get("l_id", "")
        send_date = order.get("send_date", "")
        sign_time = order.get("sign_time", "")
        used_endpoint = state.get("used_endpoint", "")
        is_outbound = "out/simple" in used_endpoint

        if _is_address_or_intercept_request(msg):
            reply, answer_type = _address_or_intercept_reply(msg, order, order_status, courier, l_id, send_date)
            return {
                "suggested_reply": reply,
                "answer_type": "verified",
                "trace_steps": state.get("trace_steps", []) + [{
                    "node": "generate_logistics_reply",
                    "status": "success",
                    "duration_ms": 0,
                    "cache_hit": False,
                    "answer_type": "verified",
                    "summary": answer_type,
                }],
            }

        # 1a. 未付款/已取消/已退款
        if order_status in ("unpaid", "canceled", "cancelled", "refunded"):
            status_text = {
                "unpaid": "未付款",
                "canceled": "已取消",
                "refunded": "已退款",
            }.get(order_status, order_status)
            reply = f"亲，您的订单（{items_text}）当前状态为{status_text}，暂时无法查询物流信息。"
            if order_status == "refunded":
                reply += "\n该订单已办理退款，如有疑问请联系客服处理。"
            return {
                "suggested_reply": reply,
                "answer_type": "verified",
                "trace_steps": state.get("trace_steps", []) + [{
                    "node": "generate_logistics_reply",
                    "status": "success",
                    "duration_ms": 0,
                    "cache_hit": False,
                    "answer_type": "verified",
                    "summary": f"订单状态{order_status}，说明状态",
                }],
            }

        # 1b. 售后中
        if order_status == "aftersales":
            reply = f"亲，您的订单（{items_text}）当前正在售后处理中。"
            reply += "\n售后期间的物流信息请以售后页面的最新状态为准，如有疑问请联系客服跟进。"
            return {
                "suggested_reply": reply,
                "answer_type": "verified",
                "trace_steps": state.get("trace_steps", []) + [{
                    "node": "generate_logistics_reply",
                    "status": "success",
                    "duration_ms": 0,
                    "cache_hit": False,
                    "answer_type": "verified",
                    "summary": "订单售后中",
                }],
            }

        # 1c. 待发货/预售/缺货
        if order_status in ("pending_shipment", "presale", "out_of_stock"):
            status_text = {
                "pending_shipment": "待发货",
                "presale": "预售",
                "out_of_stock": "缺货/备货中",
            }.get(order_status, "未发货")
            reply = f"亲，您的订单（{items_text}）当前状态为{status_text}，尚未发货。"
            if policy.get("ship_within_hours"):
                reply += f"\n我们通常会在付款后{policy['ship_within_hours']}小时内安排发货（工作日）。"
            elif policy.get("default_courier"):
                reply += "\n我们会按店铺页面承诺的时效尽快安排发货。"
            else:
                reply += "\n我们会按店铺页面承诺的时效尽快安排发货。"
            if policy.get("default_courier"):
                reply += f"\n默认使用{policy['default_courier']}配送。"
            if policy.get("eta_days_min") and policy.get("eta_days_max"):
                reply += f"\n发出后通常运输时效为 {policy['eta_days_min']}-{policy['eta_days_max']} 天，具体以实际物流为准。"
            reply += "\n发货后我会第一时间通知您，请您耐心等待哦～"
            return {
                "suggested_reply": reply,
                "answer_type": "verified",
                "trace_steps": state.get("trace_steps", []) + [{
                    "node": "generate_logistics_reply",
                    "status": "success",
                    "duration_ms": 0,
                    "cache_hit": False,
                    "answer_type": "verified",
                    "summary": f"订单{order_status}，说明未发货+时效",
                }],
            }

        # 1d. 部分发货
        if order_status == "partially_shipped":
            reply = f"亲，您的订单（{items_text}）已部分发货。"
            reply += "\n部分商品已发出，剩余商品正在仓库加紧备货中。"
            if l_id:
                reply += f"\n已发包裹物流单号：{l_id}"
            reply += "\n具体送达时间以实际物流更新为准，如有疑问欢迎随时联系我们哦～"
            return {
                "suggested_reply": reply,
                "answer_type": "verified",
                "trace_steps": state.get("trace_steps", []) + [{
                    "node": "generate_logistics_reply",
                    "status": "success",
                    "duration_ms": 0,
                    "cache_hit": False,
                    "answer_type": "verified",
                    "summary": "订单部分发货",
                }],
            }

        # 1e. 已发货/已签收 + 有物流轨迹
        if order_status in ("shipped", "delivered") and logistics_trace and logistics_trace.get("status") not in ("no_trace", "api_failed", ""):
            latest = logistics_trace.get("latest", {})
            low_conf = logistics_trace.get("low_confidence", False)
            trace_status = logistics_trace.get("status", "")

            # Outbound (sales out) sourced: only say "已发出", never "已签收" without sign_time evidence
            if is_outbound and not sign_time:
                reply = f"亲，帮您查到这笔订单已经发出"
                if courier:
                    reply += f"，快递是{courier}"
                if l_id:
                    reply += f"，单号是{l_id}"
                if send_date:
                    reply += f"，发出时间是{send_date}"
                reply += "。具体送达时间以实际物流更新为准～"
                return {
                    "suggested_reply": reply,
                    "answer_type": "verified",
                    "trace_steps": state.get("trace_steps", []) + [{
                        "node": "generate_logistics_reply",
                        "status": "success",
                        "duration_ms": 0,
                        "cache_hit": False,
                        "answer_type": "verified",
                        "summary": f"outbound 已发出（无签收证据），不承诺送达时间",
                    }],
                }

            if (order_status == "delivered" or logistics_trace.get("is_delivered")) and not low_conf:
                reply = f"亲，您的订单（{items_text}）{courier}包裹已签收。"
                if l_id:
                    reply += f"（单号：{l_id}）"
                if latest:
                    reply += f"\n签收时间：{latest.get('time', '')} {latest.get('context', '')}"
                reply += "\n如对商品有任何问题，请及时联系我们处理哦。"
            elif low_conf and trace_status == "uncertain":
                # 场景C: 物流数据返回签收但证据不足
                reply = _fallback_low_confidence_signed(l_id or "", courier)
            elif low_conf:
                # 低可信度：不肯定签收，引导核实
                reply = f"亲，您的订单（{items_text}）的物流信息更新较少，目前暂时无法确认具体状态。"
                if l_id:
                    reply += f"\n物流单号：{l_id}。"
                reply += "\n您可以先看一下家人、门卫、前台、驿站、快递柜或门口附近是否代收/暂放。"
                reply += "\n我会继续帮您核实签收记录和派送情况；如果方便，也可以补充快递通知、取件码或派送电话，定位会更快。"
            else:
                reply = f"亲，您的订单（{items_text}）已由{courier}发货"
                if l_id:
                    reply += f"，物流单号：{l_id}"
                reply += "。"
                if latest:
                    reply += f"\n最新物流：{latest.get('time', '')} {latest.get('context', '')}"
                reply += "\n具体送达时间以实际物流更新为准，如有疑问欢迎随时联系我们哦～"

            return {
                "suggested_reply": reply,
                "answer_type": "verified",
                "trace_steps": state.get("trace_steps", []) + [{
                    "node": "generate_logistics_reply",
                    "status": "success",
                    "duration_ms": 0,
                    "cache_hit": False,
                    "answer_type": "verified",
                    "summary": f"订单{order_status}，有物流轨迹" + (" [信息较少]" if low_conf else ""),
                }],
            }

        # 1f. 已发货/已签收 + 无物流轨迹（场景B: 有订单但物流未同步）
        if order_status in ("shipped", "delivered"):
            reply = _fallback_order_shipped_no_sync(order, l_id, courier)
            return {
                "suggested_reply": reply,
                "answer_type": "verified",
                "trace_steps": state.get("trace_steps", []) + [{
                    "node": "generate_logistics_reply",
                    "status": "success",
                    "duration_ms": 0,
                    "cache_hit": False,
                    "answer_type": "verified",
                    "summary": f"订单{order_status}，无物流轨迹（物流可能未同步）",
                }],
            }

    # ========== 2. 无订单 + 有物流轨迹 ==========
    if logistics_trace and logistics_trace.get("status") not in ("no_trace", "api_failed", ""):
        latest = logistics_trace.get("latest", {})
        l_id = logistics_trace.get("tracking_no", "")
        courier = logistics_trace.get("carrier", "")
        low_conf = logistics_trace.get("low_confidence", False)
        trace_status = logistics_trace.get("status", "")

        if logistics_trace.get("is_delivered") and not low_conf:
            reply = f"亲，我帮您查了一下，{courier}快递（单号：{l_id}）显示已签收。"
            if latest:
                reply += f"\n签收时间：{latest.get('time', '')} {latest.get('context', '')}"
            reply += "\n如对商品有任何问题，请及时联系我们处理哦。"
        elif low_conf and trace_status == "uncertain":
            # 场景C: 证据不足的签收
            reply = _fallback_low_confidence_signed(l_id, courier)
        elif low_conf:
            reply = f"亲，我查到这个单号（{l_id}）目前物流信息较少，状态需要进一步核实。"
            reply += "\n您可以先看一下家人、门卫、前台、驿站、快递柜或门口附近是否代收/暂放。"
            reply += "\n我会继续帮您核实签收记录和派送情况；如果方便，也可以补充订单号、快递通知、取件码或派送电话，定位会更快。"
        elif trace_status == "api_failed":
            # 场景D: 接口失败
            reply = _fallback_api_failed(l_id)
        else:
            reply = f"亲，我帮您查了一下{courier}的物流动态哦～"
            if l_id:
                reply += f"（单号：{l_id}）"
            if latest:
                reply += f"\n最新更新：{latest.get('time', '')} {latest.get('context', '')}"
            reply += "\n具体送达时间以实际物流更新为准，如有疑问欢迎随时联系我们哦～"
            if not order and "订单号" not in reply:
                reply += "\n如需查询关联的商品订单信息，请提供订单号哦～"

        answer_type_val = "estimated" if low_conf else "verified"
        return {
            "suggested_reply": reply,
            "answer_type": answer_type_val,
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "generate_logistics_reply",
                "status": "success",
                "duration_ms": 0,
                "cache_hit": False,
                "answer_type": answer_type_val,
                "summary": "无订单有物流轨迹" + (" [信息较少]" if low_conf else ""),
            }],
        }

    # ========== 3. 场景D: 接口失败/超时 ==========
    if logistics_trace and logistics_trace.get("status") == "api_failed":
        l_id = logistics_trace.get("tracking_no", "") or tracking_no
        reply = _fallback_api_failed(l_id)
        return {
            "suggested_reply": reply,
            "answer_type": "fallback",
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "generate_logistics_reply",
                "status": "success",
                "duration_ms": 0,
                "cache_hit": False,
                "answer_type": "fallback",
                "summary": "物流接口失败/超时",
            }],
        }

    # ========== 4. 无订单 + 有快递单号但查不到轨迹 ==========
    if tracking_no and not order:
        reply = (
            f"亲，我这边暂未查询到该物流单号对应的订单/物流信息。"
            f"\n麻烦您核对一下物流单号是否正确，或者发一下订单截图，我帮您继续核实～"
        )
        return {
            "suggested_reply": reply,
            "answer_type": "fallback",
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "generate_logistics_reply",
                "status": "success",
                "duration_ms": 0,
                "cache_hit": False,
                "answer_type": "fallback",
                "summary": "场景A: 有物流单号但查不到",
            }],
        }

    # ========== 5. 无订单 + 有订单号/编号但查不到订单 ==========
    possible_numeric_id = slots.get("possible_numeric_id", "")
    lookup_id = order_id or possible_numeric_id
    if lookup_id and not order and not tracking_no:
        id_type = slots.get("identifier_type", "")
        if id_type == "order_id":
            reply = (
                f"亲，我这边暂时没有查询到该订单号对应的订单/物流信息。"
                f"\n麻烦您确认一下订单号是否正确，或者发一下订单截图，我帮您继续核实～"
            )
        elif id_type == "unknown_identifier":
            reply = (
                f"亲，我已经用这个编号 {lookup_id} 在聚水潭按订单号、平台订单号和近期物流单号尝试查询，暂时没有查到对应的订单/物流信息。"
                f"\n可能是单号输入有误、平台订单暂未同步，或物流单号不在近期可检索范围内。麻烦您发一下订单截图，我帮您继续核实～"
            )
        else:
            reply = (
                f"亲，我这边暂时没有查询到该单号对应的订单/物流信息。"
                f"\n麻烦您确认一下单号是否正确，或者发一下订单截图，我帮您继续核实～"
            )
        return {
            "suggested_reply": reply,
            "answer_type": "fallback",
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "generate_logistics_reply",
                "status": "success",
                "duration_ms": 0,
                "cache_hit": False,
                "answer_type": "fallback",
                "summary": "有单号但查不到订单",
            }],
        }

    # ========== 6. 无订单 + 能匹配商品 ==========
    if product_name:
        answer_mode = state.get("answer_mode", "")
        if answer_mode == "logistics_time_commitment":
            reply = f"亲，关于{product_name}的送达时间："
            reply += "\n非常理解您着急的心情，但物流运输受天气、交通、分拣等多种因素影响，我们无法承诺具体到某一天一定能送达。"
            if policy.get("eta_days_min") and policy.get("eta_days_max"):
                reply += f"\n该商品发出后通常运输时效为 {policy['eta_days_min']}-{policy['eta_days_max']} 天，具体以实际物流更新为准。"
            if policy.get("default_courier"):
                reply += f"\n默认使用{policy['default_courier']}配送。"
            reply += "\n如果您有订单号，我可以帮您查询当前最新的物流状态和预计送达时间哦～"
        else:
            if _is_pre_sale_shipping_query(msg):
                reply = f"亲～关于「{product_name}」的发货时间："
            else:
                reply = f"亲，关于{product_name}的物流情况："
            if policy.get("default_courier"):
                reply += f"\n默认使用{policy['default_courier']}配送。"
            if policy.get("eta_days_min") and policy.get("eta_days_max"):
                reply += f"\n发出后通常运输时效为 {policy['eta_days_min']}-{policy['eta_days_max']} 天，具体以实际物流为准。"
            if policy.get("ship_within_hours"):
                reply += f"\n通常会在付款后{policy['ship_within_hours']}小时内安排发货（工作日）。"
            elif _is_pre_sale_shipping_query(msg):
                reply += "\n通常会按商品页面展示的发货时效安排，若页面有预售、定制或活动发货说明，以页面提示为准。"
            else:
                reply += "\n通常会按店铺页面承诺时效安排发货，具体以订单实际状态为准。"
            if _is_pre_sale_shipping_query(msg):
                reply += "\n如果您比较着急，可以先看下页面是否有预售/定制/活动发货说明；拍下后会按订单顺序安排出库哦～"
            elif _is_order_logistics_query(msg):
                reply += "\n如果是已经下单的包裹，您发一下订单号，我可以帮您查当前订单状态。"
        return {
            "suggested_reply": reply,
            "answer_type": "estimated",
            "trace_steps": state.get("trace_steps", []) + [{
                "node": "generate_logistics_reply",
                "status": "success",
                "duration_ms": 0,
                "cache_hit": False,
                "answer_type": "estimated",
                "summary": "无订单，匹配商品，通用政策" + (" [时效承诺]" if answer_mode == "logistics_time_commitment" else ""),
            }],
        }

    # ========== 7. 无订单无商品 ==========
    answer_mode = state.get("answer_mode", "")
    if answer_mode == "logistics_time_commitment":
        reply = (
            "亲，非常理解您希望包裹准时到达的心情。"
            "\n但由于物流运输受天气、路况、分拣等多种因素影响，我们无法对具体到某一天或某一时刻的送达做出绝对承诺。"
            "\n实际送达时间以快递公司物流更新为准。"
            "\n如果您能提供订单号或物流单号，我可以帮您查询当前最新的物流动态和预计送达时间哦～"
        )
    else:
        reply = (
            "亲，为了帮您准确查询物流信息，麻烦提供一下您的订单号哦～\n"
            "如果您记得购买的商品名称，也可以告诉我，我帮您查看发货时效。"
        )
    return {
        "suggested_reply": reply,
        "answer_type": "clarification_needed",
        "trace_steps": state.get("trace_steps", []) + [{
            "node": "generate_logistics_reply",
            "status": "success",
            "duration_ms": 0,
            "cache_hit": False,
            "answer_type": "clarification_needed",
            "summary": "无标识符，引导提供信息" + (" [时效承诺]" if answer_mode == "logistics_time_commitment" else ""),
        }],
    }
