"""Repair task aggregation for real conversation QA replay."""

import uuid
from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.real_conversation_quality_bucket_service import bucket_from_trace, should_generate_repair_task


REVIEW_DECISION_FIX_AREAS = {
    "incorrect": "manual_triage",
    "needs_knowledge": "knowledge_rag",
    "needs_rule": "agent_rules",
    "needs_media": "media_pipeline",
    "needs_human_policy": "human_policy_risk_boundary",
}

FIX_AREA_OWNERS = {
    "knowledge_rag": "knowledge_ops",
    "agent_rules": "agent_engineering",
    "media_pipeline": "media_ops",
    "human_policy_risk_boundary": "customer_service_lead",
    "manual_triage": "customer_service_lead",
    "evidence_rerank_answer_composition": "agent_engineering",
    "final_audit_semantic_compiler": "agent_quality",
    "risk_audit": "risk_policy",
    "product_identity_product_data": "product_data",
    "tool_policy": "agent_engineering",
    "system_stability": "engineering",
    "answer_composition": "agent_engineering",
}

VALID_TASK_STATUSES = {"open", "in_progress", "resolved", "ignored"}
VALID_TASK_PRIORITIES = {"low", "medium", "high"}


@dataclass
class RepairTaskGenerationResult:
    run_uid: str
    generated: int
    updated: int
    skipped_correct: int
    tasks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_uid": self.run_uid,
            "generated": self.generated,
            "updated": self.updated,
            "skipped_correct": self.skipped_correct,
            "tasks": self.tasks,
        }


def _new_task_uid() -> str:
    return f"repair_{uuid.uuid4().hex[:12]}"


def _latest_run_uid(db) -> str:
    from app.models.eval_tables import EvalRun

    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation")
        .order_by(EvalRun.created_at.desc())
        .first()
    )
    return run.run_uid if run else ""


def _latest_reviews_by_turn(reviews) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for review in reviews:
        latest[review.turn_uid] = review
    return latest


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    values = []
    seen = set()
    for value in [*existing, *incoming]:
        cleaned = sanitize_text(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            values.append(cleaned)
    return values


def _priority_for(severities: list[str]) -> str:
    severity_set = set(severities)
    if "high" in severity_set:
        return "high"
    if "low" in severity_set and len(severity_set) == 1:
        return "low"
    return "medium"


def _title_for(failure_type: str, fix_area: str, owner: str) -> str:
    return sanitize_text(f"{fix_area or 'manual_triage'} / {failure_type or 'manual_review'}")


def _description_for(failure_type: str, fix_area: str, sample_count: int) -> str:
    return sanitize_text(
        f"{sample_count} replay sample(s) require follow-up for {failure_type or 'manual_review'} "
        f"in {fix_area or 'manual_triage'}."
    )


class RealConversationRepairTaskService:
    def generate_for_run(self, db, run_uid: str | None = None, created_by: str = "") -> RepairTaskGenerationResult:
        from app.models.eval_tables import EvalFailure, EvalRepairTask, EvalReview, EvalTrace

        target_run_uid = sanitize_text(run_uid) or _latest_run_uid(db)
        if not target_run_uid:
            return RepairTaskGenerationResult("", 0, 0, 0, [])

        failures = (
            db.query(EvalFailure)
            .filter(EvalFailure.run_uid == target_run_uid)
            .order_by(EvalFailure.id.asc())
            .all()
        )
        reviews = (
            db.query(EvalReview)
            .filter(EvalReview.run_uid == target_run_uid)
            .order_by(EvalReview.id.asc())
            .all()
        )
        failures_by_turn: dict[str, list] = {}
        for failure in failures:
            failures_by_turn.setdefault(failure.turn_uid, []).append(failure)
        traces = {
            trace.turn_uid: trace
            for trace in db.query(EvalTrace).filter(EvalTrace.run_uid == target_run_uid).all()
        }
        latest_reviews = _latest_reviews_by_turn(reviews)
        correct_turns = {
            turn_uid
            for turn_uid, review in latest_reviews.items()
            if sanitize_text(review.decision) == "correct"
        }
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        skipped_correct = 0
        failure_turns = set()

        for failure in failures:
            failure_turns.add(failure.turn_uid)
            if failure.turn_uid in correct_turns:
                skipped_correct += 1
                continue
            trace = traces.get(failure.turn_uid)
            bucket = bucket_from_trace(trace, failures_by_turn.get(failure.turn_uid, [])) if trace else {}
            if not should_generate_repair_task(str(bucket.get("quality_bucket") or "")):
                continue
            review = latest_reviews.get(failure.turn_uid)
            fix_area = sanitize_text(getattr(review, "suggested_fix_area", "")) if review else ""
            if not fix_area:
                fix_area = sanitize_text(failure.suggested_fix_area) or "manual_triage"
            owner = FIX_AREA_OWNERS.get(fix_area) or sanitize_text(failure.suggested_owner) or "customer_service_lead"
            failure_type = sanitize_text(failure.failure_type) or "manual_review"
            self._add_grouped_failure(
                grouped,
                failure_type=failure_type,
                fix_area=fix_area,
                owner=owner,
                case_uid=failure.case_uid,
                turn_uid=failure.turn_uid,
                severity=failure.severity,
                message=failure.message or failure.explanation,
                review_decision=sanitize_text(getattr(review, "decision", "")) if review else "",
            )

        for review in reviews:
            decision = sanitize_text(review.decision)
            if decision == "correct" or review.turn_uid in failure_turns:
                continue
            fix_area = sanitize_text(review.suggested_fix_area) or REVIEW_DECISION_FIX_AREAS.get(decision, "")
            if not fix_area:
                continue
            self._add_grouped_failure(
                grouped,
                failure_type="manual_review",
                fix_area=fix_area,
                owner=FIX_AREA_OWNERS.get(fix_area, "customer_service_lead"),
                case_uid=review.case_uid,
                turn_uid=review.turn_uid,
                severity="medium",
                message=review.reason,
                review_decision=decision,
            )

        generated = 0
        updated = 0
        tasks = []
        for (fix_area, owner, failure_type), item in grouped.items():
            task = (
                db.query(EvalRepairTask)
                .filter(
                    EvalRepairTask.run_uid == target_run_uid,
                    EvalRepairTask.suggested_fix_area == fix_area,
                    EvalRepairTask.suggested_owner == owner,
                    EvalRepairTask.failure_type == failure_type,
                )
                .order_by(EvalRepairTask.id.asc())
                .first()
            )
            if task is None:
                task = EvalRepairTask(
                    task_uid=_new_task_uid(),
                    run_uid=target_run_uid,
                    task_type="real_conversation_repair",
                    failure_type=failure_type,
                    suggested_fix_area=fix_area,
                    suggested_owner=owner,
                    created_by=sanitize_text(created_by),
                )
                generated += 1
                db.add(task)
            else:
                updated += 1
                if not task.task_uid:
                    task.task_uid = _new_task_uid()

            case_uids = _merge_unique(task.get_related_case_uids(), item["case_uids"])
            turn_uids = _merge_unique(task.get_related_turn_uids(), item["turn_uids"])
            task.case_uid = case_uids[0] if case_uids else ""
            task.turn_uid = turn_uids[0] if turn_uids else ""
            task.title = _title_for(failure_type, fix_area, owner)
            task.description = _description_for(failure_type, fix_area, len(turn_uids))
            task.sample_count = len(turn_uids)
            task.set_related_case_uids(case_uids)
            task.set_related_turn_uids(turn_uids)
            task.priority = _priority_for(item["severities"])
            task.note = task.description
            task.set_metadata(sanitize_obj({
                "failure_messages": item["messages"][:10],
                "review_decisions": sorted(item["review_decisions"]),
            }))
            tasks.append(task)

        db.commit()
        return RepairTaskGenerationResult(
            run_uid=target_run_uid,
            generated=generated,
            updated=updated,
            skipped_correct=skipped_correct,
            tasks=[sanitize_obj(task.to_dict()) for task in tasks],
        )

    def _add_grouped_failure(
        self,
        grouped: dict[tuple[str, str, str], dict[str, Any]],
        *,
        failure_type: str,
        fix_area: str,
        owner: str,
        case_uid: str,
        turn_uid: str,
        severity: str,
        message: str,
        review_decision: str,
    ) -> None:
        key = (sanitize_text(fix_area), sanitize_text(owner), sanitize_text(failure_type))
        if key not in grouped:
            grouped[key] = {
                "case_uids": [],
                "turn_uids": [],
                "severities": [],
                "messages": [],
                "review_decisions": set(),
            }
        item = grouped[key]
        item["case_uids"].append(sanitize_text(case_uid))
        item["turn_uids"].append(sanitize_text(turn_uid))
        item["severities"].append(sanitize_text(severity) or "medium")
        if message:
            item["messages"].append(sanitize_text(message))
        if review_decision:
            item["review_decisions"].add(sanitize_text(review_decision))
