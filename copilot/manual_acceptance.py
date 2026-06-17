"""人工复验脚本 - 5 组真实 API 验收"""
import json, sys, os, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "http://127.0.0.1:5000"

def api(method, path, data=None, role="operator"):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json", "X-User-Role": role, "X-User-Name": "tester"}
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw.decode("utf-8")) if raw else {"error": str(e)}
        except: return e.code, {"error": str(e)}
    except Exception as e:
        return -1, {"error": str(e)}

def log(item, ok, actual, expected=""):
    print(f"\n{'[PASS]' if ok else '[FAIL]'} {item}")
    print(f"  实际: {actual}")
    if expected: print(f"  预期: {expected}")
    return ok

results = []

print("=" * 70)
print("一、普通知识发布链路")
print("=" * 70)

s, b = api("POST", "/api/knowledge/entries", {
    "source_type": "shipping_policy",
    "title": "人工验收-儿童书架发货时效",
    "content": "儿童书架一般按店铺页面承诺时效安排发货，发出后以实际物流为准。",
    "intent": "logistics_eta",
    "risk_level": "low",
    "auto_reply_allowed": True,
    "human_review_required": False,
})
ship_id = b.get("id")
print(f"\n创建 id={ship_id}")

# draft
s2, b2 = api("GET", f"/api/knowledge/entries/{ship_id}")
ok1 = log("1.1 保存 draft", s2 == 200 and b2.get("status") == "draft",
          f"status={b2.get('status')}", "draft")

# submit
api("POST", f"/api/knowledge/entries/{ship_id}/submit-review", {})
s3, b3 = api("GET", f"/api/knowledge/entries/{ship_id}")
ok2 = log("1.2 提交审核", s3 == 200 and b3.get("status") == "pending_review",
          f"status={b3.get('status')}", "pending_review")

# review
s4, b4 = api("POST", f"/api/knowledge/entries/{ship_id}/review",
             {"approved": True, "reviewer": "supervisor_1"}, role="supervisor")
s5, b5 = api("GET", f"/api/knowledge/entries/{ship_id}")
ok3 = log("1.3 supervisor 审核", s5 == 200 and b5.get("status") == "published",
          f"status={b5.get('status')}, published_at={b5.get('published_at')}", "published")

# chunks
import sqlite3, os as os2
db_path = os2.path.join(os2.path.dirname(os2.path.abspath(__file__)), "data", "knowledge_base.db")
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT id, chunk_text, metadata_json FROM knowledge_chunks WHERE entry_id=?", (ship_id,))
rows = c.fetchall()
conn.close()
chunk_meta = {}
if rows:
    import json as j
    chunk_meta = j.loads(rows[0][2]) if rows[0][2] else {}
ok4 = log("1.4 chunks 生成", len(rows) > 0,
          f"chunks={len(rows)}, metadata={chunk_meta}", ">0 chunks")
ok5 = log("1.5 chunk metadata", chunk_meta.get("auto_reply_allowed") == True and chunk_meta.get("human_review_required") == False,
          f"auto_reply={chunk_meta.get('auto_reply_allowed')}, hr={chunk_meta.get('human_review_required')}",
          "auto_reply=true, hr=false")

results.append(("一、普通知识发布链路", ok1 and ok2 and ok3 and ok4 and ok5))

print("\n" + "=" * 70)
print("二、Agent 检索验收")
print("=" * 70)

from app.agent.graph import customer_service_graph

msg = "这个儿童书架多久发货？"
graph_result = customer_service_graph.invoke({
    "customer_message": msg,
    "trace_steps": [],
})

steps = [s.get("node", "") for s in graph_result.get("trace_steps", [])]
allowed = graph_result.get("allowed_source_types", [])
reply = graph_result.get("suggested_reply", "")
knowledge_evidence = graph_result.get("knowledge_evidence", [])
retrieved = graph_result.get("retrieved_chunks", [])
filtered = graph_result.get("filtered_evidence", [])

print(f"\ntrace_steps: {steps}")
print(f"allowed_source_types: {allowed}")
print(f"suggested_reply: {reply}")
print(f"retrieved_chunks count: {len(retrieved)}")
print(f"filtered_evidence count: {len(filtered)}")
print(f"knowledge_evidence count: {len(knowledge_evidence)}")

ok6 = log("2.1 走物流链", any(s in steps for s in ("match_shipping_policy", "generate_logistics_reply")),
          f"steps={steps}", "物流链")
ok7 = log("2.2 不说'已发货'", "已发货" not in reply,
          f"reply={reply[:100]}", "不含'已发货'")
ok8 = log("2.3 不承诺一定到", "一定" not in reply and "保证" not in reply and "肯定" not in reply,
          f"reply={reply[:100]}", "不含承诺词")

results.append(("二、Agent 检索验收", ok6 and ok7 and ok8))

print("\n" + "=" * 70)
print("三、高风险知识验收")
print("=" * 70)

s, b = api("POST", "/api/knowledge/entries", {
    "source_type": "high_risk_sop",
    "title": "人工验收-投诉平台处理SOP",
    "content": "客户提到投诉平台时，必须先安抚并转人工复核，不能承诺赔偿。",
    "intent": "complaint",
    "risk_level": "high",
    "auto_reply_allowed": True,
    "human_review_required": False,
})
hr_id = b.get("id")
print(f"\n创建 high_risk id={hr_id}")

s2, b2 = api("GET", f"/api/knowledge/entries/{hr_id}")
ok9 = log("3.1 自动 auto_reply=false", b2.get("auto_reply_allowed") == False,
          f"auto_reply={b2.get('auto_reply_allowed')}", "false")
ok10 = log("3.2 自动 hr=true", b2.get("human_review_required") == True,
          f"hr={b2.get('human_review_required')}", "true")

api("POST", f"/api/knowledge/entries/{hr_id}/submit-review", {})
api("POST", f"/api/knowledge/entries/{hr_id}/review",
    {"approved": True, "reviewer": "supervisor_1"}, role="supervisor")
s3, b3 = api("GET", f"/api/knowledge/entries/{hr_id}")
ok11 = log("3.3 审核后 published", b3.get("status") == "published",
           f"status={b3.get('status')}", "published")

# check chunk metadata
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT metadata_json FROM knowledge_chunks WHERE entry_id=?", (hr_id,))
hr_rows = c.fetchall()
conn.close()
hr_meta = {}
if hr_rows:
    hr_meta = json.loads(hr_rows[0][0]) if hr_rows[0][0] else {}
ok12 = log("3.4 chunk metadata hr=true", hr_meta.get("human_review_required") == True,
           f"metadata={hr_meta}", "human_review_required=true")

# Agent trace
msg2 = "再不处理我就投诉平台"
graph_result2 = customer_service_graph.invoke({
    "customer_message": msg2,
    "trace_steps": [],
})
steps2 = [s.get("node", "") for s in graph_result2.get("trace_steps", [])]
reply2 = graph_result2.get("suggested_reply", "")
risk_level = graph_result2.get("risk_level", "")
needs_human = graph_result2.get("requires_human_review", False)

print(f"\n高风险输入 trace: {steps2}")
print(f"suggested_reply: {reply2}")
print(f"risk_level: {risk_level}, requires_human_review: {needs_human}")

ok13 = log("3.5 risk_level high", risk_level in ("high", "critical"),
           f"risk_level={risk_level}", "high/critical")
ok14 = log("3.6 need_human_review", needs_human == True,
           f"requires_human_review={needs_human}", "true")
ok15 = log("3.7 不承诺赔偿", "赔偿" not in reply2,
           f"reply={reply2[:100]}", "不含'赔偿'")

results.append(("三、高风险知识验收", ok9 and ok10 and ok11 and ok12 and ok13 and ok14 and ok15))

print("\n" + "=" * 70)
print("四、归档和回滚验收")
print("=" * 70)

# archive
api("DELETE", f"/api/knowledge/entries/{ship_id}")
s, b = api("GET", f"/api/knowledge/entries/{ship_id}")
ok16 = log("4.1 archive", b.get("status") == "archived",
           f"status={b.get('status')}", "archived")

# retrieve after archive (should not find)
s, b = api("POST", "/api/knowledge/retrieve",
           {"query": "儿童书架发货", "source_types": ["shipping_policy"], "intent": "logistics_eta", "top_k": 10})
ids = [r.get("entry_id") for r in b.get("results", [])]
ok17 = log("4.2 archived 不可检索", ship_id not in ids,
           f"retrieved_ids={ids}", f"不包含 {ship_id}")

# rollback
s, b = api("POST", f"/api/knowledge/entries/{ship_id}/rollback",
           {"version": 1, "changed_by": "supervisor_1"}, role="supervisor")
s2, b2 = api("GET", f"/api/knowledge/entries/{ship_id}")
ok18 = log("4.3 rollback", s == 200 and b2.get("status") == "draft",
           f"rollback_status={s}, status={b2.get('status')}, version={b2.get('version')}", "draft")

# retrieve after rollback (should not find)
s, b = api("POST", "/api/knowledge/retrieve",
           {"query": "儿童书架发货", "source_types": ["shipping_policy"], "intent": "logistics_eta", "top_k": 10})
ids = [r.get("entry_id") for r in b.get("results", [])]
ok19 = log("4.4 rollback 后不可检索", ship_id not in ids,
           f"retrieved_ids={ids}", f"不包含 {ship_id}")

# republish
api("POST", f"/api/knowledge/entries/{ship_id}/submit-review", {})
api("POST", f"/api/knowledge/entries/{ship_id}/review",
    {"approved": True, "reviewer": "supervisor_1"}, role="supervisor")
s, b = api("GET", f"/api/knowledge/entries/{ship_id}")
ok20 = log("4.5 republish", b.get("status") == "published",
           f"status={b.get('status')}", "published")

# retrieve after republish (should find)
s, b = api("POST", "/api/knowledge/retrieve",
           {"query": "儿童书架发货", "source_types": ["shipping_policy"], "intent": "logistics_eta", "top_k": 10})
ids = [r.get("entry_id") for r in b.get("results", [])]
ok21 = log("4.6 republish 后可检索", ship_id in ids,
           f"retrieved_ids={ids}", f"包含 {ship_id}")

results.append(("四、归档和回滚验收", ok16 and ok17 and ok18 and ok19 and ok20 and ok21))

print("\n" + "=" * 70)
print("五、反例验收")
print("=" * 70)

# 5.1 draft 不应命中
s, b = api("POST", "/api/knowledge/entries", {
    "source_type": "faq",
    "title": "人工验收-草稿不应命中",
    "content": "这是一条草稿知识，Agent 不应该使用。",
    "intent": "product_question",
    "risk_level": "low",
})
draft_id = b.get("id")
print(f"\n创建 draft id={draft_id}")

s, b = api("POST", "/api/knowledge/retrieve",
           {"query": "草稿不应命中", "source_types": ["faq"], "intent": "product_question", "top_k": 10})
ids = [r.get("entry_id") for r in b.get("results", [])]
ok22 = log("5.1 draft 不可检索", draft_id not in ids,
           f"retrieved_ids={ids}", f"不包含 {draft_id}")

# 5.2 无 product_facts 不得编造材质
msg3 = "这个儿童书架是不是实木的？"
graph_result3 = customer_service_graph.invoke({
    "customer_message": msg3,
    "trace_steps": [],
})
reply3 = graph_result3.get("suggested_reply", "")
evidence3 = graph_result3.get("evidence", {})
verified = evidence3.get("verified_facts", [])

print(f"\n输入: {msg3}")
print(f"reply: {reply3}")
print(f"verified_facts: {verified}")

has_wood = "实木" in reply3 or "松木" in reply3 or "材质" in reply3
has_uncertain = "核实" in reply3 or "确认" in reply3 or "订单号" in reply3 or "截图" in reply3
ok23 = log("5.2 不编造材质", not has_wood or has_uncertain,
           f"reply={reply3[:100]}", "不编造或追问")

# 5.3 无订单号不承诺时效
msg4 = "我的订单什么时候到？"
graph_result4 = customer_service_graph.invoke({
    "customer_message": msg4,
    "trace_steps": [],
})
reply4 = graph_result4.get("suggested_reply", "")
order_id_in_state = graph_result4.get("order_id", "")

print(f"\n输入: {msg4}")
print(f"reply: {reply4}")
print(f"order_id in state: '{order_id_in_state}'")

has_eta = "48小时" in reply4 or "24小时" in reply4 or "发货" in reply4
has_ask_order = "订单号" in reply4 or "物流单号" in reply4 or "截图" in reply4
ok24 = log("5.3 无订单号不承诺时效", not has_eta or has_ask_order,
           f"reply={reply4[:100]}", "不承诺或追问订单号")

results.append(("五、反例验收", ok22 and ok23 and ok24))

print("\n" + "=" * 70)
print("验收总表")
print("=" * 70)
print(f"\n{'| 验收组 | 是否通过 |':<30}")
print("|" + "-" * 28 + "|")
for name, ok in results:
    print(f"| {name:<18} | {'通过' if ok else '未通过':<6} |")
