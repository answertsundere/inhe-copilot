"""Third-round real API acceptance against /ask/api/analyze."""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests


BASE_URL = "http://127.0.0.1:5011/ask/api/analyze"
OUT_DIR = Path("round3_results")
REAL_ORDER_ID = "6926666820903533935"


def _product(name: str) -> list[dict]:
    return [{"value": name, "type": "product_candidate", "source": "round3_acceptance", "verified": True}]


CASES = [
    ("R01", "这个材质安不安全啊，宝宝用", {"product_candidates": _product("一号小熊床护栏")}),
    ("R02", "会不会潮啊，放卫生间行不", {"product_candidates": _product("英禾儿童书架落地置物架")}),
    ("R03", "能不能补一个，就那个小零件", {"order_id": REAL_ORDER_ID}),
    ("R04", "这个是不是会夹手", {"product_candidates": _product("一号小熊床护栏")}),
    ("R05", "咬了会不会有事", {"product_candidates": _product("1号快乐鲸鱼水龙头延长器")}),
    ("R06", "那这个呢？", {
        "product_candidates": _product("一号小熊床护栏"),
        "conversation_history": [{"role": "customer", "text": "这个适合一岁宝宝吗？"}],
    }),
    ("R07", "这个能补吗？", {
        "order_id": REAL_ORDER_ID,
        "conversation_history": [{"role": "customer", "text": "收到后发现少了一个连接件"}],
    }),
    ("R08", "还能发不？", {
        "product_candidates": _product("一号小熊床护栏"),
        "conversation_history": [{"role": "customer", "text": "这款现在有货吗？"}],
    }),
    ("R09", "可以退吗？", {
        "order_id": REAL_ORDER_ID,
        "conversation_history": [{"role": "customer", "text": "收到后尺寸不合适"}],
    }),
    ("R10", "有味儿咋办？", {
        "product_candidates": _product("一号小熊床护栏"),
        "conversation_history": [{"role": "customer", "text": "刚拆开包装"}],
    }),
    ("R11", "这个安全吗，今天能发吗？", {"product_candidates": _product("一号小熊床护栏")}),
    ("R12", "少了配件，还能安装吗？", {"order_id": REAL_ORDER_ID}),
    ("R13", "发错了，我想退，怎么弄？", {"order_id": REAL_ORDER_ID}),
    ("R14", "材质安全吗，有没有检测？", {"product_candidates": _product("一号小熊床护栏")}),
    ("R15", "能不能改地址，不行就拦截", {"order_id": REAL_ORDER_ID}),
    ("R16", "这个适合一岁宝宝吗？", {"product_candidates": _product("一号小熊床护栏")}),
    ("R17", "这个可以放绘本吗？", {"product_candidates": _product("刺猬桌面书架")}),
    ("R18", "有安装视频吗？", {"product_candidates": _product("一号小熊床护栏")}),
    ("R19", "物流到哪了？", {"order_id": REAL_ORDER_ID}),
    ("R20", "已签收没收到", {"order_id": REAL_ORDER_ID}),
]


def _evaluate(case_id: str, data: dict) -> tuple[bool, list[str]]:
    reply = str(data.get("suggested_reply") or "")
    intent = str(data.get("intent") or "")
    tools = set(data.get("used_fact_tools") or [])
    failures = []
    if not reply:
        failures.append("回复为空")
    if data.get("error"):
        failures.append(f"API error: {data['error']}")
    if case_id in {"R03", "R07", "R09", "R12", "R13", "R15", "R19", "R20"}:
        if case_id in {"R19", "R20"} and not any(tool.startswith("jst_lookup_") for tool in tools):
            failures.append("真实订单物流场景未调用 JST 工具")
    if case_id in {"R16", "R17", "R18"}:
        if "订单号" in reply and not any(word in reply for word in ("无需", "不需要")):
            failures.append("售前问题无故索要订单号")
    if case_id in {"R01", "R02", "R04", "R05", "R14"}:
        unsafe_claims = ("绝对安全", "保证安全", "肯定不会", "咬了没事", "一定不会夹手")
        if any(term in reply for term in unsafe_claims):
            failures.append("安全事实无证据承诺")
    if case_id in {"R03", "R07", "R12", "R13"} and intent not in {"aftersales", "complaint"}:
        failures.append(f"售后意图错误: {intent}")
    if case_id == "R08" and intent != "stock_query":
        failures.append(f"未继承库存/发货上下文: {intent}")
    if case_id == "R11":
        if not any(term in reply for term in ("发货", "仓库", "库存", "下单页")):
            failures.append("多问题漏答今天能否发货")
        if not any(term in reply for term in ("安全", "材质", "检测")):
            failures.append("多问题漏答商品安全")
    if case_id == "R12" and not (
        any(term in reply for term in ("少件", "缺配件", "缺少配件"))
        and any(term in reply for term in ("安装", "教程", "装"))
    ):
        failures.append("多问题未同时处理少件和安装")
    if case_id == "R13" and any(term in reply for term in ("还少配件", "少件/缺配件")):
        failures.append("发错场景编造少配件")
    if case_id == "R13" and not any(term in reply for term in ("退货", "退换", "申请售后", "退回")):
        failures.append("发错+退货场景漏答退货处理")
    if case_id == "R17" and any(term in reply for term in ("商品资料库", "published", "状态:")):
        failures.append("回复泄漏内部知识库术语")
    if case_id == "R15" and intent not in {"logistics_eta", "aftersales"}:
        failures.append(f"改地址/拦截意图错误: {intent}")
    if case_id == "R20":
        if data.get("risk_level") not in {"medium", "high", "critical"}:
            failures.append("签收未收到风险低于 medium")
        if not data.get("requires_human_review"):
            failures.append("签收未收到未要求人工复核")
    return not failures, failures


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    results = []
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for case_id, message, extra in CASES:
        payload = {
            "message": message,
            "conversation_id": f"round3_{case_id}_{stamp}",
            **extra,
        }
        started = time.perf_counter()
        try:
            response = requests.post(BASE_URL, json=payload, timeout=45)
            data = response.json()
            http_status = response.status_code
        except Exception as exc:
            data = {"error": str(exc)}
            http_status = 0
        elapsed = round(time.perf_counter() - started, 3)
        passed, failures = _evaluate(case_id, data)
        row = {
            "case_id": case_id,
            "user_input": message,
            "intent": data.get("intent", ""),
            "risk": data.get("risk_level", ""),
            "requires_human_review": bool(data.get("requires_human_review")),
            "used_tools": data.get("used_fact_tools", []),
            "used_knowledge_titles": data.get("used_knowledge_titles", []),
            "suggested_reply": data.get("suggested_reply", ""),
            "elapsed_s": elapsed,
            "http_status": http_status,
            "passed": passed,
            "failure_reasons": failures,
        }
        results.append(row)
        (OUT_DIR / f"{case_id}_raw_{stamp}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"{case_id}: {'PASS' if passed else 'FAIL'} {elapsed}s {row['intent']}")

    passed_count = sum(1 for row in results if row["passed"])
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "endpoint": BASE_URL,
        "total": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "pass_rate": round(passed_count / len(results), 4),
        "results": results,
    }
    json_path = OUT_DIR / f"round3_report_{stamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 第三轮真实后端验收",
        "",
        f"- 时间: {report['timestamp']}",
        f"- 接口: `{BASE_URL}`",
        f"- 通过: {passed_count}/{len(results)} ({report['pass_rate']:.0%})",
        "",
        "| 用例 | 输入 | intent | risk | 人工复核 | 工具 | 知识命中 | 耗时 | 结果 |",
        "|---|---|---|---|---:|---|---:|---:|---|",
    ]
    for row in results:
        tools = ", ".join(row["used_tools"]) or "-"
        reply = str(row["suggested_reply"]).replace("\n", " ")
        reason = "通过" if row["passed"] else "；".join(row["failure_reasons"])
        lines.append(
            f"| {row['case_id']} | {row['user_input']} | {row['intent']} | {row['risk']} | "
            f"{row['requires_human_review']} | {tools} | {len(row['used_knowledge_titles'])} | "
            f"{row['elapsed_s']}s | {reason}<br>{reply[:160]} |"
        )
    md_path = OUT_DIR / f"round3_report_{stamp}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"REPORT_JSON={json_path}")
    print(f"REPORT_MD={md_path}")
    return len(results) - passed_count


if __name__ == "__main__":
    raise SystemExit(main())
