"""
Bad Case API 路由

GET  /api/bad-cases              列表（分页+筛选）
GET  /api/bad-cases/<id>         详情
POST /api/bad-cases              手动创建
PATCH /api/bad-cases/<id>        更新标注
POST /api/bad-cases/<id>/mark-fixed   标记已修复
POST /api/bad-cases/<id>/verify       验证通过
POST /api/bad-cases/<id>/export-regression  导出回归测试 JSON
GET  /api/bad-cases/metrics      指标
"""

from flask import Blueprint, request, jsonify

bad_case_bp = Blueprint("bad_cases", __name__)

# Import constants for validation
from app.services.bad_case_service import FAILURE_TYPES, SEVERITY_LEVELS, STATUS_FLOW


def _get_store():
    from app.services.bad_case_service import BadCaseStore
    return BadCaseStore()


def _safe_int(val, default, min_val=1, max_val=100):
    """Parse int with validation. Returns None for invalid/non-integer values."""
    try:
        n = int(val)
    except (ValueError, TypeError):
        return None
    if n < min_val or n > max_val:
        return None
    return n


@bad_case_bp.route("/api/bad-cases", methods=["GET"])
def list_bad_cases():
    """分页列表。"""
    page = _safe_int(request.args.get("page", 1), 1)
    if page is None:
        return jsonify({"error": "page must be a positive integer"}), 400
    page_size = _safe_int(request.args.get("page_size", 20), 20, 1, 100)
    if page_size is None:
        return jsonify({"error": "page_size must be a positive integer"}), 400

    status = request.args.get("status", "")
    if status and status not in STATUS_FLOW:
        return jsonify({"error": f"invalid status, must be one of {STATUS_FLOW}"}), 400
    severity = request.args.get("severity", "")
    if severity and severity not in SEVERITY_LEVELS:
        return jsonify({"error": f"invalid severity, must be one of {SEVERITY_LEVELS}"}), 400
    failure_type = request.args.get("failure_type", "")
    if failure_type and failure_type not in FAILURE_TYPES:
        return jsonify({"error": f"invalid failure_type, must be one of {FAILURE_TYPES}"}), 400

    store = _get_store()
    result = store.query(
        status=status,
        failure_type=failure_type,
        severity=severity,
        scenario=request.args.get("scenario", ""),
        intent=request.args.get("intent", ""),
        tool_name=request.args.get("tool_name", ""),
        graph_version=request.args.get("graph_version", ""),
        prompt_version=request.args.get("prompt_version", ""),
        model_name=request.args.get("model_name", ""),
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
        page=page,
        page_size=page_size,
    )
    return jsonify(result)


@bad_case_bp.route("/api/bad-cases/metrics", methods=["GET"])
def bad_case_metrics():
    store = _get_store()
    return jsonify(store.get_metrics())


@bad_case_bp.route("/api/bad-cases/<case_id>", methods=["GET"])
def get_bad_case(case_id):
    store = _get_store()
    case = store.get_by_id(case_id)
    if not case:
        return jsonify({"error": "not found"}), 404
    return jsonify(case)


@bad_case_bp.route("/api/bad-cases", methods=["POST"])
def create_bad_case():
    data = request.get_json(silent=True) or {}
    # Validate fields
    if data.get("failure_type") and data["failure_type"] not in FAILURE_TYPES:
        return jsonify({"error": f"invalid failure_type"}), 400
    if data.get("severity") and data["severity"] not in SEVERITY_LEVELS:
        return jsonify({"error": f"invalid severity"}), 400
    if data.get("status") and data["status"] not in STATUS_FLOW:
        return jsonify({"error": f"invalid status"}), 400
    store = _get_store()
    case = store.create(data)
    return jsonify(case), 201


@bad_case_bp.route("/api/bad-cases/<case_id>", methods=["PATCH"])
def update_bad_case(case_id):
    data = request.get_json(silent=True) or {}
    # Validate status/failure_type/severity if provided
    if "status" in data and data["status"] not in STATUS_FLOW:
        return jsonify({"error": f"invalid status"}), 400
    if "failure_type" in data and data["failure_type"] not in FAILURE_TYPES:
        return jsonify({"error": f"invalid failure_type"}), 400
    if "severity" in data and data["severity"] not in SEVERITY_LEVELS:
        return jsonify({"error": f"invalid severity"}), 400

    store = _get_store()
    allowed_fields = {
        "failure_type", "failure_layer", "severity", "status",
        "expected_intent", "expected_tools_json", "root_cause",
        "fix_note", "reviewer", "regression_test_id",
        "expected_knowledge_entry_ids_json",
    }
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    case = store.update(case_id, updates)
    if not case:
        return jsonify({"error": "not found"}), 404
    return jsonify(case)


@bad_case_bp.route("/api/bad-cases/<case_id>/mark-fixed", methods=["POST"])
def mark_fixed(case_id):
    store = _get_store()
    case = store.update(case_id, {"status": "fixed"})
    if not case:
        return jsonify({"error": "not found"}), 404
    return jsonify(case)


@bad_case_bp.route("/api/bad-cases/<case_id>/verify", methods=["POST"])
def verify_bad_case(case_id):
    store = _get_store()
    case = store.update(case_id, {"status": "verified"})
    if not case:
        return jsonify({"error": "not found"}), 404
    return jsonify(case)


@bad_case_bp.route("/api/bad-cases/<case_id>/export-regression", methods=["POST"])
def export_regression(case_id):
    """导出回归测试 JSON 到 tests/golden_cases/bad_cases/。"""
    import json
    import os
    from app.config import BASE_DIR

    store = _get_store()
    case = store.get_by_id(case_id)
    if not case:
        return jsonify({"error": "not found"}), 404

    # Build expected from annotations
    expected_intent = case.get("expected_intent", "")
    expected_tools = []
    try:
        expected_tools = json.loads(case.get("expected_tools_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        pass

    # Check if expected fields are populated enough
    has_expectations = bool(expected_intent or expected_tools)
    if not has_expectations:
        return jsonify({
            "error": "regression_expectation_incomplete",
            "message": "至少需要填写 expected_intent 或 expected_tools_json 才能导出回归用例",
        }), 400

    conversation_history = []
    try:
        conversation_history = json.loads(case.get("conversation_history_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        pass

    context = {}
    try:
        context = json.loads(case.get("sidecar_context_json", "{}"))
    except (json.JSONDecodeError, TypeError):
        pass

    required_knowledge_entry_ids = []
    try:
        required_knowledge_entry_ids = json.loads(case.get("expected_knowledge_entry_ids_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        pass

    regression = {
        "case_id": case.get("id", ""),
        "name": f"Bad Case {case.get('id', '')}: {case.get('customer_message', '')[:50]}",
        "input": {
            "customer_message": case.get("customer_message", ""),
            "conversation_history": conversation_history,
            "context": context,
            "source": case.get("source", ""),
            "scenario": case.get("scenario", ""),
        },
        "expect": {
            "allowed_intents": [expected_intent] if expected_intent else [],
            "required_tools": expected_tools,
            "forbidden_tools": [],
            "required_knowledge_entry_ids": required_knowledge_entry_ids,
            "reply_must_contain": [],
            "reply_must_not_contain": [],
            "need_human_review": False,
            "max_duration_ms": 10000,
        },
        "versions": {
            "graph_version": case.get("graph_version", ""),
            "prompt_version": case.get("prompt_version", ""),
            "knowledge_version": case.get("knowledge_version", ""),
            "model_name": case.get("model_name", ""),
        },
    }

    # Export to tests/golden_cases/bad_cases/ (relative to project BASE_DIR)
    golden_dir = os.path.join(BASE_DIR, "tests", "golden_cases", "bad_cases")
    os.makedirs(golden_dir, exist_ok=True)
    filename = f"{case.get('id', 'unknown')}.json"
    filepath = os.path.join(golden_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(regression, f, ensure_ascii=False, indent=2)

    # Verify file was written
    if not os.path.exists(filepath):
        return jsonify({"error": "export_failed", "message": "File not written"}), 500

    store.update(case_id, {"regression_test_id": filepath})

    return jsonify({"ok": True, "regression": regression, "filepath": filepath})
