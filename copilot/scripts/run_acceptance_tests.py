#!/usr/bin/env python
"""
灰度验收测试 —— 真实 API 用例（每天上线前跑）。

直接调用本地 /api/analyze（与 real-test 页面共享同一后端），跑 20 条真实场景，
每条调用带 timeout，输出原始 JSON + 人工评估模板。复用
scripts/manual/acceptance_20_real_test.py 的用例与请求逻辑，不重复造轮子。

用法：
    python scripts/run_acceptance_tests.py                         # 默认 5011
    python scripts/run_acceptance_tests.py --base-url http://127.0.0.1:5012
    python scripts/run_acceptance_tests.py --base-url https://<公网域名>
    python scripts/run_acceptance_tests.py --timeout 90
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.manual.acceptance_20_real_test import run_all  # noqa: E402

OUT_DIR = ROOT / "scripts" / "manual" / "outputs"


def main() -> int:
    ap = argparse.ArgumentParser(description="灰度验收：真实 API 用例")
    ap.add_argument("--base-url", default="http://127.0.0.1:5011",
                    help="被测后端地址（默认 5011；可用 5012 或公网域名）")
    ap.add_argument("--timeout", type=int, default=120, help="单条调用超时秒数")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"[acceptance] 目标: {args.base_url}/api/analyze  超时={args.timeout}s")
    print("-" * 60)

    results = run_all(base_url=args.base_url, per_call_timeout=args.timeout)

    raw_path = OUT_DIR / f"acceptance_run_{ts}.json"
    with raw_path.open("w", encoding="utf-8") as f:
        json.dump({"base_url": args.base_url, "ts": ts, "results": results}, f, ensure_ascii=False, indent=2)

    ok = sum(1 for r in results if r["ok"])
    print("-" * 60)
    print(f"[acceptance] 用例={len(results)} 接口正常={ok} 异常={len(results) - ok}")
    print(f"[acceptance] 原始结果: {raw_path}")
    print("[acceptance] 提示：接口正常≠语义通过。是否可灰度请用 run_gray_release_check.py 生成评估报告。")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
