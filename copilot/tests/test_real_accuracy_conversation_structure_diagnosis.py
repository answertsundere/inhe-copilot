from __future__ import annotations

import json

from scripts.diagnose_real_accuracy_conversation_structure import diagnose


def test_structure_diagnosis_reports_only_dom_metadata_and_role_metrics():
    report = diagnose([{
        "full_context": '<div class="imui-msg imui-msg-l" data-fromnick="private-name"><div class="msg-body-text">private customer text</div></div>'
    }], "test-hmac-key")
    rendered = json.dumps(report, ensure_ascii=False)
    assert report["structural_class_counts"]["imui-msg-l"] == 1
    assert report["parsed_role_counts"]["BUYER"] == 1
    assert "private-name" not in rendered
    assert "private customer text" not in rendered
