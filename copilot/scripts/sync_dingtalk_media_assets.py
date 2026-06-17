#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉素材定时同步到本地素材库 kb_media_asset。

流程：
  1. 若钉钉凭据可用且指定 --refresh：运行 sync_dingtalk_media.py 刷新报告。
  2. 导入最新报告到 kb_media_asset：
     - content_hash 基于「稳定 URL 路径 + i_id + sku_code + asset_type」去 query，签名过期不会误判为新素材。
     - 已审核(approved)素材若 URL 未变：只更新 last_seen_at / url_expires_at，保持审核状态。
     - URL 变化时（--reset-urls-on-change）：重置为 pending_review，避免旧审核误用新内容。
     - 新素材：默认 pending_review / usable_for_agent=0，不进入 Agent 建议。
     - 支持 --auto-approve-low-risk 对 install_video / pack_guide_image / sku_image 自动审核。

设计原则：不硬写任何钉钉凭证，全部从环境变量读取；缺配置时给出明确提示而不崩溃。

用法:
    python scripts/sync_dingtalk_media_assets.py --dry-run                  # 仅预览现有报告
    python scripts/sync_dingtalk_media_assets.py --apply                    # 导入现有报告
    python scripts/sync_dingtalk_media_assets.py --refresh --apply          # 先拉钉钉再导入
    python scripts/sync_dingtalk_media_assets.py --apply --limit 5 --type sku_image --auto-approve-low-risk
"""

import argparse
import atexit
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCK_DIR = _PROJECT_ROOT / "data" / "sync_dingtalk_media_assets.lockdir"

# 加载 .env，使当前进程能读取钉钉凭据
_env_path = _PROJECT_ROOT / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=_env_path)
    except Exception:
        pass


def _dingtalk_configured() -> bool:
    """检查钉钉凭据是否齐全（只读，不输出敏感值）。"""
    keys = [
        "COPILOT_DT_CLIENT_ID",
        "COPILOT_DT_CLIENT_SECRET",
        "COPILOT_DT_OPERATOR_ID",
        "COPILOT_DT_BASE_ID",
    ]
    return all(os.environ.get(k) for k in keys)


def _acquire_process_lock() -> bool:
    _LOCK_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        _LOCK_DIR.mkdir()
        return True
    except FileExistsError:
        try:
            age_seconds = time.time() - _LOCK_DIR.stat().st_mtime
            if age_seconds > 7200:
                _LOCK_DIR.rmdir()
                _LOCK_DIR.mkdir()
                print(f"[SyncMedia] removed stale lock: {_LOCK_DIR}")
                return True
        except OSError:
            pass
        print("[SyncMedia] another sync_dingtalk_media_assets process is running; skip.")
        return False


def _release_process_lock() -> None:
    try:
        _LOCK_DIR.rmdir()
    except OSError:
        pass


def refresh_report(output_path: str) -> bool:
    """运行 sync_dingtalk_media.py 拉取钉钉最新数据，刷新报告。返回是否成功。"""
    if not _dingtalk_configured():
        print("[SyncMedia] 钉钉凭据缺失，跳过实时拉取，使用现有报告文件导入。")
        print("[SyncMedia] 如需实时拉取，请在 .env 配置 COPILOT_DT_* 系列环境变量（本次未改动任何配置）。")
        return False

    script = _PROJECT_ROOT / "scripts" / "sync_dingtalk_media.py"
    print(f"[SyncMedia] 拉取钉钉媒体数据 -> {output_path}")
    result = subprocess.run(
        [sys.executable, str(script), "--update-db", "--output", output_path],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    if result.returncode != 0:
        print(f"[SyncMedia] 钉钉拉取失败 (returncode={result.returncode})")
        if result.stderr:
            print(result.stderr[:800])
        return False
    print("[SyncMedia] 钉钉拉取完成。")
    return True


def import_assets(report_path: str, **kwargs) -> dict:
    """导入报告到 kb_media_asset。"""
    sys.path.insert(0, str(_PROJECT_ROOT))
    from scripts.import_dingtalk_media_assets import import_report  # type: ignore
    return import_report(report_path, **kwargs)


def main():
    parser = argparse.ArgumentParser(description="定时同步钉钉素材到本地素材库")
    parser.add_argument("--refresh", action="store_true", help="先从钉钉实时拉取再导入（需凭据）")
    parser.add_argument(
        "--report", default=str(_PROJECT_ROOT / "data" / "dingtalk_media_report_v2.json"),
        help="导入的报告文件路径",
    )
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--reset-urls-on-change", action="store_true", help="URL 变化时把已审核素材重置为待审核")
    parser.add_argument(
        "--daily-output", default=str(_PROJECT_ROOT / "data" / "dingtalk_media_report_daily.json"),
        help="--refresh 时拉取的报告输出路径",
    )
    parser.add_argument("--limit", type=int, default=None, help="限制处理的素材行数")
    parser.add_argument(
        "--type", dest="asset_type",
        choices=["install_video", "pack_guide_image", "sku_image"],
        default=None,
        help="只导入指定素材类型",
    )
    parser.add_argument("--product-id", type=int, default=None, help="按 product_id 过滤")
    parser.add_argument("--i-id", default=None, help="按 i_id 过滤")
    parser.add_argument("--sku-code", default=None, help="按 sku_code 过滤")
    parser.add_argument(
        "--auto-approve-low-risk", action="store_true", dest="auto_approve_low_risk",
        help="自动审核 install_video / pack_guide_image / sku_image",
    )
    args = parser.parse_args()
    if not _acquire_process_lock():
        sys.exit(0)
    atexit.register(_release_process_lock)

    print("=" * 60)
    print("钉钉素材同步到 kb_media_asset")
    print(f"  模式: {'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 60)

    report_to_import = args.report
    if args.refresh:
        ok = refresh_report(args.daily_output)
        if ok:
            report_to_import = args.daily_output

    if not os.path.exists(report_to_import):
        print(f"[SyncMedia] 报告文件不存在: {report_to_import}")
        print("[SyncMedia] 请先运行 scripts/sync_dingtalk_media.py 生成报告，或配置钉钉凭据后用 --refresh。")
        sys.exit(1)

    source_updated_at = datetime.utcnow()
    stats = import_assets(
        report_to_import,
        reset_urls_on_change=args.reset_urls_on_change,
        dry_run=not args.apply,
        limit=args.limit,
        asset_type=args.asset_type,
        product_id=args.product_id,
        i_id=args.i_id,
        sku_code=args.sku_code,
        auto_approve_low_risk=args.auto_approve_low_risk,
        source_updated_at=source_updated_at,
    )

    print(f"\n导入报告        : {report_to_import}")
    print(f"跳过（过滤）    : {stats['skipped_by_filter']}")
    print(f"新增素材        : {stats['new_assets']}")
    print(f"更新素材        : {stats['updated_assets']}")
    print(f"自动审核通过    : {stats['approved_assets']}")
    print(f"安装视频        : {stats['install_video']}")
    print(f"打包/安装指导图 : {stats['pack_guide_image']}")
    print(f"SKU 图片        : {stats['sku_image']}")
    if stats.get("url_reset_to_pending"):
        print(f"URL 变化重置审核: {stats['url_reset_to_pending']}")
    if not args.apply:
        print("\n(dry-run 模式，未写库)")
    print("\n同步完成。已审核素材的审核状态保持不变；新素材默认待审核。")


if __name__ == "__main__":
    main()
