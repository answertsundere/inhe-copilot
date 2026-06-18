/**
 * 商品卡片状态/等级/缺口/Agent 状态统一计算
 * 所有函数均为纯函数，不写死商品名/SKU/图片/统计数字
 */

export interface ProductItem {
  id: number
  product_name: string
  i_id: string
  category_l1?: string
  category_l2?: string
  category_l3?: string
  completeness_score: number
  status: 'draft' | 'pending_review' | 'published' | 'archived' | string
  qa_count?: number
  high_risk_qa_count?: number
  can_agent_use?: boolean
  updated_at?: string | null
  updated_by?: string
  specs?: Record<string, any>
  missing_fields?: string[]
  has_new_feedback?: boolean
  need_retest?: boolean
  cover_image_url?: string | null
  cover_image_source?: string | null
  media_count?: number
}

export type ProductGrade = 'S' | 'A' | 'B' | 'C'
export type ProductStatus =
  | 'published'
  | 'incomplete'
  | 'pending_review'
  | 'at_risk'
  | 'needs_retest'
  | 'new_feedback'

export interface StatusInfo {
  label: string
  type: 'success' | 'warning' | 'info' | 'danger' | 'primary'
}

export interface AgentStatusInfo {
  label: string
  type: 'success' | 'warning' | 'info' | 'danger'
  reason: string
}

export interface GapTag {
  text: string
  type: 'success' | 'warning' | 'info' | 'danger'
}

const COMPLETENESS_THRESHOLD = 60

export function getProductGrade(p: ProductItem): ProductGrade {
  const score = p.completeness_score || 0
  if (score >= 90) return 'S'
  if (score >= 75) return 'A'
  if (score >= 60) return 'B'
  return 'C'
}

export function getGradeColor(grade: ProductGrade): string {
  switch (grade) {
    case 'S':
      return '#14b8a6' // 青色/蓝绿
    case 'A':
      return '#22c55e' // 绿色
    case 'B':
      return '#3b82f6' // 蓝色
    case 'C':
      return '#f97316' // 橙色
    default:
      return '#9ca3af'
  }
}

export function getProductStatus(p: ProductItem): ProductStatus {
  if (p.has_new_feedback) return 'new_feedback'
  if (p.need_retest) return 'needs_retest'
  if (p.high_risk_qa_count) return 'at_risk'
  if (p.status === 'pending_review') return 'pending_review'
  if (p.status === 'published' && (p.completeness_score || 0) >= COMPLETENESS_THRESHOLD) return 'published'
  return 'incomplete'
}

export function getProductStatusInfo(p: ProductItem): StatusInfo {
  const status = getProductStatus(p)
  switch (status) {
    case 'published':
      return { label: '已发布', type: 'success' }
    case 'incomplete':
      return { label: '待补全', type: 'warning' }
    case 'pending_review':
      return { label: '待审核', type: 'info' }
    case 'at_risk':
      return { label: '有风险', type: 'danger' }
    case 'needs_retest':
      return { label: '需要复测', type: 'warning' }
    case 'new_feedback':
      return { label: '今日有新反馈', type: 'primary' }
    default:
      return { label: p.status || '未知', type: 'info' }
  }
}

export function getAgentStatusInfo(p: ProductItem): AgentStatusInfo {
  if (p.can_agent_use) {
    return { label: 'Agent 可用', type: 'success', reason: '已发布、完整度达标、无高风险问答' }
  }
  if (p.status === 'pending_review') {
    return { label: '审核后可用', type: 'warning', reason: '当前处于待审核状态，审核通过并发布后可使用' }
  }
  if (p.high_risk_qa_count) {
    return { label: '风险暂停调用', type: 'danger', reason: `存在 ${p.high_risk_qa_count} 条高风险问答` }
  }
  const reasons: string[] = []
  if (p.status !== 'published') reasons.push('未发布')
  if ((p.completeness_score || 0) < COMPLETENESS_THRESHOLD) reasons.push(`完整度${p.completeness_score}%`)
  if (!p.qa_count) reasons.push('无关联问答')
  return { label: 'Agent 不可用', type: 'info', reason: reasons.join('、') || '暂不可用' }
}

export function getGapTags(p: ProductItem): GapTag[] {
  const tags: GapTag[] = []
  const specs = p.specs || {}
  const missing = Array.isArray(p.missing_fields) ? p.missing_fields : []

  const fieldMap: Record<string, { label: string; check: () => boolean }> = {
    size: { label: '缺尺寸', check: () => !specs.size || specs.size === '详见商品详情页' },
    install_method: { label: '缺安装', check: () => !specs.install_method },
    material: { label: '缺材质', check: () => !specs.material || specs.material === '详见商品详情页' },
    certification_report: { label: '缺证书', check: () => !specs.certification_report },
    accessories: { label: '缺配件', check: () => !specs.accessories },
    load_capacity: { label: '缺承重', check: () => !specs.load_capacity },
  }

  Object.values(fieldMap).forEach(({ label, check }) => {
    if (check()) tags.push({ text: label, type: 'warning' })
  })

  // 若后端已计算缺失字段，优先合并
  missing.forEach((field) => {
    const text = `缺${field}`
    if (!tags.find((t) => t.text === text)) {
      tags.push({ text, type: 'warning' })
    }
  })

  if (!p.qa_count) tags.push({ text: '无问答', type: 'info' })
  if (p.high_risk_qa_count) tags.push({ text: `${p.high_risk_qa_count}有风险`, type: 'danger' })

  return tags
}

export function getCompletenessColor(score: number): string {
  if (score >= 80) return '#22c55e'
  if (score >= 60) return '#f97316'
  return '#ef4444'
}

export function formatDateTime(d: string | null | undefined): string {
  if (!d) return '-'
  try {
    return new Date(d).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return String(d)
  }
}
