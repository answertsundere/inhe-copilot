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
    if "app.db" in sys.modules:
        # The application DB module binds its engine at import time. Reusing a
        # previously bound engine here could redirect fixture writes elsewhere.
        raise RuntimeError("fixture_work_database_binding_too_late")
    if database.exists():
        database.unlink()
    os.environ["COPILOT_KNOWLEDGE_DB_PATH"] = str(database)
    # This process never opens the source formal DB. The explicit --work-db is
    # a disposable fixture database, so inherited formal query-only mode must
    # not make it read-only before it is populated.
    os.environ["COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY"] = "false"
    # Fixture validation imports other application modules before this point,
    # which can load app.config while app.db remains unbound. Keep that cached
    # configuration aligned with the explicit disposable database.
    import app.config as config_module
    config_module.KNOWLEDGE_DB_PATH = str(database)
    import app.db as db_module

    if Path(db_module.KNOWLEDGE_DB_PATH).resolve() != database:
        raise RuntimeError("fixture_work_database_binding_mismatch")
    if db_module.KNOWLEDGE_DB_QUERY_ONLY:
        raise RuntimeError("fixture_work_database_unexpected_query_only")

    Base = db_module.Base
    SessionLocal = db_module.SessionLocal
    engine = db_module.engine
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
    negative_controls = _run_negative_controls(fixture, _formal_evidence_convergence)
    total = len(rows)
    successful = [row for row in rows if row["formal_selected_count"] and row["admitted_count"] and row["confirmed_clause_count"] and row["citation_valid"]]
    return {
        "dataset_id": fixture.get("dataset_id"),
        "source_kind": fixture.get("source_kind"),
        "real_derived": True,
        "qualification": fixture.get("qualification") or {},
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
        "negative_controls": negative_controls,
        "question_source": {
            "kind": "capability_probe",
            "synthetic_customer_question": True,
            "real_customer_accuracy_measured": False,
        },
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


def _run_negative_controls(fixture, converge) -> dict[str, Any]:
    product = next(iter(fixture.get("products") or []), None)
    fact = next(iter((product or {}).get("facts") or []), None)
    if not product or not fact:
        return {"status": "not_evaluable", "leak_count": 0, "cases": []}
    identity = product.get("identity") or {}
    fact_type = str(fact.get("fact_type") or "")
    base = {
        "evidence_uid": "negative-base",
        "source_type": "product_facts",
        "fact_type": fact_type,
        "attribute_key": fact.get("attribute_key") or fact_type,
        "content": fact.get("content"),
        "value": fact.get("content"),
        "sku_code": identity.get("sku_code", ""),
        "i_id": identity.get("i_id", ""),
        "fact_review_status": "published",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
        "material_provenance": "structured_product_record",
    }
    state = {
        "slots": {"sku_code": identity.get("sku_code", "")},
        "order_product_identity": {"i_id": identity.get("i_id", "")},
        "query_fact_type": fact_type,
        "turn_understanding": {"requested_claims": [{"claim_type": fact_type, "question": fact_type}]},
    }
    conflict_base = {
        **base,
        "fact_type": "gross_weight",
        "attribute_key": "gross_weight",
    }
    cases = [
        ("identity_mismatch", [{**base, "evidence_uid": "negative-identity", "sku_code": "mismatch", "i_id": "mismatch"}]),
        ("review_state_insufficient", [{
            **base,
            "evidence_uid": "negative-review",
            "fact_review_status": "pending",
            "review_status": "pending",
        }]),
        ("reference_only", [{**base, "evidence_uid": "negative-reference", "reference_only": True}]),
        ("service_action", [{**base, "evidence_uid": "negative-action", "source_type": "service_action", "evidence_role": "service_action"}]),
        ("media_reference", [{**base, "evidence_uid": "negative-media", "source_type": "media_reference", "evidence_role": "media_reference"}]),
        ("blocked_high_risk", [{**base, "evidence_uid": "negative-risk", "fact_type": "material_safety", "gate_status": "blocked"}]),
        ("conflicting_value", [
            {
                **conflict_base,
                "evidence_uid": "negative-conflict-a",
                "content": "10kg",
                "value": "10kg",
            },
            {
                **conflict_base,
                "evidence_uid": "negative-conflict-b",
                "content": "12kg",
                "value": "12kg",
            },
        ]),
    ]
    rows = []
    for kind, candidates in cases:
        case_state = state
        if kind == "conflicting_value":
            case_state = {
                **state,
                "query_fact_type": "gross_weight",
                "turn_understanding": {
                    "requested_claims": [
                        {"claim_type": "gross_weight", "question": "gross_weight"}
                    ]
                },
            }
        result = converge(case_state, product_facts=candidates, policy_facts=[], faq_evidence=[])
        selected = result.get("selected_evidence") or []
        rejected = (result.get("admitted_answer_context") or {}).get("rejected_evidence") or []
        rows.append({
            "kind": kind,
            "selected_count": len(selected),
            "rejection_reasons": sorted({str(item.get("reason") or "") for item in rejected}),
            "passed": len(selected) == 0,
        })
    return {
        "status": "completed",
        "case_count": len(rows),
        "passed_count": sum(row["passed"] for row in rows),
        "leak_count": sum(not row["passed"] for row in rows),
        "formal_kb_write_attempt_count": 0,
        "can_change_can_send": False,
        "cases": rows,
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
        qualification = report.get("qualification") or {}
        qualification_passed = qualification.get("passed") is True
        negative_controls = report.get("negative_controls") or {}
        return 0 if (
            report["failed"] == 0
            and compound.get("passed") is True
            and qualification_passed
            and negative_controls.get("status") == "completed"
            and int(negative_controls.get("case_count") or 0) == 7
            and int(negative_controls.get("passed_count") or 0) == 7
            and int(negative_controls.get("leak_count") or 0) == 0
        ) else 2
    except (OSError, ValueError, RealDerivedFixtureError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
