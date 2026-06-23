"""Import sanitized real conversations as evaluation cases."""

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.eval_sanitizer_service import hash_sensitive, sanitize_obj, sanitize_text


BUYER_SPEAKERS = {"buyer", "customer", "user", "client", "买家", "客户", "用户", "顾客"}
SERVICE_SPEAKERS = {"seller", "service", "agent", "csr", "客服", "商家", "店铺"}


@dataclass
class ImportedTurn:
    turn_index: int
    speaker: str
    sanitized_text: str
    message_type: str = "text"
    timestamp: str = ""
    product_hint: str = ""
    order_hint_hash: str = ""
    reference_human_reply: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportedConversation:
    conversation_uid: str
    source_file: str
    platform: str
    shop_name: str
    extracted_at: str
    turns: list[ImportedTurn]
    metadata: dict[str, Any] = field(default_factory=dict)


def _stable_uid(*parts: str, prefix: str = "rc") -> str:
    raw = "|".join(str(p or "") for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _normalize_speaker(value: str) -> str:
    text = str(value or "").strip()
    low = text.lower()
    if low in BUYER_SPEAKERS or text in BUYER_SPEAKERS:
        return "buyer"
    if low in SERVICE_SPEAKERS or text in SERVICE_SPEAKERS:
        return "service"
    if "客" in text and "服" not in text:
        return "buyer"
    if "客服" in text or "商家" in text:
        return "service"
    return low or "unknown"


def _text_from_record(record: dict[str, Any]) -> str:
    for key in ("text", "content", "message", "msg", "body", "raw_text"):
        value = record.get(key)
        if value:
            return str(value)
    return ""


def _turns_from_json_obj(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        if all(isinstance(item, dict) for item in obj):
            return obj
        return []
    if not isinstance(obj, dict):
        return []
    for key in ("turns", "messages", "conversation", "chat_records", "records"):
        value = obj.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _metadata_from_json_obj(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    return {
        "platform": sanitize_text(obj.get("platform") or obj.get("channel") or ""),
        "shop_name": sanitize_text(obj.get("shop_name") or obj.get("shop") or ""),
        "conversation_id_hash": hash_sensitive(str(obj.get("conversation_id") or obj.get("id") or "")) if (obj.get("conversation_id") or obj.get("id")) else "",
    }


def _parse_json_file(path: Path) -> list[tuple[list[dict[str, Any]], dict[str, Any]]]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
        loaded = json.loads(raw)
    except Exception:
        return []
    if isinstance(loaded, list) and loaded and all(isinstance(item, dict) and _turns_from_json_obj(item) for item in loaded):
        return [(_turns_from_json_obj(item), _metadata_from_json_obj(item)) for item in loaded]
    turns = _turns_from_json_obj(loaded)
    return [(turns, _metadata_from_json_obj(loaded))] if turns else []


def _parse_jsonl_file(path: Path) -> list[tuple[list[dict[str, Any]], dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except Exception:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        conv = str(item.get("conversation_id") or item.get("session_id") or item.get("chat_id") or path.stem)
        groups.setdefault(conv, []).append(item)
    return [(turns, {"conversation_id_hash": hash_sensitive(key)}) for key, turns in groups.items()]


_TEXT_LINE_RE = re.compile(r"^\s*(买家|客户|用户|顾客|客服|商家|店铺|buyer|customer|service|seller|agent)\s*[:：]\s*(.+?)\s*$", re.I)


def _parse_text_file(path: Path) -> list[tuple[list[dict[str, Any]], dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except Exception:
        return []
    turns = []
    for line in lines:
        match = _TEXT_LINE_RE.match(line)
        if not match:
            continue
        turns.append({"speaker": match.group(1), "text": match.group(2), "message_type": "text"})
    return [(turns, {})] if turns else []


def _parse_csv_file(path: Path) -> list[tuple[list[dict[str, Any]], dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                conv = str(row.get("conversation_id") or row.get("session_id") or row.get("chat_id") or path.stem)
                groups.setdefault(conv, []).append(row)
    except Exception:
        return []
    return [(turns, {"conversation_id_hash": hash_sensitive(key)}) for key, turns in groups.items()]


def iter_conversation_files(source_dir: str) -> list[Path]:
    root = Path(source_dir)
    if not root.exists():
        return []
    suffixes = {".json", ".jsonl", ".txt", ".csv"}
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)


def parse_source_file(path: Path) -> list[ImportedConversation]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw_groups = _parse_json_file(path)
    elif suffix == ".jsonl":
        raw_groups = _parse_jsonl_file(path)
    elif suffix == ".csv":
        raw_groups = _parse_csv_file(path)
    else:
        raw_groups = _parse_text_file(path)

    conversations: list[ImportedConversation] = []
    for group_index, (records, meta) in enumerate(raw_groups):
        turns: list[ImportedTurn] = []
        for idx, record in enumerate(records):
            speaker = _normalize_speaker(
                record.get("speaker") or record.get("role") or record.get("sender") or record.get("from") or ""
            )
            raw_text = _text_from_record(record)
            sanitized = sanitize_text(raw_text)
            if not sanitized:
                continue
            order_hash = ""
            raw_order = record.get("order_id") or record.get("tid") or record.get("tracking_no") or ""
            if raw_order:
                order_hash = hash_sensitive(str(raw_order))
            turns.append(ImportedTurn(
                turn_index=len(turns),
                speaker=speaker,
                sanitized_text=sanitized,
                message_type=sanitize_text(record.get("message_type") or record.get("type") or "text") or "text",
                timestamp=sanitize_text(record.get("timestamp") or record.get("time") or record.get("created_at") or ""),
                product_hint=sanitize_text(record.get("product_hint") or record.get("product_name") or record.get("item_title") or ""),
                order_hint_hash=order_hash,
                metadata=sanitize_obj({
                    "source_row_index": idx,
                    "raw_speaker": record.get("speaker") or record.get("role") or record.get("sender") or "",
                }),
            ))
        if not turns:
            continue
        for idx, turn in enumerate(turns):
            if turn.speaker == "buyer":
                next_service = next((t.sanitized_text for t in turns[idx + 1:] if t.speaker == "service"), "")
                turn.reference_human_reply = next_service
        uid = _stable_uid(str(path.resolve()), str(group_index), "|".join(t.sanitized_text for t in turns[:8]))
        conversations.append(ImportedConversation(
            conversation_uid=uid,
            source_file=str(path),
            platform=str(meta.get("platform") or ""),
            shop_name=str(meta.get("shop_name") or ""),
            extracted_at=datetime.utcnow().isoformat(),
            turns=turns,
            metadata=sanitize_obj(meta),
        ))
    return conversations


def collect_real_conversation_samples(
    source_dir: str,
    limit: int = 50,
    min_turns: int = 6,
    date: str | None = None,
) -> list[ImportedConversation]:
    samples: list[ImportedConversation] = []
    for path in iter_conversation_files(source_dir):
        if date and date not in path.name and date not in str(path.parent):
            continue
        for conversation in parse_source_file(path):
            buyer_turns = [t for t in conversation.turns if t.speaker == "buyer"]
            if len(conversation.turns) < min_turns or not buyer_turns:
                continue
            samples.append(conversation)
            if len(samples) >= limit:
                return samples
    return samples


def write_samples_to_db(samples: list[ImportedConversation]) -> dict[str, int]:
    from app.db import SessionLocal
    from app.models.eval_tables import EvalCase, EvalConversationTurn

    db = SessionLocal()
    stats = {"cases_created": 0, "cases_updated": 0, "turns_created": 0, "turns_updated": 0}
    try:
        for conv in samples:
            case_uid = _stable_uid(conv.conversation_uid, prefix="case")
            first_buyer = next((t for t in conv.turns if t.speaker == "buyer"), conv.turns[0])
            case = db.query(EvalCase).filter(EvalCase.case_uid == case_uid).one_or_none()
            if case is None:
                case = EvalCase(case_uid=case_uid, source_type="real_conversation")
                db.add(case)
                stats["cases_created"] += 1
            else:
                stats["cases_updated"] += 1
            case.source_ref = conv.source_file
            case.title = f"real conversation {conv.conversation_uid}"
            case.message = first_buyer.sanitized_text
            case.status = "active"
            case.set_expected({})
            case.set_metadata({
                "conversation_uid": conv.conversation_uid,
                "source_file": conv.source_file,
                "platform": conv.platform,
                "shop_name": conv.shop_name,
                "extracted_at": conv.extracted_at,
                "turn_count": len(conv.turns),
                **conv.metadata,
            })
            for turn in conv.turns:
                turn_uid = _stable_uid(case_uid, str(turn.turn_index), turn.sanitized_text, prefix="turn")
                row = db.query(EvalConversationTurn).filter(EvalConversationTurn.turn_uid == turn_uid).one_or_none()
                if row is None:
                    row = EvalConversationTurn(turn_uid=turn_uid)
                    db.add(row)
                    stats["turns_created"] += 1
                else:
                    stats["turns_updated"] += 1
                row.case_uid = case_uid
                row.conversation_uid = conv.conversation_uid
                row.turn_index = turn.turn_index
                row.speaker = turn.speaker
                row.message_type = turn.message_type
                row.sanitized_text = turn.sanitized_text
                row.product_hint = turn.product_hint
                row.order_hint_hash = turn.order_hint_hash
                row.timestamp = turn.timestamp
                row.reference_human_reply = turn.reference_human_reply
                row.set_metadata(turn.metadata)
        db.commit()
        return stats
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def build_import_report(samples: list[ImportedConversation], apply: bool, stats: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "apply": apply,
        "sample_count": len(samples),
        "stats": stats or {},
        "samples": [
            {
                "conversation_uid": item.conversation_uid,
                "source_file": item.source_file,
                "platform": item.platform,
                "shop_name": item.shop_name,
                "turn_count": len(item.turns),
                "buyer_turn_count": len([t for t in item.turns if t.speaker == "buyer"]),
                "preview": [t.sanitized_text for t in item.turns[:4]],
            }
            for item in samples
        ],
    }


def default_source_dir() -> str:
    return os.path.abspath(os.path.join(os.getcwd(), "..", "客服质检系统"))
