"""Agent benchmark scenario dataset service.

The benchmark dataset is a curated eval layer. It never writes product
knowledge, media assets, or verified KB data.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


ACTIVE_STATUSES = {"candidate", "curated", "active", "retired"}
SCENARIO_TYPES = {"presales", "aftersales", "logistics", "installation", "promotion", "mixed"}
BUSINESS_REPLY_TERMS = (
    "材质",
    "尺寸",
    "承重",
    "重量",
    "毛重",
    "安装",
    "视频",
    "说明书",
    "配件",
    "补发",
    "退",
    "换",
    "退款",
    "物流",
    "快递",
    "发货",
    "优惠",
    "活动",
    "券",
    "价格",
    "送货",
    "上门",
    "订单",
    "售后",
    "检测",
    "报告",
    "味道",
    "通风",
)
WELCOME_TERMS = ("欢迎光临", "看中哪些宝贝", "我可以帮您介绍")
WAIT_TERMS = ("稍等", "等一下", "马上", "我看一下", "稍等亲", "稍等一下")
ACK_TERMS = ("好的", "可以的", "嗯嗯", "在的", "亲亲在的", "收到", "好哒")
HANDOFF_TERMS = ("人工客服", "请联系人工", "转人工", "有什么可以帮您")
URL_ONLY_RE = re.compile(r"^\s*(https?://\S+|\[SIGNED_URL_REDACTED:[^\]]+\]|\[LONG_URL_REDACTED:[^\]]+\])\s*$", re.I)


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


def is_low_quality_reference_reply(text: str) -> bool:
    """Return True when a CSR reference is not suitable as benchmark ground truth."""
    value = sanitize_text(text)
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return True
    if URL_ONLY_RE.match(value) or re.fullmatch(r"[\W_]+", compact):
        return True
    if any(term in compact for term in WELCOME_TERMS):
        return True
    if any(term in compact for term in HANDOFF_TERMS) and not any(term in compact for term in BUSINESS_REPLY_TERMS):
        return True
    if any(term in compact for term in WAIT_TERMS) and len(compact) <= 18:
        return True
    if any(compact == term or compact == f"{term}亲" or compact == f"{term}哦" for term in ACK_TERMS):
        return True
    if len(compact) <= 6 and not any(term in compact for term in BUSINESS_REPLY_TERMS):
        return True
    return False


def expected_reply_quality(text: str) -> dict[str, str]:
    text = sanitize_text(text)
    block_reason = _expected_reply_block_reason(text)
    if block_reason or is_low_quality_reference_reply(text):
        return {"quality": "missing" if not text else "low_quality", "block_reason": block_reason}
    return {"quality": "valid", "block_reason": ""}


def _expected_reply_block_reason(text: str) -> str:
    value = sanitize_text(text)
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return "missing_reference_reply"
    if URL_ONLY_RE.match(value):
        return "link_only_reference_reply"
    if any(term in compact for term in WELCOME_TERMS):
        return "welcome_reference_reply"
    if any(term in compact for term in WAIT_TERMS) and len(compact) <= 18:
        return "waiting_reference_reply"
    if any(compact == term or compact == f"{term}亲" or compact == f"{term}哦" for term in ACK_TERMS):
        return "acknowledgement_reference_reply"
    if any(term in compact for term in HANDOFF_TERMS) and not any(term in compact for term in BUSINESS_REPLY_TERMS):
        return "generic_handoff_reference_reply"
    if len(compact) <= 6 and not any(term in compact for term in BUSINESS_REPLY_TERMS):
        return "too_short_without_business_information"
    return ""


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


def build_expected_reply_candidate(trace, conversation_turns: list[dict[str, Any]], sidecar_context: dict[str, Any]) -> dict[str, Any]:
    reference = sanitize_text(trace.reference_human_reply)
    quality = expected_reply_quality(reference)
    is_low_quality = quality["quality"] != "valid"
    return sanitize_obj({
        "expected_reply": "" if is_low_quality else reference,
        "key_points": [],
        "forbidden_claims": [],
        "must_handoff": bool(trace.requires_human_review),
        "auto_send_allowed": bool(trace.passed and not trace.requires_human_review),
        "needs_review": True,
        "draft_source": "low_quality_reference_reply" if is_low_quality else "reference_human_reply",
        "quality": quality["quality"],
        "block_reason": quality["block_reason"],
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
            expected_quality_counts = {"valid": 0, "low_quality": 0, "missing": 0}
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
                scenario_type = _scenario_type_from_trace(trace)
                turns = _turns_for_case(db, trace.case_uid)
                expected = build_expected_reply_candidate(trace, turns, sidecar)
                expected_quality = expected.get("quality") or "missing"
                if not sanitize_text(trace.reference_human_reply):
                    expected_quality = "missing"
                expected_quality_counts[expected_quality] = expected_quality_counts.get(expected_quality, 0) + 1
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
                    "expected_reply_quality": expected_quality,
                    "expected_reply_block_reason": expected.get("block_reason", ""),
                    "reference_reply_preview": trace.reference_human_reply[:120],
                    "buyer_message_preview": trace.buyer_message[:120],
                    "needs_expected_reply_review": True,
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
                "valid_expected_count": expected_quality_counts.get("valid", 0),
                "low_quality_expected_count": expected_quality_counts.get("low_quality", 0),
                "missing_expected_count": expected_quality_counts.get("missing", 0),
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

    def _validate_active_row(
        self,
        row,
        reviewer: str,
        expected_reply_override: str | None = None,
    ) -> dict[str, Any]:
        reviewer = sanitize_text(reviewer)
        if not reviewer:
            return {"eligible": False, "reason": "reviewer_required"}
        if row is None:
            return {"eligible": False, "reason": "scenario_not_found", "reviewer": reviewer}

        sidecar = row.get_sidecar_context()
        expected = row.get_expected_reply()
        turns = row.get_conversation_turns()
        metadata = row.get_metadata()
        if not _has_main_sidecar_context(sidecar):
            return {"eligible": False, "reason": "sidecar_context_required", "reviewer": reviewer}
        if not turns:
            return {"eligible": False, "reason": "conversation_turns_required", "reviewer": reviewer}

        if expected_reply_override is not None:
            reply_text = sanitize_text(expected_reply_override)
            if not reply_text:
                return {"eligible": False, "reason": "expected_reply_required", "reviewer": reviewer}
            quality = expected_reply_quality(reply_text)
            if quality["quality"] != "valid":
                return {
                    "eligible": False,
                    "reason": quality["block_reason"] or "expected_reply_low_quality",
                    "reviewer": reviewer,
                }
            expected = dict(expected)
            metadata = dict(metadata)
            expected["expected_reply"] = reply_text
            expected["needs_review"] = False
            metadata["expected_reply_quality"] = "valid"

        if not sanitize_text(expected.get("expected_reply")):
            return {"eligible": False, "reason": "expected_reply_required", "reviewer": reviewer}
        if expected.get("needs_review") is not False:
            return {"eligible": False, "reason": "expected_reply_review_required", "reviewer": reviewer}
        if metadata.get("expected_reply_quality") != "valid":
            return {"eligible": False, "reason": "expected_reply_quality_required", "reviewer": reviewer}
        return {"eligible": True, "reason": "", "reviewer": reviewer}

    def validate_active_eligibility(
        self,
        scenario_uid: str,
        reviewer: str,
        expected_reply_override: str | None = None,
        db_factory=None,
    ) -> dict[str, Any]:
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
            result = self._validate_active_row(
                row,
                reviewer=reviewer,
                expected_reply_override=expected_reply_override,
            )
            result["scenario_uid"] = sanitize_text(scenario_uid)
            return sanitize_obj(result)
        finally:
            db.close()

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
            validation = self._validate_active_row(row, reviewer=reviewer)
            if not validation.get("eligible"):
                raise ValueError(validation.get("reason") or "active_eligibility_failed")
            reviewer = validation["reviewer"]
            metadata = row.get_metadata()
            history = metadata.get("status_history")
            if not isinstance(history, list):
                history = []
            history.append({
                "from": row.status,
                "to": "active",
                "reviewer": reviewer,
                "at": _utc_now(),
            })
            metadata["status_history"] = history
            row.status = "active"
            row.updated_by = reviewer
            row.set_metadata(metadata)
            db.commit()
            return row.to_dict()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def mark_expected_reply_reviewed(
        self,
        scenario_uid: str,
        reviewer: str,
        expected_reply: str | None = None,
        key_points: list[str] | None = None,
        forbidden_claims: list[str] | None = None,
        auto_send_allowed: bool | None = None,
        must_handoff: bool | None = None,
        review_note: str | None = None,
        db_factory=None,
    ) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import AgentBenchmarkScenario

        reviewer = sanitize_text(reviewer)
        if not reviewer:
            raise ValueError("reviewer_required")
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
            expected = row.get_expected_reply()
            if expected_reply is not None:
                expected["expected_reply"] = sanitize_text(expected_reply)
            if key_points is not None:
                expected["key_points"] = sanitize_obj(key_points)
            if forbidden_claims is not None:
                expected["forbidden_claims"] = sanitize_obj(forbidden_claims)
            if auto_send_allowed is not None:
                expected["auto_send_allowed"] = bool(auto_send_allowed)
            if must_handoff is not None:
                expected["must_handoff"] = bool(must_handoff)
            reply_text = sanitize_text(expected.get("expected_reply"))
            if not reply_text:
                raise ValueError("expected_reply_required")
            quality = expected_reply_quality(reply_text)
            if quality["quality"] != "valid":
                raise ValueError(quality["block_reason"] or "expected_reply_low_quality")
            expected["needs_review"] = False
            expected["quality"] = "valid"
            expected["block_reason"] = ""

            metadata = row.get_metadata()
            metadata["expected_reply_quality"] = "valid"
            metadata["expected_reply_block_reason"] = ""
            metadata["needs_expected_reply_review"] = False
            metadata["expected_reply_reviewed_by"] = reviewer
            metadata["expected_reply_reviewed_at"] = _utc_now()
            if review_note is not None:
                metadata["expected_reply_review_note"] = sanitize_text(review_note)
            row.updated_by = reviewer
            row.set_expected_reply(expected)
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
