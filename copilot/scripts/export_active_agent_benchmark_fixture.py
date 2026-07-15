"""Create a synthetic semantic projection of reviewed active benchmark scenarios."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.eval_tables import AgentBenchmarkScenario
from app.services.agent_benchmark_fixture_service import (
    BenchmarkFixtureError,
    build_manifest,
    build_semantic_projection_fixture,
    validate_fixture,
)


def export_active_fixture(
    *,
    source_db: str,
    output_fixture: str,
    output_manifest: str,
    dataset_id: str,
    dataset_version: str,
    reviewed_at: str,
) -> dict:
    source = Path(source_db).expanduser().resolve()
    if not source.exists():
        raise BenchmarkFixtureError("source database does not exist")
    engine = create_engine(f"sqlite:///{source}")
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    db = session_factory()
    try:
        rows = (
            db.query(AgentBenchmarkScenario)
            .filter(AgentBenchmarkScenario.status == "active")
            .order_by(AgentBenchmarkScenario.id.asc())
            .all()
        )
        scenarios = [row.to_dict() for row in rows]
    finally:
        db.close()
        engine.dispose()
    payload = build_semantic_projection_fixture(
        scenarios,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        reviewed_at=reviewed_at,
    )
    validation = validate_fixture(payload)
    manifest = build_manifest(payload)
    fixture_target = Path(output_fixture)
    manifest_target = Path(output_manifest)
    fixture_target.parent.mkdir(parents=True, exist_ok=True)
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    fixture_target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"validation": validation, "manifest": manifest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a privacy-safe active benchmark fixture.")
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--output-fixture", required=True)
    parser.add_argument("--output-manifest", required=True)
    parser.add_argument("--dataset-id", default="active-benchmark-synthetic-v1")
    parser.add_argument("--dataset-version", default="1.0.0")
    parser.add_argument("--reviewed-at", default="2026-07-15")
    args = parser.parse_args(argv)
    try:
        report = export_active_fixture(
            source_db=args.source_db,
            output_fixture=args.output_fixture,
            output_manifest=args.output_manifest,
            dataset_id=args.dataset_id,
            dataset_version=args.dataset_version,
            reviewed_at=args.reviewed_at,
        )
    except BenchmarkFixtureError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
