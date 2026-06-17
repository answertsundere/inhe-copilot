from __future__ import annotations

from typing import Any


MOJIBAKE_MARKERS = (
    "\u00c3", "\u00c2", "\u00e3", "\u00e4", "\u00e5", "\u00e6",
    "\u00e8", "\u00e9", "\u00e7", "\u00ef", "\u00f0", "\ufffd",
    "\u0161", "\u017d", "\u2030", "\u2039", "\u02c6",
)


def repair_mojibake_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text

    candidates = [text]
    raw_bytes = _mojibake_bytes(text)
    if raw_bytes:
        try:
            candidates.append(raw_bytes.decode("utf-8"))
        except UnicodeError:
            pass
    for encoding in ("cp1252", "latin1"):
        try:
            fixed = text.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        candidates.append(fixed)

    return max(candidates, key=_text_quality_score)


def repair_mojibake_obj(value: Any) -> Any:
    if isinstance(value, str):
        return repair_mojibake_text(value)
    if isinstance(value, list):
        return [repair_mojibake_obj(item) for item in value]
    if isinstance(value, dict):
        return {key: repair_mojibake_obj(item) for key, item in value.items()}
    return value


def _mojibake_bytes(text: str) -> bytes:
    data = bytearray()
    for ch in text:
        try:
            encoded = ch.encode("cp1252")
        except UnicodeError:
            code = ord(ch)
            if code <= 0xFF:
                data.append(code)
                continue
            return b""
        if len(encoded) != 1:
            return b""
        data.extend(encoded)
    return bytes(data)


def _text_quality_score(text: str) -> int:
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    replacement = text.count("�")
    markers = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    return cjk * 5 - replacement * 10 - markers
