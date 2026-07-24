from scripts.trace_evidence_convergence import trace_response


def test_trace_reports_context_pack_evidence_absent_from_formal_selection():
    payload = {
        "product_identity": {"sku_code": "SKU-A", "i_id": "IID-A"},
        "product_context_pack": {
            "facts": [{
                "evidence_id": "kbproduct:42:material",
                "source_type": "product_facts",
                "fact_type": "material",
                "attribute_key": "material",
                "chunk_text": "Material: verified board and steel frame.",
                "sku_scope": ["SKU-A"],
                "product_scope": ["IID-A"],
                "metadata": {
                    "product_evidence_protocol": True,
                    "verification_status": "verified",
                    "can_direct_answer": True,
                    "material_provenance": "structured_product_record",
                },
            }],
        },
    }

    report = trace_response(payload, claim_types=["material_composition"])

    assert report["direct_product_facts"][0]["text"] == "Material: verified board and steel frame."
    summary = report["evidence_convergence"]["summary"]
    assert summary["context_pack_candidate_count"] == 1
    assert summary["formal_selected_count"] == 0
    assert summary["llm_context_count"] == 1
    assert report["used_for_final_reply"] is False
    assert report["can_change_can_send"] is False
    preview = report["supervisor_candidate_preview"]
    assert preview["can_send"] is False
    assert preview["used_for_final_reply"] is False
    assert preview["evidence_uids"]
    assert "rejected_evidence" not in report["minimal_decision_context"]


def test_trace_marks_rebuilt_context_separately_from_compact_snapshot(monkeypatch):
    import scripts.trace_evidence_convergence as trace_module

    rebuilt_pack = {
        "facts": [{
            "evidence_id": "kbproduct:42:material",
            "source_type": "product_facts",
            "fact_type": "material",
            "attribute_key": "material",
            "chunk_text": "Material: verified board and steel frame.",
            "sku_scope": ["SKU-A"],
            "product_scope": ["IID-A"],
            "metadata": {
                "product_evidence_protocol": True,
                "verification_status": "verified",
                "can_direct_answer": True,
                "material_provenance": "structured_product_record",
            },
        }],
    }
    monkeypatch.setattr(trace_module, "build_product_context_pack", lambda *_args, **_kwargs: rebuilt_pack)
    payload = {
        "context_used": {
            "product_context_pack": {
                "identity": {"sku": "SKU-A", "i_id": "IID-A"},
                "facts": [{"entry_id": "kbproduct:42:material", "title": "compact"}],
            },
        },
    }

    report = trace_response(
        payload,
        claim_types=["material_composition"],
        rebuild_product_context=True,
        customer_message="A question",
        query_fact_type="material",
    )

    assert report["context_source"] == "rebuilt_current_product_context"
    assert report["input_compact_candidate_count"] == 1
    assert len(report["direct_product_facts"]) == 1
