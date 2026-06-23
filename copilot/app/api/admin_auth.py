"""Small header-based role guard for operational APIs."""

from functools import wraps

from flask import jsonify, request


SUPERVISOR_ROLES = {"supervisor", "admin"}
ADMIN_ROLES = {"admin"}


def current_role() -> str:
    return str(request.headers.get("X-User-Role") or "operator").strip().lower() or "operator"


def current_user_name() -> str:
    return str(request.headers.get("X-User-Name") or "operator").strip() or "operator"


def require_supervisor(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_role() not in SUPERVISOR_ROLES:
            return jsonify({"error": "当前角色无权访问运营监控"}), 403
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_role() not in ADMIN_ROLES:
            return jsonify({"error": "当前角色无权访问管理操作"}), 403
        return fn(*args, **kwargs)

    return wrapper
