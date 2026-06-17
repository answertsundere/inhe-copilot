"""
从钉钉多维表拉取 SKU数据库 和 商品知识库 全量数据
凭证从环境变量读取，参考 .env.example
"""

import json
import os
import sys
import time
import requests

# 凭证必须通过环境变量设置
CLIENT_ID = os.environ.get("COPILOT_DT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("COPILOT_DT_CLIENT_SECRET", "")
OPERATOR_ID = os.environ.get("COPILOT_DT_OPERATOR_ID", "")
BASE_ID = os.environ.get("COPILOT_DT_BASE_ID", "")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_access_token():
    url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
    payload = {"appKey": CLIENT_ID, "appSecret": CLIENT_SECRET}
    resp = requests.post(url, json=payload, timeout=30)
    data = resp.json()
    if "accessToken" not in data:
        raise RuntimeError(f"获取 accessToken 失败: {json.dumps(data, ensure_ascii=False)}")
    return data["accessToken"]


def list_all_records(access_token, sheet_id):
    url = f"https://api.dingtalk.com/v1.0/notable/bases/{BASE_ID}/sheets/{sheet_id}/records/list"
    headers = {
        "x-acs-dingtalk-access-token": access_token,
        "Content-Type": "application/json",
    }
    params = {"operatorId": OPERATOR_ID}

    all_records = []
    next_token = None
    page_no = 1

    while True:
        body = {"maxResults": 100}
        if next_token:
            body["nextToken"] = next_token

        resp = requests.post(url, headers=headers, params=params, json=body, timeout=60)

        # 重试 503
        retries = 0
        while resp.status_code == 503 and retries < 3:
            retries += 1
            sys.stdout.buffer.write(
                f"  [RETRY {retries}] 503, waiting 3s...\n".encode("utf-8"))
            sys.stdout.flush()
            time.sleep(3)
            resp = requests.post(url, headers=headers, params=params, json=body, timeout=60)

        data = resp.json()

        if resp.status_code != 200:
            sys.stdout.buffer.write(
                f"  [ERROR] page={page_no}, status={resp.status_code}, "
                f"msg={data.get('message', '')}\n".encode("utf-8")
            )
            break

        records = data.get("records", [])
        all_records.extend(records)

        next_token = data.get("nextToken")
        has_more = data.get("hasMore", False)

        sys.stdout.buffer.write(
            f"  Page {page_no}: +{len(records)} records, total={len(all_records)}, hasMore={has_more}\n".encode("utf-8")
        )
        sys.stdout.flush()

        if not has_more or not next_token:
            break

        page_no += 1
        time.sleep(0.3)

    return all_records


def main():
    sys.stdout.buffer.write(("=" * 60 + "\n").encode("utf-8"))
    sys.stdout.buffer.write("拉取钉钉多维表数据\n".encode("utf-8"))
    sys.stdout.buffer.write(("=" * 60 + "\n").encode("utf-8"))
    sys.stdout.flush()

    missing = []
    if not CLIENT_ID:
        missing.append("COPILOT_DT_CLIENT_ID")
    if not CLIENT_SECRET:
        missing.append("COPILOT_DT_CLIENT_SECRET")
    if not OPERATOR_ID:
        missing.append("COPILOT_DT_OPERATOR_ID")
    if not BASE_ID:
        missing.append("COPILOT_DT_BASE_ID")
    if missing:
        sys.stdout.buffer.write(
            f"[错误] 缺少必需环境变量: {', '.join(missing)}\n".encode("utf-8")
        )
        sys.stdout.flush()
        sys.exit(1)

    token = get_access_token()
    sys.stdout.buffer.write("  钉钉认证成功\n".encode("utf-8"))
    sys.stdout.flush()

    sheets_to_pull = [
        ("m6ZKv2m", "SKU数据库-自产贴牌"),
        ("JamZf9c", "商品知识库"),
        ("orzrBXC", "运营-产品定价表"),
    ]

    for sheet_id, sheet_name in sheets_to_pull:
        sys.stdout.buffer.write(f"\n--- {sheet_name} (id={sheet_id}) ---\n".encode("utf-8"))
        sys.stdout.flush()

        records = list_all_records(token, sheet_id)
        sys.stdout.buffer.write(f"  Total: {len(records)} records\n".encode("utf-8"))
        sys.stdout.flush()

        out_path = os.path.join(SCRIPT_DIR, f"dingtalk_{sheet_id}.json")
        # 只保存 fields 部分，精简体积
        simplified = []
        for r in records:
            simplified.append({
                "id": r.get("id"),
                "fields": r.get("fields", {}),
            })

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(simplified, f, ensure_ascii=False, indent=2)
        sys.stdout.buffer.write(f"  Saved: {out_path}\n".encode("utf-8"))
        sys.stdout.flush()

    sys.stdout.buffer.write(("\n" + "=" * 60 + "\n").encode("utf-8"))
    sys.stdout.buffer.write("Done!\n".encode("utf-8"))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
