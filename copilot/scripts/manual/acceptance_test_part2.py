"""验收脚本第二部分: RAG intent 检索 + factual_guard"""
import json, urllib.request, urllib.error, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "http://127.0.0.1:5000"

def api(method, path, data=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    assertion = os.environ.get("COPILOT_ADMIN_ACCESS_ASSERTION", "").strip()
    if assertion:
        headers["Cf-Access-Jwt-Assertion"] = assertion
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8")) if raw else {"error": str(e)}
        except:
            return e.code, {"error": str(e), "raw": raw.decode("utf-8", errors="replace") if raw else ""}
    except Exception as e:
        return -1, {"error": str(e)}

results = []

def log(item, status, actual, expected=""):
    results.append({"item": item, "status": status, "actual": actual, "expected": expected})
    print(f"\n[{status}] {item}")
    print(f"  实际: {actual}")
    if expected:
        print(f"  预期: {expected}")

print("=" * 70)
print("五、RAG intent 检索验收")
print("=" * 70)

# 先确保有 published 的知识用于测试
# 检查现有 published 知识
s, b = api("GET", "/api/knowledge/entries?status=published&per_page=5")
print(f"\n现有 published 知识: {len(b.get('items', []))} 条")

# 如果没有 shipping_policy 等类型的知识，创建一些测试数据
needed_types = {"shipping_policy": False, "product_facts": False, "installation_guide": False, "aftersales_policy": False, "high_risk_sop": False}
for item in b.get("items", []):
    st = item.get("source_type")
    if st in needed_types:
        needed_types[st] = True

print(f"已有 source_type: {[k for k,v in needed_types.items() if v]}")

# 手动创建测试知识并直接 publish（通过 publish API 或 seed）
for st, title, content, intent in [
    ("shipping_policy", "书架发货时效", "儿童书架一般在下单后48小时内发货，偏远地区可能延长。", "logistics_eta"),
    ("product_facts", "书架材质说明", "儿童书架采用进口实木松木，表面涂环保水性漆。", "product_question"),
    ("installation_guide", "书架安装步骤", "第一步：打开包装检查配件。第二步：按照说明书组装。", "installation"),
    ("aftersales_policy", "书架退换货政策", "自签收7天内，未安装未损坏可退。超过7天需质量问题证明。", "aftersales"),
    ("high_risk_sop", "投诉处理SOP", "客户威胁投诉时，第一时间安抚情绪，记录诉求，转交主管处理。", "complaint"),
]:
    if not needed_types.get(st, False):
        s, b = api("POST", "/api/knowledge/entries", {
            "source_type": st, "title": title, "content": content, "intent": intent,
            "risk_level": "high" if st == "high_risk_sop" else "low",
            "auto_reply_allowed": True, "human_review_required": False,
        })
        eid = b.get("id")
        api("POST", f"/api/knowledge/entries/{eid}/submit-review", {})
        s2, b2 = api("POST", f"/api/knowledge/entries/{eid}/review", {"approved": True, "reviewer": "supervisor_1"})
        # 注意：review_approve bug 导致 status 仍是 pending_review，需要额外 publish
        s3, b3 = api("POST", f"/api/knowledge/entries/{eid}/publish", {})
        print(f"  创建 {st} id={eid}, review={s2}, publish={s3}, status={b3.get('status')}")

# 现在用 Graph 测试 RAG intent 检索
print("\n--- 使用 customer_service_graph 测试 ---")
from app.agent.graph import customer_service_graph

test_cases = [
    ("这个儿童书架多久发货？", "logistics_eta", ["shipping_policy", "product_facts", "response_templates"]),
    ("这个儿童书架是什么材质？", "product_question", ["product_facts", "product_mapping", "faq"]),
    ("这个书架怎么安装？", "installation", ["installation_guide", "product_facts", "faq"]),
    ("收到后不想要了可以退吗？", "aftersales", ["aftersales_policy", "forbidden_rules", "response_templates"]),
    ("你们再不处理我就投诉平台。", "complaint", ["high_risk_sop", "forbidden_rules", "response_templates"]),
]

for msg, expected_intent, expected_sources in test_cases:
    print(f"\n--- 测试: {msg} ---")
    try:
        result = customer_service_graph.invoke({
            "customer_message": msg,
            "trace_steps": [],
        })
        steps = [s.get("node", "") for s in result.get("trace_steps", [])]
        evidence = result.get("evidence", {})
        knowledge_evidence = result.get("knowledge_evidence", [])
        allowed = result.get("allowed_source_types", [])
        reply = result.get("suggested_reply", "")
        
        print(f"  trace steps: {steps}")
        print(f"  allowed_source_types: {allowed}")
        print(f"  knowledge_evidence count: {len(knowledge_evidence)}")
        print(f"  suggested_reply: {reply[:100]}...")
        
        # 检查是否走了 RAG 链
        rag_ok = any(s in steps for s in ("rag_retrieve", "evidence_filter", "evidence_builder"))
        # 检查 allowed_source_types
        source_ok = any(s in allowed for s in expected_sources) if allowed else False
        
        log(f"5 RAG-{msg[:20]}", "PASS" if rag_ok else "FAIL",
            f"rag={rag_ok}, allowed={allowed}, reply={reply[:50]}",
            f"intent={expected_intent}, sources={expected_sources}")
    except Exception as e:
        log(f"5 RAG-{msg[:20]}", "FAIL", f"Exception: {e}", f"intent={expected_intent}")

print("\n" + "=" * 70)
print("六、factual_guard 反例验收")
print("=" * 70)

from app.agent.nodes.factual_guard import factual_guard

# 6.1 没有 product_facts 时问材质
guard_cases = [
    {
        "name": "6.1 无 product_facts 编造材质",
        "state": {
            "suggested_reply": "这款书架采用进口实木松木制作。",
            "intent": "product_question",
            "evidence": {"verified_facts": [], "estimated_facts": [], "unknowns": [], "conflicts": []},
            "guard_warnings": [],
        },
        "expected_warning": True,
    },
    {
        "name": "6.2 无订单号说具体发货时间",
        "state": {
            "suggested_reply": "您的订单明天一定能到。",
            "intent": "logistics_eta",
            "evidence": {"verified_facts": [], "estimated_facts": [], "unknowns": [], "conflicts": []},
            "guard_warnings": [],
            "order_id": "",
        },
        "expected_warning": True,
    },
    {
        "name": "6.3 出现承诺性词语",
        "state": {
            "suggested_reply": "明天一定能到，我保证。",
            "intent": "logistics_eta",
            "evidence": {"verified_facts": [], "estimated_facts": [], "unknowns": [], "conflicts": []},
            "guard_warnings": [],
        },
        "expected_warning": True,
    },
]

for case in guard_cases:
    result = factual_guard(case["state"])
    warnings = result.get("guard_warnings", [])
    has_warning = len(warnings) > 0
    log(case["name"], "PASS" if has_warning == case["expected_warning"] else "FAIL",
        f"warnings={warnings}", f"expected_warning={case['expected_warning']}")

print("\n验收完成！")
