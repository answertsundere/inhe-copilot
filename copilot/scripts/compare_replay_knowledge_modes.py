"""Compare replay trace answerability between verified and provisional modes.

This script is intentionally read-only. It summarizes the current run and the
number of stored provisional drafts that could be used by eval mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db
from app.models.eval_tables import EvalRun, EvalTrace
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


def _latest_run_uid(db) -> str:
    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation", EvalRun.status == "completed")
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .first()
    )
    return run.run_uid if run else ""


def compare_modes(run_uid: str = "", sample_limit: int = 50) -> dict:
    from app.models.eval_tables import AIProvisionalKnowledge

    db = SessionLocal()
    try:
        target = sanitize_text(run_uid) or _latest_run_uid(db)
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == target)
            .order_by(EvalTrace.turn_index.asc(), EvalTrace.id.asc())
            .limit(max(1, int(sample_limit or 50)))
            .all()
        )
        buckets = Counter()
        failures = Counter()
        answer_sources = Counter()
        for trace in traces:
            raw = trace.get_raw_response() or {}
            bucket = raw.get("quality_bucket") if isinstance(raw, dict) else {}
            if isinstance(bucket, dict):
                buckets[bucket.get("quality_bucket") or "unknown"] += 1
            for label in trace.get_failure_labels() or []:
                failures[label] += 1
            answer_trace = trace.get_answer_trace() or {}
            source = answer_trace.get("final_answer_source") or answer_trace.get("selected_evidence_role") or ""
            if source:
                answer_sources[source] += 1
        provisional_count = db.query(AIProvisionalKnowledge).filter(
            AIProvisionalKnowledge.usable_for_eval == True,  # noqa: E712
            AIProvisionalKnowledge.usable_for_auto_send == False,  # noqa: E712
        ).count()
        return sanitize_obj({
            "run_uid": target,
            "sampled_turns": len(traces),
            "verified_only": {
                "quality_bucket_counts": dict(buckets),
                "failure_type_counts": dict(failures),
                "answer_source_counts": dict(answer_sources),
            },
            "verified_plus_ai_prefill": {
                "provisional_available_count": provisional_count,
                "provisional_used_count": 0,
                "note": "Run replay with COPILOT_EVAL_KNOWLEDGE_MODE=verified_plus_ai_prefill to measure live usage.",
            },
        })
    finally:
        db.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Compare verified-only and provisional eval knowledge modes.")
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--sample-limit", type=int, default=50)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    init_db()
    result = compare_modes(args.run_uid, args.sample_limit)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
