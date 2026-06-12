"""
Shared test fixtures — autouse cleanup for module-level singletons.
"""

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
