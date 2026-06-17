"""
Simulation API Routes — /api/simulation/*
"""

import json
import logging
import os
import glob as _glob

from flask import Blueprint, request, jsonify, send_file

simulation_bp = Blueprint("simulation", __name__)
logger = logging.getLogger(__name__)

_RESULTS_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "tests", "simulation_results",
))


def _get_run_dir(run_id: str) -> str:
    return os.path.join(_RESULTS_DIR, run_id)


@simulation_bp.route("/api/simulation/runs", methods=["GET"])
@simulation_bp.route("/api/simulation/runs/", methods=["GET"])
def list_runs():
    """List all simulation runs."""
    try:
        os.makedirs(_RESULTS_DIR, exist_ok=True)
        runs = []
        for d in sorted(os.listdir(_RESULTS_DIR)):
            config_path = os.path.join(_RESULTS_DIR, d, "run_config.json")
            summary_path = os.path.join(_RESULTS_DIR, d, "summary.json")
            if os.path.isdir(os.path.join(_RESULTS_DIR, d)):
                run_info = {"run_id": d}
                if os.path.exists(config_path):
                    try:
                        with open(config_path, "r", encoding="utf-8") as f:
                            run_info["config"] = json.load(f)
                    except Exception:
                        pass
                if os.path.exists(summary_path):
                    try:
                        with open(summary_path, "r", encoding="utf-8") as f:
                            run_info["summary"] = json.load(f)
                    except Exception:
                        pass
                runs.append(run_info)
        return jsonify({"runs": runs, "total": len(runs)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@simulation_bp.route("/api/simulation/runs/<run_id>", methods=["GET"])
@simulation_bp.route("/api/simulation/runs/<run_id>/", methods=["GET"])
def get_run_detail(run_id: str):
    """Get detailed run results."""
    run_dir = _get_run_dir(run_id)
    if not os.path.isdir(run_dir):
        return jsonify({"error": "run not found"}), 404

    result = {"run_id": run_id}
    for fname in ("run_config.json", "summary.json", "performance.json"):
        fpath = os.path.join(run_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    result[fname.replace(".json", "")] = json.load(f)
            except Exception:
                pass

    # Read turns (paginated)
    turns_path = os.path.join(run_dir, "turns.jsonl")
    if os.path.exists(turns_path):
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 50, type=int)
        page = max(1, page)
        page_size = max(1, min(200, page_size))
        turns = []
        with open(turns_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= (page - 1) * page_size and i < page * page_size:
                    try:
                        turns.append(json.loads(line.strip()))
                    except Exception:
                        pass
                if i >= page * page_size:
                    break
        result["turns"] = turns

    # Read failures
    failures_path = os.path.join(run_dir, "failures.jsonl")
    if os.path.exists(failures_path):
        failures = []
        with open(failures_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    failures.append(json.loads(line.strip()))
                except Exception:
                    pass
        result["failures_count"] = len(failures)
        result["failures"] = failures[:50]

    return jsonify(result)


@simulation_bp.route("/api/simulation/runs/<run_id>/turns", methods=["GET"])
def get_run_turns(run_id: str):
    """Get turns for a run, with optional filtering."""
    turns_path = os.path.join(_get_run_dir(run_id), "turns.jsonl")
    if not os.path.exists(turns_path):
        return jsonify({"error": "no turns data"}), 404

    customer_id = request.args.get("customer_id", "")
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 50, type=int)
    page_size = min(200, max(1, page_size))

    turns = []
    with open(turns_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                t = json.loads(line.strip())
                if customer_id and t.get("customer_id") != customer_id:
                    continue
                turns.append(t)
            except Exception:
                pass

    total = len(turns)
    start = (page - 1) * page_size
    return jsonify({
        "turns": turns[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@simulation_bp.route("/api/simulation/runs/<run_id>/failures", methods=["GET"])
def get_run_failures(run_id: str):
    """Get failures for a run."""
    failures_path = os.path.join(_get_run_dir(run_id), "failures.jsonl")
    if not os.path.exists(failures_path):
        return jsonify({"failures": [], "total": 0})

    failures = []
    with open(failures_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                failures.append(json.loads(line.strip()))
            except Exception:
                pass

    return jsonify({"failures": failures, "total": len(failures)})


@simulation_bp.route("/api/simulation/runs/<run_id>/report", methods=["GET"])
def get_run_report(run_id: str):
    """Get markdown report for a run."""
    report_path = os.path.join(_get_run_dir(run_id), "report.md")
    if not os.path.exists(report_path):
        return jsonify({"error": "no report"}), 404
    with open(report_path, "r", encoding="utf-8") as f:
        return jsonify({"report": f.read()})


@simulation_bp.route("/api/simulation/golden-candidates", methods=["GET"])
def list_golden_candidates():
    """List golden case candidates."""
    candidates_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "tests", "golden_cases", "simulated_customers", "candidates",
    ))
    if not os.path.isdir(candidates_dir):
        return jsonify({"candidates": [], "total": 0})

    candidates = []
    for fname in sorted(os.listdir(candidates_dir)):
        if fname.endswith(".json"):
            fpath = os.path.join(candidates_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    candidates.append(json.load(f))
            except Exception:
                pass
    return jsonify({"candidates": candidates, "total": len(candidates)})
