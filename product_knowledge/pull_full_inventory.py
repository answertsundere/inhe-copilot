"""
补充数据拉取：全量库存 + 全量组合装商品
"""

import hashlib
import json
import time
import os
import requests
from datetime import datetime, timedelta
from collections import defaultdict

APP_KEY = "c9270ff8c41b4f1481f84f4c5669d597"
APP_SECRET = "0ac9e66c81134d8cb961904bf8b56886"
ACCESS_TOKEN = "450582fd13a8497db39eee4006e78c4b"
BASE_URL = "https://openapi.jushuitan.com/open"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_sign(app_secret, params):
    sorted_params = sorted(params.items())
    sign_str = app_secret + ''.join(f"{k}{v}" for k, v in sorted_params)
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest()


def call_api(endpoint, biz_params=None):
    ts = str(int(time.time()))
    biz_str = json.dumps(biz_params or {}, separators=(',', ':'), ensure_ascii=False)
    params = {
        'access_token': ACCESS_TOKEN,
        'app_key': APP_KEY,
        'biz': biz_str,
        'charset': 'utf-8',
        'timestamp': ts,
        'version': '2',
    }
    params['sign'] = generate_sign(APP_SECRET, params)
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.post(url, data=params, timeout=30)
    return resp.json()


def pull_endpoint_full(endpoint, dedup_key="sku_id",
                       date_field_start="modified_begin", date_field_end="modified_end"):
    start_date = datetime(2022, 1, 1)
    end_date = datetime(2026, 5, 29)
    batch_days = 6

    all_records = {}
    current = start_date
    batch_num = 0
    api_calls = 0

    while current < end_date:
        batch_end = min(current + timedelta(days=batch_days), end_date)
        batch_num += 1

        result = call_api(endpoint, {
            'page_index': 1,
            'page_size': 100,
            date_field_start: current.strftime('%Y-%m-%d 00:00:00'),
            date_field_end: batch_end.strftime('%Y-%m-%d 23:59:59'),
        })
        api_calls += 1

        if result.get('code') != 0:
            current = batch_end + timedelta(seconds=1)
            time.sleep(0.25)
            continue

        data = result.get('data', {})
        total = data.get('data_count', 0)

        if total > 0:
            for item in (data.get('datas') or []):
                key = str(item.get(dedup_key, ''))
                if key:
                    if key in all_records:
                        existing = all_records[key]
                        if str(item.get('modified', '')) > str(existing.get('modified', '')):
                            all_records[key] = item
                    else:
                        all_records[key] = item

            page_count = data.get('page_count', 1)
            for page in range(2, page_count + 1):
                time.sleep(0.25)
                page_result = call_api(endpoint, {
                    'page_index': page,
                    'page_size': 100,
                    date_field_start: current.strftime('%Y-%m-%d 00:00:00'),
                    date_field_end: batch_end.strftime('%Y-%m-%d 23:59:59'),
                })
                api_calls += 1
                if page_result.get('code') == 0:
                    for item in (page_result.get('data', {}).get('datas') or []):
                        key = str(item.get(dedup_key, ''))
                        if key:
                            if key in all_records:
                                existing = all_records[key]
                                if str(item.get('modified', '')) > str(existing.get('modified', '')):
                                    all_records[key] = item
                            else:
                                all_records[key] = item

            print(f"  Batch {batch_num}: {current.strftime('%Y-%m-%d')} ~ {batch_end.strftime('%Y-%m-%d')} "
                  f"| in_range={total} | accumulated={len(all_records)}")

        current = batch_end + timedelta(seconds=1)
        time.sleep(0.25)

    print(f"  Total API calls: {api_calls}")
    return list(all_records.values())


def main():
    print("=" * 60)
    print("补充数据拉取: 全量库存 + 组合装商品")
    print("=" * 60)

    # 1. 全量库存
    print("\n[1/2] 拉取全量库存 (inventory/query) ...")
    inventory = pull_endpoint_full("inventory/query", dedup_key="sku_id")
    print(f"  库存记录总数: {len(inventory)}")
    inv_path = os.path.join(SCRIPT_DIR, "full_inventory.json")
    with open(inv_path, 'w', encoding='utf-8') as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {inv_path}")

    # 2. 全量组合装
    print("\n[2/2] 拉取全量组合装 (combine/sku/query) ...")
    combine = pull_endpoint_full("combine/sku/query", dedup_key="sku_id")
    print(f"  组合装总数: {len(combine)}")
    combine_path = os.path.join(SCRIPT_DIR, "full_combine.json")
    with open(combine_path, 'w', encoding='utf-8') as f:
        json.dump(combine, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {combine_path}")

    # 3. 统计
    with open(os.path.join(SCRIPT_DIR, "full_skus.json"), 'r', encoding='utf-8') as f:
        skus = json.load(f)
    all_sku_ids = set(s.get('sku_id', '') for s in skus)
    inv_sku_ids = set(str(i.get('sku_id', '')) for i in inventory)
    covered = all_sku_ids & inv_sku_ids

    print("\n" + "=" * 60)
    print("拉取完成:")
    print(f"  全量库存: {len(inventory)} 条 (覆盖 {len(covered)}/{len(all_sku_ids)} 个SKU)")
    print(f"  组合装商品: {len(combine)} 条")
    print("=" * 60)


if __name__ == "__main__":
    main()
