"""
客服 Copilot 第一阶段 Loop Engineering 自动巡检脚本

只读巡检 + 自动生成下一步任务建议。
第一阶段不修改核心代码、不自动提交、不自动审核/放行知识或素材。

用法:
    python scripts/run_daily_quality_loop.py --quick
    python scripts/run_daily_quality_loop.py --with-tests
    python scripts/run_daily_quality_loop.py --check-jst-live
    python scripts/run_daily_quality_loop.py --output reports/daily_loop_report_20260101.md
    python scripts/run_daily_quality_loop.py --json-output reports/daily_loop_report_20260101.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional


# ─── 项目路径 ─────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


# ─── 安全加载 .env ────────────────────────────────────────────────────
def _load_dotenv_safely() -> None:
    try:
        from dotenv import load_dotenv

        dotenv_path = os.path.join(BASE_DIR, ".env")
        if os.path.exists(dotenv_path):
            load_dotenv(dotenv_path)
    except Exception:
        pass


_load_dotenv_safely()


# ─── 工具函数 ─────────────────────────────────────────────────────────
def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _today_str() -> str:
    return _now().strftime("%Y%m%d")


def _date_from_report_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    match = re.search(r"daily_loop_report_(\d{8})", os.path.basename(path))
    return match.group(1) if match else None


def _resolve_output_paths(output_md: Optional[str], output_json: Optional[str]) -> tuple[str, Optional[str], str]:
    report_date = _date_from_report_path(output_md) or _date_from_report_path(output_json) or _today_str()
    resolved_md = output_md or os.path.join(REPORTS_DIR, f"daily_loop_report_{report_date}.md")
    return resolved_md, output_json, report_date


def _mask_url(url: Optional[str]) -> str:
    """仅保留 URL 路径，去掉 query（可能含签名）。"""
    if not url:
        return ""
    if "?" in url:
        return url.split("?", 1)[0]
    return url


def _short_exc(e: Optional[BaseException]) -> str:
    if e is None:
        return ""
    return f"{type(e).__name__}: {str(e)[:120]}"


# ─── 数据结构 ─────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    ok: bool = True
    status: str = "ok"  # ok / warning / error / not_configured
    details: dict[str, Any] = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)

    def add_message(self, level: str, text: str) -> None:
        self.messages.append(f"[{level}] {text}")


@dataclass
class LoopReport:
    overall: str = "Green"  # Green / Yellow / Red
    overall_reasons: list[str] = field(default_factory=list)
    report_date: str = field(default_factory=_today_str)
    generated_at: str = field(default_factory=lambda: _now().isoformat())
    app_health: CheckResult = field(default_factory=CheckResult)
    jst: CheckResult = field(default_factory=CheckResult)
    rag: CheckResult = field(default_factory=CheckResult)
    media: CheckResult = field(default_factory=CheckResult)
    agent_behavior: CheckResult = field(default_factory=CheckResult)
    tests: CheckResult = field(default_factory=CheckResult)
    git: CheckResult = field(default_factory=CheckResult)
    dispatch: list[dict[str, str]] = field(default_factory=list)
    dispatch_prompts: dict[str, str] = field(default_factory=dict)


# ─── 应用工厂 ─────────────────────────────────────────────────────────
def _get_test_app():
    """创建测试 Flask app，禁用后台同步线程，避免巡检期间产生写操作。"""
    # 与 conftest.py 一致：禁用每日同步 worker
    try:
        import app.main as _app_main

        _app_main._daily_sync_worker = lambda: None
    except Exception:
        pass

    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app


# ─── 一、基础健康检查 ────────────────────────────────────────────────
def check_app_health(app) -> CheckResult:
    result = CheckResult()
    client = app.test_client()

    page_routes = [
        "/ask/kb-admin/rag",
        "/ask/kb-admin/products",
        "/ask/kb-admin/guide",
        "/ask/kb-admin/media",
        "/ask/copilot-panel",
    ]
    api_routes = [
        "/ask/api/health",
        "/ask/api/media-assets/stats",
        "/ask/api/kb/knowledge/summary",
        "/ask/api/kb/products?limit=1",
    ]

    page_results = []
    api_results = []
    any_error = False

    for path in page_routes:
        try:
            resp = client.get(path)
            page_results.append({"path": path, "status": resp.status_code})
            if resp.status_code >= 500:
                any_error = True
            elif resp.status_code >= 400 and path != "/ask/kb-admin/rag":
                # SPA 子路径可能 404 但中间件会回退 index.html，这里仅记录
                pass
        except Exception as e:
            page_results.append({"path": path, "status": -1, "error": _short_exc(e)})
            any_error = True

    for path in api_routes:
        try:
            resp = client.get(path)
            api_results.append({"path": path, "status": resp.status_code})
            if resp.status_code >= 500:
                any_error = True
        except Exception as e:
            api_results.append({"path": path, "status": -1, "error": _short_exc(e)})
            any_error = True

    result.details = {"pages": page_results, "apis": api_results}
    result.ok = not any_error
    result.status = "error" if any_error else "ok"
    if any_error:
        result.add_message("error", "部分页面或 API 返回 5xx 或异常")
    return result


# ─── 二、聚水潭 JST 检查 ─────────────────────────────────────────────
def check_jst_config(app) -> CheckResult:
    result = CheckResult()
    try:
        cfg = app.config
        key_ok = bool(cfg.get("JST_APP_KEY"))
        secret_ok = bool(cfg.get("JST_APP_SECRET"))
        token_ok = bool(cfg.get("JST_ACCESS_TOKEN"))
        configured = key_ok and secret_ok and token_ok
        result.details = {
            "app_key_present": key_ok,
            "app_secret_present": secret_ok,
            "access_token_present": token_ok,
            "configured": configured,
        }
        if not configured:
            result.status = "not_configured"
            result.ok = True  # 未配置不是错误，只是说明状态
            result.add_message("warning", "聚水潭 API 凭证未配置（如需 live 检查请加 --check-jst-live 并配置环境变量）")
        return result
    except Exception as e:
        result.ok = False
        result.status = "error"
        result.add_message("error", _short_exc(e))
        return result


def check_jst_live() -> CheckResult:
    """默认不调用；仅在 --check-jst-live 时使用。"""
    result = CheckResult()
    try:
        from app.integrations.jst.live_query import lookup_order_by_order_id
        from app.integrations.jst.errors import JSTConfigError, JSTTimeoutError, JSTAPIError

        r = lookup_order_by_order_id("99999")
        reason = r.get("safe_fallback_reason") or r.get("error_code") or ""
        found = bool(r.get("found"))
        result.details = {
            "sample": "99999",
            "found": found,
            "reason": reason,
            "duration_ms": r.get("duration_ms", 0),
        }
        if reason in ("not_found", "") and not found:
            result.status = "ok"
            result.add_message("info", "JST API 可达（样例 99999 返回 not_found）")
        elif reason == "jst_not_configured" or not reason:
            result.status = "not_configured"
            result.add_message("warning", "JST 凭证未配置")
        else:
            result.status = "warning"
            result.add_message("warning", f"JST 返回需要关注: {reason}")
        return result
    except JSTConfigError:
        result.status = "not_configured"
        result.add_message("warning", "JST 凭证未配置")
        return result
    except JSTTimeoutError as e:
        result.ok = False
        result.status = "error"
        result.add_message("error", f"JST 超时: {_short_exc(e)}")
        return result
    except JSTAPIError as e:
        result.ok = False
        result.status = "error"
        code = getattr(e, "code", -1)
        if code in (13, 14, "13", "14"):
            result.add_message("error", f"JST 认证错误: {_short_exc(e)}")
        elif code in (15, "15"):
            result.add_message("error", f"JST IP 白名单受限: {_short_exc(e)}")
        else:
            result.add_message("error", f"JST API 错误: {_short_exc(e)}")
        return result
    except Exception as e:
        result.ok = False
        result.status = "error"
        result.add_message("error", f"JST live 检查异常: {_short_exc(e)}")
        return result


# ─── 三、RAG 状态检查 ────────────────────────────────────────────────
def check_rag_status(session) -> CheckResult:
    result = CheckResult()
    try:
        from sqlalchemy import text
        from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk

        total_entries = session.query(KnowledgeEntry).count()

        status_dist = {}
        for row in session.query(KnowledgeEntry.status, text("COUNT(*)")).group_by(KnowledgeEntry.status).all():
            status_dist[str(row[0])] = row[1]

        index_dist = {}
        for row in session.query(KnowledgeEntry.index_status, text("COUNT(*)")).group_by(KnowledgeEntry.index_status).all():
            index_dist[str(row[0])] = row[1]

        published_ready = session.query(KnowledgeEntry).filter(
            KnowledgeEntry.status == "published",
            KnowledgeEntry.index_status == "ready",
        ).count()

        total_chunks = session.query(KnowledgeChunk).count()

        published_not_ready = session.query(KnowledgeEntry).filter(
            KnowledgeEntry.status == "published",
            KnowledgeEntry.index_status != "ready",
        ).count()

        ready_no_chunks = 0
        for entry in session.query(KnowledgeEntry).filter(KnowledgeEntry.index_status == "ready").all():
            if not entry.chunks:
                ready_no_chunks += 1

        pending_review_count = status_dist.get("pending_review", 0)
        pending_review_threshold = 50
        pending_review_alert = pending_review_count > pending_review_threshold

        result.details = {
            "total_entries": total_entries,
            "status_distribution": status_dist,
            "index_distribution": index_dist,
            "published_ready": published_ready,
            "total_chunks": total_chunks,
            "published_not_ready": published_not_ready,
            "ready_no_chunks": ready_no_chunks,
            "pending_review_count": pending_review_count,
            "pending_review_alert": pending_review_alert,
        }

        risks = []
        if published_not_ready:
            risks.append(f"published 但 index_status != ready: {published_not_ready} 条")
        if ready_no_chunks:
            risks.append(f"ready 但 chunks 为 0: {ready_no_chunks} 条")
        if pending_review_alert:
            risks.append(f"pending_review 过多: {pending_review_count} 条（阈值 {pending_review_threshold}）")

        if risks:
            result.status = "warning"
            for r in risks:
                result.add_message("warning", r)
        else:
            result.status = "ok"
        return result
    except Exception as e:
        result.ok = False
        result.status = "error"
        result.add_message("error", f"RAG 检查异常: {_short_exc(e)}")
        return result


# ─── 四、媒体素材状态检查 ────────────────────────────────────────────
def check_media_status(session) -> CheckResult:
    result = CheckResult()
    try:
        from datetime import datetime
        from sqlalchemy import func
        from app.models.kb_tables import KBMediaAsset

        total = session.query(KBMediaAsset).count()
        approved = session.query(KBMediaAsset).filter(KBMediaAsset.status == "approved").count()
        usable = session.query(KBMediaAsset).filter(KBMediaAsset.usable_for_agent == 1).count()
        pending = session.query(KBMediaAsset).filter(KBMediaAsset.status == "pending_review").count()
        rejected = session.query(KBMediaAsset).filter(KBMediaAsset.status == "rejected").count()
        needs_refresh = session.query(KBMediaAsset).filter(KBMediaAsset.refresh_status == "needs_refresh").count()

        now = datetime.utcnow()
        expired = session.query(KBMediaAsset).filter(
            KBMediaAsset.url_expires_at.isnot(None),
            KBMediaAsset.url_expires_at <= now,
        ).count()

        by_type = {}
        for row in session.query(KBMediaAsset.asset_type, func.count(KBMediaAsset.id)).group_by(KBMediaAsset.asset_type).all():
            by_type[str(row[0])] = row[1]

        usable_by_type = {}
        for row in session.query(KBMediaAsset.asset_type, func.count(KBMediaAsset.id)).filter(
            KBMediaAsset.usable_for_agent == 1
        ).group_by(KBMediaAsset.asset_type).all():
            usable_by_type[str(row[0])] = row[1]

        # 抽样检查：不输出 URL
        sample_rows = (
            session.query(KBMediaAsset)
            .order_by(KBMediaAsset.updated_at.desc())
            .limit(5)
            .all()
        )
        samples = [
            {
                "asset_id": r.id,
                "asset_type": r.asset_type,
                "product_name": r.product_name,
                "refresh_status": r.refresh_status,
                "url_expires_at": r.url_expires_at.isoformat() if r.url_expires_at else None,
            }
            for r in sample_rows
        ]

        result.details = {
            "total": total,
            "approved": approved,
            "usable_for_agent": usable,
            "pending_review": pending,
            "rejected": rejected,
            "needs_refresh": needs_refresh,
            "expired_url_count": expired,
            "by_asset_type": by_type,
            "usable_by_asset_type": usable_by_type,
            "samples": samples,
        }

        suggestions = []
        if needs_refresh > 0 or expired > 0:
            suggestions.append("建议运行钉钉媒体刷新脚本（scripts/sync_dingtalk_media.py + sync_dingtalk_media_assets.py）")
        if usable > 0:
            pg = usable_by_type.get("pack_guide_image", 0)
            iv = usable_by_type.get("install_video", 0)
            sku = usable_by_type.get("sku_image", 0)
            if sku > 0 and (pg / max(sku, 1) < 0.3 or iv / max(sku, 1) < 0.3):
                suggestions.append("pack_guide_image / install_video 可用数量相对 sku_image 偏低，建议扩大覆盖")
        if expired > 0:
            suggestions.append(f"有 {expired} 个素材 URL 已过期，需刷新")

        if needs_refresh > 0 or expired > 0 or pending > 20:
            result.status = "warning"
        else:
            result.status = "ok"

        for s in suggestions:
            result.add_message("info", s)
        return result
    except Exception as e:
        result.ok = False
        result.status = "error"
        result.add_message("error", f"媒体检查异常: {_short_exc(e)}")
        return result


# ─── 五、Agent / RAG / 媒体最小行为验收 ──────────────────────────────
def check_agent_behavior(app, session, usable_for_agent_count: int) -> CheckResult:
    result = CheckResult()
    client = app.test_client()

    # 动态选择一条真实已审核可用、未过期的素材，避免固定商品导致误报。
    sample_asset = None
    if session is not None and usable_for_agent_count > 0:
        try:
            from datetime import datetime
            from sqlalchemy import or_
            from app.models.kb_tables import KBMediaAsset

            for asset_type in ("install_video", "pack_guide_image", "sku_image"):
                sample_asset = (
                    session.query(KBMediaAsset)
                    .filter(
                        KBMediaAsset.status == "approved",
                        KBMediaAsset.usable_for_agent == 1,
                        KBMediaAsset.asset_type == asset_type,
                        KBMediaAsset.refresh_status.notin_(["needs_refresh", "error"]),
                        or_(KBMediaAsset.url_expires_at.is_(None), KBMediaAsset.url_expires_at > datetime.utcnow()),
                    )
                    .order_by(KBMediaAsset.updated_at.desc())
                    .first()
                )
                if sample_asset:
                    break
        except Exception:
            sample_asset = None

    def _candidate_payload(asset) -> list[dict[str, Any]]:
        if not asset:
            return [{"type": "product_name", "value": "儿童书架"}]
        candidates: list[dict[str, Any]] = []
        if asset.i_id:
            candidates.append({"type": "sku_id_candidate", "value": asset.i_id, "verified": True})
        if asset.sku_code and asset.sku_code != asset.i_id:
            candidates.append({"type": "sku_code_candidate", "value": asset.sku_code, "verified": True})
        if asset.product_name:
            candidates.append({"type": "product_name", "value": asset.product_name, "verified": True})
        return candidates or [{"type": "product_name", "value": "儿童书架"}]

    sample_info = None
    if sample_asset:
        sample_info = {
            "asset_id": sample_asset.id,
            "asset_type": sample_asset.asset_type,
            "product_name": sample_asset.product_name,
            "i_id": sample_asset.i_id,
            "sku_code": sample_asset.sku_code,
        }

    media_message_by_type = {
        "install_video": "这个怎么安装？有安装视频吗？",
        "pack_guide_image": "少了配件怎么办？包装里有哪些？",
        "sku_image": "这个有图片吗？这个是什么颜色？",
    }

    test_cases = []
    if usable_for_agent_count > 0 and sample_asset:
        test_cases.append({
            "message": media_message_by_type.get(sample_asset.asset_type, "这个有图片吗？"),
            "expect_image": True,
            "label": f"动态素材命中验证({sample_asset.asset_type})",
            "product_candidates": _candidate_payload(sample_asset),
        })
    elif usable_for_agent_count > 0:
        result.add_message("warning", "素材库有可用素材，但未找到未过期且 refresh_status=ok 的 approved 样本，跳过推荐命中验收")
    else:
        result.add_message("info", "当前没有 approved + usable_for_agent 素材，跳过推荐命中验收")

    test_cases.append({
        "message": "甲醛安全吗？",
        "expect_image": False,
        "label": "材质安全问题",
        "product_candidates": _candidate_payload(sample_asset),
    })

    results = []
    any_non_200 = False
    hits_with_image = 0

    for case in test_cases:
        payload = {
            "message": case["message"],
            "conversation_id": "daily-loop-test",
            "product_candidates": case.get("product_candidates") or _candidate_payload(sample_asset),
        }
        try:
            resp = client.post(
                "/api/analyze",
                data=json.dumps(payload),
                content_type="application/json",
            )
            data = resp.get_json(silent=True) or {}
            has_field = "recommended_assets" in data
            reco = data.get("recommended_assets") or []
            reco_count = len(reco)
            reco_types = sorted({r.get("asset_type") for r in reco if isinstance(r, dict)})
            status = resp.status_code
            if status != 200:
                any_non_200 = True
            if case["expect_image"] and reco_count > 0:
                hits_with_image += 1
            results.append({
                "label": case["label"],
                "expect_image": case["expect_image"],
                "status": status,
                "has_recommended_assets_field": has_field,
                "recommended_count": reco_count,
                "recommended_types": reco_types,
            })
        except Exception as e:
            any_non_200 = True
            results.append({
                "label": case["label"],
                "expect_image": case["expect_image"],
                "status": -1,
                "error": _short_exc(e),
            })

    result.details = {"cases": results, "sample_asset": sample_info}

    if any_non_200:
        result.ok = False
        result.status = "error"
        result.add_message("error", "Agent /analyze 存在非 200 响应")
    elif usable_for_agent_count > 0 and sample_asset and hits_with_image == 0:
        result.status = "warning"
        result.add_message("warning", "素材库有可用素材，但动态 approved 素材验收未命中 recommended_assets")
    else:
        result.status = "ok"

    return result


# ─── 六、测试状态检查 ────────────────────────────────────────────────
def run_pytest_subset(run_tests: bool, extra_tests: bool) -> CheckResult:
    result = CheckResult()
    if not run_tests:
        result.status = "skipped"
        result.add_message("info", "--quick 模式跳过 pytest")
        return result

    targets = [
        "tests/test_security.py",
        "tests/test_media_asset.py",
    ]
    if extra_tests:
        targets.append("tests/test_knowledge_graph_integration.py")

    failed_tests: list[str] = []
    passed = 0
    failed = 0
    error = 0
    exit_code = -1
    raw_summary = ""

    # 分层测试一起跑，便于获得统一汇总；如超时则降级逐个跑
    cmd = [sys.executable, "-m", "pytest"] + targets + ["--tb=short"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = proc.stdout + "\n" + proc.stderr
        # 收集失败用例名
        for line in output.splitlines():
            m = re.match(r"FAILED\s+(\S+)", line)
            if m:
                failed_tests.append(m.group(1))
        # 从最后一行解析 passed/failed/error
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line and ("passed" in line or "failed" in line or "error" in line):
                raw_summary = line
                break
        if raw_summary:
            # 例如 "3 passed, 1 failed, 2 errors in 10.23s"
            parts = raw_summary.split(",")
            for part in parts:
                part = part.strip()
                if "passed" in part:
                    try:
                        passed = int(part.split()[0])
                    except Exception:
                        pass
                elif "failed" in part:
                    try:
                        failed = int(part.split()[0])
                    except Exception:
                        pass
                elif "error" in part:
                    try:
                        error = int(part.split()[0])
                    except Exception:
                        pass
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        failed_tests.append("pytest suite (timeout)")
        exit_code = -2
    except Exception as e:
        failed_tests.append(f"pytest ({_short_exc(e)})")
        exit_code = -3

    result.details = {
        "targets": targets,
        "exit_code": exit_code,
        "passed": passed,
        "failed": failed,
        "error": error,
        "failed_tests": failed_tests[:10],
        "summary": raw_summary,
    }

    if exit_code == 0 and not failed_tests:
        result.status = "ok"
    elif any("test_security" in x for x in failed_tests):
        result.ok = False
        result.status = "error"
        result.add_message("error", "安全测试失败，需优先处理")
    else:
        result.status = "warning"
        result.add_message("warning", f"测试存在失败/错误: {failed} failed, {error} error")

    return result


# ─── 七、Git / 提交卫生检查 ──────────────────────────────────────────
def check_git_hygiene() -> CheckResult:
    result = CheckResult()
    try:
        proc = subprocess.run(
            ["git", "status", "--short"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    except Exception as e:
        result.ok = False
        result.status = "error"
        result.add_message("error", f"git status 失败: {_short_exc(e)}")
        return result

    modified = []
    deleted = []
    untracked = []
    high_risk = []

    high_risk_patterns = [
        r"^data/.*\.db",
        r"^data/.*\.backup",
        r"^data/snapshots/",
        r"^logs/",
        r"^reports/",
        r"^screenshots",
        r"^web/static/kb-admin/assets/",
        r"^\.env",
    ]

    for line in lines:
        if len(line) < 3:
            continue
        status = line[:2]
        path = line[3:].strip()
        if status.startswith("M") or status.endswith("M"):
            modified.append(path)
        elif status.startswith("D") or status.endswith("D"):
            deleted.append(path)
        elif status.startswith("?"):
            untracked.append(path)

        for pattern in high_risk_patterns:
            if re.search(pattern, path):
                high_risk.append(path)
                break

    result.details = {
        "modified_count": len(modified),
        "deleted_count": len(deleted),
        "untracked_count": len(untracked),
        "high_risk_paths": high_risk[:20],
        "sample_modified": modified[:10],
        "sample_untracked": untracked[:10],
    }

    if high_risk:
        result.status = "warning"
        result.add_message("warning", f"发现 {len(high_risk)} 个高风险路径变更，建议检查后再提交")
    else:
        result.status = "ok"
    return result


# ─── 八、自动生成下一步任务建议 ──────────────────────────────────────
def build_dispatch_recommendations(report: LoopReport) -> list[dict[str, str]]:
    dispatch: list[dict[str, str]] = []

    # 1. 部署/服务健康
    health_failed = False
    for item in report.app_health.details.get("pages", []) + report.app_health.details.get("apis", []):
        status = item.get("status", 0)
        if status == 502 or status >= 500:
            health_failed = True
            break
    api_health_status = next((x["status"] for x in report.app_health.details.get("apis", []) if x["path"] == "/ask/api/health"), 200)
    if health_failed or api_health_status != 200:
        dispatch.append({
            "window": "窗口 1：部署/服务健康",
            "reason": "页面/API 出现 5xx 或 /api/health 异常",
            "action": "检查本地服务是否可启动，查看日志定位异常",
        })

    # 2. 钉钉媒体刷新/审核
    media = report.media.details
    if media.get("needs_refresh", 0) > 0 or media.get("expired_url_count", 0) > 0:
        dispatch.append({
            "window": "窗口 2：钉钉媒体刷新/审核",
            "reason": f"needs_refresh={media.get('needs_refresh', 0)}, expired_url={media.get('expired_url_count', 0)}",
            "action": "运行钉钉同步与素材导入脚本，主管审核/刷新过期素材",
        })
    elif media.get("usable_for_agent", 0) < 5:
        dispatch.append({
            "window": "窗口 2：钉钉媒体刷新/审核",
            "reason": f"usable_for_agent 仅 {media.get('usable_for_agent', 0)}，素材可用量偏少",
            "action": "检查钉钉多维表数据覆盖，导入更多安装视频/打包图",
        })

    # 3. Agent 媒体推荐/前端展示
    agent = report.agent_behavior.details
    usable = report.media.details.get("usable_for_agent", 0)
    sample_asset = agent.get("sample_asset")
    if usable > 0:
        hits = sum(1 for c in agent.get("cases", []) if c.get("expect_image") and c.get("recommended_count", 0) > 0)
        if sample_asset and hits == 0:
            dispatch.append({
                "window": "窗口 3：Agent 媒体推荐/前端展示",
                "reason": "素材可用但 /analyze 未推荐任何图片/视频",
                "action": "检查 media_asset_service 推荐逻辑或前端 recommended_assets 展示",
            })

    # 4. RAG 知识窗口
    rag = report.rag.details
    if rag.get("published_ready", 0) < 10:
        dispatch.append({
            "window": "RAG 知识窗口：补知识草稿/审核/reindex",
            "reason": f"published+ready 仅 {rag.get('published_ready', 0)} 条",
            "action": "补充知识草稿、提交审核、或重新触发索引",
        })
    if rag.get("published_not_ready", 0) > 0:
        dispatch.append({
            "window": "RAG 知识窗口：补知识草稿/审核/reindex",
            "reason": f"published 但 index_status != ready: {rag.get('published_not_ready', 0)} 条",
            "action": "检查索引服务或 KnowledgeIndexService.on_publish 执行情况",
        })

    # 5. 安全窗口
    if report.tests.details.get("failed_tests") and any("test_security" in x for x in report.tests.details.get("failed_tests", [])):
        dispatch.append({
            "window": "安全窗口",
            "reason": "test_security.py 失败",
            "action": "检查源码中是否出现硬编码密钥或敏感信息",
        })

    # 6. 提交卫生窗口
    if report.git.details.get("high_risk_paths"):
        dispatch.append({
            "window": "提交卫生窗口",
            "reason": f"git 中存在 {len(report.git.details.get('high_risk_paths', []))} 个高风险路径",
            "action": "手动检查 data/*.db、.env、reports 等文件，勿直接 git add .",
        })

    if not dispatch:
        dispatch.append({
            "window": "无需派单",
            "reason": "当前关键指标正常",
            "action": "继续保持观察",
        })

    return dispatch


# ─── 自动派单提示词生成（纯本地模板，不调用 LLM API）────────────────────
def build_dispatch_prompts(report: LoopReport) -> dict[str, str]:
    """根据巡检报告为 5 个固定窗口生成可直接复制的处理提示词。"""
    prompts: dict[str, str] = {}

    # ── 窗口 1：部署 / 线上健康 / JST ─────────────────────────────────
    health_items = report.app_health.details.get("pages", []) + report.app_health.details.get("apis", [])
    failed_health = [x for x in health_items if x.get("status", 200) != 200]
    api_health_status = next((x["status"] for x in report.app_health.details.get("apis", []) if x["path"] == "/ask/api/health"), 200)
    jst_configured = report.jst.details.get("configured", False)
    jst_status = report.jst.status
    jst_reason = report.jst.details.get("reason", report.jst.details.get("safe_fallback_reason", ""))

    window1_lines: list[str] = [
        "## 窗口 1：部署 / 线上健康 / JST",
        "",
        f"巡检结论：{report.overall}",
        f"/ask/api/health 状态码：{api_health_status}",
    ]
    if failed_health:
        window1_lines.append("失败或异常的页面/API：")
        for item in failed_health:
            window1_lines.append(f"  - {item['path']}: {item.get('status')} {item.get('error', '')}")
    else:
        window1_lines.append("页面/API 健康检查全部通过。")
    window1_lines.extend([
        f"JST 配置状态：{'已配置' if jst_configured else '未配置'}（状态: {jst_status}）",
        "",
        "请完成以下动作：",
        "1. 在本地确认 Flask 服务可启动：`python run_web.py` 或 `python run_prod.py`。",
        "2. 检查上面列出的非 200 路径的日志，定位 5xx 原因。",
        "3. 如需检查 JST 外网连通性，配置环境变量后运行：`python scripts/run_daily_quality_loop.py --check-jst-live`。",
        "4. 修复后重新运行：`python scripts/run_daily_quality_loop.py --quick`。",
        "",
        "约束：",
        "- 不要自动重启生产服务，先在本地/ staging 复现。",
        "- 不要修改未经验证的防火墙/白名单配置。",
    ])
    prompts["window_1_deploy"] = "\n".join(window1_lines)

    # ── 窗口 2：媒体同步 / 链接刷新 / 素材审核 ─────────────────────────
    media = report.media.details
    needs_refresh = media.get("needs_refresh", 0)
    expired = media.get("expired_url_count", 0)
    usable = media.get("usable_for_agent", 0)
    pending_media = media.get("pending_review", 0)
    usable_by_type = media.get("usable_by_asset_type", {})
    iv = usable_by_type.get("install_video", 0)
    pg = usable_by_type.get("pack_guide_image", 0)
    sku = usable_by_type.get("sku_image", 0)

    media_needs_attention = (
        needs_refresh > 0
        or expired > 0
        or usable < 50
        or pending_media > 500
        or (sku > 0 and (pg / max(sku, 1) < 0.3 or iv / max(sku, 1) < 0.3))
    )

    window2_lines: list[str] = [
        "## 窗口 2：媒体同步 / 链接刷新 / 素材审核",
        "",
        f"巡检结论：{report.overall}",
        f"媒体素材指标：total={media.get('total', 'N/A')}, approved={media.get('approved', 'N/A')}, usable_for_agent={usable}, pending_review={pending_media}",
        f"过期/需刷新：needs_refresh={needs_refresh}, expired_url_count={expired}",
        f"可用素材类型分布：sku_image={sku}, pack_guide_image={pg}, install_video={iv}",
        "",
    ]
    if media_needs_attention:
        window2_lines.extend([
            "请完成以下动作：",
            "1. 如需同步钉钉多维表最新媒体数据，运行：",
            "   python scripts/sync_dingtalk_media.py --update-db --output data/dingtalk_media_report_daily.json",
            "2. 将报告导入素材库（仅新增/更新，不自动审核）：",
            "   python scripts/sync_dingtalk_media_assets.py --report data/dingtalk_media_report_daily.json",
            "3. 主管登录 kb-admin 后台，对 pending_review 素材进行人工审核。",
            "4. 对 needs_refresh / expired_url 的素材，使用后台刷新或重新导入获取新的 OSS URL。",
            "5. 若 pack_guide_image / install_video 可用量偏低，检查钉钉表中对应商品是否已上传打包图/安装视频。",
            "",
            "约束：",
            "- 不要自动 approve 所有 pending_review 素材。",
            "- 不要自动群发或自动发送任何素材给客户。",
            "- 不要在报告/日志中打印完整 OSS 签名 URL。",
        ])
    else:
        window2_lines.append("本轮无需处理。")
    prompts["window_2_media"] = "\n".join(window2_lines)

    # ── 窗口 3：Agent 前端 / 素材展示 / analyze/copilot ────────────────
    agent_cases = report.agent_behavior.details.get("cases", [])
    failed_agent = [c for c in agent_cases if c.get("status", 200) != 200]
    missing_field = [c for c in agent_cases if not c.get("has_recommended_assets_field")]
    material_safety = next((c for c in agent_cases if c["label"] == "材质安全问题"), {})
    material_has_image = bool(material_safety.get("recommended_count", 0) > 0)
    usable = report.media.details.get("usable_for_agent", 0)
    sample_asset = report.agent_behavior.details.get("sample_asset")
    hits = sum(1 for c in agent_cases if c.get("expect_image") and c.get("recommended_count", 0) > 0)

    window3_lines: list[str] = [
        "## 窗口 3：Agent 前端 / 素材展示 / analyze/copilot",
        "",
        f"巡检结论：{report.overall}",
        "Agent 最小行为验收结果：",
    ]
    for c in agent_cases:
        window3_lines.append(f"  - {c['label']}: status={c.get('status')}, recommended_count={c.get('recommended_count')}, types={c.get('recommended_types')}")
    if sample_asset:
        window3_lines.append(
            f"动态样本：asset_id={sample_asset.get('asset_id')}, type={sample_asset.get('asset_type')}, "
            f"product={sample_asset.get('product_name')}, i_id={sample_asset.get('i_id')}"
        )
    window3_lines.append("")

    if failed_agent or missing_field or material_has_image or (usable > 0 and sample_asset and hits == 0):
        window3_lines.extend([
            "请完成以下动作：",
            "1. 确认 /ask/api/analyze 返回 200 且响应中包含 `recommended_assets` 字段。",
            "2. 检查 `app/services/media_asset_service.py` 中的推荐逻辑：",
            "   - 是否因 product_name/i_id/sku_code 未匹配导致推荐为空；",
            "   - `material_safety` 意图是否错误地返回了图片/视频；",
            "   - 素材库有可用素材但安装/图片/配件问题均未命中时，检查 url_expires_at 是否过期。",
            "3. 检查前端 copilot-panel / kb-admin 是否正确读取并展示 `recommended_assets`。",
            "4. 验证命令：",
            "   curl -X POST http://localhost:5011/ask/api/analyze -H 'Content-Type: application/json' -d '{\"message\":\"这个怎么安装？\",\"product_candidates\":[{\"type\":\"product_name\",\"value\":\"三层火箭书架\"}]}'",
            "",
            "约束：",
            "- 不要修改 Agent 主链路核心判断逻辑，只修复推荐注入/展示层。",
            "- 不要自动把未审核素材暴露给客户侧。",
        ])
    else:
        window3_lines.append("本轮无需处理。")
    prompts["window_3_agent"] = "\n".join(window3_lines)

    # ── 窗口 4：RAG 知识窗口 ───────────────────────────────────────────
    rag = report.rag.details
    published_ready = rag.get("published_ready", 0)
    published_not_ready = rag.get("published_not_ready", 0)
    ready_no_chunks = rag.get("ready_no_chunks", 0)
    rag_test_failed = any("knowledge_graph" in x for x in report.tests.details.get("failed_tests", []))

    window4_lines: list[str] = [
        "## 窗口 4：RAG 知识窗口",
        "",
        f"巡检结论：{report.overall}",
        f"知识库指标：total_entries={rag.get('total_entries', 'N/A')}, published_ready={published_ready}, total_chunks={rag.get('total_chunks', 'N/A')}",
        f"异常项：published_not_ready={published_not_ready}, ready_no_chunks={ready_no_chunks}, pending_review={rag.get('pending_review_count', 'N/A')}",
        "",
    ]
    if published_ready < 50 or published_not_ready > 0 or ready_no_chunks > 0 or rag_test_failed:
        window4_lines.extend([
            "请完成以下动作：",
            "1. 补充商品知识草稿：优先补充热销 SKU 的 product_facts、FAQ。",
            "2. 在 kb-admin 中将草稿提交审核并 publish；publish 后观察 index_status 是否变为 ready。",
            "3. 若 published 后 index_status 未变 ready，检查 `app/services/knowledge_index_service.py` 的 `on_publish` 与索引 pipeline。",
            "4. 对 ready 但 chunks 为 0 的条目，手动触发 reindex 或重新 publish。",
            "5. 若 RAG 集成测试失败，先确认 `COPILOT_LLM_API_KEY` 是否配置，再检查证据链节点。",
            "",
            "验证命令：",
            "   python -m pytest tests/test_knowledge_graph_integration.py -q",
            "",
            "约束：",
            "- 不要自动全量 publish 所有草稿。",
            "- 不要修改已有 published 知识的业务内容，除非经过审核。",
        ])
    else:
        window4_lines.append("本轮无需处理。")
    prompts["window_4_rag"] = "\n".join(window4_lines)

    # ── 窗口 5：测试与提交卫生窗口 ─────────────────────────────────────
    tests = report.tests.details
    failed_tests = tests.get("failed_tests", [])
    security_failed = any("test_security" in x for x in failed_tests)
    high_risk_paths = report.git.details.get("high_risk_paths", [])
    modified = report.git.details.get("modified_count", 0)
    untracked = report.git.details.get("untracked_count", 0)

    window5_lines: list[str] = [
        "## 窗口 5：测试与提交卫生窗口",
        "",
        f"巡检结论：{report.overall}",
        f"测试汇总：passed={tests.get('passed', 'N/A')}, failed={tests.get('failed', 'N/A')}, error={tests.get('error', 'N/A')}, exit_code={tests.get('exit_code', 'N/A')}",
        f"失败用例：{failed_tests if failed_tests else '无'}",
        f"Git 变更：modified={modified}, untracked={untracked}, 高风险路径数={len(high_risk_paths)}",
        "",
    ]
    if security_failed or failed_tests or high_risk_paths:
        window5_lines.extend([
            "请完成以下动作：",
            "1. 修复失败的 pytest 用例，优先处理 test_security.py（检查源码是否出现硬编码密钥、Secret、Token）。",
            "2. 对于 test_knowledge_graph_integration.py 失败，先确认 LLM key 与网络，再检查 RAG 证据链。",
            "3. 清理 git 工作区前，逐条检查高风险路径：",
        ])
        for p in high_risk_paths[:10]:
            window5_lines.append(f"   - {p}")
        window5_lines.extend([
            "4. 仅提交必要的源代码/配置变更；数据库、备份、日志、运行时产物、构建产物原则上不入库。",
            "",
            "验证命令：",
            "   python -m pytest tests/test_security.py tests/test_media_asset.py -q",
            "   git status --short",
            "",
            "约束（必须遵守）：",
            "- 不要执行 `git add .`。",
            "- 不要提交 data/*.db、data/*.backup*、data/snapshots/、logs/、reports/、screenshots、.env、完整 OSS 签名 URL。",
            "- 不要提交密钥、Access Token、App Secret。",
            "- 不要全量 apply 或自动提交所有变更。",
        ])
    else:
        window5_lines.append("本轮无需处理。")
    prompts["window_5_test_hygiene"] = "\n".join(window5_lines)

    return prompts


# ─── 从 JSON 重构报告（用于 --dispatch-only）───────────────────────────
def _report_from_dict(data: dict[str, Any]) -> LoopReport:
    """从 JSON 报告字典重构 LoopReport，字段缺失时保持兼容。"""

    def _check_result_from_dict(d: dict[str, Any]) -> CheckResult:
        return CheckResult(
            ok=d.get("ok", True),
            status=d.get("status", "ok"),
            details=d.get("details", {}),
            messages=d.get("messages", []),
        )

    return LoopReport(
        overall=data.get("overall", "Green"),
        overall_reasons=data.get("overall_reasons", []),
        report_date=data.get("report_date", _date_from_report_path(data.get("source")) or _today_str()),
        generated_at=data.get("generated_at", _now().isoformat()),
        app_health=_check_result_from_dict(data.get("app_health", {})),
        jst=_check_result_from_dict(data.get("jst", {})),
        rag=_check_result_from_dict(data.get("rag", {})),
        media=_check_result_from_dict(data.get("media", {})),
        agent_behavior=_check_result_from_dict(data.get("agent_behavior", {})),
        tests=_check_result_from_dict(data.get("tests", {})),
        git=_check_result_from_dict(data.get("git", {})),
        dispatch=data.get("dispatch", []),
        dispatch_prompts=data.get("dispatch_prompts", {}),
    )


def _find_latest_report_json() -> Optional[str]:
    """查找 reports/ 下最新的 daily_loop_report_*.json。"""
    candidates = []
    for name in os.listdir(REPORTS_DIR):
        if name.startswith("daily_loop_report_") and name.endswith(".json"):
            path = os.path.join(REPORTS_DIR, name)
            candidates.append((os.path.getmtime(path), path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def run_dispatch_only(json_path: Optional[str], output_md: Optional[str], output_json: Optional[str]) -> int:
    """只读模式：从 JSON 报告生成派单提示词，不跑巡检。"""
    source = json_path or _find_latest_report_json()
    if not source or not os.path.exists(source):
        print("[loop] 错误：未找到 daily_loop_report_*.json，请先运行一次巡检并生成 JSON 报告。", file=sys.stderr)
        return 2

    print(f"[loop] dispatch-only 读取报告: {source}")
    with open(source, "r", encoding="utf-8") as f:
        data = json.load(f)

    report = _report_from_dict(data)
    if not data.get("report_date"):
        report.report_date = _date_from_report_path(source) or report.report_date
    print(f"[loop] report_date: {report.report_date}")
    prompts = build_dispatch_prompts(report)
    report.dispatch_prompts = prompts

    if output_md:
        lines = [
            "# 客服 Copilot 自动派单提示词",
            "",
            f"来源报告: {source}",
            f"来源报告日期: {report.report_date}",
            f"生成时间: {_now().isoformat()}",
            "",
        ]
        for key in ["window_1_deploy", "window_2_media", "window_3_agent", "window_4_rag", "window_5_test_hygiene"]:
            lines.append(prompts.get(key, f"## {key}\n\n本轮无需处理。"))
            lines.append("")
        lines.append("---")
        lines.append("_本提示词由 run_daily_quality_loop.py --dispatch-only 本地模板生成，未调用任何 LLM API。_")
        os.makedirs(os.path.dirname(output_md), exist_ok=True)
        with open(output_md, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[loop] 已写入 Markdown: {output_md}")

    if output_json:
        out_data = {
            "source": source,
            "report_date": report.report_date,
            "generated_at": _now().isoformat(),
            "dispatch_prompts": prompts,
        }
        os.makedirs(os.path.dirname(output_json), exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)
        print(f"[loop] 已写入 JSON: {output_json}")

    if not output_md and not output_json:
        print("\n" + "=" * 70)
        print("客服 Copilot 自动派单提示词")
        print("=" * 70)
        for key in ["window_1_deploy", "window_2_media", "window_3_agent", "window_4_rag", "window_5_test_hygiene"]:
            print(prompts.get(key, f"## {key}\n\n本轮无需处理。"))
            print("\n" + "-" * 70 + "\n")

    return 0


# ─── 总体结论计算 ────────────────────────────────────────────────────
def compute_overall(report: LoopReport) -> tuple[str, list[str]]:
    reasons: list[str] = []

    # Red 条件
    api_health_status = next((x["status"] for x in report.app_health.details.get("apis", []) if x["path"] == "/ask/api/health"), 200)
    if api_health_status != 200:
        reasons.append(f"/api/health 返回 {api_health_status}")

    for item in report.app_health.details.get("pages", []) + report.app_health.details.get("apis", []):
        if item.get("status", 0) >= 500:
            reasons.append(f"{item['path']} 返回 {item['status']}")

    if report.tests.status == "error":
        reasons.append("安全测试失败")

    if report.rag.status == "error":
        reasons.append("RAG 数据库检查失败")

    if report.agent_behavior.status == "error":
        reasons.append("Agent /analyze 行为验收失败")

    if reasons:
        return "Red", reasons

    # Yellow 条件
    if report.rag.status == "warning":
        reasons.append("RAG 状态存在风险提醒")
    if report.media.status == "warning":
        reasons.append("媒体状态存在风险提醒")
    if report.agent_behavior.status == "warning":
        reasons.append("Agent 媒体推荐未命中")
    if report.jst.status in ("error", "warning"):
        reasons.append(f"JST 检查状态: {report.jst.status}")
    if report.git.status == "warning":
        reasons.append("git 存在高风险路径")
    if report.tests.status == "warning":
        reasons.append("测试存在失败/错误")

    if reasons:
        return "Yellow", reasons

    return "Green", ["所有关键指标正常"]


# ─── 报告生成 ────────────────────────────────────────────────────────
def _render_dict_table(d: dict[str, Any]) -> str:
    if not d:
        return "_无_"
    rows = "\n".join(f"| {k} | {v} |" for k, v in d.items())
    return f"| 指标 | 数值 |\n|---|---|\n{rows}"


def write_markdown_report(report: LoopReport, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    lines: list[str] = []
    lines.append("# 客服 Copilot 每日 Loop Engineering 巡检报告")
    lines.append("")
    lines.append(f"报告日期: {report.report_date}")
    lines.append(f"生成时间: {report.generated_at}")
    lines.append(f"总体结论: **{report.overall}**")
    lines.append("")

    lines.append("## 1. 总体结论")
    lines.append("")
    lines.append(f"**{report.overall}**")
    lines.append("")
    lines.append("判断理由:")
    for r in report.overall_reasons:
        lines.append(f"- {r}")
    lines.append("")

    lines.append("## 2. 关键指标表")
    lines.append("")
    lines.append("| 模块 | 状态 | 关键数值 |")
    lines.append("|---|---|---|")
    rag = report.rag.details
    media = report.media.details
    lines.append(f"| 应用健康 | {report.app_health.status} | pages/apis 见下节 |")
    lines.append(f"| JST | {report.jst.status} | configured={report.jst.details.get('configured', report.jst.details.get('reason', 'N/A'))} |")
    lines.append(f"| RAG | {report.rag.status} | entries={rag.get('total_entries', 'N/A')}, published_ready={rag.get('published_ready', 'N/A')} |")
    lines.append(f"| 媒体 | {report.media.status} | total={media.get('total', 'N/A')}, usable={media.get('usable_for_agent', 'N/A')}, needs_refresh={media.get('needs_refresh', 'N/A')} |")
    lines.append(f"| Agent 行为 | {report.agent_behavior.status} | 见第 7 节 |")
    lines.append(f"| 测试 | {report.tests.status} | passed={report.tests.details.get('passed', 'N/A')}, failed={report.tests.details.get('failed', 'N/A')} |")
    lines.append(f"| Git 卫生 | {report.git.status} | modified={report.git.details.get('modified_count', 'N/A')}, untracked={report.git.details.get('untracked_count', 'N/A')} |")
    lines.append("")

    lines.append("## 3. 健康检查结果")
    lines.append("")
    lines.append("### 页面")
    lines.append(_render_dict_table({x["path"]: x.get("status", "error") for x in report.app_health.details.get("pages", [])}))
    lines.append("")
    lines.append("### API")
    lines.append(_render_dict_table({x["path"]: x.get("status", "error") for x in report.app_health.details.get("apis", [])}))
    lines.append("")

    lines.append("## 4. JST 检查结果")
    lines.append("")
    lines.append(_render_dict_table(report.jst.details))
    lines.append("")
    for m in report.jst.messages:
        lines.append(f"- {m}")
    lines.append("")

    lines.append("## 5. RAG 状态")
    lines.append("")
    rag = report.rag.details
    lines.append(f"- 总数: {rag.get('total_entries', 'N/A')}")
    lines.append(f"- status 分布: {rag.get('status_distribution', {})}")
    lines.append(f"- index_status 分布: {rag.get('index_distribution', {})}")
    lines.append(f"- published + ready: {rag.get('published_ready', 'N/A')}")
    lines.append(f"- knowledge_chunks 总数: {rag.get('total_chunks', 'N/A')}")
    lines.append(f"- published 但 index_status != ready: {rag.get('published_not_ready', 'N/A')}")
    lines.append(f"- ready 但 chunks 为 0: {rag.get('ready_no_chunks', 'N/A')}")
    lines.append(f"- pending_review: {rag.get('pending_review_count', 'N/A')}")
    for m in report.rag.messages:
        lines.append(f"- {m}")
    lines.append("")

    lines.append("## 6. 媒体状态")
    lines.append("")
    media = report.media.details
    lines.append(f"- 总数: {media.get('total', 'N/A')}")
    lines.append(f"- approved: {media.get('approved', 'N/A')}")
    lines.append(f"- usable_for_agent: {media.get('usable_for_agent', 'N/A')}")
    lines.append(f"- pending_review: {media.get('pending_review', 'N/A')}")
    lines.append(f"- rejected: {media.get('rejected', 'N/A')}")
    lines.append(f"- needs_refresh: {media.get('needs_refresh', 'N/A')}")
    lines.append(f"- expired_url_count: {media.get('expired_url_count', 'N/A')}")
    lines.append(f"- by asset_type: {media.get('by_asset_type', {})}")
    lines.append(f"- usable_by_asset_type: {media.get('usable_by_asset_type', {})}")
    lines.append("")
    lines.append("### 抽样（脱敏，不显示 URL）")
    for s in media.get("samples", []):
        lines.append(f"- asset_id={s['asset_id']}, type={s['asset_type']}, product={s['product_name']}, refresh={s['refresh_status']}, expires={s['url_expires_at']}")
    lines.append("")
    for m in report.media.messages:
        lines.append(f"- {m}")
    lines.append("")

    lines.append("## 7. Agent 最小行为验收")
    lines.append("")
    for c in report.agent_behavior.details.get("cases", []):
        lines.append(f"- {c['label']}: status={c.get('status')}, has_field={c.get('has_recommended_assets_field')}, count={c.get('recommended_count')}, types={c.get('recommended_types')}")
    for m in report.agent_behavior.messages:
        lines.append(f"- {m}")
    lines.append("")

    lines.append("## 8. 测试结果")
    lines.append("")
    if report.tests.status == "skipped":
        lines.append("- 状态: 已跳过（--quick 模式不跑 pytest）")
    else:
        tests = report.tests.details
        lines.append(f"- 目标: {tests.get('targets', [])}")
        lines.append(f"- exit_code: {tests.get('exit_code', 'N/A')}")
        lines.append(f"- passed: {tests.get('passed', 'N/A')}")
        lines.append(f"- failed: {tests.get('failed', 'N/A')}")
        lines.append(f"- error: {tests.get('error', 'N/A')}")
        lines.append(f"- summary: {tests.get('summary', 'N/A')}")
        failed = tests.get("failed_tests", [])
        if failed:
            lines.append("- 失败用例:")
            for ft in failed:
                lines.append(f"  - {ft}")
    for m in report.tests.messages:
        lines.append(f"- {m}")
    lines.append("")

    lines.append("## 9. Git 提交卫生风险")
    lines.append("")
    git = report.git.details
    lines.append(f"- modified: {git.get('modified_count', 'N/A')}")
    lines.append(f"- deleted: {git.get('deleted_count', 'N/A')}")
    lines.append(f"- untracked: {git.get('untracked_count', 'N/A')}")
    high_risk = git.get("high_risk_paths", [])
    if high_risk:
        lines.append("- 高风险路径:")
        for p in high_risk:
            lines.append(f"  - {p}")
    for m in report.git.messages:
        lines.append(f"- {m}")
    lines.append("")

    lines.append("## 10. 自动派单建议")
    lines.append("")
    for i, d in enumerate(report.dispatch, 1):
        lines.append(f"{i}. **{d['window']}**")
        lines.append(f"   - 原因: {d['reason']}")
        lines.append(f"   - 建议动作: {d['action']}")
    lines.append("")

    lines.append("## 11. 下一步推荐命令")
    lines.append("")
    lines.append("```bash")
    lines.append(f"cd {BASE_DIR}")
    lines.append("# 快速巡检（不跑 pytest）")
    lines.append("python scripts/run_daily_quality_loop.py --quick")
    lines.append("")
    lines.append("# 完整巡检（含分层测试）")
    lines.append("python scripts/run_daily_quality_loop.py --with-tests")
    lines.append("")
    lines.append("# 如需检查 JST 外网连通性")
    lines.append("python scripts/run_daily_quality_loop.py --check-jst-live")
    lines.append("")
    lines.append("# 仅生成派单提示词（读取最近 JSON 报告）")
    lines.append("python scripts/run_daily_quality_loop.py --dispatch-only")
    lines.append("```")
    lines.append("")

    lines.append("## 12. 自动派单提示词")
    lines.append("")
    for key in ["window_1_deploy", "window_2_media", "window_3_agent", "window_4_rag", "window_5_test_hygiene"]:
        lines.append(report.dispatch_prompts.get(key, f"### {key}\n\n本轮无需处理。"))
        lines.append("")
    lines.append("")
    lines.append("---")
    lines.append("_本报告由 run_daily_quality_loop.py 自动生成，第一阶段只读，不自动修复/提交/审核。_")
    lines.append("_自动派单提示词由本地模板生成，未调用 DeepSeek/OpenAI/Kimi/GLM 等任何 LLM API。_")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_json_report(report: LoopReport, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "overall": report.overall,
        "overall_reasons": report.overall_reasons,
        "report_date": report.report_date,
        "generated_at": report.generated_at,
        "app_health": {
            "ok": report.app_health.ok,
            "status": report.app_health.status,
            "details": report.app_health.details,
            "messages": report.app_health.messages,
        },
        "jst": {
            "ok": report.jst.ok,
            "status": report.jst.status,
            "details": report.jst.details,
            "messages": report.jst.messages,
        },
        "rag": {
            "ok": report.rag.ok,
            "status": report.rag.status,
            "details": report.rag.details,
            "messages": report.rag.messages,
        },
        "media": {
            "ok": report.media.ok,
            "status": report.media.status,
            "details": report.media.details,
            "messages": report.media.messages,
        },
        "agent_behavior": {
            "ok": report.agent_behavior.ok,
            "status": report.agent_behavior.status,
            "details": report.agent_behavior.details,
            "messages": report.agent_behavior.messages,
        },
        "tests": {
            "ok": report.tests.ok,
            "status": report.tests.status,
            "details": report.tests.details,
            "messages": report.tests.messages,
        },
        "git": {
            "ok": report.git.ok,
            "status": report.git.status,
            "details": report.git.details,
            "messages": report.git.messages,
        },
        "dispatch": report.dispatch,
        "dispatch_prompts": report.dispatch_prompts,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 主流程 ──────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="客服 Copilot 每日 Loop Engineering 巡检")
    parser.add_argument("--quick", action="store_true", help="只跑健康、DB 统计、git 风险，不跑 pytest")
    parser.add_argument("--with-tests", action="store_true", help="跑分层测试")
    parser.add_argument("--output", default=None, help="Markdown 报告路径")
    parser.add_argument("--json-output", default=None, help="JSON 报告路径（可选）")
    parser.add_argument("--check-jst-live", action="store_true", help="默认不访问外网；加此参数才 live 调用 JST")
    parser.add_argument("--dispatch-only", action="store_true", help="只从最近 JSON 报告生成派单提示词，不重新跑巡检")
    args = parser.parse_args()

    output_md, output_json, report_date = _resolve_output_paths(args.output, args.json_output)

    if args.dispatch_only:
        return run_dispatch_only(json_path=args.json_output, output_md=args.output, output_json=None)

    report = LoopReport(report_date=report_date)

    print("[loop] 正在创建 Flask app...")
    app = _get_test_app()

    print("[loop] 1. 基础健康检查...")
    report.app_health = check_app_health(app)

    print("[loop] 2. JST 检查...")
    report.jst = check_jst_config(app)
    if args.check_jst_live:
        report.jst = check_jst_live()

    print("[loop] 3. RAG 状态检查...")
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        report.rag = check_rag_status(session)
        print("[loop] 4. 媒体素材状态检查...")
        report.media = check_media_status(session)
        usable_for_agent_count = report.media.details.get("usable_for_agent", 0)

        print("[loop] 5. Agent 最小行为验收...")
        report.agent_behavior = check_agent_behavior(app, session, usable_for_agent_count)
    finally:
        session.close()

    run_tests = not args.quick
    print(f"[loop] 6. 测试状态检查（run_tests={run_tests})...")
    report.tests = run_pytest_subset(run_tests=run_tests, extra_tests=args.with_tests)

    print("[loop] 7. Git 提交卫生检查...")
    report.git = check_git_hygiene()

    print("[loop] 8. 生成派单建议...")
    report.dispatch = build_dispatch_recommendations(report)

    print("[loop] 9. 计算总体结论...")
    report.overall, report.overall_reasons = compute_overall(report)

    print("[loop] 10. 生成自动派单提示词...")
    report.dispatch_prompts = build_dispatch_prompts(report)

    print(f"[loop] 11. 写入报告: {output_md}")
    write_markdown_report(report, output_md)
    if output_json:
        print(f"[loop] 写入 JSON: {output_json}")
        write_json_report(report, output_json)

    print(f"[loop] 完成。总体结论: {report.overall}")
    for d in report.dispatch:
        print(f"  -> {d['window']}: {d['reason']}")

    return 0 if report.overall != "Red" else 1


if __name__ == "__main__":
    sys.exit(main())
