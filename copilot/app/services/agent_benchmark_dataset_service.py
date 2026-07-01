"""Agent benchmark scenario dataset service.

The benchmark dataset is a curated eval layer. It never writes product
knowledge, media assets, or verified KB data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


ACTIVE_STATUSES = {"candidate", "curated", "active", "retired"}
SCENARIO_TYPES = {"presales", "aftersales", "logistics", "installation", "promotion", "mixed"}


def _new_scenario_uid() -> str:
    return f"bench_{uuid.uuid4().hex[:12]}"


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _first_text(*values: Any) -> str:
    for value in values:
        text = sanitize_text(value)
        if text:
            return text
    return ""


def _has_main_sidecar_context(sidecar: dict[str, Any]) -> bool:
    return bool(
        sidecar.get("product_title")
        or sidecar.get("product_name")
        or sidecar.get("sku_code")
        or sidecar.get("i_id")
        or sidecar.get("order_id")
        or sidecar.get("platform_order_id")
    )


def _extract_sidecar_context(trace) -> dict[str, Any]:
    answer_trace = trace.get_answer_trace()
    raw = trace.get_raw_response()
    product_identity = trace.get_product_identity()
    turn_understanding = trace.get_turn_understanding()

    for container in (answer_trace, raw, product_identity, turn_understanding):
        if not isinstance(container, dict):
            continue
        sidecar = container.get("sidecar_context")
        if isinstance(sidecar, dict) and sidecar:
            return sanitize_obj(sidecar)

    return sanitize_obj({
        "product_title": _first_text(
            raw.get("product_title") if isinstance(raw, dict) else "",
            answer_trace.get("product_title") if isinstance(answer_trace, dict) else "",
        ),
        "sku_code": _first_text(
            raw.get("sku_code") if isinstance(raw, dict) else "",
            answer_trace.get("sku_code") if isinstance(answer_trace, dict) else "",
        ),
        "i_id": _first_text(
            raw.get("i_id") if isinstance(raw, dict) else "",
            answer_trace.get("i_id") if isinstance(answer_trace, dict) else "",
        ),
        "order_id": "",
    })


def _scenario_type_from_trace(trace) -> str:
    qft = sanitize_text(trace.query_fact_type or "")
    labels = set(trace.get_failure_labels() or [])
    understanding = trace.get_turn_understanding()
    qft = qft or sanitize_text(understanding.get("query_fact_type") if isinstance(understanding, dict) else "")
    if qft in {"logistics", "order_status", "delivery_not_received"}:
        return "logistics"
    if qft in {"aftersales", "aftersales_policy", "after_sales"} or "aftersales" in labels:
        return "aftersales"
    if qft in {"installation", "accessory_usage", "accessory_availability", "accessory_compatibility"}:
        return "installation"
    if qft in {"promotion", "promotion_policy", "price_negotiation", "coupon", "discount"}:
        return "promotion"
    if qft:
        return "presales"
    return "mixed"


def _turns_for_case(db, case_uid: str) -> list[dict[str, Any]]:
    from app.models.eval_tables import EvalConversationTurn

    rows = (
        db.query(EvalConversationTurn)
        .filter(EvalConversationTurn.case_uid == case_uid)
        .order_by(EvalConversationTurn.turn_index.asc())
        .all()
    )
    return sanitize_obj([
        {
            "turn_uid": row.turn_uid,
            "turn_index": row.turn_index,
            "speaker": row.speaker,
            "text": row.sanitized_text,
            "reference_human_reply": row.reference_human_reply,
        }
        for row in rows
        if row.sanitized_text
    ])


def _expected_reply_from_trace(trace) -> dict[str, Any]:
    reference = sanitize_text(trace.reference_human_reply)
    return sanitize_obj({
        "expected_reply": reference,
        "key_points": [],
        "forbidden_claims": [],
        "must_handoff": bool(trace.requires_human_review),
        "auto_send_allowed": bool(trace.passed and not trace.requires_human_review),
        "needs_review": True,
        "draft_source": "reference_human_reply" if reference else "empty_candidate",
    })


class AgentBenchmarkDatasetService:
    def create_candidate_from_real_replay(
        self,
        run_uid: str,
        limit: int | None = None,
        apply: bool = False,
        created_by: str = "benchmark_generator",
        db_factory=None,
    ) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import AgentBenchmarkScenario, EvalRun, EvalTrace

        run_uid = sanitize_text(run_uid)
        if not run_uid:
            raise ValueError("run_uid is required")
        db_factory = db_factory or SessionLocal
        db = db_factory()
        try:
            run = db.query(EvalRun).filter(EvalRun.run_uid == run_uid).one_or_none()
            if run is None:
                return {"run_uid": run_uid, "apply": bool(apply), "created": 0, "skipped": 0, "candidates": [], "error": "run_not_found"}

            query = (
                db.query(EvalTrace)
                .filter(EvalTrace.run_uid == run_uid)
                .order_by(EvalTrace.turn_index.asc(), EvalTrace.id.asc())
            )
            if limit:
                query = query.limit(max(int(limit), 1))

            candidates: list[dict[str, Any]] = []
            created = 0
            skipped = 0
            for trace in query.all():
                quality_bucket = trace.get_quality_bucket()
                if (
                    quality_bucket.get("quality_bucket") == "unscored_or_noise"
                    and quality_bucket.get("should_count_in_quality_rate") is False
                ):
                    skipped += 1
                    continue
                source_uid = f"{trace.run_uid}:{trace.turn_uid}"
                existing = (
                    db.query(AgentBenchmarkScenario)
                    .filter(
                        AgentBenchmarkScenario.source_type == "real_conversation",
                        AgentBenchmarkScenario.source_uid == source_uid,
                    )
                    .one_or_none()
                )
                if apply and existing is not None:
                    skipped += 1
                    candidates.append(existing.to_dict())
                    continue

                sidecar = _extract_sidecar_context(trace)
                missing_sidecar = not _has_main_sidecar_context(sidecar)
                expected = _expected_reply_from_trace(trace)
                scenario_type = _scenario_type_from_trace(trace)
                turns = _turns_for_case(db, trace.case_uid)
                title = _first_text(trace.buyer_message, f"benchmark {trace.turn_uid}")[:120]
                metadata = sanitize_obj({
                    "source_run_uid": trace.run_uid,
                    "source_case_uid": trace.case_uid,
                    "source_turn_uid": trace.turn_uid,
                    "original_cs_reply": trace.reference_human_reply,
                    "created_from": "real_replay",
                    "missing_sidecar": missing_sidecar,
                    "failure_labels": trace.get_failure_labels(),
                    "quality_bucket": quality_bucket,
                    "query_fact_type": trace.query_fact_type,
                })
                payload = {
                    "scenario_uid": _new_scenario_uid(),
                    "source_type": "real_conversation",
                    "source_uid": source_uid,
                    "status": "candidate",
                    "title": title,
                    "scenario_type": scenario_type if scenario_type in SCENARIO_TYPES else "mixed",
                    "sidecar_context": sidecar,
                    "conversation_turns": turns,
                    "expected_reply": expected,
                    "rubric": {
                        "fact_correctness": True,
                        "empathy": True,
                        "next_step": True,
                        "evidence_grounding": True,
                        "tone": "customer_service",
                    },
                    "metadata": metadata,
                    "created_by": sanitize_text(created_by),
                }
                if apply:
                    row = AgentBenchmarkScenario(
                        scenario_uid=payload["scenario_uid"],
                        source_type=payload["source_type"],
                        source_uid=payload["source_uid"],
                        status="candidate",
                        title=payload["title"],
                        scenario_type=payload["scenario_type"],
                        created_by=payload["created_by"],
                        updated_by=payload["created_by"],
                    )
                    row.set_sidecar_context(payload["sidecar_context"])
                    row.set_conversation_turns(payload["conversation_turns"])
                    row.set_expected_reply(payload["expected_reply"])
                    row.set_rubric(payload["rubric"])
                    row.set_metadata(payload["metadata"])
                    db.add(row)
                    db.flush()
                    payload = row.to_dict()
                    created += 1
                candidates.append(sanitize_obj(payload))

            if apply:
                db.commit()
            return {
                "run_uid": run_uid,
                "apply": bool(apply),
                "created": created if apply else 0,
                "dry_run_count": len(candidates) if not apply else 0,
                "skipped": skipped,
                "candidates": candidates,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create_candidate_from_training_samples(self, limit: int | None = None, apply: bool = False) -> dict[str, Any]:
        return {
            "apply": bool(apply),
            "created": 0,
            "dry_run_count": 0,
            "skipped": 0,
            "candidates": [],
            "note": "No reviewed training-sample source is wired for benchmark extraction yet.",
        }

    def promote_to_active(self, scenario_uid: str, reviewer: str, db_factory=None) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import AgentBenchmarkScenario

        db_factory = db_factory or SessionLocal
        db = db_factory()
        try:
            row = (
                db.query(AgentBenchmarkScenario)
                .filter(AgentBenchmarkScenario.scenario_uid == sanitize_text(scenario_uid))
                .one_or_none()
            )
            if row is None:
                raise ValueError("scenario_not_found")
            sidecar = row.get_sidecar_context()
            expected = row.get_expected_reply()
            if not _has_main_sidecar_context(sidecar):
                raise ValueError("sidecar_context_required")
            if not sanitize_text(expected.get("expected_reply")):
                raise ValueError("expected_reply_required")
            metadata = row.get_metadata()
            history = metadata.get("status_history")
            if not isinstance(history, list):
                history = []
            history.append({
                "from": row.status,
                "to": "active",
                "reviewer": sanitize_text(reviewer),
                "at": _utc_now(),
            })
            metadata["status_history"] = history
            row.status = "active"
            row.updated_by = sanitize_text(reviewer)
            row.set_metadata(metadata)
            db.commit()
            return row.to_dict()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def list_scenarios(self, filters: dict[str, Any] | None = None, db_factory=None) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import AgentBenchmarkScenario

        filters = filters or {}
        db_factory = db_factory or SessionLocal
        db = db_factory()
        try:
            query = db.query(AgentBenchmarkScenario)
            for field in ("status", "source_type", "scenario_type"):
                value = sanitize_text(filters.get(field))
                if value:
                    query = query.filter(getattr(AgentBenchmarkScenario, field) == value)
            created_from = sanitize_text(filters.get("created_from"))
            rows = query.order_by(AgentBenchmarkScenario.created_at.desc(), AgentBenchmarkScenario.id.desc()).all()
            items = []
            for row in rows:
                item = row.to_dict()
                if created_from and item.get("metadata", {}).get("created_from") != created_from:
                    continue
                items.append(item)
            return {"total": len(items), "items": items}
        finally:
            db.close()

    def get_scenario_detail(self, scenario_uid: str, db_factory=None) -> dict[str, Any] | None:
        from app.db import SessionLocal
        from app.models.eval_tables import AgentBenchmarkScenario

        db_factory = db_factory or SessionLocal
        db = db_factory()
        try:
            row = (
                db.query(AgentBenchmarkScenario)
                .filter(AgentBenchmarkScenario.scenario_uid == sanitize_text(scenario_uid))
                .one_or_none()
            )
            return row.to_dict() if row else None
        finally:
            db.close()
