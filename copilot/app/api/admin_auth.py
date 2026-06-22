"""Small role gate for ops/admin APIs.

This is intentionally header-based for the current admin console. It does not
replace a real login system.
"""

from __future__ import annotations

from flask import jsonify, request


def get_user_role() -> str:
    return str(request.headers.get("X-User-Role") or "operator").strip().lower() or "operator"


def require_supervisor():
    role = get_user_role()
    if role not in {"supervisor", "admin"}:
        return jsonify({"error": "forbidden", "required_role": "supervisor"}), 403
    return None


def require_admin():
    role = get_user_role()
    if role != "admin":
        return jsonify({"error": "forbidden", "required_role": "admin"}), 403
    return None
