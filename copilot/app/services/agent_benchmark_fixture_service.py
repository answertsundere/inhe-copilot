"""Versioned, privacy-safe fixtures for reproducible Agent benchmarks."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import KNOWLEDGE_DB_PATH
from app.models.eval_tables import AgentBenchmarkScenario
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


FIXTURE_SCHEMA_VERSION = "agent-benchmark-fixture/v1"
FIXTURE_METADATA_TABLE = "benchmark_fixture_metadata"
_SENSITIVE_PATTERNS = {
    "phone": re.compile(r"(?<![0-9])1[0-9]{10}(?![0-9])"),
    "long_numeric_identifier": re.compile(r"(?<![A-Za-z0-9])[0-9]{12,}(?![0-9])"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "credential": re.compile(r"(?i:sk-|api[_-]?key|access[_-]?token|password|dsn)"),
    "address": re.compile(r"[\u4e00-\u9fff]{2,}(?:省|市|区|县|路|街|小区|镇|村)[\u4e00-\u9fff0-9-]{1,}"),
}
_ALLOWED_STATUSES = {"active"}
_SOURCE_METADATA_KEYS = {"query_fact_type", "source_turn_uid"}


class BenchmarkFixtureError(ValueError):
    """Raised when a benchmark fixture cannot be used safely."""


def canonical_fixture_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        sanitize_obj(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def fixture_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_fixture_bytes(payload)).hexdigest()


def _walk_strings(value: Any, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")


def scan_sensitive_content(payload: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for path, text in _walk_strings(payload):
        for category, pattern in _SENSITIVE_PATTERNS.items():
            if pattern.search(text):
                findings.append({"category": category, "path": path})
    return {
        "passed": not findings,
        "finding_count": len(findings),
        "findings": findings,
    }


def _fixture_fact_type(item: dict[str, Any]) -> str:
    expected = item.get("expected_reply") or {}
    rubric = item.get("rubric") or {}
    metadata = item.get("metadata") or {}
    return sanitize_text(
        metadata.get("query_fact_type")
        or expected.get("query_fact_type")
        or rubric.get("query_fact_type")
        or item.get("scenario_type")
    )


def _first_customer_turn(turns: list[dict[str, Any]], target_turn_uid: str = "") -> dict[str, Any] | None:
    customer_roles = {"buyer", "customer", "客户", "买家", ""}
    candidates = [
        item for item in turns or []
        if isinstance(item, dict) and sanitize_text(item.get("speaker")).lower() in customer_roles
    ]
    if target_turn_uid:
        for item in candidates:
            if sanitize_text(item.get("turn_uid")) == target_turn_uid:
                return item
    return candidates[-1] if candidates else None


def _synthetic_customer_message(scenario_type: str, fact_type: str) -> str:
    messages = {
        "installation": "请核对这款商品的安装资料和操作步骤。",
        "accessory_usage": "这个配件应该怎样安装和使用？",
        "accessory_availability": "这个配件是否可以补配？",
        "accessory_compatibility": "这个配件和当前商品是否适配？",
        "promotion": "请核对当前页面可用的优惠活动。",
        "promotion_policy": "请核对当前页面可用的优惠活动。",
        "price_negotiation": "请核对当前页面可用的优惠活动。",
        "aftersales": "收到商品后发现有破损，请协助核对售后处理。",
        "aftersales_policy": "收到商品后发现有破损，请协助核对售后处理。",
    }
    return messages.get(fact_type) or messages.get(scenario_type) or "请核对这款商品的相关信息。"


def _synthetic_sidecar(index: int) -> dict[str, str]:
    suffix = f"{index:02d}"
    return {
        "product_title": f"基准商品 {suffix}",
        "sku_code": f"FIXTURE-SKU-{suffix}",
        "i_id": f"FIXTURE-IID-{suffix}",
        "order_id": f"FIXTURE-ORDER-{suffix}",
    }


def build_semantic_projection_fixture(
    scenarios: list[dict[str, Any]],
    *,
    dataset_id: str,
    dataset_version: str,
    reviewed_at: str,
) -> dict[str, Any]:
    """Project reviewed scenarios without retaining raw conversations or IDs."""
    projected: list[dict[str, Any]] = []
    ordered = sorted(
        (sanitize_obj(item) for item in scenarios),
        key=lambda item: (
            sanitize_text(item.get("scenario_type")),
            _fixture_fact_type(item),
            sanitize_text(item.get("scenario_uid")),
        ),
    )
    for index, item in enumerate(ordered, start=1):
        status = sanitize_text(item.get("status") or "active")
        if status not in _ALLOWED_STATUSES:
            raise BenchmarkFixtureError(f"fixture export only supports active scenarios: {status}")
        expected = sanitize_obj(item.get("expected_reply") or {})
        rubric = sanitize_obj(item.get("rubric") or {})
        if not expected.get("key_points") or not expected.get("expected_reply"):
            raise BenchmarkFixtureError("reviewed benchmark scenario is missing expected reply or key points")
        fact_type = _fixture_fact_type(item)
        scenario_type = sanitize_text(item.get("scenario_type") or "mixed")
        fixture_uid = f"{dataset_id}-{index:03d}"
        projected.append({
            "scenario_uid": fixture_uid,
            "source_type": "benchmark_fixture",
            "source_uid": f"{dataset_id}-source-{index:03d}",
            "status": "active",
            "title": f"{scenario_type}/{fact_type}/case-{index:03d}",
            "scenario_type": scenario_type,
            "sidecar_context": _synthetic_sidecar(index),
            "conversation_turns": [{
                "turn_uid": f"{fixture_uid}-turn-1",
                "speaker": "buyer",
                "text": _synthetic_customer_message(scenario_type, fact_type),
            }],
            "expected_reply": expected,
            "rubric": rubric,
            "metadata": {
                "query_fact_type": fact_type,
                "source_turn_uid": f"{fixture_uid}-turn-1",
            },
        })
    payload = {
        "dataset_id": sanitize_text(dataset_id),
        "dataset_version": sanitize_text(dataset_version),
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "reviewed_at": sanitize_text(reviewed_at),
        "source": {
            "kind": "semantic_projection_of_reviewed_active_benchmark",
            "raw_transcript_included": False,
            "source_identifiers_included": False,
            "sidecar_identity_mode": "synthetic",
        },
        "scenarios": projected,
    }
    validate_fixture(payload)
    return payload


def validate_fixture(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BenchmarkFixtureError("fixture payload must be an object")
    for field in ("dataset_id", "dataset_version", "schema_version", "scenarios"):
        if not payload.get(field):
            raise BenchmarkFixtureError(f"fixture is missing {field}")
    if sanitize_text(payload.get("schema_version")) != FIXTURE_SCHEMA_VERSION:
        raise BenchmarkFixtureError("fixture schema version is unsupported")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise BenchmarkFixtureError("fixture has no scenarios")
    seen_uids: set[str] = set()
    categories: Counter[str] = Counter()
    for item in scenarios:
        if not isinstance(item, dict):
            raise BenchmarkFixtureError("fixture scenario must be an object")
        uid = sanitize_text(item.get("scenario_uid"))
        if not uid or uid in seen_uids:
            raise BenchmarkFixtureError("fixture has duplicate or empty scenario_uid")
        seen_uids.add(uid)
        if sanitize_text(item.get("status")) not in _ALLOWED_STATUSES:
            raise BenchmarkFixtureError("fixture contains an unsupported scenario status")
        if not isinstance(item.get("sidecar_context"), dict):
            raise BenchmarkFixtureError("fixture scenario is missing canonical sidecar context")
        turns = item.get("conversation_turns")
        if not isinstance(turns, list) or not _first_customer_turn(turns, sanitize_text((item.get("metadata") or {}).get("source_turn_uid"))):
            raise BenchmarkFixtureError("fixture scenario is missing its target customer turn")
        expected = item.get("expected_reply")
        if not isinstance(expected, dict) or not sanitize_text(expected.get("expected_reply")) or not expected.get("key_points"):
            raise BenchmarkFixtureError("fixture scenario is missing reviewed expected reply or rubric key points")
        if not isinstance(item.get("rubric"), dict):
            raise BenchmarkFixtureError("fixture scenario is missing rubric")
        categories[sanitize_text(item.get("scenario_type")) or "unknown"] += 1
    privacy = scan_sensitive_content(payload)
    if not privacy["passed"]:
        raise BenchmarkFixtureError("fixture privacy scan failed")
    return {
        "dataset_id": sanitize_text(payload.get("dataset_id")),
        "dataset_version": sanitize_text(payload.get("dataset_version")),
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "scenario_count": len(scenarios),
        "category_counts": dict(sorted(categories.items())),
        "fixture_sha256": fixture_sha256(payload),
        "privacy_scan": privacy,
    }


def build_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_fixture(payload)
    return {
        "dataset_id": validation["dataset_id"],
        "dataset_version": validation["dataset_version"],
        "schema_version": validation["schema_version"],
        "reviewed_at": sanitize_text(payload.get("reviewed_at")),
        "fixture_sha256": validation["fixture_sha256"],
        "scenario_count": validation["scenario_count"],
        "category_counts": validation["category_counts"],
        "privacy_declaration": {
            "contains_real_customer_conversations": False,
            "contains_production_order_identifiers": False,
            "contains_production_product_identifiers": False,
            "scan_passed": validation["privacy_scan"]["passed"],
        },
    }


def load_fixture(path: str | Path, manifest_path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkFixtureError(f"unable to load fixture: {type(exc).__name__}") from exc
    validation = validate_fixture(payload)
    manifest = build_manifest(payload)
    if manifest_path:
        try:
            stored_manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BenchmarkFixtureError(f"unable to load fixture manifest: {type(exc).__name__}") from exc
        for key in ("dataset_id", "dataset_version", "schema_version", "fixture_sha256", "scenario_count"):
            if stored_manifest.get(key) != manifest.get(key):
                raise BenchmarkFixtureError(f"fixture manifest mismatch: {key}")
        manifest = stored_manifest
    return payload, {**manifest, "validation": validation}


def _safe_database_path(path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    production = Path(KNOWLEDGE_DB_PATH).expanduser().resolve()
    if output == production or output.name.lower() == "knowledge_base.db":
        raise BenchmarkFixtureError("refusing to write a knowledge_base.db path")
    if output.exists():
        raise BenchmarkFixtureError("fixture database path already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def initialize_fixture_database(
    fixture_path: str | Path,
    database_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    payload, manifest = load_fixture(fixture_path, manifest_path)
    output = _safe_database_path(database_path)
    engine = create_engine(f"sqlite:///{output}")
    AgentBenchmarkScenario.__table__.create(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {FIXTURE_METADATA_TABLE} (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
        )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    reviewed_at = sanitize_text(payload.get("reviewed_at")) or "2026-01-01"
    try:
        created_at = datetime.fromisoformat(reviewed_at).replace(tzinfo=None)
    except ValueError:
        created_at = datetime(2026, 1, 1)
    db = session_factory()
    try:
        for item in payload["scenarios"]:
            row = AgentBenchmarkScenario(
                scenario_uid=sanitize_text(item["scenario_uid"]),
                source_type="benchmark_fixture",
                source_uid=sanitize_text(item["source_uid"]),
                status="active",
                title=sanitize_text(item["title"]),
                scenario_type=sanitize_text(item["scenario_type"]),
                created_by="benchmark_fixture",
                updated_by="benchmark_fixture",
                created_at=created_at,
                updated_at=created_at,
            )
            row.set_sidecar_context(item["sidecar_context"])
            row.set_conversation_turns(item["conversation_turns"])
            row.set_expected_reply(item["expected_reply"])
            row.set_rubric(item["rubric"])
            row.set_metadata(item["metadata"])
            db.add(row)
        db.commit()
    finally:
        db.close()
    metadata = {
        "dataset_id": manifest["dataset_id"],
        "dataset_version": manifest["dataset_version"],
        "schema_version": manifest["schema_version"],
        "fixture_sha256": manifest["fixture_sha256"],
        "scenario_count": str(manifest["scenario_count"]),
        "database_source": "versioned_fixture",
    }
    with engine.begin() as connection:
        for key, value in metadata.items():
            connection.exec_driver_sql(
                f"INSERT INTO {FIXTURE_METADATA_TABLE} (key, value) VALUES (?, ?)",
                (key, value),
            )
    engine.dispose()
    return {**manifest, "database_path": str(output), "database_source": "versioned_fixture"}


def fixture_database_metadata(path: str | Path) -> dict[str, str]:
    database = Path(path).expanduser().resolve()
    if not database.exists():
        raise BenchmarkFixtureError("fixture database does not exist")
    try:
        connection = sqlite3.connect(database)
        rows = connection.execute(f"SELECT key, value FROM {FIXTURE_METADATA_TABLE}").fetchall()
    except sqlite3.Error as exc:
        raise BenchmarkFixtureError(f"invalid fixture database: {type(exc).__name__}") from exc
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    metadata = {str(key): str(value) for key, value in rows}
    required = {"dataset_id", "dataset_version", "schema_version", "fixture_sha256", "scenario_count", "database_source"}
    if required - metadata.keys():
        raise BenchmarkFixtureError("fixture database metadata is incomplete")
    if metadata["schema_version"] != FIXTURE_SCHEMA_VERSION:
        raise BenchmarkFixtureError("fixture database schema version is unsupported")
    return metadata


def fixture_session_factory(path: str | Path):
    fixture_database_metadata(path)
    engine = create_engine(f"sqlite:///{Path(path).expanduser().resolve()}")
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
