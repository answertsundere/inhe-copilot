"""
图片/视频素材库 API 路由。

挂载点: /api/media-assets/*
（经 /ask 前缀中间件后，公网/本地均可通过 /ask/api/media-assets/* 访问）

权限：
- 列表/推荐：所有已登录后台/工作台可读。
- 导入/审核/编辑：仅 supervisor/admin（主管/管理员），通过 X-User-Role 判断。
- 本服务不会自动发送任何素材给客户，仅做「AI 推荐 + 人工确认」。
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from app.config import BASE_DIR

media_bp = Blueprint("media", __name__, url_prefix="/api/media-assets")

_UPLOAD_DIR = os.environ.get(
    "COPILOT_MEDIA_ASSET_UPLOAD_DIR",
    os.path.join(BASE_DIR, "data", "media_asset_uploads"),
)

_ALLOWED_MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm", ".mov"}
_ALLOWED_MEDIA_MIMES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "video/mp4", "video/webm", "video/quicktime",
}
_MEDIA_MAX_SIZE = 50 * 1024 * 1024

# 允许操作（写）的角色
_SUPERVISOR_ROLES = ("supervisor", "admin")


def _user_info():
    role = request.headers.get("X-User-Role", "operator")
    name = request.headers.get("X-User-Name", "anonymous")
    return role, name


def _require_supervisor():
    role, name = _user_info()
    return role in _SUPERVISOR_ROLES, role, name


def _ensure_media_upload_dir():
    today = datetime.utcnow().strftime("%Y%m%d")
    path = os.path.join(_UPLOAD_DIR, today)
    os.makedirs(path, exist_ok=True)
    return path, today


def _validate_media_file(file):
    if not file or not file.filename:
        return "未选择文件"
    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in _ALLOWED_MEDIA_EXTS:
        return f"不支持的文件格式: {ext}"
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > _MEDIA_MAX_SIZE:
        return f"文件大小超过 50MB: {size}"
    mime = file.content_type or "application/octet-stream"
    if mime not in _ALLOWED_MEDIA_MIMES:
        return f"不支持的 MIME 类型: {mime}"
    return None


@media_bp.route("", methods=["GET"])
def list_assets():
    """素材列表（支持筛选）。"""
    from app.db import SessionLocal
    from app.services.media_asset_service import list_media_assets

    args = request.args
    db = SessionLocal()
    try:
        result = list_media_assets(
            db,
            product_id=int(args["product_id"]) if args.get("product_id") else None,
            i_id=args.get("i_id") or None,
            sku_code=args.get("sku_code") or None,
            product_name=args.get("product_name") or None,
            asset_type=args.get("asset_type") or None,
            status=args.get("status") or None,
            usable_for_agent=_parse_bool(args.get("usable_for_agent")),
            keyword=args.get("keyword") or None,
            category_l1=args.get("category_l1") or None,
            category_l2=args.get("category_l2") or None,
            category_l3=args.get("category_l3") or None,
            limit=int(args.get("limit", 200)),
            offset=int(args.get("offset", 0)),
        )
        return jsonify(result)
    finally:
        db.close()


@media_bp.route("/stats", methods=["GET"])
def stats():
    """素材库总览统计。"""
    from app.db import SessionLocal
    from app.services.media_asset_service import media_stats

    db = SessionLocal()
    try:
        return jsonify(media_stats(db))
    finally:
        db.close()


@media_bp.route("/recommend", methods=["GET"])
def recommend():
    """根据消息推荐已审核可用素材（供工作台/Agent 调用）。

    只返回 status=approved 且 usable_for_agent=1 的素材。
    """
    from app.services.media_asset_service import get_recommended_assets_for_message

    args = request.args
    result = get_recommended_assets_for_message(
        customer_message=args.get("customer_message", ""),
        product_id=int(args["product_id"]) if args.get("product_id") else None,
        i_id=args.get("i_id") or None,
        sku_code=args.get("sku_code") or None,
        intent=args.get("intent") or "",
        limit=int(args.get("limit", 5)),
    )
    return jsonify(result)


@media_bp.route("/import-dingtalk-report", methods=["POST"])
def import_dingtalk_report():
    """手动触发从 dingtalk_media_report_v2.json 导入本地素材库。

    仅 supervisor/admin 可用（后台维护，不暴露给普通客服）。
    """
    ok, role, name = _require_supervisor()
    if not ok:
        return jsonify({"error": "仅主管/管理员可执行导入"}), 403

    import os
    from pathlib import Path

    body = request.get_json(silent=True) or {}
    project_root = Path(__file__).resolve().parent.parent.parent
    report_path = body.get("report") or str(project_root / "data" / "dingtalk_media_report_v2.json")

    if not os.path.exists(report_path):
        return jsonify({"error": f"报告文件不存在: {report_path}"}), 400

    # 延迟导入脚本（脚本内会触发 sys.path 插入）
    import importlib.util
    import sys
    script_path = project_root / "scripts" / "import_dingtalk_media_assets.py"
    spec = importlib.util.spec_from_file_location("import_dingtalk_media_assets", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["import_dingtalk_media_assets"] = mod
    spec.loader.exec_module(mod)

    reset = bool(body.get("reset_urls_on_change", False))
    stats = mod.import_report(report_path, reset_urls_on_change=reset, dry_run=False)
    stats["performed_by"] = name
    return jsonify({"ok": True, "stats": stats})


@media_bp.route("/<int:asset_id>/approve", methods=["POST"])
def approve_asset(asset_id):
    """审核通过：status=approved, usable_for_agent=1。"""
    ok, role, name = _require_supervisor()
    if not ok:
        return jsonify({"error": "仅主管/管理员可审核"}), 403
    from app.db import SessionLocal
    from app.services.media_asset_service import approve_asset as _approve
    db = SessionLocal()
    try:
        asset = _approve(db, asset_id, reviewer=name)
        if not asset:
            return jsonify({"error": "素材不存在"}), 404
        return jsonify({"ok": True, "asset": asset.to_dict()})
    finally:
        db.close()


@media_bp.route("/<int:asset_id>/reject", methods=["POST"])
def reject_asset(asset_id):
    """审核拒绝：status=rejected, usable_for_agent=0。"""
    ok, role, name = _require_supervisor()
    if not ok:
        return jsonify({"error": "仅主管/管理员可审核"}), 403
    from app.db import SessionLocal
    from app.services.media_asset_service import reject_asset as _reject
    db = SessionLocal()
    try:
        asset = _reject(db, asset_id, reviewer=name)
        if not asset:
            return jsonify({"error": "素材不存在"}), 404
        return jsonify({"ok": True, "asset": asset.to_dict()})
    finally:
        db.close()


@media_bp.route("/<int:asset_id>/update", methods=["POST"])
def update_asset(asset_id):
    """人工编辑素材字段。"""
    ok, role, name = _require_supervisor()
    if not ok:
        return jsonify({"error": "仅主管/管理员可编辑"}), 403
    from app.db import SessionLocal
    from app.services.media_asset_service import update_asset as _update
    body = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        asset = _update(db, asset_id, body, editor=name)
        if not asset:
            return jsonify({"error": "素材不存在"}), 404
        return jsonify({"ok": True, "asset": asset.to_dict()})
    finally:
        db.close()


@media_bp.route("/<int:asset_id>", methods=["DELETE"])
def delete_asset(asset_id):
    """删除素材（仅从素材库移除，不影响已发出的消息记录）。"""
    ok, role, name = _require_supervisor()
    if not ok:
        return jsonify({"error": "仅主管/管理员可删除"}), 403
    from app.db import SessionLocal
    from app.services.media_asset_service import delete_asset as _delete
    db = SessionLocal()
    try:
        asset = _delete(db, asset_id)
        if not asset:
            return jsonify({"error": "素材不存在"}), 404
        return jsonify({"ok": True})
    finally:
        db.close()


@media_bp.route("/upload", methods=["POST"])
def upload_asset():
    """本地上传图片/视频到素材库。

    表单字段:
    - file: 必填, 图片或视频
    - product_id: 可选, 关联商品 id
    - i_id: 可选
    - product_name: 可选
    - asset_type: 默认 other
    - asset_title: 默认原文件名
    - scene_tags: JSON 数组字符串, 默认 []
    """
    ok, role, name = _require_supervisor()
    if not ok:
        return jsonify({"error": "仅主管/管理员可上传素材"}), 403

    from app.db import SessionLocal
    from app.models.kb_tables import KBMediaAsset

    if "file" not in request.files:
        return jsonify({"error": "未找到文件字段 file"}), 400
    file = request.files["file"]
    err = _validate_media_file(file)
    if err:
        return jsonify({"error": err}), 400

    today_dir, today = _ensure_media_upload_dir()
    ext = os.path.splitext(file.filename.lower())[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(today_dir, stored_name)
    file.save(file_path)

    product_id = request.form.get("product_id") or None
    if product_id:
        try:
            product_id = int(product_id)
        except ValueError:
            product_id = None
    i_id = request.form.get("i_id", "")
    product_name = request.form.get("product_name", "")
    asset_type = request.form.get("asset_type", "other")
    asset_title = request.form.get("asset_title") or file.filename
    try:
        scene_tags = json.loads(request.form.get("scene_tags", "[]"))
        if not isinstance(scene_tags, list):
            scene_tags = []
    except Exception:
        scene_tags = []

    asset_url = f"/ask/api/media-assets/uploads/{today}/{stored_name}"
    db = SessionLocal()
    try:
        asset = KBMediaAsset(
            product_id=product_id,
            i_id=i_id,
            sku_code="",
            product_name=product_name,
            asset_type=asset_type,
            asset_title=asset_title,
            asset_url=asset_url,
            source="upload",
            source_doc_id="",
            match_confidence=1.0,
            match_reason="本地上传",
            status="pending_review",
            audit_status="unreviewed",
            usable_for_agent=0,
            created_by=name,
            updated_by=name,
        )
        asset.set_scene_tags(scene_tags)
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return jsonify({"ok": True, "asset": asset.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@media_bp.route("/uploads/<path:filename>", methods=["GET"])
def serve_upload(filename):
    """访问本地上传的素材文件。"""
    from werkzeug.utils import safe_join
    file_path = safe_join(_UPLOAD_DIR, filename)
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "文件不存在"}), 404
    mime = None
    if filename.lower().endswith((".mp4", ".webm", ".mov")):
        mime_map = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
        ext = os.path.splitext(filename.lower())[1]
        mime = mime_map.get(ext)
    return send_file(file_path, mimetype=mime, as_attachment=False)


@media_bp.route("/batch-update-tags", methods=["POST"])
def batch_update_tags():
    """批量为素材添加/移除场景标签。"""
    ok, role, name = _require_supervisor()
    if not ok:
        return jsonify({"error": "仅主管/管理员可操作"}), 403
    from app.db import SessionLocal
    from app.models.kb_tables import KBMediaAsset
    body = request.get_json(silent=True) or {}
    asset_ids = body.get("asset_ids", [])
    add_tags = body.get("add_tags", []) or []
    remove_tags = body.get("remove_tags", []) or []
    if not asset_ids:
        return jsonify({"error": "asset_ids 不能为空"}), 400
    if not isinstance(asset_ids, list):
        return jsonify({"error": "asset_ids 必须是列表"}), 400

    db = SessionLocal()
    try:
        assets = db.query(KBMediaAsset).filter(KBMediaAsset.id.in_(asset_ids)).all()
        updated = 0
        for asset in assets:
            tags = set(asset.get_scene_tags())
            for t in add_tags:
                if t:
                    tags.add(t)
            for t in remove_tags:
                tags.discard(t)
            asset.set_scene_tags(sorted(tags))
            asset.updated_by = name
            asset.updated_at = datetime.utcnow()
            updated += 1
        db.commit()
        return jsonify({"ok": True, "updated": updated})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _parse_bool(val):
    if val is None:
        return None
    return str(val).lower() in ("1", "true", "yes", "on")
