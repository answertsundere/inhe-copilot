"""Run daily sanitized real conversation replay.

Default mode is dry-run: collect samples and print a sanitized summary without
writing eval cases, replay traces, failures, or repair tasks. Pass --apply to
write data and run the replay.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_dotenv_safely() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass


_load_dotenv_safely()

from app.services.eval_sanitizer_service import sanitize_obj
from app.services.real_conversation_daily_replay_service import (
    DailyReplayOptions,
    run_daily_real_conversation_replay,
)
from app.services.real_conversation_import_service import default_source_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=default_source_dir())
    parser.add_argument("--sample-limit", "--limit", dest="sample_limit", type=int, default=50)
    parser.add_argument("--date", default="")
    parser.add_argument("--min-turns", type=int, default=6)
    parser.add_argument("--json-output", "--output", dest="json_output", default="")
    parser.add_argument("--apply", action="store_true", help="write imported samples, replay traces, and failures")
    parser.add_argument("--sample-only", action="store_true", help="extract/import samples only, no Agent replay")
    parser.add_argument("--replay-only", action="store_true", help="skip extraction and replay existing real_conversation cases")
    parser.add_argument("--generate-repair-tasks", action="store_true", help="generate repair tasks after replay")
    parser.add_argument("--created-by", default="daily_replay")
    parser.add_argument("--eval-sidecar-product-title", default="", help="eval-only QianNiu sidecar product title")
    parser.add_argument("--eval-sidecar-sku-code", default="", help="eval-only QianNiu sidecar SKU code")
    parser.add_argument("--eval-sidecar-i-id", default="", help="eval-only internal product i_id")
    parser.add_argument("--eval-sidecar-order-id", default="", help="eval-only QianNiu sidecar order id")
    parser.add_argument("--disable-external-tools", action="store_true", help="eval replay only: skip live external tools")
    parser.add_argument("--external-tool-timeout-seconds", type=float, default=0, help="eval replay only: per-tool hard timeout")
    parser.add_argument(
        "--agent-turn-timeout-seconds",
        "--turn-timeout-seconds",
        dest="agent_turn_timeout_seconds",
        type=float,
        default=0,
        help="eval replay only: per-turn Agent hard timeout",
    )
    parser.add_argument("--progress-log", action="store_true", help="eval replay only: print sanitized per-turn progress")
    parser.add_argument(
        "--enable-pgvector-shadow-trace",
        action="store_true",
        help="eval replay only: record read-only pgvector shadow diagnostics in replay traces",
    )
    parser.add_argument("--pgvector-shadow-top-k", type=int, default=5, help="eval replay only: pgvector shadow top_k")
    return parser


def _json_for_file(report: dict[str, Any]) -> str:
    return json.dumps(sanitize_obj(report), ensure_ascii=False, indent=2)


def _print_json_safely(report: dict[str, Any]) -> None:
    """Print readable UTF-8 JSON, falling back when Windows console cannot encode it."""
    text = _json_for_file(report)
    try:
        print(text)
    except UnicodeEncodeError:
        print(json.dumps(sanitize_obj(report), ensure_ascii=True, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    eval_sidecar_context = {
        key: value
        for key, value in {
            "sidecar_product_title": args.eval_sidecar_product_title,
            "sidecar_sku_code": args.eval_sidecar_sku_code,
            "sidecar_i_id": args.eval_sidecar_i_id,
            "sidecar_order_id": args.eval_sidecar_order_id,
        }.items()
        if value
    }
    report = run_daily_real_conversation_replay(DailyReplayOptions(
        source_dir=args.source_dir,
        sample_limit=args.sample_limit,
        run_date=args.date,
        min_turns=args.min_turns,
        apply=args.apply,
        sample_only=args.sample_only,
        replay_only=args.replay_only,
        generate_repair_tasks=args.generate_repair_tasks,
        created_by=args.created_by,
        eval_sidecar_context=eval_sidecar_context,
        disable_external_tools=args.disable_external_tools,
        external_tool_timeout_seconds=args.external_tool_timeout_seconds,
        agent_turn_timeout_seconds=args.agent_turn_timeout_seconds,
        progress_log=args.progress_log,
        enable_pgvector_shadow_trace=args.enable_pgvector_shadow_trace,
        pgvector_shadow_top_k=args.pgvector_shadow_top_k,
    ))
    output = _json_for_file(report)
    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    _print_json_safely(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
