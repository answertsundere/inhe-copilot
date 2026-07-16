"""Exercise a real-derived fixture through Pack, convergence, and preview.

The source database is never opened here.  A temporary fixture database is
constructed from the already-sanitised fixture, so the product-first path can
run without exposing source identities to the clean worktree.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_derived_evidence_fixture_service import (
    RealDerivedFixtureError,
    validate_real_derived_fixture,
)


def _load(fixture_path: str, manifest_path: str) -> dict[str, Any]:
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return validate_real_derived_fixture(fixture, manifest)


def _seed_fixture_database(fixture: dict[str, Any], database: Path) -> None:
    if database.name.lower() == "knowledge_base.db":
        raise ValueError("refusing_to_write_knowledge_base")
    if database.exists():
        database.unlink()
    os.environ["COPILOT_KNOWLEDGE_DB_PATH"] = str(database)
    from app.db import Base, SessionLocal, engine
    from app.models import kb_tables, knowledge_base  # noqa: F401
    from app.models.kb_tables import KBProduct

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        for index, product in enumerate(fixture.get("products") or [], start=1):
            identity = product.get("identity") or {}
            specs: dict[str, Any] = {}
            logistics: dict[str, Any] = {}
            warranty: dict[str, Any] = {}
            for fact in product.get("facts") or []:
                target = specs
                key = {"material": "material", "dimensions": "size", "gross_weight": "gross_weight_kg", "detachable": "detachable"}.get(fact.get("fact_type"), "")
                if not key:
                    continue
                target[key] = fact.get("content")
            session.add(KBProduct(
                id=index,
                i_id=str(identity.get("i_id") or ""),
                product_name=f"Fixture product {index}",
                sku_list_json=json.dumps([{"sku_code": identity.get("sku_code", "")}], ensure_ascii=False),
                specs_json=json.dumps(specs, ensure_ascii=False),
                logistics_json=json.dumps(logistics, ensure_ascii=False),
                warranty_json=json.dumps(warranty, ensure_ascii=False),
                status="published",
            ))
        session.commit()
    finally:
        session.close()


def run_vertical_slice(fixture: dict[str, Any], work_database: str | Path) -> dict[str, Any]:
    database = Path(work_database).expanduser().resolve()
    _seed_fixture_database(fixture, database)
    os.environ["COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED"] = "true"
    from app.agent.nodes.evidence_builder import _formal_evidence_convergence
    from app.services.product_context_pack_service import build_product_context_pack

    rows: list[dict[str, Any]] = []
    for product in fixture.get("products") or []:
        identity = product.get("identity") or {}
        for expected in product.get("facts") or []:
            fact_type = str(expected.get("fact_type") or "")
            state = {
                "customer_message": f"请核对当前商品的{fact_type}资料。",
                "normalized_message": f"请核对当前商品的{fact_type}资料。",
                "slots": {"sku_code": identity.get("sku_code", "")},
                "order_product_identity": {"i_id": identity.get("i_id", "")},
                "query_fact_type": fact_type,
                "turn_understanding": {"requested_claims": [{"claim_type": fact_type, "question": fact_type}]},
            }
            pack = build_product_context_pack(state, query=state["customer_message"], query_fact_type=fact_type)
            result = _formal_evidence_convergence(
                {**state, "product_context_pack": pack}, product_facts=[], policy_facts=[], faq_evidence=[]
            )
            selected = result.get("selected_evidence") or []
            preview = result.get("supervisor_candidate_preview") or {}
            confirmed = preview.get("confirmed_clauses") or []
            cited = {uid for clause in confirmed for uid in clause.get("evidence_uids") or []}
            selected_uids = {item.get("evidence_uid") for item in selected}
            rows.append({
                "fact_type": fact_type,
                "expected_provenance_hash": expected.get("provenance_hash"),
                "pack_candidate_count": len(pack.get("facts") or []),
                "formal_selected_count": len(selected),
                "admitted_count": len((result.get("admitted_answer_context") or {}).get("direct_product_facts") or []),
                "confirmed_clause_count": len(confirmed),
                "citation_valid": bool(cited and cited.issubset(selected_uids)),
                "preview_can_send": preview.get("can_send"),
                "preview_requires_human_review": preview.get("requires_human_review"),
                "preview_used_for_final_reply": preview.get("used_for_final_reply"),
                "formal_reply_changed": False,
            })
    compound = _compound_supported_and_unresolved(fixture, _formal_evidence_convergence, build_product_context_pack)
    total = len(rows)
    successful = [row for row in rows if row["formal_selected_count"] and row["admitted_count"] and row["confirmed_clause_count"] and row["citation_valid"]]
    return {
        "dataset_id": fixture.get("dataset_id"),
        "source_kind": fixture.get("source_kind"),
        "real_derived": True,
        "total": total,
        "passed": len(successful),
        "failed": total - len(successful),
        "metrics": {
            "eligible_fact_admission_rate": {"numerator": len(successful), "denominator": total, "rate": len(successful) / total if total else None},
            "formal_selected_rate": {"numerator": sum(row["formal_selected_count"] > 0 for row in rows), "denominator": total, "rate": sum(row["formal_selected_count"] > 0 for row in rows) / total if total else None},
            "admitted_evidence_rate": {"numerator": sum(row["admitted_count"] > 0 for row in rows), "denominator": total, "rate": sum(row["admitted_count"] > 0 for row in rows) / total if total else None},
            "confirmed_clause_coverage": {"numerator": sum(row["confirmed_clause_count"] > 0 for row in rows), "denominator": total, "rate": sum(row["confirmed_clause_count"] > 0 for row in rows) / total if total else None},
            "evidence_citation_rate": {"numerator": sum(row["citation_valid"] for row in rows), "denominator": total, "rate": sum(row["citation_valid"] for row in rows) / total if total else None},
        },
        "safety": {
            "can_send_change_count": sum(row["preview_can_send"] is not False for row in rows),
            "formal_reply_mutation_count": sum(row["formal_reply_changed"] is not False for row in rows),
            "requires_human_review_count": sum(row["preview_requires_human_review"] is True for row in rows),
            "used_for_final_reply_count": sum(row["preview_used_for_final_reply"] is True for row in rows),
        },
        "compound_supported_and_unresolved": compound,
        "by_fact_type": dict(Counter(row["fact_type"] for row in rows)),
        "rows": rows,
    }


def _compound_supported_and_unresolved(fixture, converge, build_pack) -> dict[str, Any]:
    """Check that one unsupported subclaim does not erase a real supported fact."""
    product = next((item for item in fixture.get("products") or [] if any(f.get("fact_type") == "material" for f in item.get("facts") or [])), None)
    if not product:
        return {"not_evaluable": True, "reason": "material_fact_missing"}
    identity = product.get("identity") or {}
    state = {
        "customer_message": "请核对当前商品的材质和安全说明。",
        "normalized_message": "请核对当前商品的材质和安全说明。",
        "slots": {"sku_code": identity.get("sku_code", "")},
        "order_product_identity": {"i_id": identity.get("i_id", "")},
        "query_fact_type": "material",
        "turn_understanding": {"requested_claims": [
            {"claim_type": "material_composition", "question": "material"},
            {"claim_type": "material_safety", "question": "safety", "risk_level": "high"},
        ]},
    }
    pack = build_pack(state, query=state["customer_message"], query_fact_type="material")
    result = converge({**state, "product_context_pack": pack}, product_facts=[], policy_facts=[], faq_evidence=[])
    statuses = {item.get("claim_type"): item.get("status") for item in (result.get("minimal_decision_context") or {}).get("claim_resolutions") or []}
    return {
        "not_evaluable": False,
        "statuses": statuses,
        "passed": statuses.get("material_composition") == "supported" and statuses.get("material_safety") == "unresolved",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--work-db", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    try:
        report = run_vertical_slice(_load(args.fixture, args.manifest), args.work_db)
        Path(args.json_output).write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: report[key] for key in ("total", "passed", "failed", "safety")}, ensure_ascii=False))
        compound = report.get("compound_supported_and_unresolved") or {}
        return 0 if report["failed"] == 0 and compound.get("passed") is True else 2
    except (OSError, ValueError, RealDerivedFixtureError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
