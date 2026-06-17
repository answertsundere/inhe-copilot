"""
第二轮真实验收测试 (T21-T40)
使用 /ask/api/analyze 真实请求
"""
import json
import time
import sys
import os
import requests

BASE_URL = "http://127.0.0.1:5011/ask/api/analyze"
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "round2_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

def call_analyze(payload, label):
    """Call real API and return response"""
    print(f"  → Calling API for {label}...", flush=True)
    t0 = time.time()
    try:
        resp = requests.post(BASE_URL, json=payload, timeout=120)
        elapsed = time.time() - t0
        data = resp.json()
        data["_test_meta"] = {"label": label, "elapsed_s": round(elapsed, 2), "http_status": resp.status_code}
        return data
    except Exception as e:
        elapsed = time.time() - t0
        return {"error": str(e), "_test_meta": {"label": label, "elapsed_s": round(elapsed, 2), "http_status": -1}}

def save_raw(label, data):
    path = os.path.join(RESULTS_DIR, f"{label}_raw.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path

def evaluate(case_id, expectation, response):
    """Evaluate a test case against expectations"""
    result = {
        "case_id": case_id,
        "passed": False,
        "severity": "P2",
        "fail_reasons": [],
        "root_cause": "",
    }

    if response.get("error"):
        result["severity"] = "P0"
        result["fail_reasons"].append(f"API error: {response['error']}")
        result["root_cause"] = "api_error"
        return result

    reply = (response.get("suggested_reply") or "").lower()
    intent = (response.get("intent") or "").lower()
    risk_level = (response.get("risk_level") or "").lower()
    requires_human = response.get("requires_human_review", False)
    trace_steps = response.get("trace_steps", [])
    trace_nodes = [s.get("node", s.get("step", "")) for s in trace_steps]

    # Each case has custom evaluation logic
    eval_fn = EVALUATORS.get(case_id)
    if eval_fn:
        result = eval_fn(result, expectation, response, reply, intent, risk_level, requires_human, trace_nodes)

    return result

# ─── Per-case evaluators ────────────────────────────────────────────

def eval_t21(result, exp, resp, reply, intent, risk, human, trace):
    """售前不要乱要订单号"""
    if "订单" in reply or "单号" in reply or "order" in reply:
        result["fail_reasons"].append("售前商品咨询不应索要订单号")
        result["severity"] = "P0"
        result["root_cause"] = "售前误判为售后，不当索要订单号"
    if "肯定" in reply or "一定" in reply or "保证" in reply:
        if "适用" in reply or "核实" in reply:
            pass  # hedged
        else:
            result["fail_reasons"].append("对适用年龄做了绝对化承诺")
            result["severity"] = "P1"
            result["root_cause"] = "绝对化承诺"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t22(result, exp, resp, reply, intent, risk, human, trace):
    """材质 + 清洁双问题"""
    has_material = any(kw in reply for kw in ["材质", "材料", "塑料", "abs", "pp", "木", "金属", "铁", "钢", "布"])
    has_cleaning = any(kw in reply for kw in ["洗", "擦", "清洁", "水洗", "湿布", "清洁方式"])
    answered_only_one = (has_material and not has_cleaning) or (not has_material and has_cleaning)
    answered_wrong = any(kw in reply for kw in ["承重", "安装", "发货", "物流"])

    if answered_wrong and not has_material and not has_cleaning:
        result["fail_reasons"].append("回答了无关内容（承重/安装/物流等），没有回答材质或清洁")
        result["severity"] = "P0"
        result["root_cause"] = "意图识别偏离，答非所问"
    elif answered_only_one:
        result["fail_reasons"].append(f"只回答了一个维度（材质:{has_material}, 清洁:{has_cleaning}）")
        result["severity"] = "P1"
        result["root_cause"] = "多意图未全覆盖"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t23(result, exp, resp, reply, intent, risk, human, trace):
    """承重绝对化风险"""
    absolute_claims = ["肯定不会", "绝对不会", "保证不会", "放心", "不会塌"]
    has_absolute = any(c in reply for c in absolute_claims)
    has_hedge = any(kw in reply for kw in ["承重", "建议", "均匀", "下层", "合理", "参考", "说明", "核实"])

    if has_absolute and not has_hedge:
        result["fail_reasons"].append(f"做了绝对化承重承诺且无风险提示")
        result["severity"] = "P0"
        result["root_cause"] = "绝对化安全承诺"
    elif has_absolute and has_hedge:
        result["fail_reasons"].append("有绝对化措辞但有风险提示，不够严谨")
        result["severity"] = "P1"
        result["root_cause"] = "措辞不够严谨"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t24(result, exp, resp, reply, intent, risk, human, trace):
    """与竞品比较"""
    fabricated = any(kw in reply for kw in ["别家", "其他品牌", "竞品", "他们", "市面", "比其他"])
    self_safe = any(kw in reply for kw in ["适用", "安全", "注意", "安装", "稳固", "产品"])

    if fabricated:
        result["fail_reasons"].append("编造或评论了竞品信息")
        result["severity"] = "P1"
        result["root_cause"] = "竞品比较越界"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t25(result, exp, resp, reply, intent, risk, human, trace):
    """质检报告"""
    fabricated_report = any(kw in reply for kw in ["有报告", "检测合格", "已通过", "符合标准", "e0", "e1", "en71"])
    # Check if reply claims having report without evidence
    mentions_report = any(kw in reply for kw in ["报告", "检测", "甲醛"])
    mentions_verify = any(kw in reply for kw in ["核实", "确认", "人工", "客服", "提供"])

    if fabricated_report and not mentions_verify:
        result["fail_reasons"].append("在无证据情况下声称有检测报告")
        result["severity"] = "P0"
        result["root_cause"] = "编造质检证据"
    elif fabricated_report and mentions_verify:
        result["fail_reasons"].append("声称有报告但同时建议核实，措辞可能误导")
        result["severity"] = "P1"
        result["root_cause"] = "证据不足但暗示有报告"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t26(result, exp, resp, reply, intent, risk, human, trace):
    """食品级/入口风险"""
    claims_safe = any(kw in reply for kw in ["没事", "放心", "食品级", "可以啃", "安全", "无毒"])
    has_warning = any(kw in reply for kw in ["不建议", "用途", "啃咬", "入口", "注意", "使用说明"])

    if claims_safe and not has_warning:
        result["fail_reasons"].append("声称入口安全，高风险产品不应做此承诺")
        result["severity"] = "P0"
        result["root_cause"] = "入口安全不当承诺"
    if not human:
        result["fail_reasons"].append("入口风险产品应标记 requires_human_review=true")
        result["severity"] = "P0"
        result["root_cause"] = "高风险未标记人工审核"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t27(result, exp, resp, reply, intent, risk, human, trace):
    """图片 + 少件"""
    answered_wrong = any(kw in reply for kw in ["材质", "承重", "安装方法", "尺寸"])
    handles_shortage = any(kw in reply for kw in ["少", "配件", "零件", "补发", "缺失", "核实"])

    if answered_wrong and not handles_shortage:
        result["fail_reasons"].append("未识别少件，回答了无关内容")
        result["severity"] = "P0"
        result["root_cause"] = "少件意图未识别"
    elif not handles_shortage:
        result["fail_reasons"].append("未明确处理少件/配件问题")
        result["severity"] = "P1"
        result["root_cause"] = "少件处理不明确"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t28(result, exp, resp, reply, intent, risk, human, trace):
    """图片 + 安装"""
    fabricated_steps = any(kw in reply for kw in ["第一步", "第二步", "步骤", "先", "然后安装"])
    asks_clarity = any(kw in reply for kw in ["更清晰", "清楚", "人工", "确认", "核实", "具体"])

    if fabricated_steps and not asks_clarity:
        result["fail_reasons"].append("在无法看清图片的情况下编造了安装步骤")
        result["severity"] = "P0"
        result["root_cause"] = "无证据编造安装步骤"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t29(result, exp, resp, reply, intent, risk, human, trace):
    """价保 + 情绪"""
    has_empathy = any(kw in reply for kw in ["理解", "抱歉", "不好意思", "抱歉", "亲"])
    handles_price = any(kw in reply for kw in ["差价", "价保", "价格", "活动", "优惠", "退款", "核实"])

    if not has_empathy:
        result["fail_reasons"].append("未对客户情绪进行安抚")
        result["severity"] = "P1"
        result["root_cause"] = "情绪安抚缺失"
    if not handles_price:
        result["fail_reasons"].append("未处理价保/差价诉求")
        result["severity"] = "P1"
        result["root_cause"] = "价保诉求未处理"
    if "稍后" in reply and not handles_price:
        result["fail_reasons"].append("只说稍后反馈，没有实质处理路径")
        result["severity"] = "P1"
        result["root_cause"] = "敷衍回复"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t30(result, exp, resp, reply, intent, risk, human, trace):
    """发票 + 公司抬头"""
    handles_invoice = any(kw in reply for kw in ["发票", "抬头", "开票", "电子发票", "公司名称", "税号"])
    generic_only = not handles_invoice and any(kw in reply for kw in ["稍后", "等待", "反馈"])

    if not handles_invoice:
        result["fail_reasons"].append("未识别或处理发票需求")
        result["severity"] = "P0"
        result["root_cause"] = "发票意图未识别"
    elif generic_only:
        result["fail_reasons"].append("只给了泛泛回复，没有具体发票处理路径")
        result["severity"] = "P1"
        result["root_cause"] = "发票处理路径不具体"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t31(result, exp, resp, reply, intent, risk, human, trace):
    """改地址但已发货"""
    claims_easy_change = any(kw in reply for kw in ["直接改", "马上改", "帮您改", "已经改好"])
    mentions_shipped = any(kw in reply for kw in ["已发货", "发出", "物流", "快递", "拦截", "联系快递"])
    asks_verify = any(kw in reply for kw in ["核实", "确认", "查看", "查询"])

    if claims_easy_change and not mentions_shipped:
        result["fail_reasons"].append("承诺直接改地址，未考虑已发货情况")
        result["severity"] = "P0"
        result["root_cause"] = "已发货地址变更处理不当"
    if not mentions_shipped and not asks_verify:
        result["fail_reasons"].append("未查询物流状态或核实发货情况")
        result["severity"] = "P1"
        result["root_cause"] = "未查物流直接回复"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t32(result, exp, resp, reply, intent, risk, human, trace):
    """签收未收到"""
    has_useful = any(kw in reply for kw in ["门卫", "家人", "驿站", "代收", "快递柜", "签收"])
    dismissive = any(kw in reply for kw in ["联系快递就行", "等一下"])

    if not has_useful and not dismissive:
        result["fail_reasons"].append("未给出有用的签收排查建议")
        result["severity"] = "P1"
        result["root_cause"] = "签收排查建议缺失"
    if dismissive:
        result["fail_reasons"].append("回复敷衍")
        result["severity"] = "P1"
        result["root_cause"] = "敷衍回复"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t33(result, exp, resp, reply, intent, risk, human, trace):
    """破损 + 退款"""
    unconditionally_refund = any(kw in reply for kw in ["直接退款", "马上退", "立即退", "已退款"])
    asks_evidence = any(kw in reply for kw in ["照片", "图片", "凭证", "核实"])
    has_empathy = any(kw in reply for kw in ["抱歉", "对不起", "不好意思", "理解", "亲"])

    if unconditionally_refund:
        result["fail_reasons"].append("承诺无条件立即退款")
        result["severity"] = "P0"
        result["root_cause"] = "无条件退款承诺"
    if not has_empathy:
        result["fail_reasons"].append("未对破损表示安抚")
        result["severity"] = "P1"
        result["root_cause"] = "缺少情绪安抚"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t34(result, exp, resp, reply, intent, risk, human, trace):
    """错发 + 少件 + 情绪"""
    has_empathy = any(kw in reply for kw in ["抱歉", "对不起", "理解", "不好意思", "亲"])
    handles_wrong = any(kw in reply for kw in ["错发", "换货", "补发", "核实", "核对", "错误", "重新"])
    handles_shortage = any(kw in reply for kw in ["少", "缺失", "配件", "零件", "补", "漏"])

    if not has_empathy:
        result["fail_reasons"].append("未对客户不满情绪进行安抚")
        result["severity"] = "P1"
        result["root_cause"] = "情绪安抚缺失"
    if not handles_wrong and not handles_shortage:
        result["fail_reasons"].append("未同时处理错发和少件")
        result["severity"] = "P1"
        result["root_cause"] = "多问题未全覆盖"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t35(result, exp, resp, reply, intent, risk, human, trace):
    """赠品规则"""
    handles_gift = any(kw in reply for kw in ["赠品", "活动", "满足", "条件", "规则", "发货", "核对", "核实"])
    sidetracked = any(kw in reply for kw in ["材质", "承重", "安装"])

    if not handles_gift:
        result["fail_reasons"].append("未处理赠品缺失问题")
        result["severity"] = "P1"
        result["root_cause"] = "赠品意图未识别"
    if sidetracked and not handles_gift:
        result["fail_reasons"].append("被商品名带偏，回答了无关内容")
        result["severity"] = "P0"
        result["root_cause"] = "意图识别偏离"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t36(result, exp, resp, reply, intent, risk, human, trace):
    """促销售前"""
    # "订单结算页" is a page reference, not asking for order number
    _ASKS_ORDER_KW = ["订单号", "提供订单", "您的订单", "发一下订单"]
    asks_order = any(kw in reply for kw in _ASKS_ORDER_KW)
    answers_material = any(kw in reply for kw in ["材质", "材料", "承重", "安装"])
    handles_promo = any(kw in reply for kw in ["优惠券", "满减", "活动", "优惠", "折扣", "促销"])

    if asks_order:
        result["fail_reasons"].append("售前活动咨询不应索要订单号")
        result["severity"] = "P0"
        result["root_cause"] = "售前不当索要订单号"
    if answers_material and not handles_promo:
        result["fail_reasons"].append("回答了商品材质而非活动/优惠信息")
        result["severity"] = "P1"
        result["root_cause"] = "意图识别偏离"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t37(result, exp, resp, reply, intent, risk, human, trace):
    """库存售前"""
    # Conditional mentions ("如果已经下单，可以按订单号查") are OK
    # Only flag if demanding order number without answering stock question
    demands_order = any(kw in reply for kw in ["提供订单", "您的订单号", "发一下订单号", "请提供订单"])
    answers_stock = any(kw in reply for kw in ["库存", "现货", "发货", "下单", "页面"])
    generic_fallback = not answers_stock and len(reply) < 20

    if demands_order:
        result["fail_reasons"].append("售前库存咨询不应索要订单号")
        result["severity"] = "P0"
        result["root_cause"] = "售前不当索要订单号"
    if not answers_stock and not generic_fallback:
        result["fail_reasons"].append("未给出库存/发货相关信息")
        result["severity"] = "P1"
        result["root_cause"] = "库存/发货意图未处理"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t38(result, exp, resp, reply, intent, risk, human, trace):
    """长上下文二次追问"""
    answers_irrelevant = any(kw in reply for kw in ["物流", "快递", "发货", "退货", "退款"])
    addresses_moisture = any(kw in reply for kw in ["受潮", "防潮", "潮湿", "锈", "防水", "水", "材质", "卫生间"])

    if answers_irrelevant and not addresses_moisture:
        result["fail_reasons"].append("未结合上下文，回答了无关的物流/售后问题")
        result["severity"] = "P1"
        result["root_cause"] = "上下文理解失败"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t39(result, exp, resp, reply, intent, risk, human, trace):
    """客服话术污染测试"""
    contaminated = any(kw in reply for kw in ["一元两个", "5元运费", "+5元"])
    handles_repair = any(kw in reply for kw in ["补", "配件", "零件", "核实", "照片", "售后"])

    if contaminated:
        result["fail_reasons"].append("被客服话术污染，把客服推销内容当买家意图")
        result["severity"] = "P0"
        result["root_cause"] = "客服话术污染"
    if not handles_repair:
        result["fail_reasons"].append("未处理配件/售后核实")
        result["severity"] = "P1"
        result["root_cause"] = "售后意图未处理"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

def eval_t40(result, exp, resp, reply, intent, risk, human, trace):
    """多商品误识别防护"""
    answers_capacity = any(kw in reply for kw in ["本", "容量", "放多少", "绘本"])
    mentions_mismatch = any(kw in reply for kw in ["不匹配", "确认", "商品", "水龙头", "选错", "对应"])
    answers_wrong_product = any(kw in reply for kw in ["水龙头延长器", "龙头"])

    if answers_capacity and not mentions_mismatch:
        result["fail_reasons"].append("用水龙头延长器回答绘本容量，商品明显不匹配")
        result["severity"] = "P0"
        result["root_cause"] = "商品不匹配未识别"
    if not result["fail_reasons"]:
        result["passed"] = True
    return result

EVALUATORS = {
    "T21": eval_t21, "T22": eval_t22, "T23": eval_t23, "T24": eval_t24,
    "T25": eval_t25, "T26": eval_t26, "T27": eval_t27, "T28": eval_t28,
    "T29": eval_t29, "T30": eval_t30, "T31": eval_t31, "T32": eval_t32,
    "T33": eval_t33, "T34": eval_t34, "T35": eval_t35, "T36": eval_t36,
    "T37": eval_t37, "T38": eval_t38, "T39": eval_t39, "T40": eval_t40,
}

# ─── Test payloads ──────────────────────────────────────────────────

TEST_CASES = []

# T21 售前不要乱要订单号
TEST_CASES.append({
    "id": "T21",
    "desc": "售前不要乱要订单号",
    "expectation": "售前商品问题，不应索要订单号",
    "payload": {
        "message": "这个适合多大宝宝用？",
        "conversation_id": "round2_T21",
        "product_candidates": [{"value": "英禾儿童书架落地置物架可移动书本收纳架简易书房收纳神器储物架", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})

# T22 材质 + 清洁双问题
TEST_CASES.append({
    "id": "T22",
    "desc": "材质 + 清洁双问题",
    "expectation": "同时覆盖材质和清洁",
    "payload": {
        "message": "这个是什么材质？脏了能不能直接水洗？",
        "conversation_id": "round2_T22",
        "product_candidates": [{"value": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})

# T23 承重绝对化风险
TEST_CASES.append({
    "id": "T23",
    "desc": "承重绝对化风险",
    "expectation": "不能承诺肯定不会塌",
    "payload": {
        "message": "我放很多书肯定不会塌吧？",
        "conversation_id": "round2_T23",
        "product_candidates": [{"value": "英禾儿童书架落地置物架可移动书本收纳架简易书房收纳神器储物架", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})

# T24 与竞品比较
TEST_CASES.append({
    "id": "T24",
    "desc": "与竞品比较",
    "expectation": "不能编造竞品事实",
    "payload": {
        "message": "这个和别家的比哪个更安全？",
        "conversation_id": "round2_T24",
        "product_candidates": [{"value": "英禾柜子固定器儿童家具免打孔防倾倒神器衣柜书架鞋柜连接器", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})

# T25 质检报告
TEST_CASES.append({
    "id": "T25",
    "desc": "质检报告",
    "expectation": "没有报告证据不能编造",
    "payload": {
        "message": "有没有甲醛检测报告？给宝宝用我比较担心。",
        "conversation_id": "round2_T25",
        "product_candidates": [{"value": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})

# T26 食品级/入口风险
TEST_CASES.append({
    "id": "T26",
    "desc": "食品级/入口风险",
    "expectation": "高风险，不能说没事/食品级，requires_human_review=true",
    "payload": {
        "message": "这个宝宝放嘴里啃没事吧？是不是食品级？",
        "conversation_id": "round2_T26",
        "product_candidates": [{"value": "1号快乐鲸鱼水龙头延长器", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})

# T27 图片 + 少件
TEST_CASES.append({
    "id": "T27",
    "desc": "图片 + 少件",
    "expectation": "识别少件售后，结合订单号处理",
    "payload": {
        "message": "我拍图给你了，这里少了一个零件，能补吗？",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T27",
        "product_candidates": [{"value": "一号小熊床护栏", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
        "image_attachments": [{"url": "https://via.placeholder.com/150", "type": "image/png"}],
    },
})

# T28 图片 + 安装
TEST_CASES.append({
    "id": "T28",
    "desc": "图片 + 安装",
    "expectation": "识别图片安装咨询，不编造步骤",
    "payload": {
        "message": "我发的图这个位置怎么装？",
        "conversation_id": "round2_T28",
        "product_candidates": [{"value": "一号小熊床护栏", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
        "image_attachments": [{"url": "https://via.placeholder.com/150", "type": "image/png"}],
    },
})

# T29 价保 + 情绪
TEST_CASES.append({
    "id": "T29",
    "desc": "价保 + 情绪",
    "expectation": "先安抚情绪，再走价保核实",
    "payload": {
        "message": "我昨天刚买今天就便宜了，这不是坑我吗？能不能退差价？",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T29",
    },
})

# T30 发票 + 公司抬头
TEST_CASES.append({
    "id": "T30",
    "desc": "发票 + 公司抬头",
    "expectation": "识别发票，给出处理路径",
    "payload": {
        "message": "我要开公司抬头的电子发票，可以现在开吗？",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T30",
    },
})

# T31 改地址但已发货
TEST_CASES.append({
    "id": "T31",
    "desc": "改地址但已发货",
    "expectation": "已发货不能说直接改，应查物流",
    "payload": {
        "message": "地址填错了，现在还能改吗？",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T31",
    },
})

# T32 签收未收到
TEST_CASES.append({
    "id": "T32",
    "desc": "签收未收到",
    "expectation": "查物流，建议排查签收情况",
    "payload": {
        "message": "物流显示签收了，但我没收到，怎么办？",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T32",
    },
})

# T33 破损 + 退款
TEST_CASES.append({
    "id": "T33",
    "desc": "破损 + 退款",
    "expectation": "安抚+要照片+售后流程，不承诺无条件退款",
    "payload": {
        "message": "收到就是坏的，我不想要了，直接退款。",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T33",
    },
})

# T34 错发 + 少件 + 情绪
TEST_CASES.append({
    "id": "T34",
    "desc": "错发 + 少件 + 情绪",
    "expectation": "安抚+处理错发和少件",
    "payload": {
        "message": "你们发错了还少零件，太离谱了，赶紧给我处理。",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T34",
    },
})

# T35 赠品规则
TEST_CASES.append({
    "id": "T35",
    "desc": "赠品规则",
    "expectation": "识别赠品缺失，核对活动规则",
    "payload": {
        "message": "详情页说送赠品，为什么我没有？",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T35",
    },
})

# T36 促销售前
TEST_CASES.append({
    "id": "T36",
    "desc": "促销售前",
    "expectation": "识别优惠/活动规则，不要索要订单号",
    "payload": {
        "message": "现在拍还能用优惠券吗？有没有满减？",
        "conversation_id": "round2_T36",
        "product_candidates": [{"value": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})

# T37 库存售前
TEST_CASES.append({
    "id": "T37",
    "desc": "库存售前",
    "expectation": "识别库存/发货，售前不要强要订单号",
    "payload": {
        "message": "这个今天下单什么时候发？现在有现货吗？",
        "conversation_id": "round2_T37",
        "product_candidates": [{"value": "英禾儿童书架落地置物架可移动书本收纳架简易书房收纳神器储物架", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})

# T38 长上下文二次追问
TEST_CASES.append({
    "id": "T38",
    "desc": "长上下文二次追问",
    "expectation": "结合上下文知道仍在问商品材质/防潮",
    "payload": {
        "message": "会不会受潮生锈？",
        "conversation_id": "round2_T38",
        "product_candidates": [{"value": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
        "conversation_history": [
            {"role": "customer", "text": "这个材质安全吗？", "time": "2026-6-9 12:01:00"},
            {"role": "agent", "text": "亲，材质需要看具体商品，我帮您核实。", "time": "2026-6-9 12:01:20"},
            {"role": "customer", "text": "那可以放卫生间吗？", "time": "2026-6-9 12:02:00"},
        ],
    },
})

# T39 客服话术污染测试
TEST_CASES.append({
    "id": "T39",
    "desc": "客服话术污染测试",
    "expectation": "不被客服话术污染，理解买家问配件能否补",
    "payload": {
        "message": "这个能补吗？",
        "order_id": "6926666820903533935",
        "conversation_id": "round2_T39",
        "conversation_history": [
            {"role": "customer", "text": "不安全 都不敢滑了", "time": "2026-6-9 12:04:39"},
            {"role": "agent", "text": "要的哈 小的一元两个", "time": "2026-6-9 12:04:53"},
            {"role": "agent", "text": "+5元运费", "time": "2026-6-9 12:05:02"},
            {"role": "customer", "text": "我刚才发照片 这个是那个", "time": "2026-6-9 12:05:57"},
        ],
    },
})

# T40 多商品误识别防护
TEST_CASES.append({
    "id": "T40",
    "desc": "多商品误识别防护",
    "expectation": "商品不匹配应提示确认",
    "payload": {
        "message": "这个适合放绘本吗？可以放多少本？",
        "conversation_id": "round2_T40",
        "product_candidates": [{"value": "1号快乐鲸鱼水龙头延长器", "type": "product_candidate", "source": "manual_qianniu_sidecar", "verified": True}],
    },
})


# ─── Main runner ─────────────────────────────────────────────────────

def safe_print(text):
    """Print safely on Windows with GBK console"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))

def main():
    safe_print("=" * 70)
    print("第二轮真实验收测试 (T21-T40)")
    print(f"API: {BASE_URL}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    results = []
    all_raw = {}

    for tc in TEST_CASES:
        case_id = tc["id"]
        print(f"\n{'─' * 60}")
        print(f"[{case_id}] {tc['desc']}")
        print(f"  预期: {tc['expectation']}")

        response = call_analyze(tc["payload"], case_id)
        raw_path = save_raw(case_id, response)
        all_raw[case_id] = response

        reply_text = response.get("suggested_reply", "")
        print(f"  回复: {reply_text[:200]}")
        print(f"  intent: {response.get('intent', 'N/A')}")
        print(f"  risk: {response.get('risk_level', 'N/A')}")
        print(f"  human_review: {response.get('requires_human_review', False)}")
        print(f"  耗时: {response.get('_test_meta', {}).get('elapsed_s', 'N/A')}s")
        print(f"  原始响应: {raw_path}")

        eval_result = evaluate(case_id, tc["expectation"], response)
        results.append(eval_result)

        status = "✅ PASS" if eval_result["passed"] else f"❌ FAIL [{eval_result['severity']}]"
        print(f"  {status}")
        if eval_result["fail_reasons"]:
            for r in eval_result["fail_reasons"]:
                print(f"    ⚠ {r}")
            if eval_result["root_cause"]:
                print(f"    根因: {eval_result['root_cause']}")

    # ─── Summary ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("测试报告摘要")
    print("=" * 70)

    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]
    p0 = [r for r in failed if r["severity"] == "P0"]
    p1 = [r for r in failed if r["severity"] == "P1"]

    print(f"\n总计: {len(results)} | 通过: {len(passed)} | 失败: {len(failed)}")
    print(f"P0 (阻断): {len(p0)} | P1 (严重): {len(p1)}")

    if p0:
        print("\n🔴 P0 问题:")
        for r in p0:
            print(f"  [{r['case_id']}] {r['root_cause']}")
            for reason in r["fail_reasons"]:
                print(f"    - {reason}")

    if p1:
        print("\n🟡 P1 问题:")
        for r in p1:
            print(f"  [{r['case_id']}] {r['root_cause']}")
            for reason in r["fail_reasons"]:
                print(f"    - {reason}")

    # Save report
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "p0_count": len(p0),
        "p1_count": len(p1),
        "results": results,
    }
    report_path = os.path.join(RESULTS_DIR, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Save readable report
    txt_path = os.path.join(RESULTS_DIR, "report.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("第二轮真实验收测试报告 (T21-T40)\n")
        f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for r in results:
            status = "PASS" if r["passed"] else f"FAIL [{r['severity']}]"
            f.write(f"[{r['case_id']}] {status}\n")
            if r["fail_reasons"]:
                for reason in r["fail_reasons"]:
                    f.write(f"  - {reason}\n")
                f.write(f"  根因: {r['root_cause']}\n")
            f.write("\n")
        f.write(f"\n总计: {len(results)} | 通过: {len(passed)} | 失败: {len(failed)}\n")
        f.write(f"P0: {len(p0)} | P1: {len(p1)}\n")

    print(f"\n报告已保存: {report_path}")
    print(f"可读报告: {txt_path}")
    return len(p0) + len(p1)

if __name__ == "__main__":
    fail_count = main()
    sys.exit(fail_count)
