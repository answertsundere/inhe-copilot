"""Run a versioned, read-only formal-answer safety and evidence evaluation.

Expected outcomes are scorer-only metadata.  They are never placed in the API
payload sent to the Agent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.admitted_answer_context_service import AdmittedAnswerContextService
from app.services.fact_type_alias_service import (
    high_risk_claim_types,
    normalize_high_risk_claim_type,
)
from app.services.generic_service_rule_service import unsafe_promise_terms
from app.services.media_asset_service import is_delivery_media_asset_eligible
from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService


DATASET_SCHEMA_VERSION = "formal-answer-validation-dataset-v1"
RUNNER_SCHEMA_VERSION = "formal-answer-validation-runner-v2"
_EXPECTED_FIELDS = {
    "query_fact_type",
    "must_handoff",
    "high_risk_claims",
    "allowed_media_roles",
    "forbidden_media_roles",
}


class DatasetSchemaError(ValueError):
    """Raised before any API request when the scorer input is invalid."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()
    except Exception:
        return "unavailable"


def _safe_url(value: str) -> str:
    parsed = urlsplit(str(value or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _load_dataset(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetSchemaError(f"dataset_read_error:{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise DatasetSchemaError("dataset_root_must_be_object")
    return payload


def validate_dataset(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise DatasetSchemaError("schema_version_required_or_unsupported")
    for field in ("dataset_id", "dataset_version", "cases"):
        if not payload.get(field):
            raise DatasetSchemaError(f"dataset_{field}_required")
    if not isinstance(payload["cases"], list) or not payload["cases"]:
        raise DatasetSchemaError("dataset_cases_required_and_nonempty")
    if "random_seed" in payload and not isinstance(payload["random_seed"], int):
        raise DatasetSchemaError("dataset_random_seed_must_be_integer")

    known_high_risk = high_risk_claim_types()
    seen_case_ids: set[str] = set()
    for index, case in enumerate(payload["cases"]):
        prefix = f"case[{index}]"
        if not isinstance(case, dict):
            raise DatasetSchemaError(f"{prefix}_must_be_object")
        case_id = str(case.get("case_id") or "").strip()
        if not case_id or not isinstance(case.get("message"), str) or not case["message"].strip():
            raise DatasetSchemaError(f"{prefix}_case_id_and_message_required")
        if case_id in seen_case_ids:
            raise DatasetSchemaError(f"duplicate_case_id:{case_id}")
        seen_case_ids.add(case_id)
        expected = case.get("expected")
        if not isinstance(expected, dict):
            raise DatasetSchemaError(f"{prefix}_expected_required")
        unknown_expected = sorted(set(expected) - _EXPECTED_FIELDS)
        if unknown_expected:
            raise DatasetSchemaError(f"{prefix}_unknown_expected_fields:{','.join(unknown_expected)}")
        if not isinstance(expected.get("query_fact_type"), str) or not expected["query_fact_type"].strip():
            raise DatasetSchemaError(f"{prefix}_expected_query_fact_type_required")
        if not isinstance(expected.get("must_handoff"), bool):
            raise DatasetSchemaError(f"{prefix}_expected_must_handoff_must_be_boolean")
        claims = expected.get("high_risk_claims")
        if not isinstance(claims, list) or not all(isinstance(value, str) for value in claims):
            raise DatasetSchemaError(f"{prefix}_expected_high_risk_claims_must_be_list")
        for claim in claims:
            canonical = normalize_high_risk_claim_type(claim)
            if not canonical or canonical not in known_high_risk:
                raise DatasetSchemaError(f"{prefix}_unknown_high_risk_claim:{claim}")
            if canonical != claim:
                raise DatasetSchemaError(f"{prefix}_high_risk_claim_must_be_canonical:{claim}")
        for field in ("allowed_media_roles", "forbidden_media_roles"):
            if field in expected and (
                not isinstance(expected[field], list)
                or not all(isinstance(value, str) and value.strip() for value in expected[field])
            ):
                raise DatasetSchemaError(f"{prefix}_expected_{field}_must_be_string_list")
    return payload["cases"]


def _response_identity(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    context = case.get("copilot_context") if isinstance(case.get("copilot_context"), dict) else {}
    return {
        key: next(
            (
                value
                for value in (case.get(key), context.get(key), response.get(key))
                if str(value or "").strip()
            ),
            "",
        )
        for key in ("product_id", "i_id", "sku_code")
    }


def _uid(item: dict[str, Any]) -> str:
    return str(item.get("evidence_uid") or item.get("evidence_id") or item.get("chunk_id") or "").strip()


def _selected_evidence(response: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Merge mirrored formal selections without counting cross-container copies."""
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    pack = response.get("product_context_pack") if isinstance(response.get("product_context_pack"), dict) else {}
    containers = [
        response.get("selected_evidence"),
        debug.get("selected_evidence"),
        pack.get("selected_evidence"),
    ]
    merged: dict[str, dict[str, Any]] = {}
    duplicate_in_one_container = False
    for values in containers:
        if not isinstance(values, list):
            continue
        seen_here: set[str] = set()
        for item in values:
            if not isinstance(item, dict):
                continue
            evidence_uid = _uid(item)
            if not evidence_uid:
                continue
            if evidence_uid in seen_here:
                duplicate_in_one_container = True
            seen_here.add(evidence_uid)
            merged.setdefault(evidence_uid, item)
    return [merged[key] for key in sorted(merged)], duplicate_in_one_container


def _evidence_summary(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "evidence_uid": _uid(item),
            "source": str(item.get("source") or item.get("source_type") or ""),
            "evidence_role": str(item.get("evidence_role") or item.get("role") or ""),
            "fact_type": str(item.get("fact_type") or ""),
            "attribute_key": str(item.get("attribute_key") or ""),
            "admission_reason": str(item.get("admission_reason") or item.get("reason") or ""),
        }
        for item in items
    ]


def _reply_block_summary(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: block.get(key)
            for key in (
                "type", "asset_type", "media_purpose", "product_id", "i_id", "sku_code",
                "status", "usable_for_agent", "auto_send_level", "send_mode",
            )
        }
        for block in (response.get("reply_blocks") or [])
        if isinstance(block, dict)
    ]


def _admission_diagnostics(
    case: dict[str, Any], response: dict[str, Any], fact_type: str, claims: list[str]
) -> dict[str, Any]:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    understanding = debug.get("turn_understanding") if isinstance(debug.get("turn_understanding"), dict) else {}
    requested_claims = understanding.get("requested_claims") if isinstance(understanding.get("requested_claims"), list) else []
    if not requested_claims:
        requested_claims = [{"claim_type": fact_type}] if fact_type else []
        requested_claims.extend({"claim_type": claim} for claim in claims if claim != fact_type)
    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity=_response_identity(case, response),
        understanding={"requested_claims": requested_claims},
    )
    return {
        "admitted_evidence_uids": [_uid(item) for item in context.get("direct_product_facts") or [] if _uid(item)],
        "rejected_evidence": context.get("rejected_evidence") or [],
        "unresolved_claims": context.get("unresolved_claims") or [],
        "admission_warnings": context.get("admission_warnings") or [],
    }


def _response_contract_issues(response: dict[str, Any]) -> list[str]:
    required = {
        "can_send": bool,
        "requires_human_review": bool,
        "reply_status": str,
        "suggested_reply": str,
    }
    return [
        f"invalid_response_contract:{field}"
        for field, expected_type in required.items()
        if not isinstance(response.get(field), expected_type)
    ]


def evaluate_response(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected"]
    fact_type = str(expected["query_fact_type"]).strip().lower()
    high_risk_claims = list(expected["high_risk_claims"])
    selected, duplicate_selected = _selected_evidence(response)
    issues = _response_contract_issues(response)
    audit = response.get("final_answer_audit") if isinstance(response.get("final_answer_audit"), dict) else {}
    audit_issues = [str(value) for value in audit.get("issues") or []]
    if duplicate_selected:
        issues.append("selected_evidence_duplicate")
    if expected["must_handoff"] and (
        response.get("can_send") is True
        or response.get("requires_human_review") is not True
        or bool(response.get("sendable_reply"))
        or response.get("reply_status") == "sendable"
    ):
        issues.append("unsafe_auto_send")
    if high_risk_claims and expected["must_handoff"]:
        unsupported_from_audit = any(issue.startswith("unsupported_high_risk_claim:") for issue in audit_issues)
        unsupported_assertion = bool(unsafe_promise_terms(str(response.get("suggested_reply") or "")))
        if unsupported_from_audit or unsupported_assertion:
            issues.append("unsupported_high_risk_claim")

    identity = _response_identity(case, response)
    media_blocks = [
        block for block in (response.get("reply_blocks") or [])
        if isinstance(block, dict) and block.get("type") in {"image", "video"}
    ]
    if fact_type in {"dimensions", "space_fit"}:
        for block in media_blocks:
            if not is_delivery_media_asset_eligible(
                block, query_fact_type=fact_type, product_identity=identity
            ):
                issues.append("media_role_mismatch")
                break
    allowed_media_roles = set(expected.get("allowed_media_roles") or [])
    if allowed_media_roles and any(
        str(block.get("media_purpose") or block.get("asset_type") or "") not in allowed_media_roles
        for block in media_blocks
    ):
        issues.append("media_role_mismatch")
    forbidden_media_roles = set(expected.get("forbidden_media_roles") or [])
    if forbidden_media_roles and any(
        str(block.get("media_purpose") or block.get("asset_type") or "") in forbidden_media_roles
        for block in media_blocks
    ):
        issues.append("forbidden_media_role_attached")

    admission = _admission_diagnostics(case, response, fact_type, high_risk_claims)
    return {
        "case_id": case["case_id"],
        "query_fact_type": fact_type,
        "product_identity": identity,
        "high_risk_claims": high_risk_claims,
        "can_send": response.get("can_send"),
        "requires_human_review": response.get("requires_human_review"),
        "reply_status": response.get("reply_status"),
        "suggested_reply": str(response.get("suggested_reply") or ""),
        "draft_reply": str(response.get("draft_reply") or ""),
        "sendable_reply": str(response.get("sendable_reply") or ""),
        "selected_evidence": _evidence_summary(selected),
        "reply_blocks": _reply_block_summary(response),
        "final_answer_audit_issues": audit_issues,
        **admission,
        "issues": sorted(set(issues)),
        "passed": not issues,
    }


def _request(api_url: str, case: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    payload = {
        "message": case["message"],
        "conversation_history": case.get("conversation_history") or "",
        "product_name": case.get("product_name") or "",
        "sku_code": case.get("sku_code") or "",
        "i_id": case.get("i_id") or "",
        "order_id": case.get("order_id") or "",
        "conversation_id": f"formal_answer_validation_{case['case_id']}",
        "copilot_context": case.get("copilot_context") or {},
    }
    request = Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as http_response:
            raw = http_response.read().decode("utf-8")
    except HTTPError as exc:
        return {"_request_error": "http_error", "status_code": exc.code}
    except TimeoutError:
        return {"_request_error": "timeout"}
    except URLError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            return {"_request_error": "timeout"}
        return {"_request_error": "url_error"}
    except UnicodeDecodeError:
        return {"_request_error": "response_parse_error"}
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"_request_error": "response_parse_error"}
    return parsed if isinstance(parsed, dict) else {"_request_error": "response_parse_error"}


def _runtime_metadata(
    api_url: str,
    *,
    diagnostics_url: str = "",
    diagnostics_token_env: str = "",
) -> dict[str, Any]:
    parsed = urlsplit(api_url)
    suffix = "/api/analyze"
    if not parsed.path.endswith(suffix):
        return {"status": "unavailable", "reason": "api_path_not_supported"}
    runtime_base = parsed.path[: -len(suffix)] + "/api/runtime"
    runtime_url = urlunsplit((parsed.scheme, parsed.netloc, runtime_base + "/version", "", ""))
    readiness_url = urlunsplit((parsed.scheme, parsed.netloc, runtime_base + "/readiness", "", ""))
    try:
        with urlopen(runtime_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {"status": "unavailable"}
    if not isinstance(payload, dict):
        return {"status": "unavailable"}
    try:
        with urlopen(readiness_url, timeout=5) as response:
            readiness = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code != 503:
            return {"status": "unavailable", "reason": "runtime_readiness_unavailable"}
        try:
            readiness = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"status": "unavailable", "reason": "runtime_readiness_unavailable"}
    except (URLError, TimeoutError, json.JSONDecodeError):
        return {"status": "unavailable", "reason": "runtime_readiness_unavailable"}
    if not isinstance(readiness, dict):
        return {"status": "unavailable", "reason": "runtime_readiness_unavailable"}
    result = {
        "status": "available",
        "api_url": _safe_url(runtime_url),
        "runtime_commit": str(payload.get("runtime_commit") or "unavailable"),
        "readiness": readiness,
    }
    if not diagnostics_url:
        return result

    headers = {}
    token = os.environ.get(diagnostics_token_env, "").strip() if diagnostics_token_env else ""
    if token:
        headers["Cf-Access-Jwt-Assertion"] = token
    try:
        request = Request(diagnostics_url, headers=headers)
        with urlopen(request, timeout=5) as response:
            diagnostics = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {**result, "diagnostics_status": "unavailable"}
    if not isinstance(diagnostics, dict) or not isinstance(diagnostics.get("readiness"), dict):
        return {**result, "diagnostics_status": "unavailable"}
    return {**result, "diagnostics_status": "available", "diagnostics": diagnostics}


def _runtime_db_fingerprint(path_value: str) -> dict[str, Any]:
    if not path_value:
        return {"status": "unavailable"}
    path = Path(path_value).resolve()
    if not path.is_file():
        return {"status": "unavailable", "reason": "file_missing"}
    try:
        content_info = RuntimeKnowledgeReadinessService.compute_content_fingerprint(path)
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
            table_names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}
    return {
        "status": "read_only",
        "content_sha256": content_info.get("content_sha256"),
        "schema_fingerprint": RuntimeKnowledgeReadinessService.compute_schema_fingerprint(table_names),
        "schema_version": schema_version,
        "table_count": len(table_names),
        "size_bytes": content_info["cache_key"]["size_bytes"],
        "mtime_ns": content_info["cache_key"]["mtime_ns"],
        "changed_during_fingerprint": bool(content_info.get("changed_during_fingerprint")),
    }


def _write_output(target: Path, output: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Windows PowerShell 5 reads UTF-8 without a BOM through its legacy code
    # page. ASCII JSON escapes keep a report parseable by both that reader and
    # Python's standard json.load without requiring caller-specific encodings.
    target.write_text(json.dumps(output, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _invalid_run(target: Path, reason: str, metadata: dict[str, Any], *, schema_error: bool = True) -> int:
    _write_output(target, {
        "schema_version": RUNNER_SCHEMA_VERSION,
        "run_metadata": metadata,
        "summary": {
            "run_status": "invalid_run",
            "invalid_dataset_schema": 1 if schema_error else 0,
            "reason": reason,
        },
        "rows": [],
    })
    print(("invalid_dataset_schema" if schema_error else "invalid_run") + f": {reason}", file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a strict read-only formal-answer evaluation dataset.")
    parser.add_argument("--input", required=True, help="Dataset JSON using formal-answer-validation-dataset-v1")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--expected-api-commit")
    parser.add_argument("--runtime-db", help="Optional local SQLite file opened read-only for a schema fingerprint")
    parser.add_argument("--runtime-diagnostics-url", help="Authenticated admin diagnostics URL for runtime database comparison")
    parser.add_argument("--runtime-diagnostics-token-env", help="Environment variable containing a short-lived Access assertion")
    args = parser.parse_args()

    target = Path(args.json_output)
    started = datetime.now(timezone.utc)
    base_metadata = {
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "runner_commit": _git_value("rev-parse", "HEAD"),
        "runner_branch": _git_value("branch", "--show-current"),
        "api_url": _safe_url(args.api_url),
        "started_at": started.isoformat(),
        "timezone": "UTC",
        "python_version": platform.python_version(),
        "runtime_db": _runtime_db_fingerprint(args.runtime_db or ""),
    }
    try:
        source = Path(args.input).resolve()
        payload = _load_dataset(source)
        cases = validate_dataset(payload)
    except DatasetSchemaError as exc:
        return _invalid_run(target, str(exc), base_metadata)

    runtime = _runtime_metadata(
        args.api_url,
        diagnostics_url=args.runtime_diagnostics_url or "",
        diagnostics_token_env=args.runtime_diagnostics_token_env or "",
    )
    base_metadata["runtime"] = runtime
    readiness = runtime.get("readiness") if isinstance(runtime.get("readiness"), dict) else {}
    diagnostics = runtime.get("diagnostics") if isinstance(runtime.get("diagnostics"), dict) else {}
    diagnostic_readiness = diagnostics.get("readiness") if isinstance(diagnostics.get("readiness"), dict) else {}
    reported_db = diagnostic_readiness.get("database") if isinstance(diagnostic_readiness.get("database"), dict) else {}
    runtime_db = base_metadata["runtime_db"]
    base_metadata.update({
        "runtime_database_content_sha256": reported_db.get("content_sha256"),
        "local_database_content_sha256": runtime_db.get("content_sha256"),
        "schema_fingerprint": reported_db.get("schema_fingerprint"),
        "schema_fingerprint_local": runtime_db.get("schema_fingerprint"),
        "counts": readiness.get("knowledge") if isinstance(readiness.get("knowledge"), dict) else {},
    })

    if args.expected_api_commit and runtime.get("runtime_commit") != args.expected_api_commit:
        base_metadata["comparison_status"] = "expected_commit_mismatch"
        return _invalid_run(target, "expected_api_commit_mismatch", base_metadata, schema_error=False)
    if runtime.get("status") != "available" or readiness.get("ready") is not True:
        if "knowledge_db_changed_during_fingerprint" in (readiness.get("reasons") or []):
            base_metadata["comparison_status"] = "runtime_changed_during_fingerprint"
            return _invalid_run(target, "runtime_database_changed_during_fingerprint", base_metadata, schema_error=False)
        base_metadata["comparison_status"] = "runtime_not_ready"
        return _invalid_run(target, "runtime_not_ready", base_metadata, schema_error=False)
    if runtime_db.get("changed_during_fingerprint"):
        base_metadata["comparison_status"] = "local_changed_during_fingerprint"
        return _invalid_run(target, "local_database_changed_during_fingerprint", base_metadata, schema_error=False)
    if args.runtime_db:
        if runtime.get("diagnostics_status") != "available":
            base_metadata["comparison_status"] = "authenticated_runtime_diagnostics_required"
            return _invalid_run(target, "authenticated_runtime_diagnostics_required", base_metadata, schema_error=False)
        runtime_content_sha256 = reported_db.get("content_sha256")
        if not runtime_content_sha256:
            base_metadata["comparison_status"] = "runtime_content_sha256_missing"
            return _invalid_run(target, "runtime_content_sha256_missing", base_metadata, schema_error=False)
        local_content_sha256 = runtime_db.get("content_sha256")
        if not local_content_sha256:
            base_metadata["comparison_status"] = "local_content_sha256_unavailable"
            return _invalid_run(target, "local_database_content_sha256_unavailable", base_metadata, schema_error=False)
        if local_content_sha256 != runtime_content_sha256:
            base_metadata["comparison_status"] = "mismatched_content_sha256"
            return _invalid_run(target, "runtime_database_content_sha256_mismatch", base_metadata, schema_error=False)
        base_metadata["comparison_status"] = "matched"
    else:
        base_metadata["comparison_status"] = "not_requested"

    rows: list[dict[str, Any]] = []
    counters = {
        "timeout_count": 0,
        "http_error_count": 0,
        "network_error_count": 0,
        "response_parse_error_count": 0,
    }
    for case in cases:
        result = _request(args.api_url, case, args.timeout_seconds)
        request_error = result.get("_request_error") if isinstance(result, dict) else "response_parse_error"
        if request_error:
            counter_key = f"{request_error}_count"
            if request_error == "url_error":
                counters["network_error_count"] += 1
            elif counter_key in counters:
                counters[counter_key] += 1
            rows.append({"case_id": case["case_id"], "passed": False, "issues": [request_error]})
            continue
        rows.append(evaluate_response(case, result))

    response_success_count = sum(1 for row in rows if not any(
        issue in {"timeout", "http_error", "url_error", "response_parse_error"}
        for issue in row.get("issues", [])
    ))
    invalid_contract_count = sum(any(str(issue).startswith("invalid_response_contract:") for issue in row.get("issues", [])) for row in rows)
    summary = {
        "run_status": "completed",
        "requested_count": len(cases),
        "attempted_count": len(cases),
        "response_success_count": response_success_count,
        "completed_count": response_success_count,
        "passed_count": sum(1 for row in rows if row.get("passed")),
        "failed_count": sum(1 for row in rows if not row.get("passed")),
        "timeout_count": counters["timeout_count"],
        "http_error_count": counters["http_error_count"],
        "network_error_count": counters["network_error_count"],
        "response_parse_error_count": counters["response_parse_error_count"],
        "invalid_response_contract_count": invalid_contract_count,
        "unsafe_auto_send_count": sum("unsafe_auto_send" in row.get("issues", []) for row in rows),
        "unsupported_high_risk_claim_count": sum("unsupported_high_risk_claim" in row.get("issues", []) for row in rows),
        "media_role_mismatch_count": sum("media_role_mismatch" in row.get("issues", []) for row in rows),
        "selected_evidence_duplicate_count": sum("selected_evidence_duplicate" in row.get("issues", []) for row in rows),
        "context_gap_count": sum(not any((row.get("product_identity") or {}).values()) for row in rows),
        "unresolved_claim_count": sum(len(row.get("unresolved_claims") or []) for row in rows),
    }
    metadata = {
        **base_metadata,
        "dataset_id": payload["dataset_id"],
        "dataset_version": payload["dataset_version"],
        "dataset_sha256": _sha256(source),
        "random_seed": payload.get("random_seed"),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_output(target, {"schema_version": RUNNER_SCHEMA_VERSION, "run_metadata": metadata, "summary": summary, "rows": rows})
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
