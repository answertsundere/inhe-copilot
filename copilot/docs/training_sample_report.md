# 客服训练样本收集模块交付报告

## 1. 改动文件清单

### 新增文件

| 文件路径 | 说明 |
|---------|------|
| `app/models/kb_tables.py`（追加模型） | 新增 `KBTrainingSample`、`KBTrainingSampleAttachment` 表定义 |
| `app/repositories/training_sample_repository.py` | 训练样本仓库（创建 / 列表 / 详情 / 更新 / 附件） |
| `app/api/training_sample_routes.py` | 训练样本 REST API，含 base64 图片自动提取 |
| `frontend/src/components/RichEditor.vue` | 富文本编辑器组件，支持图文混排、粘贴/拖拽图片 |
| `frontend/src/api/trainingSample.ts` | 前端 API 客户端 |
| `frontend/src/views/TrainingSamplePage.vue` | 训练样本收集管理页面（卡片式） |
| `tests/test_training_sample.py` | 单元/接口测试 |

### 修改文件

| 文件路径 | 说明 |
|---------|------|
| `app/config.py` | 新增 `TRAINING_SAMPLE_UPLOAD_DIR` 配置 |
| `app/main.py` | 注册 `training_sample_bp` 蓝图 |
| `frontend/src/router/index.ts` | 新增 `/training-samples` 路由 |
| `frontend/src/components/layout/AppLayout.vue` | 左侧菜单新增「训练样本收集」入口 |
| `web/templates/real_test_panel.html` | 回复检查区新增「加入训练样本」按钮 |
| `web/templates/copilot_panel.html` | 操作区新增「加入训练样本」按钮 |

### 已删除文件（旧的知识缺口反馈模块）

- `app/repositories/kb_knowledge_gap_feedback_repository.py`
- `app/api/knowledge_gap_routes.py`
- `frontend/src/api/knowledgeGap.ts`
- `frontend/src/views/KnowledgeGapFeedbackPage.vue`
- `tests/test_knowledge_gap_feedback.py`
- `docs/knowledge_gap_feedback_report.md`

### 构建产物

- `web/static/kb-admin/assets/TrainingSamplePage-*.js/css`
- `web/static/kb-admin/assets/RichEditor` 相关产物已打包进页面 chunk

## 2. 数据库表与字段

使用现有 SQLite 知识库（`data/knowledge_base.db`），由 SQLAlchemy `create_all()` 自动建表。

### `kb_training_sample`

| 字段 | 类型 | 说明 |
|-----|------|------|
| `id` | Integer PK | 自增主键 |
| `collected_at` | DateTime | 收集日期（默认当天） |
| `csr_name` | String(64) | 客服姓名 |
| `shop_platform` | String(64) | 店铺/平台 |
| `customer_quote` | Text | 客户原话（富文本 HTML） |
| `full_context` | Text | 完整上下文（富文本 HTML） |
| `product_title` | String(255) | 商品标题 |
| `sku` | String(64) | 商品编码/SKU |
| `order_no` | String(64) | 订单号 |
| `question_type` | String(64) | 问题类型 |
| `difficulty_reason` | String(64) | 为什么难回答 |
| `csr_actual_reply` | Text | 客服实际怎么回复（富文本 HTML） |
| `correct_answer` | Text | 最终正确答案（富文本 HTML） |
| `need_knowledge_base` | Boolean | 是否需要补知识库 |
| `target_knowledge_base` | String(64) | 应补到哪里 |
| `need_media` | Boolean | 是否需要配图/视频 |
| `media_links_json` | Text | 图片/视频链接（JSON 数组） |
| `risk_level` | String(16) | 低/中/高 |
| `auto_reply_type` | String(32) | 可自动/需人工确认/禁止自动 |
| `review_status` | String(16) | 待处理/已确认/已入库/已上线 |
| `owner` | String(64) | 负责人 |
| `notes` | Text | 备注 |
| `created_by` / `created_at` / `updated_at` | 标准审计字段 |

### `kb_training_sample_attachment`

| 字段 | 类型 | 说明 |
|-----|------|------|
| `id` | Integer PK | 自增主键 |
| `sample_id` | Integer FK | 外键 |
| `field_name` | String(64) | 所属富文本字段 |
| `original_filename` | String(255) | 原始文件名 |
| `stored_filename` | String(255) | 存储文件名（UUID） |
| `file_path` | Text | 本地路径 |
| `file_size` | Integer | 文件大小 |
| `mime_type` | String(64) | MIME 类型 |
| `created_at` | DateTime | 上传时间 |

## 3. API 列表

基础路径：`/ask/api/kb`

| 方法 | 路径 | 说明 |
|-----|------|------|
| POST | `/training-samples` | 创建训练样本（自动提取 base64 图片为附件） |
| GET | `/training-samples` | 列表 + 筛选（状态 / 类型 / 风险 / 关键词 / 分页） |
| GET | `/training-samples/{id}` | 详情 |
| PATCH | `/training-samples/{id}` | 更新（自动提取新增 base64 图片） |
| POST | `/training-samples/{id}/attachments` | 上传附件 |
| GET | `/training-samples/{id}/attachments/{attachment_id}` | 查看/下载附件 |
| DELETE | `/training-samples/{id}/attachments/{attachment_id}` | 删除附件 |

## 4. 前端入口

### 独立页面（推荐从工作台跳转）

直接访问：`http://127.0.0.1:5011/ask/training-samples`

该页面为独立全屏页面，无知识库后台侧边栏，适合客服专心录入训练样本。

### 知识库后台入口

1. 打开：`/ask/kb-admin/`
2. 左侧菜单点击「训练样本收集」

### 页面功能

- 卡片式录入表单
- 四个富文本框支持图文混排（客户原话、完整上下文、客服实际回复、最终正确答案）
- 图片可直接粘贴/拖拽进编辑器
- 下方卡片列表展示已收集样本
- 点击卡片查看详情抽屉
- 点击编辑可回填表单

## 5. 图片处理机制

- 编辑器内粘贴/拖拽的图片先以 **base64** 形式嵌入 HTML。
- 提交到后端时，`training_sample_routes.py` 自动：
  1. 用正则匹配 `<img src="data:image/...;base64,...">`
  2. base64 解码并保存到 `data/training_sample_uploads/YYYYMMDD/{uuid}.{ext}`
  3. 创建 `kb_training_sample_attachment` 记录
  4. 将 HTML 中的 src 替换为 `/ask/api/kb/training-samples/{id}/attachments/{attachment_id}`
- 单张图片 ≤ 10MB，仅支持 `png/jpg/jpeg/webp/gif`。

## 6. 使用方法

### 客服端（工作台）

1. 在 `/ask/real-test` 页面顶部导航，点击「训练样本收集」即可直接跳转到独立录入页面。
2. 或在生成回复后，点击「加入训练样本」按钮，系统会自动带入当前对话信息并创建一条草稿，然后提示跳转到独立页面完善。
3. 系统自动带入：
   - 客户原话
   - 完整上下文（real-test 为聊天记录，copilot-panel 为客户当前消息）
   - 商品标题 / SKU / 订单号
   - 客服实际回复（AI 建议回复）

### 训练样本管理端

1. 进入「训练样本收集」页面。
2. 在卡片表单中填写/修改所有字段。
3. 在富文本框中直接粘贴截图，图片会自动嵌入文字中。
4. 保存后图片自动转存为附件。
5. 主管可更新审核状态、风险等级、自动回复类型、负责人等。

## 7. 测试结果

```bash
cd copilot
python -m pytest tests/test_training_sample.py tests/test_security.py -q
```

结果：

```
19 passed in X.XXs
```

前端构建：

```bash
cd copilot/frontend
npm run build
```

结果：构建成功，生成 `TrainingSamplePage-*.js/css`。

Flask 应用启动验证：

```bash
python -c "from app.main import create_app; create_app()"
# app created ok
```

## 8. 是否修改生产数据

否。本次改动：
- 不读取、不修改真实订单/商品/SKU/客户数据。
- 删除旧的知识缺口反馈模块（代码层面删除，数据库中的旧表数据仍保留在 `knowledge_base.db` 中，如需清理请手动 DROP）。
- 新增表在应用启动时由 SQLAlchemy `create_all()` 自动创建。

## 9. 已知风险

1. **附件存储在本地磁盘**：多实例部署需要共享存储或迁移到对象存储。
2. **未做图片内容安全扫描**：仅校验 MIME 类型和扩展名。
3. **富文本 base64 图片过大**：单张限制 10MB，但总上下文可能较大；建议后续限制单条样本总大小。
4. **工作台仅预填充基础字段**：复杂字段（如为什么难回答、最终正确答案）需要客服在管理端补充。
5. **权限依赖 Header**：`X-User-Name` 由调用方传入，生产环境应结合登录态校验。

## 10. 下一步建议

1. 接入钉钉/企业微信通知：主管/负责人收到待处理提醒。
2. 与 RAG 训练流程打通：status 为 `已入库` 时自动导出为训练语料。
3. 附件迁移到 OSS：支持多实例和 CDN 分发。
4. 增加批量导入/导出 Excel 功能。
5. 增加权限中间件和字段级权限（客服只能看自己提交的，主管可修改全部）。
6. 补充前端 E2E 测试：覆盖粘贴图片 → 保存 → 详情查看完整流程。
