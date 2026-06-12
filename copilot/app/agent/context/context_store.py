"""Small in-process conversation context store.

This is intentionally simple for the copilot MVP. It keeps context across
turns while the web process is alive and avoids storing private recipient
details or tokens.
"""

from __future__ import annotations

import threading
from copy import deepcopy


class ContextStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}

    def get(self, conversation_id: str) -> dict:
        with self._lock:
            return deepcopy(self._items.get(conversation_id, {}))

    def set(self, conversation_id: str, context: dict) -> None:
        with self._lock:
            self._items[conversation_id] = deepcopy(context)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


context_store = ContextStore()
