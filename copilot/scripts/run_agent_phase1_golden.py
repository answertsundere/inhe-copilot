#!/usr/bin/env python3
"""Run Agent Phase 1 golden cases against a real /ask/api/analyze endpoint."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE_DIR = ROOT / "tests" / "golden_cases" / "agent_phase1"
DEFAULT_REPORT_DIR = ROOT / "reports" / "agent_phase1_golden"
DEFAULT_FIXTURE_NAME = "knowledge_fixtures.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_cases(case_dir: Path) -> list[dict]:
    cases: list[dict] = []
    for path in sorted(case_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, list):
            cases.extend(payload)
        elif isinstance(payload, dict) and isinstance(payload.get("cases"), list):
            cases.extend(payload["cases"])
        elif isinstance(payload, dict) and payload.get("case_id"):
            cases.append(payload)
    return cases


def _seed_knowledge_fixtures(case_dir: Path) -> int:
    """Seed published knowledge needed by the golden set in a clean SQLite DB.

    This is test harness data, not business routing logic. The production agent
    still uses whatever published knowledge exists in the deployed DB.
    """
    fixture_path = case_dir / DEFAULT_FIXTURE_NAME
    if not fixture_path.exists():
        return 0
    with fixture_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    entries = payload.get("knowledge_entries") if isinstance(payload, dict) else []
    if not entries:
        return 0

    from app.db import SessionLocal, init_db
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    init_db()
    db = SessionLocal()
    try:
        seeded = 0
        for item in entries:
            business_key = str(item.get("business_key") or "").strip()
            content = str(item.get("content") or "").strip()
            if not business_key or not content:
                continue

            existing = (
                db.query(KnowledgeEntry)
                .filter(KnowledgeEntry.business_key == business_key)
                .first()
            )
            if existing:
                db.query(KnowledgeChunk).filter(KnowledgeChunk.entry_id == existing.id).delete()
                db.delete(existing)
                db.flush()

            product_scope = item.get("product_scope") or []
            sku_scope = item.get("sku_scope") or []
            platform_scope = item.get("platform_scope") or []
            metadata = {
                "auto_reply_allowed": True,
                "human_review_required": False,
                "fact_type": item.get("fact_type", ""),
                "fact_review_status": "verified",
                "golden_fixture": True,
            }
            entry = KnowledgeEntry(
                source_type=item.get("source_type", "product_facts"),
                title=item.get("title", business_key),
                content=content,
                intent=item.get("intent", "product_question"),
                category=item.get("category", ""),
                category_l3=item.get("category_l3", ""),
                search_keywords=item.get("search_keywords", ""),
                product_scope_json=json.dumps(product_scope, ensure_ascii=False),
                sku_scope_json=json.dumps(sku_scope, ensure_ascii=False),
                platform_scope_json=json.dumps(platform_scope, ensure_ascii=False),
                risk_level=item.get("risk_level", "low"),
                auto_reply_allowed=True,
                human_review_required=False,
                status="published",
                index_status="ready",
                source_confidence=float(item.get("source_confidence", 0.95)),
                fact_review_status="verified",
                fact_type=item.get("fact_type", ""),
                fact_scope=item.get("fact_scope", "sku"),
                business_key=business_key,
                product_id=item.get("product_id", ""),
                sku_id=item.get("sku_id", ""),
                source_sheet="agent_phase1_golden_fixture",
                reviewed_by="golden_runner",
            )
            db.add(entry)
            db.flush()
            db.add(KnowledgeChunk(
                entry_id=entry.id,
                chunk_text=content,
                chunk_index=0,
                source_type=item.get("source_type", "product_facts"),
                intent=item.get("intent", "product_question"),
                product_scope_json=json.dumps(product_scope, ensure_ascii=False),
                sku_scope_json=json.dumps(sku_scope, ensure_ascii=False),
                platform_scope_json=json.dumps(platform_scope, ensure_ascii=False),
                metadata_json=json.dumps(metadata, ensure_ascii=False),
                category=item.get("category", ""),
                category_l3=item.get("category_l3", ""),
                search_keywords=item.get("search_keywords", ""),
                embedding_status="pending",
                source_confidence=float(item.get("source_confidence", 0.95)),
                fact_review_status="verified",
                fact_source_type="golden_fixture",
            ))
            seeded += 1
        db.commit()
        return seeded
    finally:
        db.close()


def _post_json(url: str, payload: dict, timeout: int) -> tuple[dict, int]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.time()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw[:500]}") from exc
    duration_ms = int((time.time() - started) * 1000)
    return json.loads(raw), duration_ms


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _check_ordered(text: str, terms: list[str]) -> bool:
    pos = -1
    for term in terms:
        next_pos = text.find(term, pos + 1)
        if next_pos < 0:
            return False
        pos = next_pos
    return True


def _trace_nodes(response: dict) -> list[str]:
    return [
        str(step.get("node", ""))
        for step in response.get("trace_steps", []) or []
        if isinstance(step, dict)
    ]


def _evaluate(case: dict, response: dict, duration_ms: int) -> dict:
    expect = case.get("expect", {}) or {}
    evidence = response.get("evidence_debug", {}) or {}
    reply = response.get("suggested_reply", "") or ""
    nodes = _trace_nodes(response)

    checks: dict[str, bool] = {}
    details: dict[str, object] = {}

    allowed_intents = expect.get("allowed_intents") or []
    if allowed_intents:
        checks["intent"] = response.get("intent") in allowed_intents
        details["intent"] = response.get("intent")

    allowed_risk = expect.get("allowed_risk_levels") or []
    if allowed_risk:
        checks["risk_level"] = response.get("risk_level") in allowed_risk
        details["risk_level"] = response.get("risk_level")

    if "need_human_review" in expect:
        actual_review = bool(
            response.get("need_human_review")
            or response.get("requires_human_review")
            or evidence.get("need_human_review")
        )
        checks["need_human_review"] = actual_review is bool(expect["need_human_review"])
        details["need_human_review"] = actual_review

    allowed_fact_types = expect.get("allowed_query_fact_types") or []
    if allowed_fact_types:
        actual_fact_type = evidence.get("query_fact_type") or response.get("query_fact_type")
        checks["query_fact_type"] = actual_fact_type in allowed_fact_types
        details["query_fact_type"] = actual_fact_type

    reply_all = expect.get("reply_must_contain_all") or []
    if reply_all:
        checks["reply_must_contain_all"] = all(term in reply for term in reply_all)

    reply_any = expect.get("reply_must_contain_any") or []
    if reply_any:
        checks["reply_must_contain_any"] = _contains_any(reply, reply_any)

    forbidden = expect.get("reply_must_not_contain") or []
    if forbidden:
        checks["reply_must_not_contain"] = all(term not in reply for term in forbidden)

    ordered = expect.get("reply_terms_in_order") or []
    if ordered:
        checks["reply_terms_in_order"] = _check_ordered(reply, ordered)

    trace_nodes = expect.get("trace_must_include") or []
    if trace_nodes:
        checks["trace_must_include"] = all(node in nodes for node in trace_nodes)

    max_duration = int(expect.get("max_duration_ms") or 30000)
    checks["duration"] = duration_ms <= max_duration
    details["duration_ms"] = duration_ms

    passed = all(checks.values()) if checks else True
    return {
        "case_id": case.get("case_id", ""),
        "name": case.get("name", ""),
        "passed": passed,
        "checks": checks,
        "details": details,
        "summary": {
            "intent": response.get("intent"),
            "risk_level": response.get("risk_level"),
            "need_human_review": bool(response.get("need_human_review") or response.get("requires_human_review")),
            "query_fact_type": evidence.get("query_fact_type"),
            "query_fact_type_source": evidence.get("query_fact_type_source"),
            "used_knowledge_titles": response.get("used_knowledge_titles") or evidence.get("used_knowledge_titles") or [],
            "used_fact_tools": response.get("used_fact_tools") or evidence.get("used_fact_tools") or [],
            "reply": reply,
            "trace_nodes": nodes,
        },
    }


def _write_reports(results: list[dict], report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = report_dir / f"agent_phase1_golden_{stamp}.json"
    md_path = report_dir / f"agent_phase1_golden_{stamp}.md"
    payload = {
        "total": len(results),
        "passed": sum(1 for item in results if item.get("passed")),
        "failed": sum(1 for item in results if not item.get("passed")),
        "results": results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Agent Phase 1 Golden Report",
        "",
        f"- total: {payload['total']}",
        f"- passed: {payload['passed']}",
        f"- failed: {payload['failed']}",
        "",
        "| case_id | result | intent | risk | fact_type | duration_ms |",
        "|---|---|---|---|---|---:|",
    ]
    for item in results:
        summary = item.get("summary", {}) or {}
        details = item.get("details", {}) or {}
        lines.append(
            "| {case_id} | {status} | {intent} | {risk} | {fact_type} | {duration} |".format(
                case_id=item.get("case_id", ""),
                status="PASS" if item.get("passed") else "FAIL",
                intent=summary.get("intent", ""),
                risk=summary.get("risk_level", ""),
                fact_type=summary.get("query_fact_type", ""),
                duration=details.get("duration_ms", ""),
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5011/ask/api/analyze")
    parser.add_argument("--case-dir", default=str(DEFAULT_CASE_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--timeout", type=int, default=35)
    args = parser.parse_args()

    case_dir = Path(args.case_dir)
    cases = _load_cases(case_dir)
    if not cases:
        print(f"No golden cases found in {case_dir}", file=sys.stderr)
        return 2

    seeded_count = _seed_knowledge_fixtures(case_dir)
    if seeded_count:
        print(f"seeded_golden_knowledge={seeded_count}")

    results: list[dict] = []
    for case in cases:
        payload = dict(case.get("request", {}) or {})
        payload.setdefault("conversation_id", f"agent_phase1_{case.get('case_id', '')}")
        try:
            response, duration_ms = _post_json(args.base_url, payload, args.timeout)
            result = _evaluate(case, response, duration_ms)
        except Exception as exc:
            result = {
                "case_id": case.get("case_id", ""),
                "name": case.get("name", ""),
                "passed": False,
                "checks": {"request": False},
                "details": {"error": str(exc)},
                "summary": {},
            }
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {result['case_id']} {result['name']}")
        if not result["passed"]:
            failed_checks = [name for name, ok in result.get("checks", {}).items() if not ok]
            print(f"  failed_checks={failed_checks} details={result.get('details', {})}")
            reply = (result.get("summary", {}) or {}).get("reply", "")
            if reply:
                print(f"  reply={reply[:240]}")

    json_path, md_path = _write_reports(results, Path(args.report_dir))
    passed = sum(1 for item in results if item.get("passed"))
    total = len(results)
    print(f"\n{passed}/{total} passed")
    print(f"json_report={json_path}")
    print(f"md_report={md_path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
