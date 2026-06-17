"""
Shared test fixtures — autouse cleanup for module-level singletons.
"""

# 测试环境禁用 app.main.create_app() 启动的后台每日同步守护线程，
# 避免每个用 test_client 的测试都额外 spawn 一个 daemon 线程/子进程。
# 纯测试侧处理：把 worker 替换为 no-op，不改动 app 业务代码（避免与素材库窗口
# 在 app/main.py 上冲突）。必须在 conftest 导入阶段、早于任何 create_app 调用执行。
try:
    import app.main as _app_main  # noqa: E402
    _app_main._daily_sync_worker = lambda: None
except Exception:
    pass

import pytest


@pytest.fixture(autouse=True)
def _clear_global_state():
    """Clear module-level singleton caches between tests to prevent state leakage."""
    yield
    # Context store (conversation_context)
    try:
        from app.agent.context.context_store import context_store
        context_store.clear()
    except Exception:
        pass
    # Resolution cache (order_product_resolver)
    try:
        from app.agent.nodes.order_product_resolver import _RESOLUTION_CACHE
        _RESOLUTION_CACHE.clear()
    except Exception:
        pass
