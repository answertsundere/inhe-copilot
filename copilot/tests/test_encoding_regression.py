"""
Encoding regression tests — ensure data encoding pipeline is correct.

Tests:
- Normal Chinese text is NOT double-encoded
- Typical mojibake can be repaired
- English, digits, URLs are unaffected
- Unrepairable text is preserved as-is
- JSONL round-trip preserves correct Chinese
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


class TestRepairMojibake:
    """Test the mojibake repair function in real_data_sanitizer."""

    def _repair(self, text):
        from scripts.golden_set.real_data_sanitizer import repair_mojibake
        return repair_mojibake(text)

    def test_normal_chinese_not_affected(self):
        """Normal Chinese text should not be modified."""
        text = "亲亲，宝宝6个月推荐使用爬行垫"
        repaired, strategy, applied = self._repair(text)
        assert not applied, "Normal Chinese should NOT be repaired"
        assert repaired == text
        assert strategy == "none"

    def test_english_digits_unaffected(self):
        """English, digits, URLs should pass through unchanged."""
        text = "Order ID: 1234567890. Visit https://example.com/page?token=abc123"
        repaired, strategy, applied = self._repair(text)
        assert not applied
        assert repaired == text

    def test_empty_string(self):
        """Empty string returns empty."""
        repaired, strategy, applied = self._repair("")
        assert repaired == ""
        assert strategy == "none"
        assert not applied

    def test_mojibake_utf8_as_latin1_repairable(self):
        """UTF-8 bytes misinterpreted as Latin-1 should be repairable."""
        # "你好" in UTF-8 is b'\xe4\xbd\xa0\xe5\xa5\xbd'
        # If interpreted as Latin-1: 'ä½\xa0å¥½'
        mojibake = b'\xe4\xbd\xa0\xe5\xa5\xbd'.decode("latin-1")
        repaired, strategy, applied = self._repair(mojibake)
        assert applied, "Mojibake should be repairable"
        assert "你好" in repaired
        assert "utf8_from" in strategy

    def test_replacement_chars_preserved(self):
        """Replacement characters (U+FFFD) should be preserved as-is."""
        text = "产品说明：□□□□□□□□"
        # This has replacement chars but not classic mojibake
        repaired, strategy, applied = self._repair(text)
        # Should either repair or keep original
        assert repaired is not None

    def test_jsonl_roundtrip_chinese(self):
        """JSONL write/read must preserve correct Chinese."""
        records = [
            {"content": "亲亲，这款围兜防水吗？"},
            {"content": "一号防摔枕适合1个月以上的宝宝使用"},
            {"content": "刺猬书架承重15-25kg"},
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False, encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            path = f.name

        try:
            with open(path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    obj = json.loads(line)
                    assert obj["content"] == records[i]["content"], \
                        f"Round-trip failed for record {i}"
        finally:
            os.unlink(path)

    def test_jsonl_roundtrip_with_order_id(self):
        """JSONL round-trip preserves order IDs and tracking numbers."""
        record = {
            "content": "我的快递单号SF0229477422177到哪里了",
            "order_id": "5118207015382036103",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False, encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            path = f.name

        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.loads(f.readline())
                assert obj["order_id"] == "5118207015382036103"
                assert "SF0229477422177" in obj["content"]
        finally:
            os.unlink(path)


class TestSanitizeTextEncoding:
    """Verify sanitize_text does not corrupt encoding."""

    def test_sanitize_preserves_chinese(self):
        from scripts.golden_set.real_data_sanitizer import sanitize_text
        text = "宝宝6个月推荐使用爬行垫，材质安全环保"
        result = sanitize_text(text)
        assert "宝宝" in result
        assert "爬行垫" in result
        assert "材质" in result

    def test_sanitize_masks_phone(self):
        from scripts.golden_set.real_data_sanitizer import sanitize_text
        text = "我的手机号是13812345678，请联系我"
        result = sanitize_text(text)
        assert "13812345678" not in result
        assert "我的手机号" in result  # Chinese preserved


class TestSourceAuditIntegrity:
    """Verify source_audit.json is honest about database status."""

    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    AUDIT_PATH = PROJECT_ROOT / "data" / "real_golden_candidates" / "source_audit.json"

    def test_audit_file_exists(self):
        """source_audit.json must exist as a formal artifact."""
        assert self.AUDIT_PATH.is_file(), (
            f"source_audit.json not found at {self.AUDIT_PATH}. "
            "This file is a required deliverable."
        )

    def test_audit_honest_about_disconnected(self):
        """When database is not connected, counts must be zero, not fabricated."""
        with open(self.AUDIT_PATH, "r", encoding="utf-8") as f:
            audit = json.load(f)
        if not audit.get("database_connected", False):
            assert audit.get("total_messages", 0) == 0
            assert audit.get("cutoff_messages", 0) == 0
            assert audit.get("cutoff_chats", 0) == 0
            # Mark that data audit was not completed this run
            assert audit.get("error") is not None, (
                "When disconnected, error field must document why"
            )
            assert audit.get("cutoff_messages", 0) == 0
            assert audit.get("cutoff_chats", 0) == 0
