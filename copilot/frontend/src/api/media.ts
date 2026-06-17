import apiClient from './client'

// 素材库接口实际挂载在后端 /api/media-assets。
// 由于项目其他接口走 baseURL=/ask/api/kb，而 media 不在 /api/kb 下，
// 这里用相对路径并覆盖 baseURL=/ask，避免 axios 把 baseURL 和绝对路径拼成 /ask/api/kb/ask/api/...。
const MEDIA_BASE = '/api/media-assets'
const MEDIA_CONFIG = { baseURL: '/ask' }

export interface ApplicableStyle {
  scope_type: 'all' | 'sku' | 'combo' | 'color' | 'size' | 'version' | 'custom'
  scope_values: string[]
  scope_note: string
}

export interface MediaAsset {
  id: number
  asset_id?: number
  product_id: number | null
  i_id: string
  sku_code: string
  product_name: string
  asset_type: string
  asset_title: string
  asset_url: string
  source: string
  source_raw: Record<string, any>
  match_confidence: number
  match_reason: string
  status: string
  audit_status: string
  usable_for_agent: boolean
  scene_tags: string[]
  updated_at: string | null
  last_seen_at: string | null
  refresh_status?: string
  // 通过 source_raw 兼容存储的扩展字段
  applicable_scope?: string
  risk_level?: string
  source_type?: string
}

export interface MediaStats {
  total: number
  pending_review: number
  approved: number
  rejected: number
  usable_for_agent: number
  by_type: Record<string, number>
}

export interface MediaListResult {
  total: number
  items: MediaAsset[]
}

export function getMediaStats() {
  return apiClient.get<MediaStats>(`${MEDIA_BASE}/stats`, MEDIA_CONFIG)
}

export function getMediaAssets(params: Record<string, any>) {
  return apiClient.get<MediaListResult>(MEDIA_BASE, { ...MEDIA_CONFIG, params })
}

export function approveMedia(assetId: number) {
  return apiClient.post<{ ok: boolean; asset: MediaAsset }>(`${MEDIA_BASE}/${assetId}/approve`, undefined, MEDIA_CONFIG)
}

export function rejectMedia(assetId: number) {
  return apiClient.post<{ ok: boolean; asset: MediaAsset }>(`${MEDIA_BASE}/${assetId}/reject`, undefined, MEDIA_CONFIG)
}

export function updateMedia(assetId: number, fields: Record<string, any>) {
  return apiClient.post<{ ok: boolean; asset: MediaAsset }>(`${MEDIA_BASE}/${assetId}/update`, fields, MEDIA_CONFIG)
}

export function deleteMedia(assetId: number) {
  return apiClient.delete<{ ok: boolean }>(`${MEDIA_BASE}/${assetId}`, MEDIA_CONFIG)
}

export function uploadMediaAsset(formData: FormData) {
  return apiClient.post<{ ok: boolean; asset: MediaAsset }>(
    `${MEDIA_BASE}/upload`,
    formData,
    { ...MEDIA_CONFIG, headers: { 'Content-Type': 'multipart/form-data' } },
  )
}

export function batchUpdateMediaTags(assetIds: number[], addTags: string[], removeTags: string[]) {
  return apiClient.post<{ ok: boolean; updated: number }>(
    `${MEDIA_BASE}/batch-update-tags`,
    { asset_ids: assetIds, add_tags: addTags, remove_tags: removeTags },
    MEDIA_CONFIG,
  )
}

export function importDingtalkReport(reportPath?: string) {
  return apiClient.post<{ ok: boolean; stats: any }>(
    `${MEDIA_BASE}/import-dingtalk-report`,
    reportPath ? { report: reportPath } : {},
    MEDIA_CONFIG,
  )
}

// ─── 运营端「素材用途」↔ 底层 asset_type 映射（不新增 DB 列） ───
export const MEDIA_PURPOSE_TO_ASSET_TYPE: Record<string, string> = {
  appearance_image: 'sku_image',
  size_image: 'size_image',
  install_image: 'install_image',
  install_video: 'install_video',
  packing_list_image: 'pack_guide_image',
  accessory_image: 'accessory_image',
  certificate_image: 'certificate_image',
  material_image: 'material_image',
  aftersales_image: 'aftersales_image',
  other: 'other',
}

export const ASSET_TYPE_TO_MEDIA_PURPOSE: Record<string, string> = {
  sku_image: 'appearance_image',
  size_image: 'size_image',
  install_image: 'install_image',
  install_video: 'install_video',
  pack_guide_image: 'packing_list_image',
  accessory_image: 'accessory_image',
  certificate_image: 'certificate_image',
  material_image: 'material_image',
  aftersales_image: 'aftersales_image',
  other: 'other',
}

// 旧 scene_tags → 新 answer_scenarios 兼容映射
const SCENE_TAG_TO_ANSWER_SCENARIO: Record<string, string> = {
  dimensions: 'dimensions',
  detachable: 'detachable',
  installation: 'installation',
  accessories: 'accessories',
  packing_list: 'packing_list',
  certification_report: 'certificate',
  certificate: 'certificate',
  color: 'appearance',
  appearance: 'appearance',
  material: 'material',
  age_range: 'age_range',
  cleaning: 'cleaning_care',
  usage: 'usage',
  comparison: 'comparison',
  ask_photo: 'ask_photo',
  drilling: 'drilling',
}

// 素材类型中文名映射（底层 asset_type）
export const ASSET_TYPE_LABELS: Record<string, string> = {
  install_video: '安装视频',
  install_image: '安装图',
  sku_image: 'SKU 图片',
  pack_guide_image: '打包/安装指导图',
  accessory_image: '配件图',
  size_image: '尺寸图',
  certificate_image: '证书图片',
  qa_report_image: '质检报告图片',
  package_image: '包装/配件清单图',
  detail_image: '商品详情图',
  material_image: '材质说明图',
  aftersales_image: '售后说明图',
  other: '其他',
}

// 运营端素材用途选项
export const MEDIA_PURPOSE_OPTIONS = [
  { value: 'appearance_image', label: '外观/实物图' },
  { value: 'size_image', label: '尺寸/规格图' },
  { value: 'install_image', label: '安装步骤图' },
  { value: 'install_video', label: '安装/组装视频' },
  { value: 'packing_list_image', label: '包装/配件清单图' },
  { value: 'accessory_image', label: '配件/零件图' },
  { value: 'certificate_image', label: '证书/质检图' },
  { value: 'material_image', label: '材质说明图' },
  { value: 'aftersales_image', label: '售后说明图' },
  { value: 'other', label: '其他' },
]

// 适用款式类型选项
export const APPLICABLE_STYLE_TYPE_OPTIONS = [
  { value: 'all', label: '全部款式' },
  { value: 'sku', label: '指定 SKU' },
  { value: 'combo', label: '组合/套装' },
  { value: 'color', label: '颜色' },
  { value: 'size', label: '尺寸' },
  { value: 'version', label: '版本' },
  { value: 'custom', label: '自定义' },
]

// 可回答问题选项
export const ANSWER_SCENARIO_OPTIONS = [
  { value: 'ask_photo', label: '要图片/照片' },
  { value: 'appearance', label: '外观/颜色/款式' },
  { value: 'dimensions', label: '尺寸/规格' },
  { value: 'detachable', label: '可拆卸/结构' },
  { value: 'installation', label: '安装/组装' },
  { value: 'drilling', label: '打孔/固定' },
  { value: 'packing_list', label: '包装清单' },
  { value: 'accessories', label: '配件/零件' },
  { value: 'material', label: '材质' },
  { value: 'certificate', label: '证书/质检' },
  { value: 'age_range', label: '适用年龄' },
  { value: 'cleaning_care', label: '清洁保养' },
  { value: 'usage', label: '使用方法' },
  { value: 'comparison', label: '对比/区别' },
]

// 自动发送等级选项
export const AUTO_SEND_LEVEL_OPTIONS = [
  { value: 'auto', label: '自动发送' },
  { value: 'review', label: '人工确认后发送' },
  { value: 'disabled', label: '不推荐/禁用' },
]

export const RISK_LEVEL_OPTIONS = [
  { value: 'low', label: '低风险' },
  { value: 'medium', label: '中风险' },
  { value: 'high', label: '高风险' },
  { value: 'critical', label: '极高风险' },
]

export const SOURCE_TYPE_OPTIONS = [
  { value: 'manual', label: '人工上传' },
  { value: 'dingtalk', label: '钉钉拉取' },
  { value: 'product_detail', label: '商品详情页' },
  { value: 'supplier', label: '供应商' },
  { value: 'other', label: '其他' },
]

export const STATUS_LABELS: Record<string, string> = {
  pending_review: '待审核',
  approved: '已审核可用',
  rejected: '已拒绝',
}

export const STATUS_TAG_TYPES: Record<string, string> = {
  pending_review: 'warning',
  approved: 'success',
  rejected: 'danger',
}

// 素材用途显示文本
export function getMediaPurposeLabel(asset: MediaAsset): string {
  const purpose = getMediaPurpose(asset)
  return MEDIA_PURPOSE_OPTIONS.find((o) => o.value === purpose)?.label || purpose
}

// 从 source_raw / asset_type 读取运营端素材用途
export function getMediaPurpose(asset: MediaAsset): string {
  const sr = asset.source_raw || {}
  const mp = sr.media_purpose
  if (mp && MEDIA_PURPOSE_TO_ASSET_TYPE[mp]) return mp
  return ASSET_TYPE_TO_MEDIA_PURPOSE[asset.asset_type] || asset.asset_type
}

// 读取适用款式，兼容旧 source_raw.applicable_scope
export function getApplicableStyle(asset: MediaAsset): ApplicableStyle {
  const sr = asset.source_raw || {}
  const style = sr.applicable_style
  if (style && typeof style === 'object') {
    return {
      scope_type: style.scope_type || 'all',
      scope_values: (style.scope_values || []).filter(Boolean),
      scope_note: (style.scope_note || '').trim(),
    }
  }
  const legacy = sr.applicable_scope
  if (legacy) {
    const text = String(legacy).trim()
    return { scope_type: 'custom', scope_values: [text], scope_note: text }
  }
  return { scope_type: 'all', scope_values: [], scope_note: '' }
}

// 读取可回答问题，兼容旧 scene_tags
export function getAnswerScenarios(asset: MediaAsset): string[] {
  const sr = asset.source_raw || {}
  const scenarios = sr.answer_scenarios
  if (Array.isArray(scenarios) && scenarios.length) {
    return scenarios.filter(Boolean)
  }
  const mapped: string[] = []
  for (const t of asset.scene_tags || []) {
    const m = SCENE_TAG_TO_ANSWER_SCENARIO[String(t).trim().toLowerCase()]
    if (m && !mapped.includes(m)) mapped.push(m)
  }
  return mapped
}

// 读取自动发送等级
export function getAutoSendLevel(asset: MediaAsset): string {
  const sr = asset.source_raw || {}
  const level = sr.auto_send_level
  if (level === 'auto' || level === 'review' || level === 'disabled') return level
  const purpose = getMediaPurpose(asset)
  if (['certificate_image', 'material_image', 'aftersales_image'].includes(purpose)) return 'review'
  return 'auto'
}

// 生成保存 payload（source_raw 兼容存储，不新增 DB 列）
export function buildMediaUpdatePayload(asset: MediaAsset): Record<string, any> {
  const style = getApplicableStyle(asset)
  const sourceRaw = asset.source_raw || {}
  return {
    asset_title: asset.asset_title,
    asset_type: asset.asset_type,
    status: asset.status,
    usable_for_agent: asset.usable_for_agent,
    scene_tags: asset.scene_tags || [],
    media_purpose: getMediaPurpose(asset),
    applicable_style: {
      scope_type: style.scope_type || 'all',
      scope_values: style.scope_values || [],
      scope_note: style.scope_note || '',
    },
    answer_scenarios: getAnswerScenarios(asset),
    auto_send_level: getAutoSendLevel(asset),
    source_raw: {
      ...sourceRaw,
      media_purpose: getMediaPurpose(asset),
      applicable_style: {
        scope_type: style.scope_type || 'all',
        scope_values: style.scope_values || [],
        scope_note: style.scope_note || '',
      },
      answer_scenarios: getAnswerScenarios(asset),
      auto_send_level: getAutoSendLevel(asset),
      applicable_scope: sourceRaw.applicable_scope || '',
      risk_level: sourceRaw.risk_level || 'low',
      source_type: sourceRaw.source_type || 'manual',
    },
  }
}
