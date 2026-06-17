#!/usr/bin/env python3
"""Run premium manual cases against local /ask/api/analyze and record results."""
import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_PATH = os.path.join(BASE_DIR, "data", "premium_manual_cases.json")
OUT_PATH = os.path.join(BASE_DIR, "data", "premium_api_test_results.json")
URL = "http://127.0.0.1:5011/ask/api/analyze"


def load_cases():
    with open(CASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases", [])


def call_analyze(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code
    except Exception as e:
        return {"error": str(e)}, 0


def summarize_response(case_id, resp, status):
    dbg = resp.get("evidence_debug", {}) or {}
    ctx = resp.get("context_used", {}) or {}
    identity = dbg.get("order_product_identity") or {}
    tool_plan = dbg.get("tool_plan") or []
    tool_results = resp.get("tool_results") or dbg.get("tool_results") or {}
    rag_result = tool_results.get("rag_search_tool") or {}
    if not rag_result:
        # old chain
        rag_result = {"chunks": ctx.get("knowledge_evidence", []) or []}
    evidence_summary = dbg.get("knowledge_evidence_summary") or []
    filtered_summary = dbg.get("filtered_evidence_summary") or []
    gate_summary = dbg.get("evidence_gate_summary") or {}
    used_ids = ctx.get("used_knowledge_entry_ids") or dbg.get("used_knowledge_entry_ids") or []
    return {
        "case_id": case_id,
        "status": status,
        "error": resp.get("error"),
        "intent": resp.get("intent"),
        "risk_level": resp.get("risk_level"),
        "requires_human_review": resp.get("requires_human_review"),
        "reason_for_review": resp.get("reason_for_review"),
        "product_identity_status": identity.get("status"),
        "product_identity_source": identity.get("source"),
        "matched_product_name": identity.get("matched_product_name"),
        "sku_id": identity.get("sku_id"),
        "i_id": identity.get("i_id"),
        "strategy": resp.get("response_strategy"),
        "answer_mode": resp.get("answer_mode"),
        "allowed_source_types": dbg.get("allowed_source_types") or [],
        "tool_plan": tool_plan,
        "rag_chunks_count": rag_result.get("count") if rag_result.get("count") is not None else len(used_ids),
        "evidence_summary_count": len(evidence_summary),
        "filtered_summary_count": len(filtered_summary),
        "gate_allowed": gate_summary.get("allowed", 0),
        "gate_blocked": gate_summary.get("blocked", 0),
        "used_knowledge_entry_ids": used_ids,
        "query_fact_type": dbg.get("query_fact_type"),
        "request_duration_ms": dbg.get("request_duration_ms"),
        "suggested_reply": resp.get("suggested_reply"),
        "trace_steps": [s.get("node") for s in (resp.get("trace_steps") or [])],
    }


def main():
    cases = load_cases()
    print(f"Loaded {len(cases)} cases from {CASES_PATH}")
    results = []
    for i, case in enumerate(cases, 1):
        case_id = case.get("case_id", f"case_{i}")
        payload = case.get("payload", {})
        print(f"\n[{i}/{len(cases)}] {case_id}: {payload.get('message', '')[:40]}...")
        t0 = time.time()
        resp, status = call_analyze(payload)
        elapsed = int((time.time() - t0) * 1000)
        summary = summarize_response(case_id, resp, status)
        summary["elapsed_ms"] = elapsed
        results.append(summary)
        print(
            f"  status={status} intent={summary['intent']} risk={summary['risk_level']} "
            f"review={summary['requires_human_review']} product={summary['product_identity_status']} "
            f"rag={summary['rag_chunks_count']} used={len(summary['used_knowledge_entry_ids'])} "
            f"dur={elapsed}ms"
        )
        if summary.get("error"):
            print(f"  ERROR: {summary['error']}")
        # Be polite to external APIs
        time.sleep(0.5)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved results to {OUT_PATH}")

    # Quick stats
    ok = [r for r in results if r["status"] == 200 and not r.get("error")]
    failed = [r for r in results if r["status"] != 200 or r.get("error")]
    print(f"\nSummary: {len(ok)} OK, {len(failed)} failed, total {len(results)}")
    for r in failed:
        print(f"  FAILED: {r['case_id']} status={r['status']} error={r.get('error')}")


if __name__ == "__main__":
    main()
