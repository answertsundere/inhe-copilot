"""
20 条真实验收用例 API 测试脚本

直接调用本地 /api/analyze（与 real-test 页面共享同一后端服务），
模拟侧边栏商品、订单号、上下文、图片等输入，输出原始 AI 回复供人工评估。

运行：
    cd copilot
    python scripts/manual/acceptance_20_real_test.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("COPILOT_TEST_URL", "http://127.0.0.1:5011")
API_ENDPOINT = f"{BASE_URL}/api/analyze"
OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
RAW_JSON = OUTPUT_DIR / f"acceptance_20_raw_{RUN_TS}.json"
REPORT_MD = OUTPUT_DIR / f"acceptance_20_report_{RUN_TS}.md"

# ---------------------------------------------------------------------------
# 工具：生成一个最小的 1x1 PNG 作为图片附件占位
# ---------------------------------------------------------------------------
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _tiny_image_attachment() -> dict[str, Any]:
    return {
        "mime_type": "image/png",
        "base64": _TINY_PNG_B64,
        "filename": "test_image.png",
        "description": "客户发来的商品照片（测试占位图）",
    }


# ---------------------------------------------------------------------------
# 用例定义
# ---------------------------------------------------------------------------
TEST_CASES: list[dict[str, Any]] = [
    {
        "id": "T01",
        "scene": "售前材质安全",
        "message": "这个材质安全吗？会不会容易受潮？",
        "product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "focus": "是否先识别商品，再查材质，不乱要订单号",
    },
    {
        "id": "T02",
        "scene": "宝妈安全焦虑",
        "message": "家里有两岁宝宝，这个会不会夹手或者有安全隐患？",
        "product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "focus": "是否温暖回答，同时不绝对承诺",
    },
    {
        "id": "T03",
        "scene": "绝对保证风险",
        "message": "你直接保证我家孩子用了，一定不会出事，我就拍。",
        "product_name": "英禾儿童书架落地置物架可移动书本收纳架简易书房收纳神器储物架",
        "focus": "是否拒绝绝对保证，但给安心建议",
    },
    {
        "id": "T04",
        "scene": "承重/容量",
        "message": "这个可以放多少本绘本？会不会压弯？",
        "product_name": "英禾儿童书架落地置物架可移动书本收纳架简易书房收纳神器储物架",
        "focus": "是否查对应商品承重/容量，不串到别的商品",
    },
    {
        "id": "T05",
        "scene": "基础款/升级款",
        "message": "基础款和升级款差什么？",
        "product_name": "英禾儿童书架落地置物架可移动书本收纳架简易书房收纳神器储物架",
        "focus": "是否能回答款式差异，不能答错就提示需核实",
    },
    {
        "id": "T06",
        "scene": "安装方式",
        "message": "这个安装麻烦吗？需要打孔吗？租房能不能用？",
        "product_name": "英禾柜子固定器儿童家具免打孔防倾倒神器衣柜书架鞋柜连接器",
        "focus": "是否走安装/固定方式，不要回答材质",
    },
    {
        "id": "T07",
        "scene": "安装视频",
        "message": "我需要安装视频",
        "product_name": "英禾柜子固定器儿童家具免打孔防倾倒神器衣柜书架鞋柜连接器",
        "focus": "是否识别为安装视频，不要答承重/容量",
    },
    {
        "id": "T08",
        "scene": "清洁方式",
        "message": "这个脏了怎么清洁？可以水洗吗？",
        "product_name": "一号小熊床护栏",
        "focus": "是否走清洁知识，不要回答材质安全",
    },
    {
        "id": "T09",
        "scene": "异味",
        "message": "它有没有味道？我们孩子闻着不舒服。",
        "product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "focus": "是否识别异味/儿童风险，语气像客服",
    },
    {
        "id": "T10",
        "scene": "放嘴里咬",
        "message": "宝宝喜欢啃东西，这个咬了会不会有问题？",
        "product_name": "1号快乐鲸鱼水龙头延长器",
        "focus": "高风险是否人工确认，不乱保证",
    },
    {
        "id": "T11",
        "scene": "售前发货",
        "message": "今天拍还有货吗？能不能马上发？",
        "product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "focus": "售前是否不要强要订单号；是否回答库存/发货边界",
    },
    {
        "id": "T12",
        "scene": "当前优惠",
        "message": "现在拍这个有什么优惠吗？",
        "product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "focus": "是否走活动/优惠规则，不要答商品材质",
    },
    {
        "id": "T13",
        "scene": "发票",
        "message": "这个订单可以开电子发票吗？",
        "platform_order_id": "6926666820903533935",
        "focus": "是否走发票政策，不要泛泛敷衍",
    },
    {
        "id": "T14",
        "scene": "价保",
        "message": "我刚买就降价了，可以申请价保吗？",
        "platform_order_id": "6926666820903533935",
        "focus": "是否给价保处理路径，不只是“稍后核实”",
    },
    {
        "id": "T15",
        "scene": "改地址",
        "message": "还没发的话可以帮我改地址吗？",
        "platform_order_id": "6926666820903533935",
        "focus": "是否先查订单状态，未发才可改，不要说已发还让仓库拦截",
    },
    {
        "id": "T16",
        "scene": "拦截",
        "message": "可以帮我拦截吗？我不想要了。",
        "platform_order_id": "6926666820903533935",
        "focus": "是否区分未发/已发/物流中，并给正确下一步",
    },
    {
        "id": "T17",
        "scene": "赠品缺失",
        "message": "页面说有赠品，我收到怎么没有？",
        "platform_order_id": "6926666820903533935",
        "focus": "是否识别赠品缺失，不要被侧边栏商品带偏",
    },
    {
        "id": "T18",
        "scene": "少件/配件",
        "message": "我的滑滑梯零件都掉了，有没有补？",
        "product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "focus": "是否要求订单/图片核对少件，不要像机器人",
    },
    {
        "id": "T19",
        "scene": "图片 + 文字",
        "message": "我收到的不是我拍的这个，而且还少了配件，这个东西怎么安装？",
        "product_name": "一号小熊床护栏",
        "image_attachments": [_tiny_image_attachment()],
        "focus": "粘贴图片后测：是否能同时处理错发/少件/安装多个问题",
    },
    {
        "id": "T20",
        "scene": "长聊天上下文",
        "message": "这个是哪个？还能补吗？",
        "focus": "是否只识别买家最后一句，不把客服话当客户问题",
        "conversation_history": [
            {"role": "customer", "text": "在吗？"},
            {"role": "agent", "text": "亲，在的，有什么可以帮您？"},
            {"role": "customer", "text": "我前几天买的那个床护栏，有个零件断了"},
            {"role": "agent", "text": "麻烦您拍一下断掉的零件和订单号，我帮您核实补发哦"},
            {"role": "customer", "text": "订单号找不到了，就是那个小熊护栏"},
            {"role": "agent", "text": "好的，您提供一下收货手机号或者收件人姓名，我帮您查一下"},
            {"role": "customer", "text": "手机号是我老公买的，我也不记得了"},
            {"role": "agent", "text": "那您看看能不能找到订单截图，或者让您老公查一下手机号呢？"},
            {"role": "customer", "text": "这个是哪个？还能补吗？"},
        ],
    },
]


def _build_payload(case: dict[str, Any]) -> dict[str, Any]:
    """把用例转换成 /api/analyze 接受的 payload。"""
    payload: dict[str, Any] = {
        "message": case["message"],
        "conversation_id": f"acceptance_{case['id']}_{RUN_TS}",
        "source": "acceptance_test",
    }

    if case.get("product_name"):
        payload["product_name"] = case["product_name"]
        # 同时给 product_candidates，更接近真实侧边栏识别
        payload["product_candidates"] = [
            {"value": case["product_name"], "type": "product_candidate", "confidence": 0.95}
        ]

    if case.get("platform_order_id"):
        payload["platform_order_id"] = case["platform_order_id"]

    if case.get("conversation_history"):
        payload["conversation_history"] = case["conversation_history"]

    if case.get("image_attachments"):
        payload["image_attachments"] = case["image_attachments"]

    return payload


def _call_analyze(payload: dict[str, Any], endpoint: str | None = None, timeout: int = 120) -> dict[str, Any]:
    """调用分析接口，返回原始响应。"""
    target = endpoint or API_ENDPOINT
    try:
        resp = requests.post(target, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e), "raw_status": getattr(e.response, "status_code", None) if hasattr(e, "response") else None}


def run_all(base_url: str | None = None, per_call_timeout: int = 120) -> list[dict[str, Any]]:
    """执行全部用例，返回带耗时的结构化结果（供 run_acceptance_tests / run_gray_release_check 复用）。

    每条结果含：id/scene/message/product_name/focus/payload/display/raw_response/elapsed_ms/ok。
    """
    endpoint = f"{base_url.rstrip('/')}/api/analyze" if base_url else API_ENDPOINT
    results: list[dict[str, Any]] = []
    for case in TEST_CASES:
        payload = _build_payload(case)
        t0 = time.perf_counter()
        response = _call_analyze(payload, endpoint=endpoint, timeout=per_call_timeout)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        ok = "error" not in response
        print(f"[{case['id']}] {case['scene']} -> {'OK' if ok else 'ERROR: ' + str(response.get('error'))}")
        results.append({
            "id": case["id"],
            "scene": case["scene"],
            "message": case["message"],
            "product_name": case.get("product_name", ""),
            "focus": case["focus"],
            "payload": payload,
            "display": _extract_display_fields(response),
            "raw_response": response,
            "elapsed_ms": elapsed_ms,
            "ok": ok,
        })
        time.sleep(0.3)  # 简单错峰，避免打爆本地服务
    return results


def _extract_display_fields(response: dict[str, Any]) -> dict[str, Any]:
    """从原始响应中提取评估需要的字段。"""
    return {
        "suggested_reply": response.get("suggested_reply", ""),
        "intent": response.get("intent", ""),
        "risk_level": response.get("risk_level", ""),
        "requires_human_review": response.get("requires_human_review", False),
        "need_human_review": response.get("need_human_review", False),
        "answer_mode": response.get("answer_mode", ""),
        "action_proposal": response.get("action_proposal", {}),
        "used_knowledge_titles": response.get("used_knowledge_titles", []),
        "used_fact_tools": response.get("used_fact_tools", ""),
        "customer_emotion": response.get("customer_emotion", ""),
        "evidence_debug": response.get("evidence_debug", {}),
    }


def main() -> int:
    print(f"测试目标: {API_ENDPOINT}")
    print(f"用例数: {len(TEST_CASES)}")
    print("-" * 60)

    results = run_all()

    # 保存原始 JSON
    with RAW_JSON.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n原始结果: {RAW_JSON}")

    # 生成 Markdown 评估模板
    lines: list[str] = []
    lines.append(f"# 20 条验收用例测试报告 ({RUN_TS})")
    lines.append("")
    lines.append(f"- 测试接口: `{API_ENDPOINT}`")
    lines.append(f"- 用例数: {len(TEST_CASES)}")
    lines.append("- 本报告为原始 AI 输出，**人工评估列留空**，需人工填写“是否通过 / 问题类型 / AI 回复哪里不对 / 客服应该怎么回”")
    lines.append("")

    for r in results:
        d = r["display"]
        lines.append(f"## {r['id']} - {r['scene']}")
        lines.append("")
        lines.append(f"**买家问题：** {r['message']}")
        lines.append("")
        if r["payload"].get("product_name"):
            lines.append(f"**侧边栏商品：** {r['payload']['product_name']}")
        if r["payload"].get("platform_order_id"):
            lines.append(f"**订单号：** {r['payload']['platform_order_id']}")
        if r["payload"].get("image_attachments"):
            lines.append(f"**图片附件：** 有（测试占位图）")
        if r["payload"].get("conversation_history"):
            lines.append(f"**上下文轮数：** {len(r['payload']['conversation_history'])}")
        lines.append("")
        lines.append(f"**重点看什么：** {r['focus']}")
        lines.append("")
        lines.append("**AI 识别：**")
        lines.append(f"- intent: `{d.get('intent')}`")
        lines.append(f"- risk_level: `{d.get('risk_level')}`")
        lines.append(f"- requires_human_review: `{d.get('requires_human_review')}`")
        lines.append(f"- answer_mode: `{d.get('answer_mode')}`")
        lines.append(f"- action_proposal: `{json.dumps(d.get('action_proposal'), ensure_ascii=False)}`")
        lines.append(f"- used_knowledge_titles: `{d.get('used_knowledge_titles')}`")
        lines.append(f"- used_fact_tools: `{d.get('used_fact_tools')}`")
        lines.append("")
        lines.append("**AI 建议回复：**")
        lines.append("```text")
        lines.append(d.get("suggested_reply", "（空）"))
        lines.append("```")
        lines.append("")
        lines.append("**人工评估：**")
        lines.append("- 是否通过：")
        lines.append("- 问题类型：")
        lines.append("- AI 回复哪里不对：")
        lines.append("- 客服应该怎么回：")
        lines.append("")
        lines.append("---")
        lines.append("")

    with REPORT_MD.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"评估模板: {REPORT_MD}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
