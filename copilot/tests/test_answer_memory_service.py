from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import AgentAnswerMemory
from app.services import answer_memory_service as service_module
from app.services.answer_memory_service import AnswerMemoryService, build_memory_from_training_sample, hash_order_id


def _session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[AgentAnswerMemory.__table__])
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service_module, "SessionLocal", factory)
    return factory


def _sample(**kwargs):
    data = {
        "id": 101,
        "review_status": "已确认",
        "customer_quote": "螺丝拧紧了还是会掉怎么办",
        "correct_answer": "先安抚客户，让客户拍照说明问题位置，再转人工核实安装和售后处理方案",
        "product_title": "测试收纳柜",
        "sku": "SKU-1",
        "order_no": "512345678901234",
        "question_type": "安装",
        "risk_level": "medium",
    }
    data.update(kwargs)
    return data


def test_build_memory_from_training_sample_defaults_to_no_auto_send_and_hashes_order():
    payload = build_memory_from_training_sample(_sample())

    assert payload is not None
    assert payload["can_auto_send"] is False
    assert payload["requires_human_review"] is True
    assert payload["source_order_id_hash"] == hash_order_id("512345678901234")
    assert payload["source_order_id_hash"] != "512345678901234"
    assert payload["approved_answer"]
    assert payload["review_status"] == "verified_answer"


def test_missing_correct_answer_is_not_importable(monkeypatch):
    _session_factory(monkeypatch)

    result = AnswerMemoryService().import_training_samples([_sample(correct_answer="")], apply=True)

    assert result["importable_count"] == 0
    assert result["skipped_count"] == 1


def test_import_dry_run_does_not_write(monkeypatch):
    factory = _session_factory(monkeypatch)

    result = AnswerMemoryService().import_training_samples([_sample()], apply=False)

    db = factory()
    assert result["dry_run"] is True
    assert result["importable_count"] == 1
    assert db.query(AgentAnswerMemory).count() == 0
    db.close()


def test_import_apply_writes_candidate_without_formal_knowledge(monkeypatch):
    factory = _session_factory(monkeypatch)

    result = AnswerMemoryService().import_training_samples([_sample()], apply=True)

    db = factory()
    row = db.query(AgentAnswerMemory).one()
    assert result["writes_formal_knowledge"] is False
    assert row.can_auto_send is False
    assert row.requires_human_review is True
    assert row.source_type == "reviewed_training_sample"
    assert row.source_order_id_hash
    assert row.source_order_id_hash != "512345678901234"
    db.close()


def test_high_risk_answer_requires_human_review(monkeypatch):
    factory = _session_factory(monkeypatch)

    AnswerMemoryService().import_training_samples(
        [
            _sample(
                customer_quote="有没有适合2周岁宝宝的",
                correct_answer="需要按商品页适用年龄和安全说明核对后回复",
                question_type="商品",
                risk_level="",
            )
        ],
        apply=True,
    )

    db = factory()
    row = db.query(AgentAnswerMemory).one()
    assert row.query_fact_type == "age_range"
    assert row.risk_level == "high"
    assert row.requires_human_review is True
    assert row.can_auto_send is False
    db.close()


def test_search_prefers_exact_product_identity(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    exact = AgentAnswerMemory(memory_uid="m1", product_i_id="I1", sku_code="", query_fact_type="installation", scenario_type="installation")
    exact.approved_answer = "exact product answer"
    exact.review_status = "verified_answer"
    exact.answer_quality = "verified_answer"
    exact.can_auto_send = False
    exact.requires_human_review = True
    exact.set_required_fact_types(["installation"])
    generic = AgentAnswerMemory(memory_uid="m2", product_i_id="", sku_code="", query_fact_type="installation", scenario_type="installation")
    generic.reference_reply = "generic scenario answer"
    generic.review_status = "reference_reply"
    generic.answer_quality = "reference_reply"
    generic.can_auto_send = False
    generic.requires_human_review = True
    db.add_all([exact, generic])
    db.commit()
    db.close()

    hits = AnswerMemoryService().search_answer_memory(
        product_i_id="I1",
        query_fact_type="installation",
        scenario_type="installation",
        customer_message="有安装视频吗",
    )

    assert hits
    assert hits[0]["memory_uid"] == "m1"
    assert hits[0]["reference_only"] is False


def test_search_without_product_identity_returns_reference_only(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    row = AgentAnswerMemory(memory_uid="m1", query_fact_type="promotion_policy", scenario_type="promotion")
    row.reference_reply = "按当前活动规则核对"
    row.review_status = "reference_reply"
    row.answer_quality = "reference_reply"
    row.can_auto_send = False
    row.requires_human_review = True
    db.add(row)
    db.commit()
    db.close()

    hits = AnswerMemoryService().search_answer_memory(
        query_fact_type="promotion_policy",
        scenario_type="promotion",
        customer_message="有什么优惠吗",
    )

    assert hits[0]["reference_only"] is True
    assert hits[0]["can_auto_send"] is False


def test_forbidden_claims_return_to_upstream_gate(monkeypatch):
    _session_factory(monkeypatch)
    AnswerMemoryService().import_training_samples(
        [
            _sample(
                customer_quote="这个材质无毒吗",
                correct_answer="需要按商品材质和检测资料核对后回复",
                question_type="商品",
                risk_level="",
            )
        ],
        apply=True,
    )

    hits = AnswerMemoryService().search_answer_memory(
        sku_code="SKU-1",
        query_fact_type="material",
        scenario_type="product_fact",
        customer_message="这个材质无毒吗",
    )

    assert hits
    assert "无毒" in hits[0]["forbidden_claims"]
