"""Run a local-only P1 Supervisor Assist smoke check on the formal API.

The command starts an isolated development process, binds it to loopback, uses
an explicit read-only knowledge snapshot, and checks review-only delivery
contracts. It intentionally stores no conversation or reply text in its JSON
report. This is a safety and operability check, not a real-customer accuracy
evaluation and never enables automatic sending.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "case_id": "low_risk_review_draft",
        "message": "Hello. Please tell me what needs human confirmation.",
        "conversation_history": [],
        "requires_nonempty_draft": True,
    },
    {
        "case_id": "after_sales_no_send_boundary",
        "message": (
            "I reported a problem. Should I receive a refund, replacement, or "
            "compensation? Please ask a human to confirm."
        ),
        "conversation_history": [
            {
                "role": "customer",
                "text": "I already submitted a description of the problem.",
            }
        ],
        "requires_nonempty_draft": False,
    },
)


class SmokeInfrastructureError(RuntimeError):
    """The isolated server could not be started or queried safely."""


class SmokeContractError(RuntimeError):
    """The server returned a response outside the Supervisor Assist boundary."""


def _loopback_base_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "http" or not parsed.hostname or parsed.hostname not in LOOPBACK_HOSTS:
        raise argparse.ArgumentTypeError("base_url_must_be_http_loopback")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("base_url_must_not_include_path_or_query")
    return parsed.geturl().rstrip("/")


def _loopback_provider_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "http" or not parsed.hostname or parsed.hostname not in LOOPBACK_HOSTS:
        raise argparse.ArgumentTypeError("llm_api_base_must_be_http_loopback")
    if parsed.params or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("llm_api_base_must_not_include_query")
    return parsed.geturl().rstrip("/")


def _positive_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port_must_be_integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port_out_of_range")
    return port


def _http_json(url: str, *, payload: dict[str, Any] | None, timeout_seconds: int) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = Request(
        url,
        data=data,
        method="GET" if data is None else "POST",
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - local-only URL is validated by caller.
        if response.status != 200:
            raise SmokeInfrastructureError(f"unexpected_http_status:{response.status}")
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise SmokeInfrastructureError("non_object_json_response")
    return result


def _reply_text(response: dict[str, Any]) -> str:
    for field in ("suggested_reply", "draft_reply", "sendable_reply"):
        value = response.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def project_case_result(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Return safe response metadata and enforce the Supervisor Assist contract."""
    reply = _reply_text(response)
    case_id = str(case["case_id"])
    if response.get("error"):
        raise SmokeContractError(f"{case_id}:response_error")
    if response.get("can_send") is True:
        raise SmokeContractError(f"{case_id}:unsafe_auto_send")
    if response.get("requires_human_review") is not True:
        raise SmokeContractError(f"{case_id}:human_review_missing")
    if case.get("requires_nonempty_draft") and not reply:
        raise SmokeContractError(f"{case_id}:review_draft_missing")
    return {
        "case_id": case_id,
        "intent": str(response.get("intent") or ""),
        "reply_status": str(response.get("reply_status") or ""),
        "review_draft_present": bool(reply),
        "review_draft_length": len(reply),
        "can_send": bool(response.get("can_send")),
        "requires_human_review": bool(response.get("requires_human_review")),
    }


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _runtime_environment(args: argparse.Namespace, knowledge_db: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({
        "COPILOT_WEB_HOST": args.host,
        "COPILOT_WEB_PORT": str(args.port),
        "COPILOT_WEB_DEBUG": "false",
        "COPILOT_RUNTIME_ENV": "development",
        "COPILOT_ADMIN_AUTH_MODE": "development_loopback",
        "COPILOT_ADMIN_DEV_SUBJECT": "p1-isolated-smoke",
        "COPILOT_ADMIN_DEV_ROLE": "admin",
        "COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY": "true",
        "COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED": "false",
        "COPILOT_KNOWLEDGE_DB_PATH": str(knowledge_db),
        "COPILOT_LLM_API_BASE": args.llm_api_base,
        "COPILOT_LLM_MODEL": args.llm_model,
        # This value is only a non-secret presence marker for a loopback model
        # server that does not authenticate requests. It must not be reused for
        # an external provider.
        "COPILOT_LLM_API_KEY": "local-isolated-smoke-placeholder",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return environment


def _wait_for_ready(base_url: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    latest_error = "health_not_available"
    while time.monotonic() < deadline:
        try:
            health = _http_json(f"{base_url}/api/health", payload=None, timeout_seconds=4)
        except (URLError, TimeoutError, json.JSONDecodeError, SmokeInfrastructureError) as exc:
            latest_error = type(exc).__name__
            time.sleep(1)
            continue
        if health.get("ready") is not True:
            reasons = ",".join(str(item) for item in health.get("readiness_reasons") or [])
            raise SmokeInfrastructureError(f"runtime_not_ready:{reasons or 'unspecified'}")
        return health
    raise SmokeInfrastructureError(f"health_timeout:{latest_error}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    knowledge_db = Path(args.knowledge_db).expanduser().resolve()
    if not knowledge_db.is_file():
        raise SmokeInfrastructureError("knowledge_db_missing")
    if not _port_available(args.host, args.port):
        raise SmokeInfrastructureError("port_in_use")

    base_url = _loopback_base_url(args.base_url)
    environment = _runtime_environment(args, knowledge_db)
    server = subprocess.Popen(
        [sys.executable, "run_web.py"],
        cwd=PROJECT_ROOT,
        env=environment,
        # The report intentionally contains metadata only. Discard process logs
        # too, rather than leaving transcript-adjacent data in a temp directory.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        health = _wait_for_ready(base_url, args.startup_timeout)
        version = _http_json(f"{base_url}/api/runtime/version", payload=None, timeout_seconds=10)
        results = []
        for case in SCENARIOS:
            payload = {
                "conversation_id": f"p1-isolated-smoke-{case['case_id']}",
                "message": case["message"],
                "conversation_history": case["conversation_history"],
            }
            response = _http_json(
                f"{base_url}/api/analyze",
                payload=payload,
                timeout_seconds=args.request_timeout,
            )
            results.append(project_case_result(case, response))
    except Exception:
        if server.poll() is not None:
            raise SmokeInfrastructureError(f"server_exited:{server.returncode}") from None
        raise
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)

    return {
        "schema_version": "p1-isolated-smoke-report/v1",
        "base_url": base_url,
        "knowledge_snapshot": {
            "basename": knowledge_db.name,
            "size_bytes": knowledge_db.stat().st_size,
        },
        "health": {
            "ready": bool(health.get("ready")),
            "status": str(health.get("readiness_status") or ""),
            "reasons": [str(item) for item in health.get("readiness_reasons") or []],
        },
        "runtime": {
            "runtime_commit": str(version.get("runtime_commit") or ""),
            "formal_knowledge_query_only": bool(version.get("formal_knowledge_query_only")),
            "formal_evidence_convergence": bool(
                (version.get("feature_flags") or {}).get("formal_evidence_convergence")
            ),
        },
        "cases": results,
        "can_send_true_count": sum(item["can_send"] for item in results),
        "human_review_required_count": sum(item["requires_human_review"] for item in results),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local-only P1 Supervisor Assist smoke check.")
    parser.add_argument("--knowledge-db", required=True, help="Explicit read-only SQLite knowledge snapshot.")
    parser.add_argument("--host", default="127.0.0.1", choices=sorted(LOOPBACK_HOSTS))
    parser.add_argument("--port", type=_positive_port, default=5012)
    parser.add_argument("--base-url", type=_loopback_base_url, default="http://127.0.0.1:5012")
    parser.add_argument("--llm-api-base", required=True, type=_loopback_provider_url)
    parser.add_argument("--llm-model", required=True)
    parser.add_argument("--startup-timeout", type=int, default=35)
    parser.add_argument("--request-timeout", type=int, default=120)
    parser.add_argument("--json-output", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except SmokeContractError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=True))
        return 2
    except SmokeInfrastructureError as exc:
        print(json.dumps({"status": "infrastructure_blocked", "reason": str(exc)}, ensure_ascii=True))
        return 1
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if args.json_output:
        output = Path(args.json_output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
