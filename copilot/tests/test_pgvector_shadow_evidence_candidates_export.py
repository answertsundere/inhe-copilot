from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import EvalRun, EvalTrace


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def test_pgvector_shadow_candidate_export_keeps_roles_separate():
    import scripts.export_pgvector_shadow_evidence_candidates as script

    Session = _session_factory()
    db = Session()
    db.add(EvalRun(run_uid="run-1", source_type="real_conversation", status="completed"))
    trace = EvalTrace(
        run_uid="run-1",
        case_uid="case-1",
        turn_uid="turn-1",
        buyer_message="有安装教程吗",
        query_fact_type="installation",
    )
    trace.set_raw_response({
        "sidecar_context": {"product_title": "商品A", "sku_code": "SKU-1", "i_id": "IID-1"},
        "pgvector_shadow": {
            "product_fact": {
                "top_candidates": [{
                    "id": "pgvector:1",
                    "source_type": "product_facts",
                    "evidence_role": "product_fact_direct",
                    "score": 0.9,
                    "preview": "安装方式说明",
                }]
            },
            "service_action": {
                "top_candidates": [{
                    "id": "pgvector:generic_rule:1",
                    "source_type": "generic_rule",
                    "evidence_role": "service_action",
                    "score": 0.8,
                    "preview": "安装卡住时让客户拍照",
                }]
            },
            "media_reference": {
                "top_candidates": [{
                    "id": "pgvector:media_asset:1",
                    "source_type": "media_asset",
                    "evidence_role": "media_reference",
                    "media_role": "pack_guide_image",
                    "score": 0.7,
                    "preview": "安装图素材",
                }]
            },
        },
    })
    db.add(trace)
    db.commit()
    db.close()

    result = script.export_pgvector_shadow_candidates(run_uid="run-1", db_factory=Session)

    assert result["summary"]["candidate_count"] == 3
    assert result["summary"]["by_candidate_type"] == {
        "product_fact_candidate": 1,
        "service_action_candidate": 1,
        "media_reference_candidate": 1,
    }
    service = [row for row in result["rows"] if row["candidate_type"] == "service_action_candidate"][0]
    media = [row for row in result["rows"] if row["candidate_type"] == "media_reference_candidate"][0]
    assert service["direct_answerable"] is False
    assert "不能当商品事实" in service["not_auto_send_reason"]
    assert media["direct_answerable"] is False
    assert "reply_blocks" in media["not_auto_send_reason"]


def test_pgvector_shadow_candidate_export_can_read_shadow_trace_json(tmp_path):
    import json
    import scripts.export_pgvector_shadow_evidence_candidates as script

    shadow_json = tmp_path / "shadow.json"
    shadow_json.write_text(json.dumps({
        "summary": {"run_uid": "run-1"},
        "rows": [{
            "case_uid": "case-1",
            "turn_uid": "turn-1",
            "buyer_message_preview": "有优惠吗",
            "query_fact_type": "promotion",
            "sidecar": {"product_title": "商品A"},
            "pgvector_shadow": {
                "filter_mode_results": {
                    "service_action_merge": {
                        "top_candidates": [{
                            "source_type": "generic_rule",
                            "evidence_role": "service_action",
                            "preview": "优惠以页面为准",
                        }]
                    }
                }
            },
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = script.export_pgvector_shadow_candidates(shadow_json=str(shadow_json))

    assert result["summary"]["candidate_count"] == 1
    assert result["summary"]["by_candidate_type"]["service_action_candidate"] == 1
