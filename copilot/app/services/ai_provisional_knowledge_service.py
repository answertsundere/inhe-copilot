"""Staging-only AI provisional knowledge for replay/eval experiments."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from app.db import SessionLocal
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text, stable_hash


EVAL_MODE_VERIFIED_ONLY = "verified_only"
EVAL_MODE_WITH_PREFILL = "verified_plus_ai_prefill"
ALLOWED_EVAL_MODES = {EVAL_MODE_VERIFIED_ONLY, EVAL_MODE_WITH_PREFILL}
PROVISIONAL_USABLE_STATUSES = {"ai_prefill", "pending_review", "approved"}
PROVISIONAL_FACT_TYPE_ALIASES = {
    "promotion": {"promotion", "promotion_policy", "activity_rule", "coupon", "discount", "gift_policy", "price_negotiation"},
    "promotion_policy": {"promotion", "promotion_policy", "activity_rule", "coupon", "discount", "gift_policy", "price_negotiation"},
    "price_negotiation": {"promotion", "promotion_policy", "price_negotiation"},
    "stock_shipping": {"stock_shipping", "shipping", "delivery"},
    "shipping": {"stock_shipping", "shipping", "delivery"},
    "delivery": {"stock_shipping", "shipping", "delivery"},
}
HIGH_RISK_FACT_TYPES = {
    "dimensions",
    "gross_weight",
    "load_capacity",
    "material",
    "applicable_age",
    "certification_report",
    "safety",
    "installation_video",
    "3c",
    "food_grade",
}
NON_KNOWLEDGE_REFERENCE_TEXTS = {
    "好的",
    "好的亲",
    "好",
    "嗯嗯",
    "可以的",
    "收到",
    "稍等",
}


def current_eval_knowledge_mode() -> str:
    mode = sanitize_text(os.getenv("COPILOT_EVAL_KNOWLEDGE_MODE", EVAL_MODE_VERIFIED_ONLY)).lower()
    return mode if mode in ALLOWED_EVAL_MODES else EVAL_MODE_VERIFIED_ONLY


def provisional_enabled_for_eval() -> bool:
    return current_eval_knowledge_mode() == EVAL_MODE_WITH_PREFILL


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _draft_uid(*parts: Any) -> str:
    raw = "|".join(sanitize_text(part) for part in parts)
    return f"aipk_{stable_hash(raw, 18)}"


def _confidence_for_fact_type(fact_type: str, has_reference: bool) -> str:
    if sanitize_text(fact_type) in HIGH_RISK_FACT_TYPES:
        return "low"
    return "medium" if has_reference else "low"


def _fact_type_aliases(fact_type: str) -> set[str]:
    clean = sanitize_text(fact_type)
    if not clean:
        return set()
    return set(PROVISIONAL_FACT_TYPE_ALIASES.get(clean, {clean}))


def _provisional_answer(*, question: str, reference_reply: str, fact_type: str, product_title: str) -> tuple[str, str]:
    reference = sanitize_text(reference_reply)
    if reference.strip() in NON_KNOWLEDGE_REFERENCE_TEXTS or len(reference.strip()) <= 2:
        reference = ""
    if reference:
        return reference[:500], reference[:500]
    label = sanitize_text(fact_type) or "product_fact"
    title = sanitize_text(product_title)
    if label in HIGH_RISK_FACT_TYPES:
        return "", ""
    if title:
        answer = f"关于{title}的{label}问题，建议客服结合当前商品资料核对后回复。"
    else:
        answer = f"关于{label}问题，建议客服结合当前商品资料核对后回复。"
    return "", answer[:500]


def _metadata_from_task(task, sample: dict[str, Any] | None, *, source: str) -> dict[str, Any]:
    return sanitize_obj({
        "source": source,
        "source_task_uid": getattr(task, "task_uid", ""),
        "gap_type": getattr(task, "gap_type", ""),
        "failure_type": getattr(task, "failure_type", ""),
        "suggested_fix_area": getattr(task, "suggested_fix_area", ""),
        "missing_evidence_type": getattr(task, "missing_evidence_type", ""),
        "sample": sample or {},
        "created_from": "knowledge_gap_task",
        "formal_verified": False,
    })


def _latest_real_conversation_run_uid(db) -> str:
    try:
        from app.models.eval_tables import EvalRun
        run = (
            db.query(EvalRun)
            .filter(EvalRun.source_type == "real_conversation", EvalRun.status == "completed")
            .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
            .first()
        )
        return sanitize_text(run.run_uid) if run else ""
    except Exception:
        return ""


def _sample_for_task(db, task) -> dict[str, Any]:
    try:
        from app.models.eval_tables import KnowledgeGapTaskSample
        sample = (
            db.query(KnowledgeGapTaskSample)
            .filter(KnowledgeGapTaskSample.task_uid == task.task_uid)
            .order_by(KnowledgeGapTaskSample.id.asc())
            .first()
        )
    except Exception:
        sample = None
    if sample is None:
        return {}
    return {
        "run_uid": sample.run_uid,
        "case_uid": sample.case_uid,
        "turn_uid": sample.turn_uid,
        "buyer_message": sample.buyer_message,
        "reference_human_reply": sample.reference_human_reply,
        "agent_reply": sample.agent_reply,
    }


def _product_id_for_i_id(db, i_id: str) -> int | None:
    if not i_id:
        return None
    try:
        from app.models.kb_tables import KBProduct
        product = db.query(KBProduct).filter(KBProduct.i_id == i_id).one_or_none()
        return product.id if product else None
    except Exception:
        return None


class AIProvisionalKnowledgeService:
    def generate_for_run(
        self,
        *,
        run_uid: str = "",
        limit: int = 100,
        apply: bool = False,
        db_factory=None,
    ) -> dict[str, Any]:
        from app.models.eval_tables import AIProvisionalKnowledge, KnowledgeGapTask

        db_factory = db_factory or SessionLocal
        db = db_factory()
        generated = 0
        skipped: list[dict[str, Any]] = []
        drafts: list[dict[str, Any]] = []
        try:
            query = db.query(KnowledgeGapTask).order_by(KnowledgeGapTask.updated_at.desc(), KnowledgeGapTask.id.desc())
            target_run_uid = sanitize_text(run_uid) or _latest_real_conversation_run_uid(db)
            tasks = query.limit(500).all()
            if target_run_uid:
                try:
                    from app.services.knowledge_gap_task_service import filter_tasks_by_run
                    tasks = filter_tasks_by_run(db, tasks, target_run_uid)
                except Exception:
                    tasks = [task for task in tasks if target_run_uid in (task.metadata_json or "")]
            from app.services.ai_provisional_identity_binding_service import AIProvisionalIdentityBindingService
            identity_binder = AIProvisionalIdentityBindingService()
            for task in tasks[:max(1, min(int(limit or 100), 500))]:
                sample = _sample_for_task(db, task)
                fact_type = sanitize_text(task.query_fact_type or task.missing_evidence_type or task.gap_type)
                field_name = sanitize_text(task.missing_evidence_type or fact_type)
                identity_binding = identity_binder.bind_for_task(db, task)
                value, answer = _provisional_answer(
                    question=sample.get("buyer_message", ""),
                    reference_reply=sample.get("reference_human_reply", ""),
                    fact_type=fact_type,
                    product_title=task.product_title,
                )
                has_basis = bool(value or answer)
                bound_i_id = identity_binding.i_id if identity_binding.identity_status == "resolved" else ""
                bound_sku_code = identity_binding.sku_code if identity_binding.identity_status == "resolved" else ""
                usable_for_eval = bool(has_basis and identity_binding.identity_status == "resolved")
                draft_uid = _draft_uid(task.task_uid, fact_type, bound_i_id, bound_sku_code, value, answer)
                existing = db.query(AIProvisionalKnowledge).filter(AIProvisionalKnowledge.draft_uid == draft_uid).one_or_none()
                if existing:
                    skipped.append({"task_uid": task.task_uid, "reason": "existing_draft", "draft_uid": draft_uid})
                    drafts.append(existing.to_dict())
                    continue
                draft = AIProvisionalKnowledge(
                    draft_uid=draft_uid,
                    source_run_uid=target_run_uid or sanitize_text(task.get_metadata().get("source_run_uid")),
                    case_uid=sample.get("case_uid", ""),
                    turn_uid=sample.get("turn_uid", ""),
                    task_uid=task.task_uid,
                    kb_product_id=identity_binding.kb_product_id,
                    i_id=bound_i_id,
                    sku_code=bound_sku_code,
                    query_fact_type=fact_type,
                    field_name=field_name,
                    provisional_value=value,
                    provisional_answer=answer,
                    confidence=_confidence_for_fact_type(fact_type, has_basis),
                    source="ai_prefill",
                    verification_status="pending_review" if has_basis else "ai_prefill",
                    usable_for_eval=usable_for_eval,
                    usable_for_auto_send=False,
                    created_by="ai_prefill_service",
                )
                metadata = _metadata_from_task(task, sample, source="generate_for_run")
                metadata["identity_binding_trace"] = identity_binding.to_dict()
                metadata["identity_status"] = identity_binding.identity_status
                if has_basis and identity_binding.identity_status != "resolved":
                    metadata["usable_for_eval_blocked_reason"] = identity_binding.skipped_reason or identity_binding.identity_status
                draft.set_metadata(metadata)
                drafts.append(draft.to_dict())
                generated += 1
                if apply:
                    db.add(draft)
            if apply:
                db.commit()
            else:
                db.rollback()
            return sanitize_obj({
                "ok": True,
                "dry_run": not apply,
                "run_uid": target_run_uid,
                "generated_count": generated,
                "skipped_count": len(skipped),
                "skipped_reasons": skipped,
                "drafts": drafts,
                "writes_verified_knowledge": False,
            })
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def import_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        apply: bool = False,
        operator: str = "",
        db_factory=None,
    ) -> dict[str, Any]:
        from app.models.eval_tables import AIProvisionalKnowledge

        db_factory = db_factory or SessionLocal
        db = db_factory()
        matched = 0
        skipped: list[dict[str, Any]] = []
        updated: list[str] = []
        try:
            for index, row in enumerate(rows, start=2):
                fact_type = sanitize_text(row.get("query_fact_type") or row.get("field_name"))
                value = sanitize_text(row.get("provisional_value"))
                answer = sanitize_text(row.get("provisional_answer"))
                i_id = sanitize_text(row.get("i_id"))
                sku_code = sanitize_text(row.get("sku_code"))
                status = sanitize_text(row.get("verification_status") or "pending_review")
                if status == "verified":
                    skipped.append({"row": index, "reason": "verified_status_not_allowed"})
                    continue
                if not (value or answer):
                    skipped.append({"row": index, "reason": "empty_provisional_content"})
                    continue
                draft_uid = sanitize_text(row.get("draft_uid")) or _draft_uid(
                    row.get("source_run_uid"), row.get("case_uid"), row.get("turn_uid"), i_id, sku_code, fact_type, value, answer
                )
                identity_binding = None
                if i_id or sku_code:
                    from app.services.ai_provisional_identity_binding_service import AIProvisionalIdentityBindingService
                    identity_binding = AIProvisionalIdentityBindingService()._merge_candidates([
                        item for item in [
                            AIProvisionalIdentityBindingService()._resolve_from_iid_or_sku(
                                db,
                                i_id=i_id,
                                sku_code=sku_code,
                                source="manual_ai_provisional_import",
                            )
                        ] if item
                    ], [])
                    if identity_binding.identity_status != "resolved":
                        skipped.append({"row": index, "reason": "identity_not_resolved"})
                        continue
                existing = db.query(AIProvisionalKnowledge).filter(AIProvisionalKnowledge.draft_uid == draft_uid).one_or_none()
                draft = existing or AIProvisionalKnowledge(draft_uid=draft_uid)
                draft.source_run_uid = sanitize_text(row.get("source_run_uid"))
                draft.case_uid = sanitize_text(row.get("case_uid"))
                draft.turn_uid = sanitize_text(row.get("turn_uid"))
                draft.task_uid = sanitize_text(row.get("task_uid"))
                draft.i_id = i_id
                draft.sku_code = sku_code
                draft.kb_product_id = identity_binding.kb_product_id if identity_binding else _product_id_for_i_id(db, i_id)
                draft.query_fact_type = fact_type
                draft.field_name = sanitize_text(row.get("field_name") or fact_type)
                draft.provisional_value = value
                draft.provisional_answer = answer
                draft.confidence = sanitize_text(row.get("confidence") or _confidence_for_fact_type(fact_type, True))
                draft.source = "ai_prefill"
                draft.verification_status = status if status in PROVISIONAL_USABLE_STATUSES else "pending_review"
                requested_eval = str(row.get("usable_for_eval", "true")).strip().lower() not in {"false", "0", "no"}
                draft.usable_for_eval = bool(requested_eval and (draft.i_id or draft.sku_code))
                draft.usable_for_auto_send = False
                draft.created_by = sanitize_text(operator or row.get("created_by"))
                metadata = {
                    "source": "manual_ai_provisional_import",
                    "operator": operator,
                    "imported_at": _now_iso(),
                    "formal_verified": False,
                    "note": row.get("note", ""),
                }
                if identity_binding:
                    metadata["identity_binding_trace"] = identity_binding.to_dict()
                    metadata["identity_status"] = identity_binding.identity_status
                draft.set_metadata(sanitize_obj(metadata))
                matched += 1
                updated.append(draft_uid)
                if apply:
                    db.add(draft)
            if apply:
                db.commit()
            else:
                db.rollback()
            return sanitize_obj({
                "ok": True,
                "dry_run": not apply,
                "matched_count": matched,
                "skipped_count": len(skipped),
                "skipped_reasons": skipped,
                "updated_draft_uids": updated,
                "writes_verified_knowledge": False,
            })
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def backfill_identity(
        self,
        *,
        run_uid: str = "",
        apply: bool = False,
        limit: int = 500,
        db_factory=None,
    ) -> dict[str, Any]:
        from app.models.eval_tables import AIProvisionalKnowledge
        from app.services.ai_provisional_identity_binding_service import AIProvisionalIdentityBindingService

        db_factory = db_factory or SessionLocal
        db = db_factory()
        matched = 0
        skipped: list[dict[str, Any]] = []
        updated: list[str] = []
        try:
            query = db.query(AIProvisionalKnowledge).order_by(AIProvisionalKnowledge.updated_at.desc(), AIProvisionalKnowledge.id.desc())
            if sanitize_text(run_uid):
                query = query.filter(AIProvisionalKnowledge.source_run_uid == sanitize_text(run_uid))
            rows = query.limit(max(1, min(int(limit or 500), 2000))).all()
            binder = AIProvisionalIdentityBindingService()
            for row in rows:
                binding = binder.bind_for_draft(db, row)
                metadata = row.get_metadata()
                metadata["identity_binding_trace"] = binding.to_dict()
                metadata["identity_status"] = binding.identity_status
                if binding.identity_status != "resolved":
                    metadata["usable_for_eval_blocked_reason"] = binding.skipped_reason or binding.identity_status
                    skipped.append({
                        "draft_uid": row.draft_uid,
                        "reason": binding.skipped_reason or binding.identity_status,
                    })
                    if apply:
                        row.usable_for_eval = False
                        row.set_metadata(metadata)
                    continue
                matched += 1
                updated.append(row.draft_uid)
                if apply:
                    row.i_id = binding.i_id
                    row.sku_code = binding.sku_code
                    row.kb_product_id = binding.kb_product_id
                    row.usable_for_eval = bool(row.provisional_value or row.provisional_answer)
                    row.usable_for_auto_send = False
                    row.set_metadata(metadata)
            if apply:
                db.commit()
            else:
                db.rollback()
            return sanitize_obj({
                "ok": True,
                "dry_run": not apply,
                "run_uid": sanitize_text(run_uid),
                "matched_count": matched,
                "skipped_count": len(skipped),
                "skipped_reasons": skipped,
                "updated_draft_uids": updated,
                "writes_verified_knowledge": False,
                "auto_send_enabled": False,
            })
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def find_eval_evidence(
        self,
        *,
        i_id: str = "",
        sku_code: str = "",
        query_fact_type: str = "",
        limit: int = 5,
        db=None,
    ) -> list[dict[str, Any]]:
        if not provisional_enabled_for_eval():
            return []
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            from app.models.eval_tables import AIProvisionalKnowledge

            query = db.query(AIProvisionalKnowledge).filter(
                AIProvisionalKnowledge.usable_for_eval == True,  # noqa: E712
                AIProvisionalKnowledge.usable_for_auto_send == False,  # noqa: E712
                AIProvisionalKnowledge.verification_status.in_(list(PROVISIONAL_USABLE_STATUSES)),
            )
            identifiers = []
            if sanitize_text(i_id):
                identifiers.append(AIProvisionalKnowledge.i_id == sanitize_text(i_id))
            if sanitize_text(sku_code):
                identifiers.append(AIProvisionalKnowledge.sku_code == sanitize_text(sku_code))
            if identifiers:
                from sqlalchemy import or_
                query = query.filter(or_(*identifiers))
            else:
                return []
            aliases = _fact_type_aliases(query_fact_type)
            if aliases:
                query = query.filter(AIProvisionalKnowledge.query_fact_type.in_(list(aliases)))
            rows = query.order_by(AIProvisionalKnowledge.updated_at.desc(), AIProvisionalKnowledge.id.desc()).limit(limit).all()
            return [self.to_evidence(row) for row in rows]
        finally:
            if close_db:
                db.close()

    @staticmethod
    def to_evidence(row) -> dict[str, Any]:
        text = sanitize_text(row.provisional_answer or row.provisional_value)
        metadata = row.get_metadata()
        identity_trace = metadata.get("identity_binding_trace") if isinstance(metadata, dict) else {}
        identity_sources = []
        identity_status = ""
        if isinstance(identity_trace, dict):
            identity_sources = identity_trace.get("identity_sources") or []
            identity_status = identity_trace.get("identity_status") or ""
        return sanitize_obj({
            "evidence_id": row.draft_uid,
            "entry_id": row.draft_uid,
            "chunk_id": row.draft_uid,
            "title": f"AI provisional {row.query_fact_type}",
            "chunk_text": text,
            "preview": text[:240],
            "source_type": "product_facts",
            "protocol_source_type": "ai_prefill",
            "source_table": "ai_provisional_knowledge",
            "source_id": row.draft_uid,
            "verification_status": row.verification_status,
            "identity_status": identity_status or ("resolved" if row.i_id or row.sku_code or row.kb_product_id else "unresolved"),
            "identity_sources": identity_sources,
            "i_id": row.i_id,
            "sku_code": row.sku_code,
            "kb_product_id": row.kb_product_id,
            "fact_type": row.query_fact_type,
            "evidence_fact_type": row.query_fact_type,
            "score": 6.0 if row.confidence == "medium" else 4.0,
            "rerank_score": 6.0 if row.confidence == "medium" else 4.0,
            "product_context_pack": True,
            "direct_answer_allowed": True,
            "evidence_allowed_for_direct_answer": True,
            "can_direct_answer": True,
            "needs_human_review": True,
            "usable_for_eval": bool(row.usable_for_eval),
            "usable_for_auto_send": False,
            "provisional_draft_uid": row.draft_uid,
            "provisional_knowledge_used": True,
            "metadata": {
                "source": "ai_prefill",
                "usable_for_eval": bool(row.usable_for_eval),
                "usable_for_auto_send": False,
                "verification_status": row.verification_status,
                "identity_status": identity_status or ("resolved" if row.i_id or row.sku_code or row.kb_product_id else "unresolved"),
                "identity_sources": identity_sources,
                "i_id": row.i_id,
                "sku_code": row.sku_code,
                "kb_product_id": row.kb_product_id,
                "confidence": row.confidence,
            },
        })
