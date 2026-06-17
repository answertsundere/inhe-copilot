"""复测 6 个 P0 验收项 - 使用 Flask 测试客户端"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import create_app
app = create_app()
client = app.test_client()

def api(method, path, data=None, role="operator"):
    headers = {"Content-Type": "application/json", "X-User-Role": role, "X-User-Name": "tester"}
    body = json.dumps(data) if data else None
    if method == "GET":
        resp = client.get(path, headers=headers)
    elif method == "POST":
        resp = client.post(path, data=body, headers=headers)
    elif method == "PUT":
        resp = client.put(path, data=body, headers=headers)
    elif method == "DELETE":
        resp = client.delete(path, headers=headers)
    else:
        resp = client.open(path, method=method, data=body, headers=headers)
    try:
        return resp.status_code, json.loads(resp.data.decode("utf-8"))
    except:
        return resp.status_code, {}

print("=" * 60)
print("复测 6 个 P0 验收项")
print("=" * 60)

# 创建 shipping_policy
s, b = api("POST", "/api/knowledge/entries", {
    "source_type": "shipping_policy", "title": "复测-儿童书架发货时效",
    "content": "儿童书架一般按店铺页面承诺时效安排发货，发出后以实际物流为准。",
    "intent": "logistics_eta", "risk_level": "low",
    "auto_reply_allowed": True, "human_review_required": False,
})
ship_id = b.get("id")
print(f"\n创建 shipping_policy id={ship_id}")

# 1.9 supervisor 审核通过
print("\n--- [1.9] supervisor 审核通过 ---")
api("POST", f"/api/knowledge/entries/{ship_id}/submit-review", {})
s, b = api("POST", f"/api/knowledge/entries/{ship_id}/review", {"approved": True, "reviewer": "supervisor_1"}, role="supervisor")
s2, b2 = api("GET", f"/api/knowledge/entries/{ship_id}")
print(f"review_status={s}, entry_status={b2.get('status')}")
print(f"结果: {'通过' if s == 200 and b2.get('status') == 'published' else '失败'}")

# 2.3 published 可以检索到
print("\n--- [2.3] published 可以检索到 ---")
s, b = api("POST", "/api/knowledge/retrieve", {"query": "儿童书架发货", "source_types": ["shipping_policy"], "intent": "logistics_eta", "top_k": 5})
ids = [c.get("entry_id") for c in b.get("results", [])]
print(f"retrieved_ids={ids}")
print(f"结果: {'通过' if ship_id in ids else '失败'}")

# 2.5 rollback / 1.10b
print("\n--- [2.5/1.10b] rollback ---")
api("DELETE", f"/api/knowledge/entries/{ship_id}")
s, b = api("POST", f"/api/knowledge/entries/{ship_id}/rollback", {"version": 1, "changed_by": "supervisor_1"}, role="supervisor")
s2, b2 = api("GET", f"/api/knowledge/entries/{ship_id}")
print(f"rollback_status={s}, entry_status={b2.get('status')}, version={b2.get('version')}, title={b2.get('title')}")
print(f"结果: {'通过' if s == 200 and b2.get('status') == 'draft' else '失败'}")

# 3.4 高风险 supervisor 审核
print("\n--- [3.4] 高风险 supervisor 审核 ---")
s, b = api("POST", "/api/knowledge/entries", {
    "source_type": "high_risk_sop", "title": "复测-投诉平台处理 SOP",
    "content": "客户提到投诉平台时，必须安抚并转人工复核。",
    "intent": "complaint", "risk_level": "high",
    "auto_reply_allowed": True, "human_review_required": False,
})
hr_id = b.get("id")
api("POST", f"/api/knowledge/entries/{hr_id}/submit-review", {})
s, b = api("POST", f"/api/knowledge/entries/{hr_id}/review", {"approved": True, "reviewer": "supervisor_1"}, role="supervisor")
s2, b2 = api("GET", f"/api/knowledge/entries/{hr_id}")
print(f"review_status={s}, entry_status={b2.get('status')}, auto_reply={b2.get('auto_reply_allowed')}, hr={b2.get('human_review_required')}")
print(f"结果: {'通过' if s == 200 and b2.get('status') == 'published' else '失败'}")

# 3.5 发布后 need_human_review
print("\n--- [3.5] 发布后 need_human_review ---")
s, b = api("POST", "/api/knowledge/retrieve", {"query": "投诉平台", "source_types": ["high_risk_sop"], "intent": "complaint", "top_k": 20})
results = b.get("results", [])
hr_chunks = [c for c in results if c.get("entry_id") == hr_id]
if hr_chunks:
    meta = hr_chunks[0].get("metadata", {})
    print(f"metadata={meta}")
    print(f"结果: {'通过' if meta.get('human_review_required') == True else '失败'}")
else:
    print(f"未检索到 chunk, total_results={len(results)}, ids={[c.get('entry_id') for c in results]}")
    print("结果: 失败")

print("\n复测完成")
