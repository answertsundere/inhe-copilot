#!/usr/bin/env python
"""
快速本地单元测试 —— 每次改代码后跑。

目标：1-3 分钟内完成；只跑 tests/ 下的单元测试（不打真实外部服务）。
继承 pytest.ini 的默认超时（--timeout=60 --timeout-method=thread），
任何单测卡住会在 60s 被判失败并继续，不会无限挂起。

用法：
    python scripts/run_quick_tests.py            # 跑全量单元测试
    python scripts/run_quick_tests.py -x         # 失败即停（透传给 pytest）
    python scripts/run_quick_tests.py tests/test_rag_hybrid_retrieval.py   # 指定文件
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    # 透传额外参数给 pytest；默认跑 tests/
    extra = sys.argv[1:]
    targets = [a for a in extra if not a.startswith("-")] or ["tests/"]
    flags = [a for a in extra if a.startswith("-")]

    cmd = [sys.executable, "-m", "pytest", *targets, *flags]
    print("[quick] 运行:", " ".join(cmd))
    print("-" * 60)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(ROOT))
    dur = time.perf_counter() - t0
    print("-" * 60)
    print(f"[quick] 退出码={proc.returncode}  耗时={dur:.1f}s")
    print("[quick] 说明：默认含 60s 单测超时安全网；此命令不调用任何真实外部服务。")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
