"""
聚水潭 JST Live Query 诊断工具
用法: python scripts/diagnose_jst_live_query.py <identifier>
"""
import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.integrations.jst.live_query import (
    lookup_order_by_order_id,
    lookup_order_by_platform_order_id,
    lookup_logistics_by_tracking_no,
    lookup_order_by_identifier,
)


def diagnose(identifier: str):
    print(f"诊断标识符: {identifier}")
    print("=" * 70)

    queries = [
        ("order_id (o_ids)", lambda: lookup_order_by_order_id(identifier)),
        ("platform_order_id (so_ids)", lambda: lookup_order_by_platform_order_id(identifier)),
        ("tracking_no", lambda: lookup_logistics_by_tracking_no(identifier)),
        ("unknown_identifier (o_ids→so_ids)", lambda: lookup_order_by_identifier(identifier, "unknown_identifier")),
    ]

    results = []
    for name, fn in queries:
        t0 = time.time()
        try:
            r = fn()
        except Exception as e:
            r = {"found": False, "error_code": "exception", "error_message": str(e)}
        elapsed = int((time.time() - t0) * 1000)
        results.append((name, r, elapsed))

    # 表格输出
    print(f"\n{'查询类型':<40} {'found':<6} {'dur_ms':<8} {'reason':<40}")
    print("-" * 100)
    for name, r, elapsed in results:
        found = str(r.get("found", ""))
        dur = str(r.get("duration_ms", elapsed))
        reason = r.get("safe_fallback_reason", "") or r.get("error_code", "") or ""
        print(f"{name:<40} {found:<6} {dur:<8} {reason:<40}")

    # 详细输出
    print("\n" + "=" * 70)
    for name, r, elapsed in results:
        if r.get("found"):
            print(f"\n## {name} → FOUND")
            data = r.get("data", {})
            # 脱敏输出
            safe_fields = ["o_id", "so_id", "status", "shop_status", "amount",
                           "logistics_company", "l_id", "send_date", "sign_time",
                           "created", "pay_date", "items"]
            for k in safe_fields:
                v = data.get(k, "")
                if v:
                    if k == "items":
                        v = [{"name": i.get("name", ""), "qty": i.get("qty", 0)} for i in v[:3]]
                    print(f"  {k}: {v}")

    print(f"\n{'=' * 70}")
    print("诊断完成")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/diagnose_jst_live_query.py <identifier>")
        print("示例:")
        print("  python scripts/diagnose_jst_live_query.py 99999")
        print("  python scripts/diagnose_jst_live_query.py SF0221700958051")
        sys.exit(1)

    diagnose(sys.argv[1])
