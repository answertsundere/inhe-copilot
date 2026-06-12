"""
Flask 应用工厂 - 创建和配置 Flask 应用
"""

import os
import subprocess
import threading
import time
from datetime import datetime, timedelta

from flask import Flask

from app.config import BASE_DIR, KNOWLEDGE_DIR, KNOWLEDGE_DB_PATH


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
_DAILY_SYNC_HOUR = 8
_DAILY_SYNC_MINUTE = 57
_DAILY_SYNC_SCRIPT = os.path.join(BASE_DIR, "scripts", "sync_dingtalk_media.py")
_DAILY_SYNC_OUTPUT = os.path.join(BASE_DIR, "data", "dingtalk_media_report_daily.json")


def _daily_sync_worker():
    """后台线程：每天固定时间同步钉钉多维表媒体数据到商品库。"""
    # 首次启动时先等一会儿，让服务完全初始化
    time.sleep(30)

    while True:
        now = datetime.now()
        target = now.replace(
            hour=_DAILY_SYNC_HOUR,
            minute=_DAILY_SYNC_MINUTE,
            second=0,
            microsecond=0,
        )
        if target <= now:
            target += timedelta(days=1)

        sleep_seconds = (target - now).total_seconds()
        print(
            f"[DailySync] 下次钉钉媒体同步: {target.strftime('%Y-%m-%d %H:%M')}, "
            f"等待 {sleep_seconds / 3600:.1f} 小时"
        )
        time.sleep(sleep_seconds)

        # 执行同步
        try:
            print("[DailySync] 开始同步钉钉媒体数据...")
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
                print("[DailySync] 同步完成")
            else:
                print(f"[DailySync] 同步失败, returncode={result.returncode}")
                if result.stderr:
                    print(f"[DailySync] stderr: {result.stderr[:500]}")
        except Exception as exc:
            print(f"[DailySync] 同步异常: {exc}")


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

    print("正在加载数据仓库...")
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

    print(
        f"数据加载完成: 订单{_order_repo.count_orders()} "
        f"SKU{_product_repo.count_skus()} "
        f"商品{_product_repo.count_products()} "
        f"知识{len(_knowledge_repo.get_all())}条 "
        f"产品知识卡{_product_knowledge_repo.count()}张 "
        f"话术模板{_reply_template_repo.count()}条 "
        f"SOP场景{_sop_repo.count()}个"
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

    print("服务初始化完成!")


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

    print("实时查询服务初始化完成!")


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
    import app.models.kb_tables  # noqa: F401 - 注册新表
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
        print(f"Trace table init failed: {e}")

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

    # 让 /api/kb/knowledge/* 兼容 /api/knowledge/* 路由
    _clone_routes_under_prefix(app, "/api/knowledge/", "/api/kb/knowledge/")

    @app.route("/")
    def index():
        from flask import render_template, make_response
        resp = make_response(render_template("index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        return resp

    @app.route("/api-test")
    @app.route("/api-debug")
    def api_test():
        from flask import render_template, make_response, send_file
        try:
            return send_file(os.path.join(static_dir, "api_test.html"))
        except Exception:
            resp = make_response("API test page not found")
            resp.headers["Content-Type"] = "text/plain"
            return resp, 404

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

    @app.route("/kb-admin/")
    @app.route("/kb-admin/<path:subpath>")
    def kb_admin(subpath=""):
        """Serve Vue 3 knowledge base admin SPA"""
        import re
        from flask import make_response, send_file, send_from_directory
        kb_dir = os.path.join(BASE_DIR, "web", "static", "kb-admin")

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
    def knowledge_admin():
        from flask import render_template
        return render_template("knowledge_admin.html")

    @app.route("/settings")
    def settings_page():
        from flask import render_template
        return render_template("settings.html")

    @app.route("/graph")
    def graph_page():
        from flask import render_template
        return render_template("graph.html")

    @app.route("/copilot-panel")
    def copilot_panel():
        from flask import render_template
        return render_template("copilot_panel.html")

    # 启动后台每日同步线程（daemon=True 不会阻塞服务退出）
    threading.Thread(
        target=_daily_sync_worker,
        daemon=True,
        name="DailyDingTalkSync",
    ).start()

    return app
