"""Deterministic compatibility check between a question and product context."""

from __future__ import annotations


_CATEGORY_TERMS = {
    "book_storage": (
        "绘本", "书本", "书籍", "图书", "书架", "绘本架", "书柜",
        "收纳架", "收纳柜", "置物架", "多层收纳架",
    ),
    "faucet": ("水龙头", "延长器", "导水槽", "洗浴配件"),
    "feeding": ("围兜", "餐椅", "餐具", "辅食", "喂养"),
    "pillow": ("防摔枕", "护头枕", "枕头"),
    "guardrail": ("床围栏", "床护栏", "围栏", "护栏"),
    "furniture_safety": ("防倾倒", "固定器", "家具固定"),
}


def evaluate_product_context(
    message: str,
    product_name: str = "",
    category_text: str = "",
) -> dict:
    """Return whether the customer's object conflicts with the current product."""
    query_categories = _categories(message)
    product_categories = _categories(f"{product_name} {category_text}")
    mismatch = bool(
        query_categories
        and product_categories
        and query_categories.isdisjoint(product_categories)
    )
    return {
        "mismatch": mismatch,
        "query_categories": sorted(query_categories),
        "product_categories": sorted(product_categories),
        "product_name": product_name,
        "category_text": category_text,
        "reason": (
            "question_product_category_conflict"
            if mismatch
            else "compatible_or_insufficient_category_signal"
        ),
    }


def _categories(text: str) -> set[str]:
    lowered = (text or "").lower()
    return {
        category
        for category, terms in _CATEGORY_TERMS.items()
        if any(term.lower() in lowered for term in terms)
    }
