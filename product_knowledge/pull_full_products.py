"""
全量商品数据拉取脚本
从 2022-01-01 到 2026-05-29，按6天批次拉取全量商品和SKU数据
输出: full_items.json, full_skus.json
"""

import hashlib
import json
import time
import os
import requests
from datetime import datetime, timedelta

# ============ API 配置 ============
APP_KEY = os.environ.get("JUSHUITAN_APP_KEY", "")
APP_SECRET = os.environ.get("JUSHUITAN_APP_SECRET", "")
ACCESS_TOKEN = os.environ.get("JUSHUITAN_ACCESS_TOKEN", "")
BASE_URL = os.environ.get("JUSHUITAN_BASE_URL", "https://openapi.jushuitan.com/open")

# ============ 输出路径 ============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "聚水潭api", "客服", "raw_data")

# ============ API 调用 ============

def generate_sign(app_secret, params):
    sorted_params = sorted(params.items())
    sign_str = app_secret + ''.join(f"{k}{v}" for k, v in sorted_params)
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest()


def call_api(endpoint, biz_params=None):
    if not (APP_KEY and APP_SECRET and ACCESS_TOKEN):
        raise RuntimeError("Missing JUSHUITAN_APP_KEY/JUSHUITAN_APP_SECRET/JUSHUITAN_ACCESS_TOKEN")
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


# ============ 分批拉取逻辑 ============

def pull_endpoint_full(endpoint, date_field_start="modified_begin", date_field_end="modified_end"):
    """
    从 2022-01-01 到 2026-05-29，每6天一个批次拉取全量数据。
    返回 dict: key 为去重键 (i_id 或 sku_id)，value 为完整记录。
    """
    start_date = datetime(2022, 1, 1)
    end_date = datetime(2026, 5, 29)
    batch_days = 6

    # 确定去重键
    dedup_key = "i_id" if "item" in endpoint or "mall" in endpoint else "sku_id"

    all_records = {}  # dedup_key -> record
    current = start_date
    batch_num = 0
    api_calls = 0

    while current < end_date:
        batch_end = min(current + timedelta(days=batch_days), end_date)
        batch_num += 1

        # 先查第一页获取总数
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
            # 处理第一页数据
            for item in (data.get('datas') or []):
                key = item.get(dedup_key)
                if key:
                    # 如果已存在，保留较新（modified 更晚）的记录
                    if key in all_records:
                        existing = all_records[key]
                        if item.get('modified', '') > existing.get('modified', ''):
                            all_records[key] = item
                    else:
                        all_records[key] = item

            # 继续翻页
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
                        key = item.get(dedup_key)
                        if key:
                            if key in all_records:
                                existing = all_records[key]
                                if item.get('modified', '') > existing.get('modified', ''):
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
    print("全量商品数据拉取")
    print("=" * 60)

    # ---- 1. 拉取商品主档 (mall/item/query) ----
    print("\n[1/2] 拉取商品主档 (mall/item/query) ...")
    items = pull_endpoint_full("mall/item/query")
    print(f"  商品主档总数: {len(items)}")

    items_path = os.path.join(SCRIPT_DIR, "full_items.json")
    with open(items_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {items_path}")

    # ---- 2. 拉取 SKU 明细 (sku/query) ----
    print("\n[2/2] 拉取 SKU 明细 (sku/query) ...")
    skus = pull_endpoint_full("sku/query")
    print(f"  SKU 总数: {len(skus)}")

    skus_path = os.path.join(SCRIPT_DIR, "full_skus.json")
    with open(skus_path, 'w', encoding='utf-8') as f:
        json.dump(skus, f, ensure_ascii=False, indent=2)
    print(f"  已保存: {skus_path}")

    # ---- 3. 统计摘要 ----
    item_iids = set(item.get('i_id') for item in items if item.get('i_id'))
    sku_iids = set(sku.get('i_id') for sku in skus if sku.get('i_id'))
    only_in_items = item_iids - sku_iids
    only_in_skus = sku_iids - item_iids

    print("\n" + "=" * 60)
    print("拉取完成！统计摘要:")
    print(f"  商品主档 (items): {len(items)} 个唯一 i_id")
    print(f"  SKU 明细 (skus):  {len(skus)} 个唯一 sku_id")
    print(f"  仅在 items 中的 i_id: {len(only_in_items)} 个")
    print(f"  仅在 skus 中的 i_id:  {len(only_in_skus)} 个")
    print(f"  两者共有的 i_id:     {len(item_iids & sku_iids)} 个")
    print("=" * 60)


if __name__ == "__main__":
    main()
