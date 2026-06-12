"""
Simulated Customer Runner — main evaluation harness.

Runs simulated customers through the analysis pipeline (service or HTTP mode),
evaluates each turn, and produces detailed reports.

Usage:
    python -m tests.simulated_customer_runner [options]

Modes:
    --mode service   Call execute_analysis() directly (default)
    --mode http      Call POST /api/analyze via HTTP

Options:
    --customer C001,C002   Run specific customers only
    --scenario logistics   Filter by scenario
    --priority P0          Filter by priority
    --limit 10             Max customers to run
    --resume run_id        Resume interrupted run
    --run-id my_run        Custom run ID
    --offline              Use fixture data instead of live DB/API
    --live-jst             Use live JST queries (overrides --offline for JST)
    --base-url URL         Base URL for HTTP mode (default http://localhost:5000)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CUSTOMERS_FILE = Path(__file__).resolve().parent / "simulated_customers_50.json"
RESULTS_DIR = Path(__file__).resolve().parent / "simulation_results"

# Fields that must NEVER be sent to the analysis agent (leak prevention)
LEAK_FIELDS = frozenset({
    "expected_intent", "expected_strategy", "expected_tools",
    "traps", "pass_criteria", "test_goal",
})

# Maximum turns per customer (safety limit)
MAX_TURNS_PER_CUSTOMER = 25

# Bad case / golden case directories
GOLDEN_CASES_DIR = Path(__file__).resolve().parent / "golden_cases" / "simulated_customers"
CANDIDATES_DIR = GOLDEN_CASES_DIR / "candidates"
REVIEWED_DIR = GOLDEN_CASES_DIR / "reviewed"
EXPORTED_DIR = GOLDEN_CASES_DIR / "exported"

# Failure type classification
FAILURE_TYPES = [
    "intent_error",
    "required_tool_missing",
    "forbidden_tool_called",
    "risk_missed",
    "unsupported_claim",
    "context_memory_error",
    "rag_miss",
    "timeout",
    "api_error",
    "trap_violation",
]


# ---------------------------------------------------------------------------
# Customer loading and filtering
# ---------------------------------------------------------------------------

def load_customers(filepath: Path = CUSTOMERS_FILE) -> list[dict]:
    """Load simulated customers from JSON file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("customers", [])
    except FileNotFoundError:
        logger.error("Customers file not found: %s", filepath)
        return []
    except json.JSONDecodeError as e:
        logger.error("Customers file JSON error: %s", e)
        return []


def filter_customers(
    customers: list[dict],
    customer_ids: list[str] | None = None,
    scenario: str | None = None,
    priority: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Filter customers by criteria."""
    filtered = customers

    if customer_ids:
        id_set = set(customer_ids)
        filtered = [c for c in filtered if c.get("id") in id_set]

    if scenario:
        filtered = [c for c in filtered if c.get("scenario") == scenario]

    if priority:
        filtered = [c for c in filtered if c.get("priority") == priority]

    if limit and limit > 0:
        filtered = filtered[:limit]

    return filtered


# ---------------------------------------------------------------------------
# Safe payload construction
# ---------------------------------------------------------------------------

def build_safe_payload(
    customer: dict,
    turn: dict,
    conversation_id: str,
    conversation_history: list[dict],
    offline: bool = False,
    live_jst: bool = False,
) -> dict:
    """Build a safe payload for the analysis service.

    CRITICAL: Never include expected_* fields, traps, or pass_criteria
    in the payload — these are evaluation-only data.
    """
    # Extract customer message
    customer_message = turn.get("msg", "")

    # Try to extract order_id and tracking_no from the message
    order_id = _extract_order_id_from_msg(customer_message)
    tracking_no = _extract_tracking_no_from_msg(customer_message)

    # Extract product name from customer tags/dialogue context
    product_name = _extract_product_from_customer(customer, customer_message)

    # Build copilot context if offline
    copilot_context = None
    if offline and not live_jst:
        from tests.simulation.fixture_service import inject_fixture_context
        copilot_context = inject_fixture_context(
            customer_message=customer_message,
            scenario=customer.get("scenario", ""),
        )
    elif live_jst:
        # In live-JST mode, provider is jushuitan_live
        # The pipeline will call real JST API
        copilot_context = {
            "provider": "jushuitan_live",
            "scenario": customer.get("scenario", ""),
        }

    # Build conversation history context for multi-turn
    if conversation_history:
        if copilot_context is None:
            copilot_context = {}
        copilot_context["conversation_history"] = _build_conversation_summary(
            conversation_history
        )

    return {
        "customer_message": customer_message,
        "order_id": order_id,
        "tracking_no": tracking_no,
        "conversation_id": conversation_id,
        "product_name": product_name,
        "copilot_context": copilot_context,
        "source": "simulation",
        "scenario": customer.get("scenario", ""),
    }


def _build_conversation_summary(history: list[dict]) -> list[dict]:
    """Build a safe conversation summary from previous turns."""
    summary = []
    for entry in history:
        item = {
            "turn": entry.get("turn", 0),
            "customer_message": entry.get("customer_message", ""),
            "suggested_reply": entry.get("suggested_reply", ""),
            "intent": entry.get("intent", ""),
        }
        summary.append(item)
    return summary


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def _gen_run_id() -> str:
    """Generate a unique run ID."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"sim_{ts}_{short_uuid}"


def _gen_conversation_id(customer_id: str, run_id: str) -> str:
    """Generate a unique conversation ID per customer per run."""
    return f"conv_{run_id}_{customer_id}"


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_order_id_from_msg(msg: str) -> str:
    """Extract order ID from customer message."""
    import re
    patterns = [
        r"订单[号]?[:：\s]*(\d{10,20})",
        r"订单\s*(\d{10,20})",
    ]
    for pat in patterns:
        m = re.search(pat, msg)
        if m:
            return m.group(1)
    return ""


def _extract_tracking_no_from_msg(msg: str) -> str:
    """Extract tracking number from customer message."""
    import re
    patterns = [
        r"单号[:：\s]*(\w+)",
        r"(SF\d{10,})",
        r"(ZT\d{10,})",
        r"(DB\d{10,})",
    ]
    for pat in patterns:
        m = re.search(pat, msg)
        if m:
            return m.group(1)
    return ""


def _extract_product_from_customer(customer: dict, msg: str) -> str:
    """Extract product name from customer context."""
    tags = customer.get("tags", [])
    product_keywords = {
        "尺寸咨询": "爬行垫",
        "安全材质": "爬行垫",
        "产品对比": "爬行垫",
        "催发货": "",
        "改地址": "",
        "物流停滞": "",
        "签收异常": "",
        "换货": "爬行垫",
        "退货": "爬行垫",
        "补发": "游戏围栏",
        "破损": "爬行垫",
        "安装": "游戏围栏",
        "安全投诉": "游戏围栏",
        "送礼": "爬行垫+围栏套装",
        "定制尺寸": "爬行垫",
        "材质过敏": "爬行垫",
        "加急发货": "爬行垫",
        "轻便": "爬行垫",
        "简单安装": "游戏围栏",
        "低价": "爬行垫",
        "新品": "游戏围栏",
    }
    for tag in tags:
        if tag in product_keywords:
            return product_keywords[tag]

    # Fallback: check message for product references
    for kw, product in [("垫", "爬行垫"), ("围栏", "游戏围栏"), ("收纳", "收纳柜")]:
        if kw in msg:
            return product

    return ""


# ---------------------------------------------------------------------------
# Analysis execution — service mode
# ---------------------------------------------------------------------------

def run_service_analysis(payload: dict) -> dict:
    """Execute analysis by calling execute_analysis() directly."""
    try:
        from app.main import create_app, get_reply_service
        from app.services.analysis_execution_service import execute_analysis

        # Ensure app is initialized
        app = create_app()

        with app.app_context():
            reply_service = get_reply_service()
            result = execute_analysis(
                reply_service=reply_service,
                customer_message=payload["customer_message"],
                order_id=payload.get("order_id", ""),
                tracking_no=payload.get("tracking_no", ""),
                conversation_id=payload.get("conversation_id", "default"),
                product_name=payload.get("product_name", ""),
                copilot_context=payload.get("copilot_context"),
                source=payload.get("source", "simulation"),
                scenario=payload.get("scenario", ""),
            )
            return result

    except Exception as e:
        logger.error("Service mode analysis failed: %s", e, exc_info=True)
        return {"error": str(e), "suggested_reply": "", "intent": ""}


# ---------------------------------------------------------------------------
# Analysis execution — HTTP mode
# ---------------------------------------------------------------------------

def run_http_analysis(payload: dict, base_url: str) -> dict:
    """Execute analysis via HTTP POST /api/analyze."""
    try:
        import requests

        url = f"{base_url.rstrip('/')}/api/analyze"
        request_body = {
            "message": payload["customer_message"],
            "order_id": payload.get("order_id", ""),
            "tracking_no": payload.get("tracking_no", ""),
            "conversation_id": payload.get("conversation_id", "default"),
            "product_name": payload.get("product_name", ""),
            "copilot_context": payload.get("copilot_context"),
        }

        response = requests.post(
            url,
            json=request_body,
            timeout=60,
        )

        if response.status_code == 200:
            return response.json()
        else:
            return {
                "error": f"HTTP {response.status_code}: {response.text[:200]}",
                "suggested_reply": "",
                "intent": "",
            }

    except ImportError:
        return {"error": "requests library not installed", "suggested_reply": "", "intent": ""}
    except Exception as e:
        logger.error("HTTP mode analysis failed: %s", e)
        return {"error": str(e), "suggested_reply": "", "intent": ""}


# ---------------------------------------------------------------------------
# Run output management
# ---------------------------------------------------------------------------

class RunOutput:
    """Manages output files for a simulation run."""

    def __init__(self, run_id: str, results_dir: Path = RESULTS_DIR):
        self.run_id = run_id
        self.run_dir = results_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self._customers_file = self.run_dir / "customers.jsonl"
        self._turns_file = self.run_dir / "turns.jsonl"
        self._failures_file = self.run_dir / "failures.jsonl"

    def save_run_config(self, config: dict) -> None:
        """Save the run configuration."""
        path = self.run_dir / "run_config.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def save_turn(self, turn_data: dict) -> None:
        """Append a turn result."""
        with open(self._turns_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn_data, ensure_ascii=False) + "\n")

    def save_customer(self, customer_summary: dict) -> None:
        """Append a customer summary."""
        with open(self._customers_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(customer_summary, ensure_ascii=False) + "\n")

    def save_failure(self, failure_data: dict) -> None:
        """Append a failure record."""
        with open(self._failures_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(failure_data, ensure_ascii=False) + "\n")

    def save_summary(self, summary: dict) -> None:
        """Save the overall run summary."""
        path = self.run_dir / "summary.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    def save_performance(self, perf: dict) -> None:
        """Save performance metrics."""
        path = self.run_dir / "performance.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(perf, f, ensure_ascii=False, indent=2)

    def save_report(self, report: str) -> None:
        """Save the markdown report."""
        path = self.run_dir / "report.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)

    def load_completed_customers(self) -> set[str]:
        """Load set of already-completed customer IDs (for resume)."""
        completed = set()
        if self._customers_file.exists():
            with open(self._customers_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            completed.add(data.get("customer_id", ""))
                        except json.JSONDecodeError:
                            pass
        return completed


# ---------------------------------------------------------------------------
# Bad case classification and export
# ---------------------------------------------------------------------------

def classify_failure_types(turn_scores: dict) -> list[str]:
    """Classify a failed turn into specific failure types."""
    failures = []
    meta = turn_scores.get("metadata", {})

    # Intent error
    intent = turn_scores.get("intent_match", {})
    if not intent.get("match", True) and intent.get("score", 1.0) < 0.5:
        failures.append("intent_error")

    # Required tool missing
    tool = turn_scores.get("tool_routing", {})
    if tool.get("missing"):
        failures.append("required_tool_missing")

    # Risk missed
    risk = turn_scores.get("risk_recall", {})
    if risk.get("score", 1.0) < 0.5:
        failures.append("risk_missed")

    # Trap violation
    trap = turn_scores.get("trap_detection", {})
    if trap.get("triggered", False):
        failures.append("trap_violation")

    # Context memory error
    mem = turn_scores.get("context_memory", {})
    if mem.get("issues"):
        failures.append("context_memory_error")

    # Unsupported claim / grounding failure
    grounding = turn_scores.get("grounding", {})
    if grounding.get("score", 1.0) < 0.5:
        failures.append("unsupported_claim")

    # API error
    if meta.get("error"):
        failures.append("api_error")

    # Timeout
    if meta.get("duration_s", 0) > 30:
        failures.append("timeout")

    return failures or ["unknown"]


def export_bad_case(run_id: str, turn_scores: dict) -> Path | None:
    """Export a bad case candidate to the candidates directory.

    Uses run_id + customer_id + turn + failure_type as unique key.
    Returns the path to the created file, or None if duplicate.
    """
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    REVIEWED_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTED_DIR.mkdir(parents=True, exist_ok=True)

    cid = turn_scores.get("customer_id", "")
    turn_num = turn_scores.get("turn_num", 0)
    failure_types = classify_failure_types(turn_scores)

    exported = []
    for ft in failure_types:
        unique_key = f"{run_id}_{cid}_t{turn_num}_{ft}"
        filename = f"{unique_key}.json"
        filepath = CANDIDATES_DIR / filename

        # Dedup: skip if already exists
        if filepath.exists():
            continue

        record = {
            "unique_key": unique_key,
            "run_id": run_id,
            "customer_id": cid,
            "turn_num": turn_num,
            "failure_type": ft,
            "status": "candidate",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "turn_scores": turn_scores,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        exported.append(filepath)

    return exported[0] if exported else None


# ---------------------------------------------------------------------------
# Context state tracking
# ---------------------------------------------------------------------------

def build_context_state(conversation_history: list[dict], customer_message: str = "") -> dict:
    """Build context state snapshot from conversation history.

    Extracts slot values (order_id, product, color, size, decision).
    """
    from tests.simulation.evaluator import extract_context_slots
    return extract_context_slots(conversation_history, customer_message)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    run_config: dict,
    summary: dict,
    customer_summaries: list[dict],
    turn_results: list[dict],
) -> str:
    """Generate a markdown report for the run."""
    from tests.simulation.evaluator import compute_intent_confusion_matrix

    lines = []
    lines.append(f"# Simulation Run Report: {run_config.get('run_id', 'unknown')}")
    lines.append("")

    # Run config
    lines.append("## Run Configuration")
    lines.append("")
    lines.append(f"- **Run ID**: {run_config.get('run_id', '')}")
    lines.append(f"- **Mode**: {run_config.get('mode', '')}")
    lines.append(f"- **Offline**: {run_config.get('offline', False)}")
    lines.append(f"- **Started**: {run_config.get('started_at', '')}")
    lines.append(f"- **Completed**: {run_config.get('completed_at', '')}")
    lines.append(f"- **Customers**: {run_config.get('customer_count', 0)}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total Customers**: {summary.get('total_customers', 0)}")
    lines.append(f"- **Customers Passed**: {summary.get('customers_passed', 0)}")
    lines.append(f"- **Pass Rate**: {summary.get('pass_rate', 0):.1%}")
    lines.append(f"- **Average Score**: {summary.get('avg_score', 0):.3f}")
    lines.append(f"- **Min Score**: {summary.get('min_score', 0):.3f}")
    lines.append(f"- **Max Score**: {summary.get('max_score', 0):.3f}")
    lines.append("")

    # Dimension averages
    dim_avgs = summary.get("dimension_averages", {})
    if dim_avgs:
        lines.append("### Dimension Averages")
        lines.append("")
        lines.append("| Dimension | Average Score |")
        lines.append("|-----------|--------------|")
        for dim, score in sorted(dim_avgs.items()):
            lines.append(f"| {dim} | {score:.3f} |")
        lines.append("")

    # Scenario breakdown
    scenario_scores = summary.get("scenario_scores", {})
    if scenario_scores:
        lines.append("### Scores by Scenario")
        lines.append("")
        lines.append("| Scenario | Avg Score |")
        lines.append("|----------|-----------|")
        for scenario, score in sorted(scenario_scores.items()):
            lines.append(f"| {scenario} | {score:.3f} |")
        lines.append("")

    # Intent confusion matrix
    confusion = compute_intent_confusion_matrix(turn_results)
    lines.append("## Intent Confusion Matrix")
    lines.append("")
    lines.append(f"- **Overall Accuracy**: {confusion.get('accuracy', 0):.1%} ({confusion.get('correct', 0)}/{confusion.get('total', 0)})")
    lines.append("")

    matrix = confusion.get("matrix", {})
    if matrix:
        all_intents = sorted(set(list(matrix.keys()) + [a for row in matrix.values() for a in row]))
        header = "| Expected \\ Actual | " + " | ".join(all_intents) + " |"
        sep = "|---" + "|---" * len(all_intents) + "|"
        lines.append(header)
        lines.append(sep)
        for expected in all_intents:
            row_data = matrix.get(expected, {})
            cells = [str(row_data.get(a, 0)) for a in all_intents]
            lines.append(f"| {expected} | " + " | ".join(cells) + " |")
        lines.append("")

    misclass = confusion.get("misclassifications", [])
    if misclass:
        lines.append("### Top Misclassifications")
        lines.append("")
        lines.append("| Expected | Actual | Count |")
        lines.append("|----------|--------|-------|")
        for mc in misclass[:10]:
            lines.append(f"| {mc['expected']} | {mc['actual']} | {mc['count']} |")
        lines.append("")

    # Tool accuracy
    tool_results = [t.get("tool_routing", {}) for t in turn_results if "tool_routing" in t]
    if tool_results:
        total_tools = sum(len(t.get("found_expected", []) + t.get("missing", [])) for t in tool_results)
        found_tools = sum(len(t.get("found_expected", [])) for t in tool_results)
        tool_acc = found_tools / total_tools if total_tools else 1.0
        lines.append("## Tool Accuracy")
        lines.append("")
        lines.append(f"- **Accuracy**: {tool_acc:.1%} ({found_tools}/{total_tools})")
        lines.append("")

    # Risk recall
    risk_results = [t for t in turn_results if t.get("risk_recall", {}).get("triggered_high")]
    risk_ok = [t for t in risk_results if t.get("risk_recall", {}).get("score", 0) >= 0.5]
    lines.append("## Risk Recall")
    lines.append("")
    lines.append(f"- **High-risk messages detected**: {len(risk_results)}")
    lines.append(f"- **Correctly handled**: {len(risk_ok)}")
    if risk_results:
        lines.append(f"- **Recall**: {len(risk_ok)/len(risk_results):.1%}")
    lines.append("")

    # Grounding
    grounding_results = [t.get("grounding", {}) for t in turn_results if "grounding" in t]
    if grounding_results:
        g_avg = sum(g.get("score", 0) for g in grounding_results) / len(grounding_results)
        lines.append("## Grounding")
        lines.append("")
        lines.append(f"- **Average Score**: {g_avg:.3f}")
        lines.append("")

    # Context memory
    memory_results = [t.get("context_memory", {}) for t in turn_results if "context_memory" in t]
    if memory_results:
        m_avg = sum(m.get("score", 0) for m in memory_results) / len(memory_results)
        issues = [m for m in memory_results if m.get("issues")]
        lines.append("## Context Memory")
        lines.append("")
        lines.append(f"- **Average Score**: {m_avg:.3f}")
        lines.append(f"- **Turns with Issues**: {len(issues)}/{len(memory_results)}")
        lines.append("")

    # Customer details
    lines.append("## Customer Results")
    lines.append("")
    lines.append("| ID | Name | Scenario | Score | Turns | Passed |")
    lines.append("|----|------|----------|-------|-------|--------|")
    for cs in customer_summaries:
        cid = cs.get("customer_id", "")
        name = cs.get("customer_name", "")
        scenario = cs.get("scenario", "")
        score = cs.get("overall_score", 0)
        turns = cs.get("turn_count", 0)
        passed = "Y" if cs.get("passed") else "N"
        lines.append(f"| {cid} | {name} | {scenario} | {score:.3f} | {turns} | {passed} |")
    lines.append("")

    # Failures
    failures = [t for t in turn_results if not t.get("passed", True)]
    if failures:
        lines.append("## Failed Turns")
        lines.append("")
        for ft in failures:
            cid = ft.get("customer_id", "")
            turn_num = ft.get("turn_num", 0)
            score = ft.get("overall_score", 0)
            detail = ft.get("metadata", {}).get("error", "")
            failure_types = ft.get("failure_types", [])
            lines.append(f"### {cid} Turn {turn_num} (score: {score:.3f})")
            if failure_types:
                lines.append(f"- Failure types: {', '.join(failure_types)}")
            if detail:
                lines.append(f"- Error: {detail}")
            # Dimension breakdown
            for dim in ["intent_match", "risk_recall", "trap_detection", "reply_quality"]:
                dim_data = ft.get(dim, {})
                if dim_data.get("score", 1.0) < 0.5:
                    lines.append(f"- {dim}: {dim_data.get('detail', 'low score')}")
            lines.append("")

    # Bad case candidates
    lines.append("## Bad Case Candidates")
    lines.append("")
    if CANDIDATES_DIR.exists():
        candidates = list(CANDIDATES_DIR.glob(f"{run_config.get('run_id', '')}*.json"))
        lines.append(f"- **Total candidates**: {len(candidates)}")
        if candidates:
            by_type: dict[str, int] = {}
            for c in candidates:
                try:
                    data = json.loads(c.read_text(encoding="utf-8"))
                    ft = data.get("failure_type", "unknown")
                    by_type[ft] = by_type.get(ft, 0) + 1
                except Exception:
                    pass
            lines.append(f"- By type: {by_type}")
        lines.append(f"- **Directory**: `{CANDIDATES_DIR}`")
    else:
        lines.append("- No candidates directory")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_simulation(args: argparse.Namespace) -> None:
    """Execute the full simulation run."""
    from tests.simulation.evaluator import (
        evaluate_turn,
        compute_customer_summary,
        compute_run_summary,
    )

    # Generate run ID
    run_id = args.run_id or _gen_run_id()

    # Setup output
    output = RunOutput(run_id)
    logger.info("Simulation run '%s' starting. Output dir: %s", run_id, output.run_dir)

    # Load and filter customers
    all_customers = load_customers()
    customer_ids = args.customer.split(",") if args.customer else None
    customers = filter_customers(
        all_customers,
        customer_ids=customer_ids,
        scenario=args.scenario,
        priority=args.priority,
        limit=args.limit,
    )

    if not customers:
        logger.error("No customers matched the filter criteria")
        return

    # Resume support
    completed_ids: set[str] = set()
    if args.resume:
        resume_dir = RESULTS_DIR / args.resume
        if resume_dir.exists():
            resume_output = RunOutput(args.resume)
            completed_ids = resume_output.load_completed_customers()
            logger.info("Resuming run '%s': %d customers already completed",
                       args.resume, len(completed_ids))
            output = resume_output
            run_id = args.resume

    # Save run config
    started_at = datetime.now(timezone.utc).isoformat()
    run_config = {
        "run_id": run_id,
        "mode": args.mode,
        "offline": args.offline,
        "live_jst": args.live_jst,
        "base_url": args.base_url,
        "customer_count": len(customers),
        "started_at": started_at,
        "args": vars(args),
    }
    output.save_run_config(run_config)

    # Track results
    all_turn_results: list[dict] = []
    all_customer_summaries: list[dict] = []
    all_durations: list[float] = []

    mode = args.mode
    base_url = args.base_url
    offline = args.offline

    # Process each customer
    for idx, customer in enumerate(customers):
        cid = customer.get("id", f"unknown_{idx}")

        # Skip if already completed (resume)
        if cid in completed_ids:
            logger.info("Skipping completed customer: %s", cid)
            continue

        conversation_id = _gen_conversation_id(cid, run_id)
        dialogue = customer.get("dialogue", [])

        if not dialogue:
            logger.warning("Customer %s has no dialogue, skipping", cid)
            continue

        # Safety limit
        dialogue = dialogue[:MAX_TURNS_PER_CUSTOMER]

        customer_turn_results: list[dict] = []
        conversation_history: list[dict] = []

        logger.info(
            "[%d/%d] Running customer %s (%s) - %d turns",
            idx + 1, len(customers), cid, customer.get("name", ""), len(dialogue)
        )

        # Process each turn
        for turn_idx, turn in enumerate(dialogue):
            turn_num = turn.get("turn", turn_idx + 1)

            if turn.get("speaker") != "customer":
                # Skip agent turns (we only simulate customer messages)
                continue

            try:
                # Build context state BEFORE this turn
                customer_msg = turn.get("msg", "")
                context_state_before = build_context_state(
                    conversation_history, customer_msg
                )

                # Build safe payload (NO leak fields)
                payload = build_safe_payload(
                    customer=customer,
                    turn=turn,
                    conversation_id=conversation_id,
                    conversation_history=conversation_history,
                    offline=offline,
                    live_jst=args.live_jst,
                )

                # Verify no leak fields
                payload_str = json.dumps(payload, ensure_ascii=False)
                for field in LEAK_FIELDS:
                    if field in payload_str:
                        logger.warning("LEAK DETECTED: field '%s' found in payload!", field)

                # Execute analysis
                start_time = time.time()

                if mode == "http":
                    result = run_http_analysis(payload, base_url)
                else:
                    result = run_service_analysis(payload)

                end_time = time.time()
                duration = end_time - start_time
                all_durations.append(duration)

                # Evaluate the turn
                turn_scores = evaluate_turn(
                    customer=customer,
                    turn=turn,
                    actual_result=result,
                    conversation_history=conversation_history,
                    start_time=start_time,
                    end_time=end_time,
                )

                # Classify failure types and add context state
                if not turn_scores.get("passed", True):
                    blocking = turn_scores.get("blocking_reasons", [])
                    failure_types = blocking or classify_failure_types(turn_scores)
                    turn_scores["failure_types"] = failure_types
                    export_bad_case(run_id, turn_scores)

                # Build context state AFTER this turn
                temp_history = conversation_history + [{
                    "turn": turn_num,
                    "customer_message": customer_msg,
                    "suggested_reply": result.get("suggested_reply", ""),
                }]
                context_state_after = build_context_state(temp_history)
                turn_scores["context_state_before"] = context_state_before
                turn_scores["context_state_after"] = context_state_after

                customer_turn_results.append(turn_scores)
                all_turn_results.append(turn_scores)

                # Save turn result incrementally
                output.save_turn(turn_scores)

                # Record failure if not passed
                if not turn_scores.get("passed", True):
                    output.save_failure(turn_scores)

                # Update conversation history (safe — no expected fields)
                safe_entry = {
                    "turn": turn_num,
                    "customer_message": customer_msg,
                    "suggested_reply": result.get("suggested_reply", ""),
                    "intent": result.get("intent", ""),
                }
                conversation_history.append(safe_entry)

                logger.info(
                    "  Turn %d: score=%.3f intent=%s duration=%.1fs %s",
                    turn_num,
                    turn_scores.get("overall_score", 0),
                    result.get("intent", ""),
                    duration,
                    "PASS" if turn_scores.get("passed") else "FAIL",
                )

            except Exception as e:
                logger.error(
                    "Customer %s turn %d failed with exception: %s",
                    cid, turn_num, e, exc_info=True,
                )
                failure_record = {
                    "customer_id": cid,
                    "turn_num": turn_num,
                    "error": str(e),
                    "overall_score": 0.0,
                    "passed": False,
                    "failure_types": ["api_error"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                output.save_turn(failure_record)
                output.save_failure(failure_record)
                export_bad_case(run_id, failure_record)
                customer_turn_results.append(failure_record)
                all_turn_results.append(failure_record)
                # Continue with next turn/customer

        # Compute customer summary
        customer_summary = compute_customer_summary(customer_turn_results)
        customer_summary["customer_id"] = cid
        customer_summary["customer_name"] = customer.get("name", "")
        customer_summary["scenario"] = customer.get("scenario", "")
        customer_summary["priority"] = customer.get("priority", "")
        all_customer_summaries.append(customer_summary)
        output.save_customer(customer_summary)

        logger.info(
            "  Customer %s complete: score=%.3f turns=%d passed=%s",
            cid,
            customer_summary.get("overall_score", 0),
            customer_summary.get("turn_count", 0),
            "Y" if customer_summary.get("passed") else "N",
        )

    # Compute and save overall summary
    run_summary = compute_run_summary(all_customer_summaries)
    completed_at = datetime.now(timezone.utc).isoformat()

    # Add intent confusion matrix to summary
    from tests.simulation.evaluator import compute_intent_confusion_matrix
    confusion = compute_intent_confusion_matrix(all_turn_results)
    run_summary["intent_confusion"] = confusion

    run_config["completed_at"] = completed_at
    run_config["customer_count"] = len(customers)
    output.save_run_config(run_config)
    output.save_summary(run_summary)

    # Performance metrics (including p50/p95)
    sorted_durations = sorted(all_durations) if all_durations else [0]
    p50_idx = int(len(sorted_durations) * 0.5)
    p95_idx = int(len(sorted_durations) * 0.95)
    perf = {
        "total_turns": len(all_turn_results),
        "avg_duration_s": round(sum(all_durations) / len(all_durations), 3) if all_durations else 0,
        "max_duration_s": round(max(all_durations), 3) if all_durations else 0,
        "min_duration_s": round(min(all_durations), 3) if all_durations else 0,
        "total_duration_s": round(sum(all_durations), 3),
        "p50_duration_s": round(sorted_durations[min(p50_idx, len(sorted_durations) - 1)], 3),
        "p95_duration_s": round(sorted_durations[min(p95_idx, len(sorted_durations) - 1)], 3),
    }
    output.save_performance(perf)

    # Generate and save report
    report = generate_report(run_config, run_summary, all_customer_summaries, all_turn_results)
    output.save_report(report)

    # Print summary
    print("\n" + "=" * 60)
    print(f"Simulation Run Complete: {run_id}")
    print("=" * 60)
    print(f"  Customers: {run_summary.get('total_customers', 0)}")
    print(f"  Passed:    {run_summary.get('customers_passed', 0)}")
    print(f"  Pass Rate: {run_summary.get('pass_rate', 0):.1%}")
    print(f"  Avg Score: {run_summary.get('avg_score', 0):.3f}")
    print(f"  Turns:     {perf.get('total_turns', 0)}")
    print(f"  Avg Time:  {perf.get('avg_duration_s', 0):.1f}s")
    print(f"  Output:    {output.run_dir}")
    print(f"  Report:    {output.run_dir / 'report.md'}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Simulated Customer Runner - evaluate AI copilot against test customers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--customer", "-c",
        type=str,
        default=None,
        help="Comma-separated customer IDs to run (e.g. C001,C002)",
    )
    parser.add_argument(
        "--scenario", "-s",
        type=str,
        default=None,
        choices=["pre_sale_product", "logistics", "after_sales_return",
                 "installation", "complaint_high_risk", "edge_composite"],
        help="Filter by scenario type",
    )
    parser.add_argument(
        "--priority", "-p",
        type=str,
        default=None,
        choices=["P0", "P1", "P2"],
        help="Filter by priority level",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Maximum number of customers to run",
    )
    parser.add_argument(
        "--resume", "-r",
        type=str,
        default=None,
        help="Resume an interrupted run by run ID",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Custom run ID (auto-generated if not specified)",
    )
    parser.add_argument(
        "--mode", "-m",
        type=str,
        default="service",
        choices=["service", "http"],
        help="Execution mode: 'service' (direct call) or 'http' (POST to API)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="Use fixture data instead of live database/API calls",
    )
    parser.add_argument(
        "--live-jst",
        action="store_true",
        default=False,
        help="Use live JST queries (overrides --offline for JST lookups)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:5000",
        help="Base URL for HTTP mode (default: http://localhost:5000)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable verbose logging",
    )

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    """Main entry point."""
    args = parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Reduce noise from third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    run_simulation(args)


if __name__ == "__main__":
    main()
