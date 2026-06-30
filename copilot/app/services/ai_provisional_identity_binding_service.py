"""Resolve product identity for AI provisional knowledge drafts.

The binding rules intentionally use only strong identity signals. Product
titles alone may be kept in the trace as candidates, but they must not bind a
provisional draft to an internal product.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


ACTIVE_MAPPING_STATUSES = {"active", "verified", "confirmed"}
RESOLVED_MIN_CONFIDENCE = 0.9


@dataclass(frozen=True)
class IdentityBindingResult:
    identity_status: str
    i_id: str = ""
    sku_code: str = ""
    kb_product_id: int | None = None
    product_title_preview: str = ""
    identity_sources: tuple[str, ...] = ()
    confidence: float = 0.0
    skipped_reason: str = ""
    ambiguous_candidates: tuple[dict[str, Any], ...] = ()
    trace: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return sanitize_obj({
            "identity_status": self.identity_status,
            "i_id": self.i_id,
            "sku_code": self.sku_code,
            "kb_product_id": self.kb_product_id,
            "product_title_preview": self.product_title_preview,
            "identity_sources": list(self.identity_sources),
            "confidence": self.confidence,
            "skipped_reason": self.skipped_reason,
            "ambiguous_candidates": list(self.ambiguous_candidates),
            "trace": self.trace or {},
        })


class AIProvisionalIdentityBindingService:
    def bind_for_task(self, db, task) -> IdentityBindingResult:
        from app.models.eval_tables import EvalTrace, KnowledgeGapTaskSample

        candidates: list[dict[str, Any]] = []
        weak_candidates: list[dict[str, Any]] = []

        task_candidate = self._resolve_from_iid_or_sku(
            db,
            i_id=sanitize_text(getattr(task, "item_id", "")),
            sku_code=sanitize_text(getattr(task, "sku_code", "")),
            source="knowledge_gap_task",
        )
        if task_candidate:
            candidates.append(task_candidate)

        for item in self._extract_identity_dicts(getattr(task, "get_metadata", lambda: {})()):
            resolved = self._resolve_identity_dict(db, item, source_prefix="task.metadata")
            if resolved:
                candidates.append(resolved)
            weak_candidates.extend(self._weak_candidates_from_identity(item))

        samples = (
            db.query(KnowledgeGapTaskSample)
            .filter(KnowledgeGapTaskSample.task_uid == task.task_uid)
            .order_by(KnowledgeGapTaskSample.id.asc())
            .all()
        )
        for sample in samples:
            trace = (
                db.query(EvalTrace)
                .filter(EvalTrace.turn_uid == sample.turn_uid)
                .order_by(EvalTrace.id.desc())
                .first()
            )
            if trace is None:
                for item in self._extract_identity_dicts(sample.get_trace_summary()):
                    resolved = self._resolve_identity_dict(db, item, source_prefix="sample.trace_summary")
                    if resolved:
                        candidates.append(resolved)
                    weak_candidates.extend(self._weak_candidates_from_identity(item))
                continue
            for source_name, payload in (
                ("eval_trace.product_identity", trace.get_product_identity()),
                ("eval_trace.answer_trace", trace.get_answer_trace()),
                ("eval_trace.raw_response", trace.get_raw_response()),
                ("eval_trace.turn_understanding", trace.get_turn_understanding()),
            ):
                for item in self._extract_identity_dicts(payload):
                    resolved = self._resolve_identity_dict(db, item, source_prefix=source_name)
                    if resolved:
                        candidates.append(resolved)
                    weak_candidates.extend(self._weak_candidates_from_identity(item))

        return self._merge_candidates(candidates, weak_candidates)

    def bind_for_draft(self, db, draft) -> IdentityBindingResult:
        task_uid = sanitize_text(getattr(draft, "task_uid", ""))
        if task_uid:
            try:
                from app.models.eval_tables import KnowledgeGapTask

                task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == task_uid).one_or_none()
                if task is not None:
                    return self.bind_for_task(db, task)
            except Exception:
                pass
        candidate = self._resolve_from_iid_or_sku(
            db,
            i_id=sanitize_text(getattr(draft, "i_id", "")),
            sku_code=sanitize_text(getattr(draft, "sku_code", "")),
            source="ai_provisional_knowledge",
        )
        if candidate:
            return self._merge_candidates([candidate], [])
        return IdentityBindingResult(identity_status="unresolved", skipped_reason="no_identity_signal")

    def _merge_candidates(
        self,
        candidates: list[dict[str, Any]],
        weak_candidates: list[dict[str, Any]],
    ) -> IdentityBindingResult:
        candidates = [item for item in candidates if item.get("i_id") or item.get("kb_product_id")]
        by_key: dict[tuple[str, int | None], dict[str, Any]] = {}
        for item in candidates:
            key = (sanitize_text(item.get("i_id")), item.get("kb_product_id"))
            existing = by_key.get(key)
            if existing:
                existing["identity_sources"] = _unique([
                    *(existing.get("identity_sources") or []),
                    *(item.get("identity_sources") or []),
                ])
                existing["confidence"] = max(float(existing.get("confidence") or 0), float(item.get("confidence") or 0))
                if not existing.get("sku_code") and item.get("sku_code"):
                    existing["sku_code"] = item.get("sku_code")
            else:
                by_key[key] = dict(item)

        if len(by_key) > 1:
            return IdentityBindingResult(
                identity_status="conflict",
                skipped_reason="identity_conflict",
                ambiguous_candidates=tuple(_compact_candidate(item) for item in by_key.values()),
                trace={"candidate_count": len(by_key)},
            )
        if len(by_key) == 1:
            item = next(iter(by_key.values()))
            return IdentityBindingResult(
                identity_status="resolved",
                i_id=sanitize_text(item.get("i_id")),
                sku_code=sanitize_text(item.get("sku_code")),
                kb_product_id=item.get("kb_product_id"),
                product_title_preview=sanitize_text(item.get("product_title_preview"))[:120],
                identity_sources=tuple(_unique(item.get("identity_sources") or [])),
                confidence=float(item.get("confidence") or 0.0),
                trace={"candidate_count": 1, "match_reason": item.get("match_reason", "")},
            )
        if weak_candidates:
            return IdentityBindingResult(
                identity_status="ambiguous",
                skipped_reason="weak_or_ambiguous_identity_only",
                ambiguous_candidates=tuple(_compact_candidate(item) for item in weak_candidates[:5]),
                trace={"candidate_count": len(weak_candidates)},
            )
        return IdentityBindingResult(identity_status="unresolved", skipped_reason="no_identity_signal")

    def _resolve_identity_dict(self, db, identity: dict[str, Any], *, source_prefix: str) -> dict[str, Any] | None:
        if not isinstance(identity, dict):
            return None
        status = sanitize_text(identity.get("status") or identity.get("identity_status"))
        confidence = _float(identity.get("identity_confidence") or identity.get("confidence"))
        if status == "resolved" and confidence and confidence < RESOLVED_MIN_CONFIDENCE:
            return None
        result = self._resolve_from_iid_or_sku(
            db,
            i_id=sanitize_text(
                identity.get("i_id")
                or identity.get("internal_i_id")
                or identity.get("resolved_i_id")
            ),
            sku_code=sanitize_text(
                identity.get("sku_code")
                or identity.get("sku")
                or identity.get("sku_id")
                or identity.get("order_sku_code")
            ),
            source=f"{source_prefix}.i_id_or_sku",
        )
        if result:
            if confidence:
                result["confidence"] = max(result["confidence"], confidence)
            return result

        platform_item_id = sanitize_text(
            identity.get("platform_item_id")
            or identity.get("platform_product_id")
            or identity.get("item_id")
            or identity.get("product_item_id")
        )
        platform_item_id_hash = sanitize_text(
            identity.get("platform_item_id_hash")
            or identity.get("platform_product_id_hash")
            or identity.get("item_id_hash")
            or identity.get("product_item_id_hash")
        )
        product_url = sanitize_text(identity.get("product_url"))
        return self._resolve_from_platform_mapping(
            db,
            platform_item_id=platform_item_id,
            platform_item_id_hash=platform_item_id_hash,
            product_url=product_url,
            source=f"{source_prefix}.platform_mapping",
        )

    def _resolve_from_iid_or_sku(self, db, *, i_id: str = "", sku_code: str = "", source: str) -> dict[str, Any] | None:
        from app.models.kb_tables import KBProduct

        product = None
        clean_iid = sanitize_text(i_id)
        clean_sku = sanitize_text(sku_code)
        if clean_iid:
            product = db.query(KBProduct).filter(KBProduct.i_id == clean_iid).one_or_none()
        if product is None and clean_sku:
            product = _find_product_by_sku(db, clean_sku)
        if product is None:
            return None
        return {
            "i_id": product.i_id,
            "sku_code": clean_sku,
            "kb_product_id": product.id,
            "product_title_preview": product.product_name,
            "identity_sources": [source],
            "confidence": 1.0,
            "match_reason": "exact_i_id_or_sku_match",
        }

    def _resolve_from_platform_mapping(
        self,
        db,
        *,
        platform_item_id: str = "",
        platform_item_id_hash: str = "",
        product_url: str = "",
        source: str,
    ) -> dict[str, Any] | None:
        from app.models.kb_tables import KBProduct, ProductIdentityMapping
        from sqlalchemy import or_
        from urllib.parse import urlsplit

        filters = []
        if platform_item_id:
            filters.append(ProductIdentityMapping.platform_item_id == platform_item_id)
        if platform_item_id_hash:
            filters.append(ProductIdentityMapping.platform_item_id_hash == platform_item_id_hash)
        host = ""
        if product_url:
            try:
                host = urlsplit(product_url).netloc.lower()
            except Exception:
                host = ""
        if host and (platform_item_id or platform_item_id_hash):
            filters.append(ProductIdentityMapping.product_url_host == host)
        if not filters:
            return None
        rows = (
            db.query(ProductIdentityMapping)
            .filter(ProductIdentityMapping.status.in_(list(ACTIVE_MAPPING_STATUSES)))
            .filter(or_(*filters))
            .limit(20)
            .all()
        )
        if not rows:
            return None
        product_ids = {row.kb_product_id for row in rows if row.kb_product_id}
        if len(product_ids) != 1:
            return {
                "identity_sources": [source],
                "confidence": 0.0,
                "match_reason": "ambiguous_product_identity_mapping",
            }
        row = rows[0]
        product = db.query(KBProduct).filter(KBProduct.id == row.kb_product_id).one_or_none()
        if product is None:
            return None
        return {
            "i_id": product.i_id,
            "sku_code": sanitize_text(row.sku_code),
            "kb_product_id": product.id,
            "product_title_preview": product.product_name,
            "identity_sources": [source, "product_identity_mappings"],
            "confidence": float(row.confidence or 0.96),
            "match_reason": "product_identity_mapping_match",
        }

    def _extract_identity_dicts(self, payload: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []

        def walk(value: Any, parent_key: str = "") -> None:
            if isinstance(value, dict):
                if _looks_like_identity(value, parent_key):
                    found.append(value)
                for key, child in value.items():
                    walk(child, str(key))
            elif isinstance(value, list):
                for child in value:
                    walk(child, parent_key)

        walk(payload)
        return found

    def _weak_candidates_from_identity(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(identity, dict):
            return []
        candidates = identity.get("ambiguous_candidates") or identity.get("candidates") or []
        result = []
        if isinstance(candidates, list):
            for candidate in candidates[:5]:
                if isinstance(candidate, dict):
                    result.append(candidate)
        if sanitize_text(identity.get("product_title") or identity.get("platform_product_title") or identity.get("order_product_title")):
            result.append({
                "product_title_preview": sanitize_text(
                    identity.get("product_title")
                    or identity.get("platform_product_title")
                    or identity.get("order_product_title")
                )[:120],
                "match_reason": "title_only_not_bound",
            })
        return result


def _looks_like_identity(value: dict[str, Any], parent_key: str) -> bool:
    if parent_key in {
        "product_identity",
        "real_context_product_identity",
        "resolved_product_identity",
        "product_identity_resolution",
        "product",
        "order_product_identity",
    }:
        return True
    keys = set(value.keys())
    return bool(keys & {
        "i_id",
        "internal_i_id",
        "sku_code",
        "sku",
        "sku_id",
        "order_sku_code",
        "platform_item_id",
        "platform_product_id",
        "item_id",
        "product_item_id",
        "platform_item_id_hash",
        "platform_product_id_hash",
        "item_id_hash",
        "product_item_id_hash",
        "product_url",
        "resolved_product_id",
    })


def _find_product_by_sku(db, sku_code: str):
    from app.models.kb_tables import KBProduct

    sku = sanitize_text(sku_code)
    if not sku:
        return None
    product = db.query(KBProduct).filter(KBProduct.i_id == sku).one_or_none()
    if product:
        return product
    rows = db.query(KBProduct).filter(KBProduct.sku_list_json.like(f"%{sku}%")).limit(20).all()
    for product in rows:
        for item in product.get_sku_list() or []:
            if isinstance(item, dict):
                values = [item.get("sku_code"), item.get("sku_id"), item.get("sku")]
            else:
                values = [item]
            if any(sanitize_text(value).upper() == sku.upper() for value in values):
                return product
    family = _sku_family(sku)
    if family:
        return db.query(KBProduct).filter(KBProduct.i_id == family).one_or_none()
    return None


def _sku_family(sku_code: str) -> str:
    text = sanitize_text(sku_code)
    if not text:
        return ""
    marker = text.find("B")
    if marker > 0:
        return text[:marker]
    return ""


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen = set()
    for value in values:
        text = sanitize_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _compact_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return sanitize_obj({
        "i_id": item.get("i_id") or item.get("internal_i_id") or "",
        "sku_code": item.get("sku_code") or item.get("sku") or item.get("sku_id") or "",
        "kb_product_id": item.get("kb_product_id"),
        "product_title_preview": item.get("product_title_preview")
        or item.get("display_product_name")
        or item.get("product_name")
        or item.get("platform_product_title")
        or item.get("order_product_title")
        or "",
        "match_reason": item.get("match_reason") or item.get("reason") or "",
    })
