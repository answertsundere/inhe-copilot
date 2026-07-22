"""
Flask 应用工厂 - 创建和配置 Flask 应用
"""

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

from flask import Flask

from app.config import BASE_DIR, KNOWLEDGE_DIR, KNOWLEDGE_DB_PATH


logger = logging.getLogger(__name__)


# ============ 全局服务实例 ============
_order_repo = None
_product_repo = None
_knowledge_repo = None
_policy_repo = None
_product_knowledge_repo = None
_risk_service = None
_context_builder = None
_output_guard = None
_reply_service = None
_feedback_service = None
_review_queue_service = None
_reply_template_repo = None
_sop_repo = None
_data_quality_service = None
_quality_check_service = None
_live_jst_repo = None
_live_dingtalk_repo = None
_live_query_service = None


# ============ 后台每日同步钉钉媒体数据 ============
# 钉钉媒体 URL 签名有效期约 2 小时，因此每天按固定多个时间点同步。
_SYNC_TIMES = [(8, 57), (10, 57), (12, 57), (14, 57), (16, 57), (18, 57), (20, 57)]
_DAILY_SYNC_SCRIPT = os.path.join(BASE_DIR, "scripts", "sync_dingtalk_media.py")
_DAILY_SYNC_OUTPUT = os.path.join(BASE_DIR, "data", "dingtalk_media_report_daily.json")
_DAILY_SYNC_LOCK_DIR = os.path.join(BASE_DIR, "data", "daily_media_asset_sync.lockdir")
_DAILY_ASSET_SYNC_SCRIPT = os.path.join(BASE_DIR, "scripts", "sync_dingtalk_media_assets.py")
_DAILY_SYNC_THREAD_STARTED = False
_DAILY_SYNC_THREAD_LOCK = threading.Lock()
_DAILY_SYNC_WORKER_MUTEX_HANDLE = None

# 媒体 URL 自动保鲜
_MEDIA_REFRESH_THREAD_STARTED = False
_MEDIA_REFRESH_THREAD_LOCK = threading.Lock()
_MEDIA_REFRESH_INTERVAL_SECONDS = int(os.environ.get("COPILOT_MEDIA_REFRESH_INTERVAL", "1800"))
_MEDIA_REFRESH_THRESHOLD_MINUTES = int(os.environ.get("COPILOT_MEDIA_REFRESH_THRESHOLD", "30"))


def _daily_sync_worker():
    """后台线程：按固定多个时间点同步钉钉多维表媒体数据到商品库。"""
    # 首次启动时先等一会儿，让服务完全初始化
    time.sleep(30)

    if _env_bool("COPILOT_DAILY_MEDIA_SYNC_ON_STARTUP", True):
        _run_media_asset_sync_once("startup")

    while True:
        now = datetime.now()
        next_time = None
        for hour, minute in _SYNC_TIMES:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target > now:
                next_time = target
                break
        if next_time is None:
            # 今天所有时间点都已过，安排到明天第一个时间点
            hour, minute = _SYNC_TIMES[0]
            next_time = (now + timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

        sleep_seconds = (next_time - now).total_seconds()
        logger.info(
            "[DailySync] 下次钉钉媒体同步: %s, 等待 %.1f 小时",
            next_time.strftime('%Y-%m-%d %H:%M'),
            sleep_seconds / 3600,
        )
        time.sleep(sleep_seconds)

        # 执行同步
        try:
            logger.info("[DailySync] 开始同步钉钉媒体数据...")
            result = subprocess.run(
                [
                    "python",
                    _DAILY_SYNC_SCRIPT,
                    "--update-db",
                    "--output",
                    _DAILY_SYNC_OUTPUT,
                ],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=BASE_DIR,
            )
            if result.returncode == 0:
                logger.info("[DailySync] 同步完成")
                # 同步成功后，把最新报告导入正式素材库 kb_media_asset
                # （已审核素材审核状态保持不变；新素材默认待审核）
                try:
                    media_import_script = os.path.join(BASE_DIR, "scripts", "sync_dingtalk_media_assets.py")
                    if os.path.exists(_DAILY_SYNC_OUTPUT) and os.path.exists(media_import_script):
                        imp = subprocess.run(
                            ["python", media_import_script, "--report", _DAILY_SYNC_OUTPUT, "--apply"],
                            capture_output=True, text=True, timeout=600, cwd=BASE_DIR,
                        )
                        if imp.returncode == 0:
                            logger.info("[DailySync] 素材库导入完成")
                        else:
                            logger.warning("[DailySync] 素材库导入失败, returncode=%s", imp.returncode)
                except Exception as imp_exc:
                    logger.warning("[DailySync] 素材库导入异常: %s", imp_exc)
            else:
                logger.warning("[DailySync] 同步失败, returncode=%s", result.returncode)
                if result.stderr:
                    logger.warning("[DailySync] stderr: %s", result.stderr[:500])
        except Exception as exc:
            logger.error("[DailySync] 同步异常: %s", exc)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _acquire_daily_sync_lock(reason: str) -> bool:
    os.makedirs(os.path.dirname(_DAILY_SYNC_LOCK_DIR), exist_ok=True)
    try:
        os.mkdir(_DAILY_SYNC_LOCK_DIR)
        return True
    except FileExistsError:
        try:
            age_seconds = time.time() - os.path.getmtime(_DAILY_SYNC_LOCK_DIR)
            if age_seconds > 7200:
                os.rmdir(_DAILY_SYNC_LOCK_DIR)
                os.mkdir(_DAILY_SYNC_LOCK_DIR)
                logger.warning("[DailySync] removed stale lock reason=%s age=%.0fs", reason, age_seconds)
                return True
        except OSError:
            pass
        logger.info("[DailySync] another media asset sync is running; skip reason=%s", reason)
        return False


def _release_daily_sync_lock() -> None:
    try:
        os.rmdir(_DAILY_SYNC_LOCK_DIR)
    except OSError:
        pass


def _acquire_daily_sync_worker_mutex() -> bool:
    """Allow only one run_prod.py process to start the resident worker."""
    global _DAILY_SYNC_WORKER_MUTEX_HANDLE
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Global\\INHE_COPILOT_DAILY_MEDIA_SYNC_WORKER")
        if not handle:
            return True
        already_exists = kernel32.GetLastError() == 183
        if already_exists:
            logger.info("[DailySync] worker mutex already exists; skip worker in this process")
            return False
        _DAILY_SYNC_WORKER_MUTEX_HANDLE = handle
        return True
    except Exception as exc:
        logger.warning("[DailySync] worker mutex unavailable, using process-local guard: %s", exc)
        return True


def _run_media_asset_sync_once(reason: str) -> bool:
    """Refresh DingTalk media and apply it into kb_media_asset."""
    if not os.path.exists(_DAILY_ASSET_SYNC_SCRIPT):
        logger.warning("[DailySync] media asset sync script not found: %s", _DAILY_ASSET_SYNC_SCRIPT)
        return False
    if not _acquire_daily_sync_lock(reason):
        return False

    cmd = [
        sys.executable,
        _DAILY_ASSET_SYNC_SCRIPT,
        "--refresh",
        "--apply",
        "--auto-approve-low-risk",
        "--daily-output",
        _DAILY_SYNC_OUTPUT,
    ]
    try:
        logger.info("[DailySync] media asset sync start reason=%s", reason)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1200,
            cwd=BASE_DIR,
        )
        if result.returncode == 0:
            logger.info("[DailySync] media asset sync completed reason=%s", reason)
            if result.stdout:
                logger.info("[DailySync] stdout: %s", result.stdout[-1000:])
            return True

        logger.warning("[DailySync] media asset sync failed reason=%s returncode=%s", reason, result.returncode)
        if result.stderr:
            logger.warning("[DailySync] stderr: %s", result.stderr[-1000:])
        if result.stdout:
            logger.warning("[DailySync] stdout: %s", result.stdout[-1000:])
        return False
    finally:
        _release_daily_sync_lock()


def _start_daily_sync_thread():
    """Start the resident DingTalk media sync worker once per process."""
    global _DAILY_SYNC_THREAD_STARTED
    if not _env_bool("COPILOT_DAILY_MEDIA_SYNC_ENABLED", True):
        logger.info("[DailySync] disabled by COPILOT_DAILY_MEDIA_SYNC_ENABLED")
        return
    if (
        "hermes-agent" in sys.executable.lower()
        and _env_bool("COPILOT_DAILY_MEDIA_SYNC_SKIP_HERMES", True)
    ):
        logger.info("[DailySync] skipped in hermes-agent interpreter")
        return
    with _DAILY_SYNC_THREAD_LOCK:
        if _DAILY_SYNC_THREAD_STARTED:
            return
        if not _acquire_daily_sync_worker_mutex():
            return
        threading.Thread(
            target=_daily_sync_worker,
            daemon=True,
            name="DailyDingTalkMediaAssetSync",
        ).start()
        _DAILY_SYNC_THREAD_STARTED = True
        logger.info("[DailySync] resident media asset sync worker started")


def _media_url_auto_refresh_worker():
    """后台线程：检测即将过期的媒体 URL 并自动刷新。"""
    time.sleep(60)  # 等服务启动稳定后再开始检测
    from app.db import SessionLocal
    from app.models.kb_tables import KBMediaAsset
    from sqlalchemy import or_

    while True:
        try:
            threshold = datetime.utcnow() + timedelta(minutes=_MEDIA_REFRESH_THRESHOLD_MINUTES)
            db = SessionLocal()
            try:
                count = (
                    db.query(KBMediaAsset)
                    .filter(
                        or_(
                            KBMediaAsset.url_expires_at.is_(None),
                            KBMediaAsset.url_expires_at <= threshold,
                            KBMediaAsset.refresh_status == "needs_refresh",
                        )
                    )
                    .count()
                )
            finally:
                db.close()

            if count > 0:
                logger.info("[MediaRefresh] 发现 %s 条素材即将过期或已过期，触发自动刷新", count)
                _run_media_asset_sync_once("auto-refresh")
            else:
                logger.debug("[MediaRefresh] 暂无即将过期的素材")
        except Exception as exc:
            logger.error("[MediaRefresh] 自动检测异常: %s", exc)

        time.sleep(_MEDIA_REFRESH_INTERVAL_SECONDS)


def _start_media_auto_refresh_thread():
    """Start the resident media URL auto-refresh worker once per process."""
    global _MEDIA_REFRESH_THREAD_STARTED
    if not _env_bool("COPILOT_MEDIA_AUTO_REFRESH_ENABLED", True):
        logger.info("[MediaRefresh] disabled by COPILOT_MEDIA_AUTO_REFRESH_ENABLED")
        return
    with _MEDIA_REFRESH_THREAD_LOCK:
        if _MEDIA_REFRESH_THREAD_STARTED:
            return
        threading.Thread(
            target=_media_url_auto_refresh_worker,
            daemon=True,
            name="MediaUrlAutoRefresh",
        ).start()
        _MEDIA_REFRESH_THREAD_STARTED = True
        logger.info("[MediaRefresh] resident media URL auto-refresh worker started")


def _init_repos():
    """初始化所有仓库"""
    global _order_repo, _product_repo, _knowledge_repo, _policy_repo, _product_knowledge_repo
    global _reply_template_repo, _sop_repo

    if _order_repo is not None:
        return

    from app.repositories.json_order_repository import JsonOrderRepository
    from app.repositories.json_product_repository import JsonProductRepository
    from app.repositories.file_knowledge_repository import FileKnowledgeRepository
    from app.repositories.file_policy_repository import FilePolicyRepository
    from app.repositories.product_knowledge_repository import ProductKnowledgeRepository
    from app.repositories.reply_template_repository import ReplyTemplateRepository
    from app.repositories.sop_repository import SOPRepository

    _order_repo = JsonOrderRepository()
    _product_repo = JsonProductRepository()
    _knowledge_repo = FileKnowledgeRepository()
    _policy_repo = FilePolicyRepository()

    logger.info("正在加载数据仓库...")
    _order_repo.load()
    _product_repo.load()
    _knowledge_repo.load()
    _policy_repo.load()

    _product_knowledge_repo = ProductKnowledgeRepository(knowledge_dir=KNOWLEDGE_DIR)
    _product_knowledge_repo.load()

    _reply_template_repo = ReplyTemplateRepository(knowledge_dir=KNOWLEDGE_DIR)
    _reply_template_repo.load()

    _sop_repo = SOPRepository(knowledge_dir=KNOWLEDGE_DIR)
    _sop_repo.load()

    logger.info(
        "数据加载完成: 订单%s SKU%s 商品%s 知识%s条 产品知识卡%s张 话术模板%s条 SOP场景%s个",
        _order_repo.count_orders(),
        _product_repo.count_skus(),
        _product_repo.count_products(),
        len(_knowledge_repo.get_all()),
        _product_knowledge_repo.count(),
        _reply_template_repo.count(),
        _sop_repo.count(),
    )


def _init_services():
    """初始化所有服务"""
    global _risk_service, _context_builder, _output_guard, _reply_service
    global _feedback_service, _review_queue_service
    global _data_quality_service, _quality_check_service

    _init_repos()

    if _risk_service is not None:
        return

    from app.services.risk_service import RiskService
    from app.services.context_builder import ContextBuilder
    from app.services.output_guard import OutputGuard
    from app.services.reply_service import ReplyService
    from app.services.feedback_service import FeedbackService
    from app.services.review_queue_service import ReviewQueueService
    from app.config import REVIEW_QUEUE_FILE
    from app.services.data_quality_service import DataQualityService
    from app.services.quality_check_service import QualityCheckService

    _risk_service = RiskService(_policy_repo)
    _data_quality_service = DataQualityService()
    _data_quality_service.load()
    _quality_check_service = QualityCheckService(policy_repo=_policy_repo)
    _context_builder = ContextBuilder(
        order_repo=_order_repo,
        product_repo=_product_repo,
        knowledge_repo=_knowledge_repo,
        product_knowledge_repo=_product_knowledge_repo,
        reply_template_repo=_reply_template_repo,
        sop_repo=_sop_repo,
        data_quality_service=_data_quality_service,
    )
    _output_guard = OutputGuard(_policy_repo)
    _feedback_service = FeedbackService()
    _review_queue_service = ReviewQueueService(filepath=REVIEW_QUEUE_FILE)

    forbidden_claims = _policy_repo.get_forbidden_claims()
    _reply_service = ReplyService(
        risk_service=_risk_service,
        context_builder=_context_builder,
        output_guard=_output_guard,
        forbidden_claims=forbidden_claims,
        review_queue_service=_review_queue_service,
        quality_check_service=_quality_check_service,
    )

    logger.info("服务初始化完成!")


def _init_live_query():
    """初始化实时查询服务"""
    global _live_jst_repo, _live_dingtalk_repo, _live_query_service

    if _live_query_service is not None:
        return

    from app.repositories.live_jst_repository import LiveJSTRepository
    from app.repositories.live_dingtalk_repository import LiveDingTalkRepository
    from app.services.live_query_service import LiveQueryService

    _live_jst_repo = LiveJSTRepository()
    _live_dingtalk_repo = LiveDingTalkRepository()
    _live_query_service = LiveQueryService(_live_jst_repo, _live_dingtalk_repo)

    logger.info("实时查询服务初始化完成!")


# ============ Getter 函数 ============


def get_order_repo():
    _init_repos()
    return _order_repo


def get_product_repo():
    _init_repos()
    return _product_repo


def get_knowledge_repo():
    _init_repos()
    return _knowledge_repo


def get_policy_repo():
    _init_repos()
    return _policy_repo


def get_product_knowledge_repo():
    _init_repos()
    return _product_knowledge_repo


def get_risk_service():
    _init_services()
    return _risk_service


def get_reply_service():
    _init_services()
    return _reply_service


def get_feedback_service():
    _init_services()
    return _feedback_service


def get_review_queue_service():
    _init_services()
    return _review_queue_service


def get_output_guard():
    _init_services()
    return _output_guard


def get_live_query_service():
    _init_live_query()
    return _live_query_service


def get_live_jst_repo():
    _init_live_query()
    return _live_jst_repo


def get_live_dingtalk_repo():
    _init_live_query()
    return _live_dingtalk_repo


def get_data_quality_service():
    _init_services()
    return _data_quality_service


def get_quality_check_service():
    _init_services()
    return _quality_check_service


def get_reply_template_repo():
    _init_repos()
    return _reply_template_repo


def get_sop_repo():
    _init_repos()
    return _sop_repo


# ============ 数据库初始化 ============


def _init_db():
    """初始化知识库数据库"""
    from app.db import init_db
    import app.models.eval_tables  # noqa: F401 - register evaluation replay tables
    import app.models.kb_tables  # noqa: F401 - 注册新表
    import app.models.product_media_observation  # noqa: F401 - shadow review staging tables
    db_dir = os.path.dirname(KNOWLEDGE_DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    init_db()


# ============ Flask 应用工厂 ============


def _clone_routes_under_prefix(app, src_prefix, dst_prefix):
    """克隆 src_prefix 下的路由到 dst_prefix，复用同一个 view 函数。
    用于让 /api/kb/knowledge/* 兼容已有的 /api/knowledge/* 路由。"""
    with app.app_context():
        for rule in list(app.url_map.iter_rules()):
            if rule.rule.startswith(src_prefix):
                new_url = dst_prefix + rule.rule[len(src_prefix):]
                view_func = app.view_functions.get(rule.endpoint)
                if view_func is None:
                    continue
                methods = list(rule.methods - {"HEAD", "OPTIONS"})
                if not methods:
                    continue
                app.add_url_rule(
                    new_url,
                    endpoint=f"_alias_{rule.endpoint}",
                    view_func=view_func,
                    methods=methods,
                )


def create_app():
    """创建 Flask 应用"""
    _init_db()
    _init_services()

    # Initialize trace tables (idempotent)
    try:
        from app.tracing.repository import init_trace_tables
        init_trace_tables()
    except Exception as e:
        logger.warning("Trace table init failed: %s", e)

    template_dir = os.path.join(BASE_DIR, "web", "templates")
    static_dir = os.path.join(BASE_DIR, "web", "static")

    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=static_dir,
    )

    # WSGI middleware: transparently strip /ask prefix for Cloudflare Tunnel
    _original_wsgi = app.wsgi_app

    def _strip_ask(environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path.startswith("/ask/"):
            environ["PATH_INFO"] = path[4:]
        elif path == "/ask":
            environ["PATH_INFO"] = "/"
        return _original_wsgi(environ, start_response)

    app.wsgi_app = _strip_ask

    from app.api.analyze_routes import analyze_bp
    from app.api.order_routes import order_bp
    from app.api.feedback_routes import feedback_bp
    from app.api.health_routes import health_bp
    from app.api.live_query_routes import live_query_bp
    from app.api.review_routes import review_bp
    from app.api.knowledge_routes import knowledge_bp
    from app.api.quality_routes import quality_bp
    from app.api.config_routes import config_bp
    from app.api.metrics_routes import metrics_bp
    from app.api.copilot_routes import copilot_bp
    from app.api.sidecar_routes import sidecar_bp
    from app.api.kb_admin_routes import kb_admin_bp
    from app.api.bad_case_routes import bad_case_bp
    from app.api.runtime_routes import runtime_bp
    from app.api.trace_routes import trace_api_bp
    from app.api.simulation_routes import simulation_bp
    from app.api.media_routes import media_bp
    from app.api.product_media_observation_routes import product_media_observation_bp
    from app.api.training_sample_routes import training_sample_bp
    from app.api.real_accuracy_label_routes import real_accuracy_label_bp
    from app.api.eval_routes import eval_bp
    from app.api.material_review_routes import material_review_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(analyze_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(live_query_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(quality_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(copilot_bp)
    app.register_blueprint(sidecar_bp)
    app.register_blueprint(kb_admin_bp)
    app.register_blueprint(bad_case_bp)
    app.register_blueprint(runtime_bp)
    app.register_blueprint(trace_api_bp)
    app.register_blueprint(simulation_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(product_media_observation_bp)
    app.register_blueprint(training_sample_bp)
    app.register_blueprint(real_accuracy_label_bp)
    app.register_blueprint(eval_bp)
    app.register_blueprint(material_review_bp)

    from app.api.admin_auth import install_admin_access_control
    install_admin_access_control(app)

    # 让 /api/kb/knowledge/* 兼容 /api/knowledge/* 路由
    _clone_routes_under_prefix(app, "/api/knowledge/", "/api/kb/knowledge/")
    # 让 kb-admin（base=/api/kb）也能访问素材库接口
    _clone_routes_under_prefix(app, "/api/media-assets/", "/api/kb/media-assets/")

    @app.route("/real-test")
    def real_test_panel():
        import json
        from flask import render_template, make_response

        cases_path = os.path.join(BASE_DIR, "data", "premium_manual_cases.json")
        fallback_path = os.path.abspath(os.path.join(
            BASE_DIR,
            "..",
            "outputs",
            "manual_test_set",
            "real_jst_demo",
            "real_jst_demo_test_results.json",
        ))
        data = {"summary": {"total": 0, "passed": 0}, "cases": []}
        for path in (cases_path, fallback_path):
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if "cases" in loaded:
                data = loaded
            else:
                data = {
                    "summary": loaded.get("summary", {}),
                    "cases": loaded.get("results", []),
                }
            break

        resp = make_response(render_template(
            "real_test_panel.html",
            cases_json=json.dumps(data.get("cases", []), ensure_ascii=False),
            summary_json=json.dumps(data.get("summary", {}), ensure_ascii=False),
        ))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        return resp

    @app.route("/")
    @app.route("/products")
    @app.route("/media-observation-review")
    @app.route("/shop-rules")
    @app.route("/qa")
    @app.route("/reviews")
    @app.route("/training-samples")
    @app.route("/real-accuracy-labels")
    @app.route("/service-rules")
    @app.route("/ai-updates")
    @app.route("/quality-replay")
    @app.route("/sop")
    @app.route("/cases")
    @app.route("/traces")
    @app.route("/rag")
    @app.route("/health")
    @app.route("/media")
    @app.route("/guide")
    def ask_spa():
        """Serve Vue SPA routes under /ask/."""
        from flask import make_response, send_file

        kb_dir = os.path.join(BASE_DIR, "web", "static", "kb-admin")
        index_html = os.path.join(kb_dir, "index.html")
        if os.path.exists(index_html):
            resp = make_response(send_file(index_html))
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        return "KB Admin frontend not built", 404

    @app.route("/assets/<path:subpath>")
    def kb_admin_assets(subpath):
        import re
        from flask import make_response, send_from_directory

        kb_dir = os.path.join(BASE_DIR, "web", "static", "kb-admin")
        asset_path = f"assets/{subpath}"
        file_path = os.path.join(kb_dir, asset_path)
        if not os.path.isfile(file_path):
            return "Asset not found", 404

        resp = make_response(send_from_directory(kb_dir, asset_path))
        if re.search(r"assets/[^/]+-[a-zA-Z0-9_-]{6,}\.\w+$", asset_path):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    @app.route("/favicon.svg")
    def kb_admin_favicon():
        from flask import make_response, send_from_directory

        kb_dir = os.path.join(BASE_DIR, "web", "static", "kb-admin")
        if not os.path.isfile(os.path.join(kb_dir, "favicon.svg")):
            return "Asset not found", 404
        resp = make_response(send_from_directory(kb_dir, "favicon.svg"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    @app.route("/kb-admin/")
    @app.route("/kb-admin/<path:subpath>")
    def kb_admin(subpath=""):
        """Serve Vue 3 knowledge base admin SPA"""
        import re
        from flask import make_response, redirect, send_file, send_from_directory
        kb_dir = os.path.join(BASE_DIR, "web", "static", "kb-admin")

        legacy_static = subpath.startswith("assets/") or subpath in {"favicon.svg"}
        if not legacy_static:
            target = "/ask/"
            if subpath:
                target += subpath
            return redirect(target, code=302)

        # If subpath points to a real file (js/css/images), serve it directly
        if subpath:
            file_path = os.path.join(kb_dir, subpath)
            if os.path.isfile(file_path):
                resp = make_response(send_from_directory(kb_dir, subpath))
                # Hashed assets (e.g. assets/index-abc123.js) get long-lived cache
                if re.search(r"assets/[^/]+-[a-zA-Z0-9]{6,}\.\w+$", subpath):
                    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                else:
                    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                return resp

        # Otherwise serve index.html (SPA client-side routing)
        index_html = os.path.join(kb_dir, "index.html")
        if os.path.exists(index_html):
            resp = make_response(send_file(index_html))
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        return "KB Admin frontend not built", 404

    @app.route("/knowledge-admin")
    def knowledge_admin_redirect():
        """旧版后台入口已废弃，重定向到新版 Vue SPA"""
        from flask import redirect
        return redirect("/ask/", code=302)

    @app.route("/settings")
    def settings_page():
        from flask import render_template
        return render_template("settings.html")

    @app.route("/copilot-panel")
    def copilot_panel():
        from flask import render_template
        return render_template("copilot_panel.html")

    @app.route("/simulation-runs")
    def simulation_runs_page():
        from flask import render_template, make_response
        resp = make_response(render_template("simulation_runs.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        return resp

    @app.route("/traces")
    def traces_page():
        from flask import render_template, make_response
        resp = make_response(render_template("traces.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        return resp

    @app.route("/bad-cases")
    def bad_cases_page():
        from flask import render_template, make_response
        resp = make_response(render_template("bad_cases.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        return resp

    # 启动后台每日同步线程（daemon=True 不会阻塞服务退出）
    from app.db import KNOWLEDGE_DB_QUERY_ONLY
    if KNOWLEDGE_DB_QUERY_ONLY:
        logger.info("Formal knowledge query-only mode: writable background workers disabled")
    else:
        _start_daily_sync_thread()
        _start_media_auto_refresh_thread()

    return app
