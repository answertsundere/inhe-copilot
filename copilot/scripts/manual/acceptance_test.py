"""客服知识库 / RAG 基座 人工验收脚本 - 完整版"""
import json, urllib.request, urllib.error, urllib.parse, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "http://127.0.0.1:5000"


def _admin_headers():
    headers = {"Content-Type": "application/json"}
    assertion = os.environ.get("COPILOT_ADMIN_ACCESS_ASSERTION", "").strip()
    if assertion:
        headers["Cf-Access-Jwt-Assertion"] = assertion
    return headers


def api(method, path, data=None):
    url = f"{BASE}{path}"
    headers = _admin_headers()
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
print("一、后台页面验收")
print("=" * 70)

s, b = api("GET", "/knowledge-admin")
log("1.1 页面能否打开", "PASS" if s == 200 else "FAIL", f"status={s}", "200")

s, b = api("GET", "/api/knowledge/entries?page=1&per_page=10")
count = len(b.get("items", []))
log("1.2 知识列表是否能加载", "PASS" if s == 200 and count > 0 else "FAIL", f"status={s}, items={count}", "status=200, items>0")

for param in ["source_type=product_facts", "intent=product_question", "status=published", "risk_level=low"]:
    s, b = api("GET", f"/api/knowledge/entries?{param}&per_page=5")
    log(f"1.3 筛选 {param}", "PASS" if s == 200 else "FAIL", f"status={s}, items={len(b.get('items',[]))}")

s, b = api("GET", "/api/knowledge/entries?search=%E4%B9%A6%E6%9E%B6&per_page=5")
log("1.4 title/content 搜索", "PASS" if s == 200 else "FAIL", f"status={s}, items={len(b.get('items',[]))}", "status=200")

s, b = api("POST", "/api/knowledge/entries", {
    "source_type": "faq", "title": "验收测试-新增", "content": "这是验收测试内容",
    "intent": "product_question", "risk_level": "low",
    "auto_reply_allowed": True, "human_review_required": False,
})
test_id = b.get("id")
log("1.5 新增知识", "PASS" if s == 201 and test_id else "FAIL", f"status={s}, id={test_id}", "201+id")

s, b = api("PUT", f"/api/knowledge/entries/{test_id}", {"title": "验收测试-编辑后", "content": "编辑后的内容"})
log("1.6 编辑知识", "PASS" if s == 200 else "FAIL", f"status={s}", "200")

s, b = api("GET", f"/api/knowledge/entries/{test_id}")
log("1.7 保存草稿", "PASS" if s == 200 and b.get("status") == "draft" else "FAIL", f"status={s}, entry_status={b.get('status')}", "draft")

s, b = api("POST", f"/api/knowledge/entries/{test_id}/submit-review", {})
s2, b2 = api("GET", f"/api/knowledge/entries/{test_id}")
log("1.8 提交审核", "PASS" if s == 200 and b2.get("status") == "pending_review" else "FAIL", f"status={s}, entry_status={b2.get('status')}", "pending_review")

s, b = api("POST", f"/api/knowledge/entries/{test_id}/review", {"approved": True, "reviewer": "supervisor_1"})
s2, b2 = api("GET", f"/api/knowledge/entries/{test_id}")
log("1.9 supervisor 审核通过", "PASS" if s == 200 and b2.get("status") == "published" else "FAIL", f"review_status={s}, entry_status={b2.get('status')}", "published")

s, b = api("DELETE", f"/api/knowledge/entries/{test_id}")
s2, b2 = api("GET", f"/api/knowledge/entries/{test_id}")
archived_ok = s == 200 and b2.get("status") == "archived"
log("1.10a 归档", "PASS" if archived_ok else "FAIL", f"delete_status={s}, entry_status={b2.get('status')}", "archived")

if archived_ok:
    s3, b3 = api("POST", f"/api/knowledge/entries/{test_id}/rollback", {"target_version": 1, "changed_by": "supervisor_1"})
    s4, b4 = api("GET", f"/api/knowledge/entries/{test_id}")
    log("1.10b 回滚", "PASS" if s3 == 200 and b4.get("status") == "draft" else "FAIL",
        f"rollback_status={s3}, entry_status={b4.get('status')}, version={b4.get('version')}", "draft")

print("\n" + "=" * 70)
print("二、知识状态流转验收")
print("=" * 70)

s, b = api("POST", "/api/knowledge/entries", {
    "source_type": "shipping_policy", "title": "儿童书架发货时效",
    "content": "儿童书架一般按店铺页面承诺时效安排发货，发出后以实际物流为准。",
    "intent": "logistics_eta", "risk_level": "low",
    "auto_reply_allowed": True, "human_review_required": False,
})
ship_id = b.get("id")
print(f"\n创建 shipping_policy id={ship_id}")

s, b = api("POST", "/api/knowledge/retrieve", {"query": "儿童书架发货", "source_types": ["shipping_policy"], "intent": "logistics_eta", "top_k": 5})
ids = [c.get("entry_id") for c in b.get("chunks", [])]
log("2.1 draft 状态检索不到", "PASS" if ship_id not in ids else "FAIL", f"retrieved_ids={ids}", f"不包含 {ship_id}")

api("POST", f"/api/knowledge/entries/{ship_id}/submit-review", {})
s, b = api("POST", "/api/knowledge/retrieve", {"query": "儿童书架发货", "source_types": ["shipping_policy"], "intent": "logistics_eta", "top_k": 5})
ids = [c.get("entry_id") for c in b.get("chunks", [])]
log("2.2 pending_review 状态检索不到", "PASS" if ship_id not in ids else "FAIL", f"retrieved_ids={ids}", f"不包含 {ship_id}")

s, b = api("POST", f"/api/knowledge/entries/{ship_id}/review", {"approved": True, "reviewer": "supervisor_1"})
print(f"  审核结果: status={s}, body={b}")
s, b = api("POST", "/api/knowledge/retrieve", {"query": "儿童书架发货", "source_types": ["shipping_policy"], "intent": "logistics_eta", "top_k": 5})
ids = [c.get("entry_id") for c in b.get("chunks", [])]
log("2.3 published 状态可以检索到", "PASS" if ship_id in ids else "FAIL", f"retrieved_ids={ids}", f"包含 {ship_id}")

api("DELETE", f"/api/knowledge/entries/{ship_id}")
s, b = api("POST", "/api/knowledge/retrieve", {"query": "儿童书架发货", "source_types": ["shipping_policy"], "intent": "logistics_eta", "top_k": 5})
ids = [c.get("entry_id") for c in b.get("chunks", [])]
log("2.4 archived 状态检索不到", "PASS" if ship_id not in ids else "FAIL", f"retrieved_ids={ids}", f"不包含 {ship_id}")

s, b = api("POST", f"/api/knowledge/entries/{ship_id}/rollback", {"target_version": 1, "changed_by": "supervisor_1"})
s2, b2 = api("GET", f"/api/knowledge/entries/{ship_id}")
log("2.5 rollback", "PASS" if s == 200 and b2.get("status") == "draft" else "FAIL",
    f"rollback_status={s}, entry_status={b2.get('status')}, version={b2.get('version')}, title={b2.get('title')}", "draft")

print("\n" + "=" * 70)
print("三、高风险强制审核验收")
print("=" * 70)

s, b = api("POST", "/api/knowledge/entries", {
    "source_type": "high_risk_sop", "title": "投诉平台处理 SOP",
    "content": "客户提到投诉平台时，必须安抚并转人工复核。",
    "intent": "complaint", "risk_level": "high",
    "auto_reply_allowed": True, "human_review_required": False,
})
hr_id = b.get("id")
s2, b2 = api("GET", f"/api/knowledge/entries/{hr_id}")
print(f"\n创建后: auto_reply_allowed={b2.get('auto_reply_allowed')}, human_review_required={b2.get('human_review_required')}")

log("3.1 自动改为 auto_reply_allowed=false", "PASS" if b2.get("auto_reply_allowed") == False else "FAIL", f"auto_reply_allowed={b2.get('auto_reply_allowed')}", "false")
log("3.2 自动 human_review_required=true", "PASS" if b2.get("human_review_required") == True else "FAIL", f"human_review_required={b2.get('human_review_required')}", "true")

s, b = api("POST", f"/api/knowledge/entries/{hr_id}/publish", {})
s2, b2 = api("GET", f"/api/knowledge/entries/{hr_id}")
log("3.3 禁止 operator 直接发布", "PASS" if b2.get("status") == "draft" else "FAIL", f"publish_status={s}, entry_status={b2.get('status')}", "draft")

api("POST", f"/api/knowledge/entries/{hr_id}/submit-review", {})
s, b = api("POST", f"/api/knowledge/entries/{hr_id}/review", {"approved": True, "reviewer": "supervisor_1"})
s2, b2 = api("GET", f"/api/knowledge/entries/{hr_id}")
log("3.4 必须 supervisor 审核", "PASS" if s == 200 and b2.get("status") == "published" else "FAIL", f"review_status={s}, entry_status={b2.get('status')}", "published")

s, b = api("POST", "/api/knowledge/retrieve", {"query": "投诉平台", "source_types": ["high_risk_sop"], "intent": "complaint", "top_k": 5})
chunks = b.get("chunks", [])
hr_chunks = [c for c in chunks if c.get("entry_id") == hr_id]
if hr_chunks:
    meta = hr_chunks[0].get("metadata", {})
    log("3.5 发布后 need_human_review", "PASS" if meta.get("human_review_required") == True else "FAIL", f"metadata={meta}", "human_review_required=true")
else:
    log("3.5 发布后 need_human_review", "FAIL", f"未检索到 chunk, total_chunks={len(chunks)}, ids={[c.get('entry_id') for c in chunks]}", "human_review_required=true")

print("\n" + "=" * 70)
print("四、Excel 导入验收")
print("=" * 70)

# 检查 Excel 文件是否存在
excel_path = "../INHE全部商品_金牌客服问答手册.xlsx"
if not os.path.exists(excel_path):
    excel_path = "INHE全部商品_金牌客服问答手册.xlsx"
has_excel = os.path.exists(excel_path)
print(f"\nExcel 文件存在: {has_excel} ({excel_path})")

if has_excel:
    import pandas as pd
    xl = pd.ExcelFile(excel_path)
    print(f"  Sheets: {xl.sheet_names}")
    
    # 4.1 预览
    print("\n[4.1] 导入预览")
    for sheet in ["商品总览（增强版）", "物流发货常见问答（增强版）", "售后退换货常见问答（增强版）", "高风险SOP手册"]:
        if sheet in xl.sheet_names:
            df = pd.read_excel(excel_path, sheet_name=sheet, nrows=3)
            print(f"  {sheet}: {len(df)} 行示例, 列={list(df.columns)}")
        else:
            print(f"  {sheet}: 不存在")
    
    # 调用 import-preview API
    import requests
    with open(excel_path, "rb") as f:
        files = {"file": (os.path.basename(excel_path), f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        resp = requests.post(f"{BASE}/api/knowledge/import-preview", files=files)
    preview = resp.json()
    print(f"\n  import-preview status: {resp.status_code}")
    print(f"  preview items: {len(preview.get('items', []))}")
    print(f"  warnings: {len(preview.get('warnings', []))}")
    
    # 4.2 source_type 映射
    print("\n[4.2] source_type 映射检查")
    for item in preview.get("items", [])[:10]:
        print(f"  sheet={item.get('source_sheet')} -> source_type={item.get('source_type')}")
    
    # 4.3 执行导入
    print("\n[4.3] 执行导入")
    resp2 = requests.post(f"{BASE}/api/knowledge/import", json={"items": preview.get("items", [])}, headers=_admin_headers())
    import_result = resp2.json()
    print(f"  import status: {resp2.status_code}")
    print(f"  success: {len(import_result.get('success', []))}")
    print(f"  failed: {len(import_result.get('failed', []))}")
    print(f"  errors: {import_result.get('errors', [])}")
    
    # 4.4 检查导入后的条目
    if import_result.get("success"):
        first_id = import_result["success"][0].get("id")
        s, b = api("GET", f"/api/knowledge/entries/{first_id}")
        print(f"\n[4.4] 导入后第一条状态: status={b.get('status')}, source_sheet={b.get('source_sheet')}, row_number={b.get('row_number')}, import_batch_id={b.get('import_batch_id')}")
    
    # 4.5 重复检查
    print(f"\n[4.5] 重复检查: 再次导入同一 preview")
    resp3 = requests.post(f"{BASE}/api/knowledge/import", json={"items": preview.get("items", [])}, headers=_admin_headers())
    dup_result = resp3.json()
    print(f"  重复导入 success: {len(dup_result.get('success', []))}, failed: {len(dup_result.get('failed', []))}")
    if dup_result.get("failed"):
        print(f"  失败原因: {dup_result['failed'][0].get('reason')}")
    
    # 4.6 高风险检查
    print("\n[4.6] 高风险内容自动 human_review_required")
    for item in import_result.get("success", []):
        if item.get("source_type") == "high_risk_sop":
            s, b = api("GET", f"/api/knowledge/entries/{item['id']}")
            print(f"  high_risk_sop id={item['id']}: human_review_required={b.get('human_review_required')}, auto_reply_allowed={b.get('auto_reply_allowed')}")
            break
else:
    log("4.x Excel 导入", "SKIP", f"文件不存在: {excel_path}", "存在")

print("\n验收脚本第一部分完成。")
