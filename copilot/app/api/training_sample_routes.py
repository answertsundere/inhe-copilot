"""
客服训练样本 API
- 客服录入最新对话问题，用于训练客服系统
- 支持图文混排（富文本 HTML + 图片附件嵌入）
"""

import base64
import json
import os
import re
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file

from app.config import BASE_DIR, TRAINING_SAMPLE_UPLOAD_DIR
from app.repositories.training_sample_repository import TrainingSampleRepository
from app.api.admin_auth import current_user_name

training_sample_bp = Blueprint("training_sample", __name__, url_prefix="/api/kb")


_UPLOAD_DIR = TRAINING_SAMPLE_UPLOAD_DIR
_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _get_user_info():
    return current_user_name()


def _ensure_upload_dir():
    today = datetime.utcnow().strftime("%Y%m%d")
    path = os.path.join(_UPLOAD_DIR, today)
    os.makedirs(path, exist_ok=True)
    return path


def _json_field(data, key, default=None):
    value = data.get(key, default)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return value


_IMG_SRC_RE = re.compile(r'<img[^>]+src="(data:image/([^;]+);base64,([^"]+))"', re.IGNORECASE)
_MIME_TO_EXT = {
    "png": ".png",
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "webp": ".webp",
    "gif": ".gif",
}


def _extract_base64_images(sample_id: int, html: str, field_name: str) -> str:
    """提取 HTML 中的 base64 图片，保存为附件并替换 URL"""
    if not html:
        return html

    def _replace(match):
        mime_subtype = (match.group(2) or "").lower()
        base64_data = match.group(3)
        ext = _MIME_TO_EXT.get(mime_subtype, ".png")
        mime_type = f"image/{mime_subtype}" if mime_subtype else "image/png"

        try:
            image_bytes = base64.b64decode(base64_data)
        except Exception:
            return match.group(0)

        if len(image_bytes) > _MAX_FILE_SIZE:
            return match.group(0)

        today_dir = _ensure_upload_dir()
        stored_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(today_dir, stored_name)
        with open(file_path, "wb") as f:
            f.write(image_bytes)

        try:
            att = TrainingSampleRepository.add_attachment(
                sample_id=sample_id,
                field_name=field_name,
                original_filename=f"pasted_image{ext}",
                stored_filename=stored_name,
                file_path=file_path,
                file_size=len(image_bytes),
                mime_type=mime_type,
            )
            return match.group(0).replace(
                match.group(1),
                f"/ask/api/kb/training-samples/{sample_id}/attachments/{att.id}",
            )
        except Exception:
            try:
                os.remove(file_path)
            except OSError:
                pass
            return match.group(0)

    return _IMG_SRC_RE.sub(_replace, html)


# ============ 创建训练样本 ============

@training_sample_bp.route("/training-samples", methods=["POST"])
def api_create_training_sample():
    """创建训练样本"""
    name = _get_user_info()
    data = request.get_json(silent=True) or {}

    customer_quote = (data.get("customer_quote") or "").strip()
    if not customer_quote:
        return jsonify({"error": "客户原话不能为空"}), 400

    sample = TrainingSampleRepository.create(
        collected_at=_parse_datetime(data.get("collected_at")) or datetime.utcnow(),
        csr_name=(data.get("csr_name") or "").strip(),
        shop_platform=(data.get("shop_platform") or "").strip(),
        customer_quote=data.get("customer_quote", ""),
        full_context=data.get("full_context", ""),
        product_title=(data.get("product_title") or "").strip(),
        sku=(data.get("sku") or "").strip(),
        order_no=(data.get("order_no") or "").strip(),
        question_type=(data.get("question_type") or "").strip(),
        difficulty_reason=(data.get("difficulty_reason") or "").strip(),
        csr_actual_reply=data.get("csr_actual_reply", ""),
        correct_answer=data.get("correct_answer", ""),
        need_knowledge_base=bool(data.get("need_knowledge_base", False)),
        target_knowledge_base=(data.get("target_knowledge_base") or "").strip(),
        need_media=bool(data.get("need_media", False)),
        media_links_json=json.dumps(
            _json_field(data, "media_links", []) or [], ensure_ascii=False
        ),
        risk_level=(data.get("risk_level") or "低").strip(),
        auto_reply_type=(data.get("auto_reply_type") or "需人工确认").strip(),
        review_status=(data.get("review_status") or "待处理").strip(),
        owner=(data.get("owner") or "").strip(),
        notes=(data.get("notes") or "").strip(),
        created_by=name,
    )

    # 提取富文本中的 base64 图片并转存为附件
    updated = TrainingSampleRepository.update(
        sample.id,
        customer_quote=_extract_base64_images(sample.id, sample.customer_quote, "customer_quote"),
        full_context=_extract_base64_images(sample.id, sample.full_context, "full_context"),
        csr_actual_reply=_extract_base64_images(sample.id, sample.csr_actual_reply, "csr_actual_reply"),
        correct_answer=_extract_base64_images(sample.id, sample.correct_answer, "correct_answer"),
    )

    return jsonify({"id": updated.id, "data": updated.to_dict()}), 201


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


# ============ 列表查询 ============

@training_sample_bp.route("/training-samples", methods=["GET"])
def api_list_training_samples():
    """训练样本列表，支持筛选"""
    review_status = request.args.get("review_status", "")
    question_type = request.args.get("question_type", "")
    difficulty_reason = request.args.get("difficulty_reason", "")
    risk_level = request.args.get("risk_level", "")
    keyword = request.args.get("keyword", "")
    created_by = request.args.get("created_by", "")
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)

    try:
        items, total = TrainingSampleRepository.list_items(
            review_status=review_status,
            question_type=question_type,
            difficulty_reason=difficulty_reason,
            risk_level=risk_level,
            keyword=keyword,
            created_by=created_by,
            limit=limit,
            offset=offset,
        )
        return jsonify({
            "items": [item.to_dict() for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============ 详情 ============

# ============ Evaluation set conversion ============

@training_sample_bp.route("/training-samples/eval-set/build", methods=["POST"])
def api_build_training_sample_eval_set():
    """Preview reviewed samples for manual evaluation-set curation."""
    from app.services.training_sample_eval_set_service import TrainingSampleEvalSetService

    data = request.get_json(silent=True) or {}
    sample_ids = _json_field(data, "sample_ids", None)
    limit = data.get("limit")
    dry_run = bool(data.get("dry_run", False))
    if not dry_run:
        return jsonify({
            "error": "batch_eval_set_conversion_disabled",
            "message": "评测集必须逐条人工阅读并提供策展后的 eval_contract，禁止批量自动转入。",
        }), 400
    try:
        result = TrainingSampleEvalSetService().convert_reviewed(
            sample_ids=sample_ids if isinstance(sample_ids, list) else None,
            limit=int(limit) if limit else None,
            dry_run=True,
        )
        return jsonify(result.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@training_sample_bp.route("/training-samples/<int:sample_id>/eval-set", methods=["POST"])
def api_convert_training_sample_to_eval_set(sample_id):
    """Convert one manually curated sample into an evaluation-set contract."""
    from app.services.training_sample_eval_set_service import TrainingSampleEvalSetService

    data = request.get_json(silent=True) or {}
    contract = data.get("eval_contract")
    if not isinstance(contract, dict):
        return jsonify({
            "converted": False,
            "reason": "missing_curated_eval_contract",
            "message": "转入评测集前必须由人工/Agent 逐条阅读并提交 eval_contract。",
        }), 422
    try:
        result = TrainingSampleEvalSetService().convert_curated_sample(sample_id, contract=contract)
        return jsonify(result), 200 if result.get("converted") else 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@training_sample_bp.route("/training-samples/<int:sample_id>", methods=["GET"])
def api_get_training_sample(sample_id):
    """训练样本详情"""
    sample = TrainingSampleRepository.get_by_id(sample_id)
    if not sample:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify(sample.to_dict())


# ============ 更新 ============

@training_sample_bp.route("/training-samples/<int:sample_id>", methods=["PATCH"])
def api_update_training_sample(sample_id):
    """更新训练样本"""
    data = request.get_json(silent=True) or {}
    sample = TrainingSampleRepository.get_by_id(sample_id)
    if not sample:
        return jsonify({"error": "记录不存在"}), 404

    update_fields = {}
    for key in [
        "collected_at",
        "csr_name",
        "shop_platform",
        "customer_quote",
        "full_context",
        "product_title",
        "sku",
        "order_no",
        "question_type",
        "difficulty_reason",
        "csr_actual_reply",
        "correct_answer",
        "need_knowledge_base",
        "target_knowledge_base",
        "need_media",
        "risk_level",
        "auto_reply_type",
        "review_status",
        "owner",
        "notes",
    ]:
        if key in data:
            update_fields[key] = data[key]

    if "media_links" in data:
        update_fields["media_links_json"] = json.dumps(
            _json_field(data, "media_links", []) or [], ensure_ascii=False
        )

    if "collected_at" in update_fields:
        update_fields["collected_at"] = _parse_datetime(update_fields["collected_at"]) or sample.collected_at

    try:
        updated = TrainingSampleRepository.update(sample_id, **update_fields)
        # 再次提取可能新增的 base64 图片
        updated = TrainingSampleRepository.update(
            sample_id,
            customer_quote=_extract_base64_images(sample_id, updated.customer_quote, "customer_quote"),
            full_context=_extract_base64_images(sample_id, updated.full_context, "full_context"),
            csr_actual_reply=_extract_base64_images(sample_id, updated.csr_actual_reply, "csr_actual_reply"),
            correct_answer=_extract_base64_images(sample_id, updated.correct_answer, "correct_answer"),
        )
        return jsonify(updated.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============ 附件上传 ============

@training_sample_bp.route("/training-samples/<int:sample_id>/attachments", methods=["POST"])
def api_upload_training_sample_attachment(sample_id):
    """上传图片附件，可嵌入富文本中"""
    sample = TrainingSampleRepository.get_by_id(sample_id)
    if not sample:
        return jsonify({"error": "记录不存在"}), 404

    if "file" not in request.files:
        return jsonify({"error": "未找到文件字段 file"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "未选择文件"}), 400

    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in _ALLOWED_EXTENSIONS:
        return jsonify({"error": f"不支持的文件格式: {ext}"}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > _MAX_FILE_SIZE:
        return jsonify({"error": f"文件大小超过 10MB: {size}"}), 400

    mime = file.content_type or "application/octet-stream"
    if mime not in _ALLOWED_MIME_TYPES:
        return jsonify({"error": f"不支持的 MIME 类型: {mime}"}), 400

    today_dir = _ensure_upload_dir()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(today_dir, stored_name)
    file.save(file_path)

    field_name = (request.form.get("field_name") or "").strip()

    try:
        att = TrainingSampleRepository.add_attachment(
            sample_id=sample_id,
            field_name=field_name,
            original_filename=file.filename,
            stored_filename=stored_name,
            file_path=file_path,
            file_size=size,
            mime_type=mime,
        )
        return jsonify(att.to_dict()), 201
    except Exception as e:
        try:
            os.remove(file_path)
        except OSError:
            pass
        return jsonify({"error": str(e)}), 500


# ============ 附件下载/查看 ============

@training_sample_bp.route(
    "/training-samples/<int:sample_id>/attachments/<int:attachment_id>",
    methods=["GET"],
)
def api_get_training_sample_attachment(sample_id, attachment_id):
    """查看/下载单个附件"""
    att = TrainingSampleRepository.get_attachment(attachment_id)
    if not att or att.sample_id != sample_id:
        return jsonify({"error": "附件不存在"}), 404
    if not os.path.exists(att.file_path):
        return jsonify({"error": "文件已丢失"}), 404
    return send_file(
        att.file_path,
        mimetype=att.mime_type,
        as_attachment=False,
        download_name=att.original_filename,
    )


# ============ 附件删除 ============

@training_sample_bp.route(
    "/training-samples/<int:sample_id>/attachments/<int:attachment_id>",
    methods=["DELETE"],
)
def api_delete_training_sample_attachment(sample_id, attachment_id):
    """删除附件"""
    att = TrainingSampleRepository.get_attachment(attachment_id)
    if not att or att.sample_id != sample_id:
        return jsonify({"error": "附件不存在"}), 404

    try:
        if os.path.exists(att.file_path):
            os.remove(att.file_path)
    except OSError:
        pass

    TrainingSampleRepository.delete_attachment(attachment_id)
    return jsonify({"deleted": True})


# ============ 删除训练样本 ============

@training_sample_bp.route("/training-samples/<int:sample_id>", methods=["DELETE"])
def api_delete_training_sample(sample_id):
    """删除训练样本及其附件"""
    sample = TrainingSampleRepository.get_by_id(sample_id)
    if not sample:
        return jsonify({"error": "记录不存在"}), 404

    # 删除关联附件文件
    for att in sample.attachments:
        try:
            if os.path.exists(att.file_path):
                os.remove(att.file_path)
        except OSError:
            pass

    TrainingSampleRepository.delete(sample_id)
    return jsonify({"deleted": True})


# ============ 独立媒体文件上传（用于配图/视频链接） ============

_MEDIA_ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/webm",
    "video/quicktime",
}
_MEDIA_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov"}
_MEDIA_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _ensure_media_upload_dir():
    today = datetime.utcnow().strftime("%Y%m%d")
    path = os.path.join(_UPLOAD_DIR, "media", today)
    os.makedirs(path, exist_ok=True)
    return path


@training_sample_bp.route("/training-samples/media/upload", methods=["POST"])
def api_upload_training_sample_media():
    """上传独立配图/视频，返回可直接填入 media_links 的 URL"""
    if "file" not in request.files:
        return jsonify({"error": "未找到文件字段 file"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "未选择文件"}), 400

    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in _MEDIA_ALLOWED_EXTENSIONS:
        return jsonify({"error": f"不支持的文件格式: {ext}"}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > _MEDIA_MAX_FILE_SIZE:
        return jsonify({"error": f"文件大小超过 50MB: {size}"}), 400

    mime = file.content_type or "application/octet-stream"
    if mime not in _MEDIA_ALLOWED_MIME_TYPES:
        return jsonify({"error": f"不支持的 MIME 类型: {mime}"}), 400

    today_dir = _ensure_media_upload_dir()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(today_dir, stored_name)
    file.save(file_path)

    return jsonify({
        "url": f"/ask/api/kb/training-samples/media/{stored_name}",
        "filename": file.filename,
        "size": size,
        "mime_type": mime,
    }), 201


@training_sample_bp.route("/training-samples/media/<path:filename>", methods=["GET"])
def api_get_training_sample_media(filename):
    """查看/下载独立媒体文件"""
    # 安全：禁止路径穿越
    filename = os.path.basename(filename)
    if not filename:
        return jsonify({"error": "文件名无效"}), 400

    # 按日期目录遍历查找
    media_dir = os.path.join(_UPLOAD_DIR, "media")
    file_path = None
    for root, _dirs, files in os.walk(media_dir):
        if filename in files:
            file_path = os.path.join(root, filename)
            break

    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "文件不存在"}), 404

    mime, _ = None, None
    if filename.lower().endswith((".mp4", ".webm", ".mov")):
        mime_map = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
        ext = os.path.splitext(filename.lower())[1]
        mime = mime_map.get(ext)
    return send_file(file_path, mimetype=mime, as_attachment=False)
