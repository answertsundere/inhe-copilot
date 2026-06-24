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
from app.services.real_conversation_context_extractor import (
    empty_real_context,
    extract_real_context,
    merge_real_context,
)


BUYER_SPEAKERS = {"buyer", "customer", "user", "client", "买家", "客户", "用户", "顾客", "消费者"}
SERVICE_SPEAKERS = {"seller", "service", "agent", "csr", "客服", "商家", "店铺", "卖家"}
SYSTEM_SPEAKERS = {"system", "系统", "平台", "机器人"}

SKIP_DIR_NAMES = {
    ".git", ".github", ".claude", ".pytest_cache", ".playwright-mcp", ".playwright-cli",
    "node_modules", "htmlcov", "logs", "log", "config", "policy_backups", "docs", "nginx",
    "客服报表", "backend",
}
SKIP_FILE_NAME_TERMS = {
    "duplicate_report", "compare_report", "report_output", "daily_quality", "coverage",
    "readme", "quickstart", "terms", "models", "snapshot", "report", "统计",
}
CHAT_DIR_HINTS = {"聊天记录", "chat", "conversation", "messages", "records"}


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
    if low in SYSTEM_SPEAKERS or text in SYSTEM_SPEAKERS:
        return "system"
    if "客户" in text or "买家" in text or "用户" in text:
        return "buyer"
    if "客服" in text or "商家" in text or "店铺" in text:
        return "service"
    if "客" in text and "服" not in text:
        return "buyer"
    if "客服" in text or "商家" in text:
        return "service"
    return low or "unknown"


def _text_from_record(record: dict[str, Any]) -> str:
    for key in ("text", "content", "message", "msg", "body", "raw_text", "消息内容", "内容", "msg_content"):
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
_REPORT_LINE_RE = re.compile(
    r"(发现\s*\d+\s*组|重复|报告|统计|→\s*\d+\s*个会话|chat[_:]|business_session|capture_batch)",
    re.I,
)


def _looks_like_report_or_summary(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    if value.startswith("=") or value.startswith("----"):
        return True
    if _REPORT_LINE_RE.search(value):
        return True
    if "unknown" in value.lower() and "客服" in value and "个会话" in value:
        return True
    return False


def _is_context_only_text(text: str, message_type: str = "") -> bool:
    value = str(text or "").strip()
    msg_type = str(message_type or "").strip().lower()
    if not value:
        return True
    if msg_type in {"图片", "图像", "image", "product_link", "商品链接", "系统提示"}:
        return True
    if re.fullmatch(r"https?://\S+", value):
        return True
    if value.startswith("当前用户来自 "):
        return True
    if re.search(r"订单号[:：].*(交易时间|合计|件商品)", value):
        return True
    if value.startswith("若您需要开发票"):
        return True
    return False


def _is_non_actionable_buyer_text(text: str) -> bool:
    """Return True for buyer acknowledgements/greetings that should stay in history only."""
    value = re.sub(r"[\s~～!！?？.。…]+", "", str(text or ""))
    if not value:
        return True
    acknowledgements = {
        "好", "好的", "嗯", "恩", "可以", "行", "收到", "知道了",
        "谢谢", "谢谢你", "好的谢谢", "嗯嗯", "ok", "OK",
    }
    if value in acknowledgements:
        return True
    greetings = {"你好", "您好", "在吗", "有人吗", "客服在吗"}
    if value in greetings:
        return True
    return False


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
        text = match.group(2)
        if _looks_like_report_or_summary(text):
            continue
        turns.append({"speaker": match.group(1), "text": text, "message_type": "text"})
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


def _normalize_header(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return ""


def _parse_xlsx_file(path: Path) -> list[tuple[list[dict[str, Any]], dict[str, Any]]]:
    try:
        import openpyxl
    except Exception:
        return []
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return []

    groups: dict[str, list[dict[str, Any]]] = {}
    metadata: dict[str, Any] = {"source_format": "xlsx"}
    try:
        for worksheet in workbook.worksheets:
            rows = worksheet.iter_rows(values_only=True)
            header_values = next(rows, None)
            if not header_values:
                continue
            headers = [_normalize_header(item) for item in header_values]
            if not any(h in {"会话id", "conversation_id", "chat_id", "session_id"} for h in headers):
                continue
            if not any(h in {"说话类型", "说话人类型", "speaker_type", "role", "speaker"} for h in headers):
                continue
            if not any(h in {"消息内容", "content", "text", "message", "msg"} for h in headers):
                continue

            for raw_row in rows:
                row = {
                    headers[index]: raw_row[index]
                    for index in range(min(len(headers), len(raw_row)))
                    if headers[index]
                }
                conv = str(_first_present(row, "会话id", "conversation_id", "chat_id", "session_id") or path.stem)
                speaker = _first_present(row, "说话类型", "说话人类型", "speaker_type", "role", "speaker", "说话人")
                text = _first_present(row, "消息内容", "content", "text", "message", "msg")
                if not text:
                    text = _first_present(row, "图片链接", "image_url", "media_url")
                if not text:
                    continue
                if _looks_like_report_or_summary(str(text)):
                    continue
                groups.setdefault(conv, []).append({
                    "speaker": speaker,
                    "text": text,
                    "context_blob": " ".join(str(value or "") for value in row.values()),
                    "message_type": _first_present(row, "消息类型", "message_type", "type") or "text",
                    "timestamp": _first_present(row, "说话时间", "timestamp", "time", "created_at"),
                    "product_hint": _first_present(row, "商品名称", "商品", "product_name", "item_title"),
                    "raw_speaker": _first_present(row, "说话人", "sender", "from"),
                })
    finally:
        workbook.close()

    return [
        (turns, {**metadata, "conversation_id_hash": hash_sensitive(key)})
        for key, turns in groups.items()
    ]


def _should_skip_source_file(path: Path) -> bool:
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    name = path.name.lower()
    stem = path.stem.lower()
    if any(term in name or term in stem for term in SKIP_FILE_NAME_TERMS):
        return True
    if path.suffix.lower() in {".log", ".md", ".yml", ".yaml"}:
        return True
    return False


def _file_priority(path: Path) -> tuple[int, int, float, str]:
    in_chat_dir = any(part in CHAT_DIR_HINTS for part in path.parts)
    suffix_priority = {
        ".xlsx": 0,
        ".csv": 1,
        ".jsonl": 2,
        ".json": 3,
        ".txt": 4,
    }.get(path.suffix.lower(), 9)
    try:
        modified_rank = -path.stat().st_mtime
    except OSError:
        modified_rank = 0
    return (0 if in_chat_dir else 1, suffix_priority, modified_rank, str(path))


def iter_conversation_files(source_dir: str) -> list[Path]:
    root = Path(source_dir)
    if not root.exists():
        return []
    suffixes = {".json", ".jsonl", ".txt", ".csv", ".xlsx"}
    files = [
        path for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in suffixes
        and not _should_skip_source_file(path)
    ]
    return sorted(files, key=_file_priority)


def case_uid_for_conversation(conversation_uid: str) -> str:
    return _stable_uid(conversation_uid, prefix="case")


def parse_source_file(path: Path) -> list[ImportedConversation]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw_groups = _parse_json_file(path)
    elif suffix == ".jsonl":
        raw_groups = _parse_jsonl_file(path)
    elif suffix == ".csv":
        raw_groups = _parse_csv_file(path)
    elif suffix == ".xlsx":
        raw_groups = _parse_xlsx_file(path)
    else:
        raw_groups = _parse_text_file(path)

    conversations: list[ImportedConversation] = []
    for group_index, (records, meta) in enumerate(raw_groups):
        turns: list[ImportedTurn] = []
        rolling_context = empty_real_context()
        for idx, record in enumerate(records):
            speaker = _normalize_speaker(
                record.get("speaker") or record.get("role") or record.get("sender") or record.get("from") or ""
            )
            raw_text = _text_from_record(record)
            sanitized = sanitize_text(raw_text)
            if not sanitized:
                continue
            if _looks_like_report_or_summary(sanitized):
                continue
            message_type = sanitize_text(record.get("message_type") or record.get("type") or "text") or "text"
            context_text = "\n".join(
                str(value or "")
                for value in (
                    raw_text,
                    record.get("context_blob"),
                    record.get("product_url"),
                    record.get("item_url"),
                    record.get("url"),
                    record.get("link"),
                    record.get("media_url"),
                    record.get("image_url"),
                    record.get("video_url"),
                )
                if value
            )
            record_context = extract_real_context(context_text, {
                **record,
                "message_type": message_type,
                "product_hint": record.get("product_hint") or record.get("product_name") or record.get("item_title") or "",
            })
            rolling_context = merge_real_context(rolling_context, record_context)
            if speaker == "buyer":
                if _is_context_only_text(sanitized, message_type) or _is_non_actionable_buyer_text(sanitized):
                    speaker = "context"
            order_hash = ""
            raw_order = record.get("order_id") or record.get("tid") or record.get("tracking_no") or ""
            if raw_order:
                order_hash = hash_sensitive(str(raw_order))
            turns.append(ImportedTurn(
                turn_index=len(turns),
                speaker=speaker,
                sanitized_text=sanitized,
                message_type=message_type,
                timestamp=sanitize_text(record.get("timestamp") or record.get("time") or record.get("created_at") or ""),
                product_hint=sanitize_text(record.get("product_hint") or record.get("product_name") or record.get("item_title") or ""),
                order_hint_hash=order_hash,
                metadata=sanitize_obj({
                    "source_row_index": idx,
                    "raw_speaker": record.get("speaker") or record.get("role") or record.get("sender") or "",
                    "real_context": rolling_context,
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
            metadata=sanitize_obj({**meta, "real_context": rolling_context}),
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
            case_uid = case_uid_for_conversation(conv.conversation_uid)
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
