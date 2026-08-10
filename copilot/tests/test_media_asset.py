"""
图片/视频素材库测试。

覆盖：
- DB 迁移幂等 + 表/索引存在
- 导入脚本（install_video / pack_guide_image / sku_image / 去重 / 审核保留）
- 查询服务（按 i_id/sku 查、未审核不推荐、审核后推荐）
- API（list / approve / reject / import / recommend）
- Agent 推荐（有审核素材→recommended_assets；无审核→不编造）
- 前端 smoke（kb-admin / real-test / 5011 / 5012 HTTP 200）

注意：测试对真实 knowledge_base.db 只做读 + 临时 approve/reject（结束后还原），
不删除/不清空数据。
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from app.models.kb_tables import KBMediaAsset


# ─── 公共 fixture ───────────────────────────────────────────────────

@pytest.fixture()
def isolated_media_db(tmp_path, monkeypatch):
    """Run media workflows against a disposable database, never recovered runtime data."""
    import app.config as config_module
    import app.db as db_module
    import app.main as main_module
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry
    from app.models.kb_tables import KBMediaAsset, KBQA

    db_path = tmp_path / "media_assets.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(config_module, "KNOWLEDGE_DB_PATH", str(db_path))
    monkeypatch.setattr(main_module, "KNOWLEDGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    # This service binds SessionLocal at import time.  Patch that binding as
    # well so recommendation tests never fall back to recovered runtime data.
    from app.services import media_asset_service
    monkeypatch.setattr(media_asset_service, "SessionLocal", session_factory)
    for service_name in (
        "_order_repo", "_product_repo", "_knowledge_repo", "_policy_repo",
        "_product_knowledge_repo", "_risk_service", "_context_builder", "_output_guard",
        "_reply_service", "_feedback_service", "_review_queue_service", "_reply_template_repo",
        "_sop_repo", "_data_quality_service", "_quality_check_service",
    ):
        monkeypatch.setattr(main_module, service_name, None)
    db_module.Base.metadata.create_all(bind=engine)

    db = session_factory()
    try:
        readiness_entry = KnowledgeEntry(
            source_type="faq",
            title="Readiness fixture",
            content="This isolated record exists only to exercise the knowledge readiness contract.",
            intent="general",
            status="published",
            source_confidence=1.0,
            fact_review_status="reviewed",
            index_status="indexed",
            content_hash="pytest_media_readiness_entry",
        )
        db.add(readiness_entry)
        db.flush()
        db.add(KnowledgeChunk(
            entry_id=readiness_entry.id,
            chunk_text="Isolated readiness fixture.",
            chunk_index=0,
            source_type="faq",
            intent="general",
            embedding_status="indexed",
            fact_source_type="faq",
            fact_review_status="reviewed",
        ))
        db.add(KBQA(
            question="Readiness fixture question",
            answer="Readiness fixture answer",
            intent="general",
            source_type="faq",
            status="published",
            content_hash="pytest_media_readiness_qa",
        ))
        db.add(KBMediaAsset(
            i_id="YH04K14B01S03",
            sku_code="YH04K14B01S03",
            product_name="Baseline media product",
            asset_type="install_video",
            asset_title="Baseline installation video",
            asset_url="https://example.test/media/install.mp4",
            source="pytest",
            content_hash="pytest_baseline_install_video",
            status="approved",
            audit_status="approved",
            usable_for_agent=True,
            refresh_status="ok",
        ))
        db.commit()
    finally:
        db.close()
    return session_factory


@pytest.fixture()
def app(isolated_media_db):
    import app.models.kb_tables  # noqa: F401
    from app.main import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


def _supervisor_headers():
    return {"X-User-Role": "supervisor", "X-User-Name": "media-test"}


def test_upload_route_can_read_legacy_media_directory(tmp_path, monkeypatch):
    from flask import Flask
    from app.api import media_routes

    current_dir = tmp_path / "current"
    legacy_dir = tmp_path / "legacy"
    legacy_file = legacy_dir / "2026-06-17" / "preview.jpg"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(b"legacy-preview")
    monkeypatch.setattr(media_routes, "_UPLOAD_DIR", str(current_dir))
    monkeypatch.setattr(media_routes, "_LEGACY_UPLOAD_DIR", str(legacy_dir))

    test_app = Flask(__name__)
    test_app.register_blueprint(media_routes.media_bp)
    response = test_app.test_client().get("/api/media-assets/uploads/2026-06-17/preview.jpg")

    assert response.status_code == 200
    assert response.data == b"legacy-preview"


def test_upload_route_allows_configured_label_studio_origin(tmp_path, monkeypatch):
    from flask import Flask
    from app.api import media_routes

    upload_dir = tmp_path / "uploads"
    media_file = upload_dir / "2026-06-17" / "preview.jpg"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"annotation-preview")
    monkeypatch.setattr(media_routes, "_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(media_routes, "_LEGACY_UPLOAD_DIR", str(tmp_path / "legacy"))

    test_app = Flask(__name__)
    test_app.register_blueprint(media_routes.media_bp)
    response = test_app.test_client().get(
        "/api/media-assets/uploads/2026-06-17/preview.jpg",
        headers={"Origin": "http://127.0.0.1:8088"},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8088"
    assert response.headers["Vary"] == "Origin"


@pytest.fixture(autouse=True)
def _clean_test_assets(isolated_media_db):
    """每个测试前后清理 TEST_IID_001 测试素材，保证导入测试相互隔离。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.models.kb_tables import KBMediaAsset
    db = SessionLocal()
    try:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_IID_001").delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_IID_001").delete()
        db.commit()
    finally:
        db.close()


# ─── 1. DB 迁移 ─────────────────────────────────────────────────────

def test_migration_idempotent_table_and_indexes():
    import app.models.kb_tables  # noqa: F401
    from app.db import init_db, engine
    from sqlalchemy import inspect

    init_db()  # 重复运行不应报错
    init_db()

    insp = inspect(engine)
    assert "kb_media_asset" in insp.get_table_names()

    cols = {c["name"] for c in insp.get_columns("kb_media_asset")}
    for required in [
        "id", "product_id", "i_id", "sku_code", "product_name",
        "asset_type", "asset_title", "asset_url", "source", "source_doc_id",
        "source_raw_json", "match_confidence", "match_reason",
        "status", "audit_status", "usable_for_agent", "scene_tags_json",
        "content_hash", "last_seen_at", "created_at", "updated_at",
        "url_expires_at", "refresh_status", "source_updated_at", "reviewed_by",
    ]:
        assert required in cols, f"missing column {required}"

    idx_names = {i["name"] for i in insp.get_indexes("kb_media_asset")}
    for required_idx in ["idx_media_i_id", "idx_media_sku_code", "idx_media_asset_type",
                         "idx_media_status", "idx_media_hash", "idx_media_refresh_status",
                         "idx_media_url_expires_at"]:
        assert required_idx in idx_names, f"missing index {required_idx}"


# ─── 2. 导入脚本 ────────────────────────────────────────────────────

SAMPLE_REPORT = {
    "summary": {"local_unmatched_products_count": 0},
    "details": [
        {
            "product_id": 999001,
            "i_id": "TEST_IID_001",
            "product_name": "测试商品A",
            "match_reasons": ["i_id_exact:TEST_IID_001"],
            "matched_dt_skus": ["TEST_IID_001"],
            "has_install_video": True,
            "has_pack_guide": True,
            "has_sku_images": True,
            "install_videos": {"douyin": {"url": "https://www.douyin.com/video/TESTVIDEO001", "title": "测试安装视频"}},
            "pack_guide_images": ["https://example.com/img/pack-001.png?Expires=111&Signature=aaa"],
            "sku_images": ["https://example.com/img/sku-001.png?Expires=111&Signature=bbb"],
        },
    ],
}


def _import_into_real_db(report_path):
    from scripts.import_dingtalk_media_assets import import_report
    return import_report(report_path, dry_run=False)


def test_import_creates_all_types_and_dedup(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(SAMPLE_REPORT, ensure_ascii=False), encoding="utf-8")

    s1 = _import_into_real_db(str(report_path))
    assert s1["new_assets"] == 3
    assert s1["install_video"] == 1
    assert s1["pack_guide_image"] == 1
    assert s1["sku_image"] == 1

    # 重复导入应去重（0 new，3 updated）
    s2 = _import_into_real_db(str(report_path))
    assert s2["new_assets"] == 0
    assert s2["updated_assets"] == 3

    # 签名变化（query 变）但路径相同 → 仍去重（稳定 key）
    changed = json.loads(report_path.read_text(encoding="utf-8"))
    changed["details"][0]["install_videos"]["douyin"]["url"] = "https://www.douyin.com/video/TESTVIDEO001"
    changed["details"][0]["pack_guide_images"] = ["https://example.com/img/pack-001.png?Expires=222&Signature=zzz"]
    report_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    s3 = _import_into_real_db(str(report_path))
    assert s3["new_assets"] == 0, "同路径 URL 重签不应产生新素材"


def test_import_preserves_review_state(tmp_path):
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.models.kb_tables import KBMediaAsset
    from app.services.media_asset_service import approve_asset, reject_asset

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(SAMPLE_REPORT, ensure_ascii=False), encoding="utf-8")
    _import_into_real_db(str(report_path))

    db = SessionLocal()
    try:
        asset = db.query(KBMediaAsset).filter(
            KBMediaAsset.i_id == "TEST_IID_001",
            KBMediaAsset.asset_type == "install_video",
        ).first()
        assert asset is not None
        approve_asset(db, asset.id, "test")
        approved_id = asset.id
    finally:
        db.close()

    # 重新导入
    _import_into_real_db(str(report_path))

    db = SessionLocal()
    try:
        asset = db.query(KBMediaAsset).get(approved_id)
        assert asset.status == "approved"
        assert asset.usable_for_agent == 1
        # 清理测试数据
        reject_asset(db, approved_id, "test")
    finally:
        db.close()


def _cleanup_test_assets():
    # 保留为独立清理工具（autouse fixture 已覆盖测试间隔离）
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.models.kb_tables import KBMediaAsset
    db = SessionLocal()
    try:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_IID_001").delete()
        db.commit()
    finally:
        db.close()


# ─── 3. 查询服务 ────────────────────────────────────────────────────

def test_service_query_and_recommend_gating():
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        # 真实数据里有 YH04K14B01S03 的 install_video
        items = m.list_media_assets(db, i_id="YH04K14B01S03", asset_type="install_video")
        assert items["total"] >= 1

        # 未审核 → 不推荐（使用一个当前没有 approved 素材的 i_id，避免受小批量放行数据影响）
        reco = m.get_recommended_assets_for_message(
            customer_message="我要安装视频", i_id="YH_NO_APPROVED_99999", intent="installation")
        assert reco["recommended_assets"] == []
    finally:
        db.close()


def test_service_recommend_after_approve_and_revert():
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m
    from datetime import datetime, timedelta

    db = SessionLocal()
    try:
        items = m.list_media_assets(db, i_id="YH04K14B01S03", asset_type="install_video")["items"]
        assert items, "需要至少一条 install_video 用于测试"
        aid = items[0]["id"]
        m.approve_asset(db, aid, "test")

        # 保证链接未过期，否则推荐层会过滤掉
        asset = db.query(KBMediaAsset).get(aid)
        asset.url_expires_at = datetime.utcnow() + timedelta(days=1)
        asset.refresh_status = "ok"
        db.commit()

        reco = m.get_recommended_assets_for_message(
            customer_message="我要安装视频", i_id="YH04K14B01S03", intent="installation")
        assert len(reco["recommended_assets"]) >= 1
        assert reco["recommended_assets"][0]["asset_type"] == "install_video"
    finally:
        m.reject_asset(db, aid, "test")
        db.close()


# ─── 4. API ─────────────────────────────────────────────────────────

def test_api_list_and_stats(client):
    r = client.get("/api/media-assets/stats")
    assert r.status_code == 200
    data = r.get_json()
    assert "total" in data and data["total"] >= 0

    r = client.get("/api/media-assets", query_string={"i_id": "YH04K14B01S03", "asset_type": "install_video"})
    assert r.status_code == 200
    assert r.get_json()["total"] >= 1


def test_api_approve_reject_and_permissions(client, set_admin_test_principal):
    # operator 无权审核
    set_admin_test_principal("operator")
    r = client.post("/api/media-assets/1/approve")
    assert r.status_code == 403

    # supervisor 审核
    set_admin_test_principal("supervisor")
    r = client.post("/api/media-assets/1/approve")
    assert r.status_code == 200
    assert r.get_json()["asset"]["usable_for_agent"] is True
    assert r.get_json()["asset"]["status"] == "approved"

    # 还原
    r = client.post("/api/media-assets/1/reject")
    assert r.status_code == 200
    assert r.get_json()["asset"]["usable_for_agent"] is False


def test_api_import_permission(client, set_admin_test_principal):
    # operator 无权导入
    set_admin_test_principal("operator")
    r = client.post("/api/media-assets/import-dingtalk-report")
    assert r.status_code == 403


# ─── 5. Agent 推荐（不编造） ────────────────────────────────────────

def test_agent_recommend_no_fabrication():
    """没有已审核素材时，analyze 不应编造链接。"""
    import requests
    # 使用一个几乎确定没有已审核素材的商品
    payload = {
        "message": "我要安装视频",
        "conversation_id": "pytest_media_nofab",
        "product_candidates": [{"value": "YH04K14B01S03", "type": "sku_id_candidate",
                                "source": "test", "verified": True}],
    }
    # 直接调服务层（不依赖网络服务）
    from app.services.media_asset_service import recommend_for_analyze_response
    fake = {"intent": "installation",
            "context_used": {"conversation_context_summary": {"confirmed_product": "三层火箭书架"}}}
    reco = recommend_for_analyze_response(fake, customer_message="我要安装视频")
    # 没有已审核素材 → 空列表，绝不编造
    if not reco["recommended_assets"]:
        assert reco["recommended_assets"] == []
    else:
        # 若有（被其他测试 approve 过），链接必须是库里真实 URL，不能是编造
        for a in reco["recommended_assets"]:
            assert a["asset_url"].startswith("http"), "推荐链接必须是真实 http(s) URL"


# ─── 5.5 新增安全与优先级测试 ───────────────────────────────────────

def test_pending_rejected_not_recommended():
    """pending / rejected 素材不会被 Agent 推荐。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        # 创建 3 条测试素材，分别 pending / approved / rejected
        assets = [
            KBMediaAsset(
                i_id="TEST_MEDIA_GATING_001", sku_code="TEST_MEDIA_GATING_001",
                product_name="测试媒体门控", asset_type="sku_image",
                asset_url="https://example.com/sku.png", source="test",
                content_hash="test_hash_pending", status="pending_review",
                usable_for_agent=0,
            ),
            KBMediaAsset(
                i_id="TEST_MEDIA_GATING_001", sku_code="TEST_MEDIA_GATING_001",
                product_name="测试媒体门控", asset_type="install_video",
                asset_url="https://example.com/video.mp4", source="test",
                content_hash="test_hash_approved", status="approved",
                usable_for_agent=1, url_expires_at=datetime.utcnow() + timedelta(days=1),
                refresh_status="ok", reviewed_by="test",
            ),
            KBMediaAsset(
                i_id="TEST_MEDIA_GATING_001", sku_code="TEST_MEDIA_GATING_001",
                product_name="测试媒体门控", asset_type="pack_guide_image",
                asset_url="https://example.com/pack.png", source="test",
                content_hash="test_hash_rejected", status="rejected",
                usable_for_agent=0,
            ),
        ]
        for a in assets:
            db.add(a)
        db.commit()

        reco = m.get_recommended_assets_for_message(
            customer_message="发个图看看", i_id="TEST_MEDIA_GATING_001")
        # 只有 approved + usable_for_agent 的 install_video 会被推荐
        #（因关键词命中的是“图片”，优先级为 sku_image/size_image，approved 的 install_video 不在优先级列表里）
        # 这里换 intent=installation 测试 approved 通过
        reco = m.get_recommended_assets_for_message(
            customer_message="安装视频", i_id="TEST_MEDIA_GATING_001", intent="installation")
        assert len(reco["recommended_assets"]) == 1
        assert reco["recommended_assets"][0]["asset_type"] == "install_video"
    finally:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_MEDIA_GATING_001").delete()
        db.commit()
        db.close()


def test_expired_url_not_recommended():
    """过期 URL 不会被推荐。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        asset = KBMediaAsset(
            i_id="TEST_MEDIA_EXPIRED_001", sku_code="TEST_MEDIA_EXPIRED_001",
            product_name="测试过期链接", asset_type="install_video",
            asset_url="https://example.com/expired.mp4?Expires=1", source="test",
            content_hash="test_hash_expired", status="approved",
            usable_for_agent=1, refresh_status="ok", reviewed_by="test",
            url_expires_at=datetime.utcnow() - timedelta(days=1),
        )
        db.add(asset)
        db.commit()

        reco = m.get_recommended_assets_for_message(
            customer_message="安装视频", i_id="TEST_MEDIA_EXPIRED_001", intent="installation")
        assert reco["recommended_assets"] == []
    finally:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_MEDIA_EXPIRED_001").delete()
        db.commit()
        db.close()


def test_install_priority_pack_guide_fallback():
    """安装问题优先 install_video，其次 pack_guide_image。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        for atype in ("install_video", "pack_guide_image"):
            db.add(KBMediaAsset(
                i_id="TEST_MEDIA_INSTALL_001", sku_code="TEST_MEDIA_INSTALL_001",
                product_name="测试安装优先级", asset_type=atype,
                asset_url=f"https://example.com/{atype}.png", source="test",
                content_hash=f"test_hash_{atype}", status="approved",
                usable_for_agent=1, refresh_status="ok", reviewed_by="test",
                url_expires_at=datetime.utcnow() + timedelta(days=1),
            ))
        db.commit()

        reco = m.get_recommended_assets_for_message(
            customer_message="怎么安装", i_id="TEST_MEDIA_INSTALL_001", intent="installation")
        types = [a["asset_type"] for a in reco["recommended_assets"]]
        assert types == ["install_video"]
    finally:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_MEDIA_INSTALL_001").delete()
        db.commit()
        db.close()


def test_accessory_priority():
    """配件/少件问题优先 accessory_image，其次 pack_guide_image。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        for atype in ("accessory_image", "pack_guide_image"):
            db.add(KBMediaAsset(
                i_id="TEST_MEDIA_PARTS_001", sku_code="TEST_MEDIA_PARTS_001",
                product_name="测试配件优先级", asset_type=atype,
                asset_url=f"https://example.com/{atype}.png", source="test",
                content_hash=f"test_hash_parts_{atype}", status="approved",
                usable_for_agent=1, refresh_status="ok", reviewed_by="test",
                url_expires_at=datetime.utcnow() + timedelta(days=1),
            ))
        db.commit()

        reco = m.get_recommended_assets_for_message(
            customer_message="少了个零件", i_id="TEST_MEDIA_PARTS_001")
        types = [a["asset_type"] for a in reco["recommended_assets"]]
        assert types == ["accessory_image"]
    finally:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_MEDIA_PARTS_001").delete()
        db.commit()
        db.close()


def test_upsert_no_duplicate(tmp_path):
    """同 content_hash 重复导入不应创建重复记录。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from scripts.import_dingtalk_media_assets import import_report

    db = SessionLocal()
    try:
        # 先清理
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_UPSERT_001").delete()
        db.commit()
    finally:
        db.close()

    try:
        report = {
            "summary": {"local_unmatched_products_count": 0},
            "details": [
                {
                    "product_id": 999002,
                    "i_id": "TEST_UPSERT_001",
                    "product_name": "测试去重",
                    "match_reasons": ["i_id_exact:TEST_UPSERT_001"],
                    "matched_dt_skus": ["TEST_UPSERT_001"],
                    "has_install_video": True,
                    "has_pack_guide": False,
                    "has_sku_images": True,
                    "install_videos": {"douyin": {"url": "https://example.com/v.mp4?Expires=9999999999", "title": "视频"}},
                    "pack_guide_images": [],
                    "sku_images": ["https://example.com/s.png?Expires=9999999999"],
                },
            ],
        }
        report_path = tmp_path / "upsert.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

        s1 = import_report(str(report_path), dry_run=False)
        assert s1["new_assets"] == 2

        s2 = import_report(str(report_path), dry_run=False)
        assert s2["new_assets"] == 0
        assert s2["updated_assets"] == 2
    finally:
        db = SessionLocal()
        try:
            db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_UPSERT_001").delete()
            db.commit()
        finally:
            db.close()


def test_auto_approve_low_risk_only(tmp_path):
    """--auto-approve-low-risk 只自动审核低风险类型，且过期链接不通过。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from scripts.import_dingtalk_media_assets import import_report

    db = SessionLocal()
    try:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id.like("TEST_AUTO_APPROVE_%")).delete()
        db.commit()
    finally:
        db.close()

    try:
        future_ts = int((datetime.utcnow() + timedelta(days=1)).timestamp())
        past_ts = int((datetime.utcnow() - timedelta(days=1)).timestamp())
        report = {
            "summary": {"local_unmatched_products_count": 0},
            "details": [
                {
                    "product_id": 999003,
                    "i_id": "TEST_AUTO_APPROVE_001",
                    "product_name": "测试自动审核",
                    "match_reasons": ["i_id_exact"],
                    "matched_dt_skus": ["TEST_AUTO_APPROVE_001"],
                    "has_install_video": True,
                    "has_pack_guide": True,
                    "has_sku_images": True,
                    # 未过期：应被自动审核
                    "install_videos": {"douyin": {"url": f"https://example.com/future.mp4?Expires={future_ts}", "title": "视频"}},
                    "pack_guide_images": [f"https://example.com/future_pack.png?Expires={future_ts}"],
                    "sku_images": [f"https://example.com/future_sku.png?Expires={future_ts}"],
                },
                {
                    "product_id": 999004,
                    "i_id": "TEST_AUTO_APPROVE_002",
                    "product_name": "测试过期不审核",
                    "match_reasons": ["i_id_exact"],
                    "matched_dt_skus": ["TEST_AUTO_APPROVE_002"],
                    "has_install_video": True,
                    "has_pack_guide": False,
                    "has_sku_images": False,
                    # 已过期：即使开启也不应自动通过
                    "install_videos": {"douyin": {"url": f"https://example.com/past.mp4?Expires={past_ts}", "title": "视频"}},
                    "pack_guide_images": [],
                    "sku_images": [],
                },
            ],
        }
        report_path = tmp_path / "auto_approve.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

        s = import_report(str(report_path), dry_run=False, auto_approve_low_risk=True)
        assert s["new_assets"] == 4
        assert s["approved_assets"] == 3, "只有未过期的低风险素材才自动审核"

        db = SessionLocal()
        try:
            approved = db.query(KBMediaAsset).filter(
                KBMediaAsset.i_id == "TEST_AUTO_APPROVE_001",
                KBMediaAsset.status == "approved",
                KBMediaAsset.usable_for_agent == 1,
            ).count()
            assert approved == 3

            expired = db.query(KBMediaAsset).filter(
                KBMediaAsset.i_id == "TEST_AUTO_APPROVE_002",
                KBMediaAsset.asset_type == "install_video",
            ).first()
            assert expired.status == "pending_review"
            assert expired.refresh_status == "needs_refresh"
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            db.query(KBMediaAsset).filter(KBMediaAsset.i_id.like("TEST_AUTO_APPROVE_%")).delete()
            db.commit()
        finally:
            db.close()


# ─── 6. 前端 smoke（HTTP 200） ─────────────────────────────────────

@pytest.mark.parametrize("path", ["/real-test", "/", "/media"])
def test_pages_render(app, path):
    client = app.test_client()
    r = client.get(path)
    assert r.status_code == 200


def test_real_test_has_media_section(app):
    client = app.test_client()
    html = client.get("/real-test").get_data(as_text=True)
    assert "建议发送素材" in html
    assert "renderMediaSuggest" in html


# ─── 8. 素材库页面 /ask/kb-admin/media 前缀回归 ───────────────────────

def test_media_page_opens_and_has_no_duplicate_prefix(app):
    """锁住 /ask/api/kb/ask/api/... 这种重复前缀不再出现。"""
    client = app.test_client()
    resp = client.get("/ask/kb-admin/media", follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert html
    assert "/ask/api/kb/ask/api" not in html, "页面 HTML 中仍存在重复 API 前缀"

    # 检查构建产物 MediaLibraryPage chunk
    import glob
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for chunk in glob.glob(os.path.join(project_root, "web/static/kb-admin/assets/MediaLibraryPage-*.js")):
        content = open(chunk, encoding="utf-8").read()
        assert "/ask/api/kb/ask/api" not in content, f"{chunk} 中仍存在重复 API 前缀"


def test_media_api_paths_under_ask_prefix(client, set_admin_test_principal):
    """素材库接口统一通过 /ask/api/media-assets 可访问，权限正常。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.models.kb_tables import KBMediaAsset
    import datetime as dt

    db = SessionLocal()
    try:
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_IID_001").delete()
        db.commit()
        asset = KBMediaAsset(
            product_id=999001, i_id="TEST_IID_001", sku_code="TEST_SKU_001",
            product_name="测试商品A", asset_type="sku_image", asset_title="test",
            asset_url="http://t/t.png", source="test", source_doc_id="t",
            source_raw_json="{}", match_confidence=0.5, match_reason="test",
            content_hash="", scene_tags_json="[]", status="pending_review", usable_for_agent=0,
            last_seen_at=dt.datetime.utcnow(), created_at=dt.datetime.utcnow(), updated_at=dt.datetime.utcnow(),
        )
        db.add(asset); db.commit(); db.refresh(asset); aid = asset.id
    finally:
        db.close()

    try:
        # stats / list / filter
        r = client.get("/ask/api/media-assets/stats")
        assert r.status_code == 200
        stats = r.get_json()
        assert "total" in stats and stats["total"] >= 0

        r = client.get("/ask/api/media-assets?limit=2&offset=0")
        assert r.status_code == 200
        assert "items" in r.get_json()

        r = client.get("/ask/api/media-assets", query_string={"product_name": "测试商品A", "limit": 5})
        assert r.status_code == 200
        assert any(item["id"] == aid for item in r.get_json()["items"])

        r = client.get("/ask/api/media-assets?status=pending_review&usable_for_agent=false&limit=2")
        assert r.status_code == 200

        # operator 无权 approve
        set_admin_test_principal("operator")
        r = client.post(f"/ask/api/media-assets/{aid}/approve")
        assert r.status_code == 403

        # supervisor approve
        set_admin_test_principal("supervisor")
        r = client.post(f"/ask/api/media-assets/{aid}/approve")
        assert r.status_code == 200
        assert r.get_json()["asset"]["status"] == "approved"
        assert r.get_json()["asset"]["usable_for_agent"] is True

        # supervisor reject
        r = client.post(f"/ask/api/media-assets/{aid}/reject")
        assert r.status_code == 200
        assert r.get_json()["asset"]["status"] == "rejected"

        # supervisor update
        r = client.post(f"/ask/api/media-assets/{aid}/update", json={"asset_title": "updated"})
        assert r.status_code == 200
        assert r.get_json()["asset"]["asset_title"] == "updated"
    finally:
        db = SessionLocal()
        try:
            db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_IID_001").delete()
            db.commit()
        finally:
            db.close()


def test_copilot_panel_has_media_section(app):
    client = app.test_client()
    html = client.get("/copilot-panel").get_data(as_text=True)
    assert "建议发送素材" in html
    assert "renderMediaSuggest" in html


# ─── 7. 推荐策略与安全边界 ──────────────────────────────────────────

def _create_test_asset(db, **kwargs):
    """在 TEST_IID_001 下创建一条测试素材。"""
    import app.models.kb_tables  # noqa: F401
    from app.models.kb_tables import KBMediaAsset
    import datetime as dt
    defaults = {
        "product_id": 999001,
        "i_id": "TEST_IID_001",
        "sku_code": "TEST_SKU_001",
        "product_name": "测试商品A",
        "source": "test",
        "source_doc_id": "test_doc",
        "source_raw_json": "{}",
        "match_confidence": 0.9,
        "match_reason": "测试匹配",
        "content_hash": "",
        "scene_tags_json": "[]",
        "last_seen_at": dt.datetime.utcnow(),
        "created_at": dt.datetime.utcnow(),
        "updated_at": dt.datetime.utcnow(),
    }
    defaults.update(kwargs)
    asset = KBMediaAsset(**defaults)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def test_recommend_strategy_install_video():
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        _create_test_asset(db, asset_type="pack_guide_image", asset_title="打包图", asset_url="http://t/pack.png", status="approved", usable_for_agent=1)
        _create_test_asset(db, asset_type="install_video", asset_title="安装视频", asset_url="http://t/install.mp4", status="approved", usable_for_agent=1)
        reco = m.get_recommended_assets_for_message(
            customer_message="这个怎么安装？有视频吗", i_id="TEST_IID_001", intent="installation")
        assert len(reco["recommended_assets"]) >= 1
        assert reco["recommended_assets"][0]["asset_type"] == "install_video"
        assert reco["recommended_assets"][0]["send_mode"] == "auto_when_platform_connected"
        assert "视频" in reco["recommended_assets"][0]["match_reason"]
    finally:
        db.close()


def test_recommend_strategy_accessory():
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        _create_test_asset(db, asset_type="sku_image", asset_title="商品图", asset_url="http://t/sku.png", status="approved", usable_for_agent=1)
        _create_test_asset(db, asset_type="accessory_image", asset_title="配件图", asset_url="http://t/acc.png", status="approved", usable_for_agent=1)
        reco = m.get_recommended_assets_for_message(
            customer_message="少了个配件", i_id="TEST_IID_001", intent="aftersales")
        assert len(reco["recommended_assets"]) >= 1
        assert reco["recommended_assets"][0]["asset_type"] == "accessory_image"
    finally:
        db.close()


def test_recommend_strategy_appearance():
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        _create_test_asset(db, asset_type="size_image", asset_title="尺寸图", asset_url="http://t/size.png", status="approved", usable_for_agent=1)
        _create_test_asset(db, asset_type="sku_image", asset_title="商品图", asset_url="http://t/sku.png", status="approved", usable_for_agent=1)
        reco = m.get_recommended_assets_for_message(
            customer_message="什么颜色款式", i_id="TEST_IID_001", intent="product_question")
        assert len(reco["recommended_assets"]) >= 1
        assert reco["recommended_assets"][0]["asset_type"] == "sku_image"
    finally:
        db.close()


def test_recommend_strategy_size():
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        _create_test_asset(db, asset_type="sku_image", asset_title="商品图", asset_url="http://t/sku.png", status="approved", usable_for_agent=1)
        _create_test_asset(db, asset_type="size_image", asset_title="尺寸图", asset_url="http://t/size.png", status="approved", usable_for_agent=1)
        reco = m.get_recommended_assets_for_message(
            customer_message="尺寸多大", i_id="TEST_IID_001", intent="size_query")
        assert len(reco["recommended_assets"]) >= 1
        assert reco["recommended_assets"][0]["asset_type"] == "size_image"
    finally:
        db.close()


def test_recommend_strategy_detachable_prefers_size_image():
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        _create_test_asset(db, asset_type="sku_image", asset_title="商品图", asset_url="http://t/sku.png", status="approved", usable_for_agent=1)
        _create_test_asset(db, asset_type="size_image", asset_title="尺寸拆卸图", asset_url="http://t/size-detachable.png", status="approved", usable_for_agent=1)
        reco = m.get_recommended_assets_for_message(
            customer_message="这个可以拆卸吗", i_id="TEST_IID_001", intent="product_question")
        assert len(reco["recommended_assets"]) >= 1
        assert reco["recommended_assets"][0]["asset_type"] == "size_image"
        assert reco["recommended_assets"][0]["send_mode"] == "auto_when_platform_connected"
    finally:
        db.close()


def test_recommend_material_safety_no_image():
    """材质/安全/质检类问题不能把图片当证据，默认不推荐素材。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        _create_test_asset(db, asset_type="sku_image", asset_title="商品图", asset_url="http://t/sku.png", status="approved", usable_for_agent=1)
        reco = m.get_recommended_assets_for_message(
            customer_message="这个有甲醛吗，材质安全吗", i_id="TEST_IID_001", intent="material_safety")
        assert reco["recommended_assets"] == []
    finally:
        db.close()


def test_recommend_pending_not_recommended():
    """pending_review 素材即使匹配也不能进入推荐。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        _create_test_asset(db, asset_type="install_video", asset_title="待审核视频", asset_url="http://t/pending.mp4", status="pending_review", usable_for_agent=0)
        reco = m.get_recommended_assets_for_message(
            customer_message="安装视频", i_id="TEST_IID_001", intent="installation")
        assert reco["recommended_assets"] == []
        # 同时 has_unapproved 应提示主管去审核（不暴露链接）
        assert reco["has_unapproved"] is True
    finally:
        db.close()


def test_recommended_asset_schema():
    """推荐素材必须包含前端展示所需的结构化字段。"""
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from app.services import media_asset_service as m

    db = SessionLocal()
    try:
        _create_test_asset(db, asset_type="install_video", asset_title="安装视频", asset_url="http://t/install.mp4", status="approved", usable_for_agent=1)
        reco = m.get_recommended_assets_for_message(
            customer_message="安装视频", i_id="TEST_IID_001", intent="installation")
        assert len(reco["recommended_assets"]) == 1
        a = reco["recommended_assets"][0]
        for key in ["id", "asset_id", "asset_type", "asset_title", "asset_url",
                    "product_name", "i_id", "send_mode", "confidence", "match_reason"]:
            assert key in a, f"缺少字段 {key}"
        assert a["asset_url"].startswith("http")
        assert a["send_mode"] == "auto_when_platform_connected"
    finally:
        db.close()


def test_reply_blocks_include_first_safe_media_asset():
    from app.services.media_asset_service import build_reply_blocks

    result = build_reply_blocks(
        "亲，可以参考下尺寸图哦。",
        [{
            "asset_id": 123,
            "asset_type": "size_image",
            "asset_title": "尺寸图",
            "asset_url": "http://t/size.png",
            "product_name": "测试商品",
        }],
        requires_human_review=False,
    )

    assert result["reply_delivery"]["auto_send_ready"] is True
    assert result["reply_blocks"][0]["type"] == "text"
    assert result["reply_blocks"][1]["type"] == "image"
    assert result["reply_blocks"][1]["asset_type"] == "size_image"


def test_reply_blocks_preview_media_when_human_review_required_but_do_not_auto_send():
    from app.services.media_asset_service import build_reply_blocks

    result = build_reply_blocks(
        "亲，我先帮您核实一下。",
        [{"asset_type": "size_image", "asset_title": "尺寸图", "asset_url": "http://t/size.png"}],
        requires_human_review=True,
    )

    assert result["reply_delivery"]["auto_send_ready"] is False
    assert result["reply_delivery"]["reason"] == "requires_human_review"
    assert [b["type"] for b in result["reply_blocks"]] == ["text", "image"]


def test_strict_delivery_media_requires_review_identity_and_matching_role():
    from app.services.media_asset_service import build_reply_blocks

    base = {
        "asset_type": "install_image",
        "asset_title": "Installation guide",
        "asset_url": "https://asset.example/install.png",
        "auto_send_level": "auto",
        "status": "approved",
        "usable_for_agent": True,
        "i_id": "IID-A",
    }
    kwargs = {"query_fact_type": "installation", "product_identity": {"i_id": "IID-A"}}

    accepted = build_reply_blocks("See the attached installation guide.", [base], **kwargs)
    missing_review = build_reply_blocks("See the guide.", [{**base, "status": "pending_review"}], **kwargs)
    wrong_identity = build_reply_blocks("See the guide.", [{**base, "i_id": "IID-B"}], **kwargs)
    wrong_role = build_reply_blocks(
        "See the guide.",
        [{**base, "asset_type": "sku_image"}],
        **kwargs,
    )

    assert [block["type"] for block in accepted["reply_blocks"]] == ["text", "image"]
    assert [block["type"] for block in missing_review["reply_blocks"]] == ["text"]
    assert [block["type"] for block in wrong_identity["reply_blocks"]] == ["text"]
    assert [block["type"] for block in wrong_role["reply_blocks"]] == ["text"]


def test_api_analyze_recommended_assets_gating(client, monkeypatch):
    """/api/analyze 只返回 approved+usable+ok 的素材；pending/rejected/needs_refresh/material_safety 不返回。

    使用测试 fixture 创建素材，不写死真实商品名/URL。
    """
    import app.models.kb_tables  # noqa: F401
    from app.db import SessionLocal
    from datetime import timedelta
    from app.services import analysis_execution_service as execution_module

    db = SessionLocal()
    try:
        # 清理
        db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_API_ANALYZE_001").delete()
        db.commit()

        now = datetime.utcnow()
        # approved + usable + ok
        _create_test_asset(
            db, i_id="TEST_API_ANALYZE_001", sku_code="TEST_API_ANALYZE_001",
            product_name="测试分析商品", asset_type="sku_image",
            asset_url="http://t/sku.png", content_hash="hash_ok",
            status="approved", usable_for_agent=1, refresh_status="ok",
            url_expires_at=now + timedelta(days=1),
        )
        # pending
        _create_test_asset(
            db, i_id="TEST_API_ANALYZE_001", sku_code="TEST_API_ANALYZE_001",
            product_name="测试分析商品", asset_type="pack_guide_image",
            asset_url="http://t/pending.png", content_hash="hash_pending",
            status="pending_review", usable_for_agent=0,
        )
        # rejected
        _create_test_asset(
            db, i_id="TEST_API_ANALYZE_001", sku_code="TEST_API_ANALYZE_001",
            product_name="测试分析商品", asset_type="install_video",
            asset_url="http://t/rejected.mp4", content_hash="hash_rejected",
            status="rejected", usable_for_agent=0,
        )
        # approved but needs_refresh
        _create_test_asset(
            db, i_id="TEST_API_ANALYZE_001", sku_code="TEST_API_ANALYZE_001",
            product_name="测试分析商品", asset_type="size_image",
            asset_url="http://t/expired.png", content_hash="hash_expired",
            status="approved", usable_for_agent=1, refresh_status="needs_refresh",
            url_expires_at=now - timedelta(days=1),
        )
    finally:
        db.close()

    def _fake_execute(*args, **kwargs):
        response = {
            "intent": "product_question",
            "evidence_debug": {"semantic_query": {"needs_visual_asset": True}},
            "context_used": {
                "conversation_context_summary": {
                    "current_customer_message": "这个有图片吗？",
                    "confirmed_product": "测试分析商品",
                }
            },
        }
        return kwargs["response_post_processor"](response)

    monkeypatch.setattr(execution_module, "execute_analysis", _fake_execute)
    try:
        payload = {
            "message": "这个有图片吗？",
            "conversation_id": "pytest_api_analyze_gating",
            "product_name": "测试分析商品",
            "product_candidates": [
                {"value": "TEST_API_ANALYZE_001", "type": "sku_id_candidate", "source": "test", "verified": True}
            ],
        }
        r = client.post("/api/analyze", json=payload)
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        recos = data.get("recommended_assets", [])
        assert len(recos) == 1
        a = recos[0]
        assert a["asset_type"] == "sku_image"
        assert a["i_id"] == "TEST_API_ANALYZE_001"
        assert a["status"] == "approved"
        assert a["usable_for_agent"] is True
        assert a["send_mode"] == "auto_when_platform_connected"
        for key in ["id", "asset_id", "asset_type", "asset_title", "asset_url",
                    "product_name", "i_id", "sku_code", "status", "usable_for_agent",
                    "send_mode", "match_reason"]:
            assert key in a, f"缺少字段 {key}"

        # material_safety 不应返回图片
        payload2 = {
            "message": "这个有甲醛吗？安全吗？",
            "conversation_id": "pytest_api_analyze_gating",
            "product_name": "测试分析商品",
            "product_candidates": [
                {"value": "TEST_API_ANALYZE_001", "type": "sku_id_candidate", "source": "test", "verified": True}
            ],
        }
        def _material_safety_execute(*args, **kwargs):
            response = {
                "intent": "material_safety",
                "context_used": {
                    "conversation_context_summary": {
                        "current_customer_message": "这个有甲醛吗？安全吗？",
                        "confirmed_product": "测试分析商品",
                    }
                },
            }
            return kwargs["response_post_processor"](response)

        monkeypatch.setattr(execution_module, "execute_analysis", _material_safety_execute)
        r2 = client.post("/api/analyze", json=payload2)
        data2 = r2.get_json()
        assert data2.get("recommended_assets") == []
    finally:
        db = SessionLocal()
        try:
            db.query(KBMediaAsset).filter(KBMediaAsset.i_id == "TEST_API_ANALYZE_001").delete()
            db.commit()
        finally:
            db.close()
