import axios, { AxiosError } from 'axios'

export interface ConversationTurn {
  role: 'customer' | 'agent'
  text: string
}

export interface WorkbenchContext {
  shopId: string
  shopName: string
  jstShopId: string
  productName: string
  skuCode: string
  iId: string
  orderId: string
  trackingNo: string
}

export interface AnalyzeRequest {
  message: string
  conversation_id: string
  conversation_history: ConversationTurn[]
  product_name?: string
  sku_code?: string
  i_id?: string
  platform_trade_id?: string
  tracking_no?: string
  copilot_context?: {
    shop_id?: string
    shop_name?: string
    jst_shop_id?: string
  }
}

interface RawAnalyzeResponse {
  suggested_reply?: unknown
  draft_reply?: unknown
  can_send?: unknown
  requires_human_review?: unknown
  reply_status?: unknown
  risk_level?: unknown
  intent?: unknown
  selected_evidence?: unknown
  evidence_debug?: unknown
  final_answer_audit?: unknown
  final_semantic_fit_audit?: unknown
  reply_blocks?: unknown
}

export interface EvidenceSummary {
  uid: string
  role: string
  factType: string
  attribute: string
  source: string
  reviewStatus: string
}

export interface CandidateObservation {
  reply: string
  returnedCanSend: boolean
  requiresHumanReview: true
  replyStatus: string
  riskLevel: string
  intent: string
  evidence: EvidenceSummary[]
  reviewReasons: string[]
}

const supervisorAssistClient = axios.create({
  baseURL: '/ask/api',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

supervisorAssistClient.interceptors.request.use((config) => {
  config.headers['X-User-Role'] = localStorage.getItem('kb_user_role') || 'operator'
  config.headers['X-User-Name'] = localStorage.getItem('kb_user_name') || 'admin'
  return config
})

function optionalValue(value: string): string | undefined {
  const normalized = value.trim()
  return normalized || undefined
}

export function buildAnalyzeRequest(
  message: string,
  conversationId: string,
  history: ConversationTurn[],
  context: WorkbenchContext,
): AnalyzeRequest {
  return {
    message: message.trim(),
    conversation_id: conversationId,
    conversation_history: history.map((turn) => ({ ...turn })),
    product_name: optionalValue(context.productName),
    sku_code: optionalValue(context.skuCode),
    i_id: optionalValue(context.iId),
    // The workbench sidebar contains the marketplace order number, not JST's
    // internal order id. Preserve that provenance so the backend selects the
    // outbound-order lookup deterministically for every shop.
    platform_trade_id: optionalValue(context.orderId),
    tracking_no: optionalValue(context.trackingNo),
    copilot_context: {
      shop_id: optionalValue(context.shopId),
      shop_name: optionalValue(context.shopName),
      jst_shop_id: optionalValue(context.jstShopId),
    },
  }
}

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function textOf(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function firstText(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = textOf(record[key])
    if (value) return value
  }
  return ''
}

function evidenceRows(data: RawAnalyzeResponse): Record<string, unknown>[] {
  if (Array.isArray(data.selected_evidence)) {
    return data.selected_evidence.map(recordOf).filter((item) => Object.keys(item).length > 0)
  }
  const debug = recordOf(data.evidence_debug)
  if (Array.isArray(debug.selected_evidence)) {
    return debug.selected_evidence.map(recordOf).filter((item) => Object.keys(item).length > 0)
  }
  const admitted = recordOf(debug.admitted_answer_context)
  if (Array.isArray(admitted.admitted_evidence)) {
    return admitted.admitted_evidence.map(recordOf).filter((item) => Object.keys(item).length > 0)
  }
  return []
}

function normalizeEvidence(row: Record<string, unknown>): EvidenceSummary {
  return {
    uid: firstText(row, ['evidence_uid', 'uid']),
    role: firstText(row, ['evidence_role', 'role']),
    factType: firstText(row, ['fact_type', 'claim_type']),
    attribute: firstText(row, ['attribute_key', 'attribute']),
    source: firstText(row, ['source', 'source_type', 'provider_name']),
    reviewStatus: firstText(row, ['review_status', 'status']),
  }
}

function issueTexts(value: unknown): string[] {
  const record = recordOf(value)
  const issues = Array.isArray(record.issues) ? record.issues : []
  return issues
    .map((issue) => typeof issue === 'string' ? issue : firstText(recordOf(issue), ['reason', 'code', 'message']))
    .filter(Boolean)
}

function textBlockReply(value: unknown): string {
  if (!Array.isArray(value)) return ''
  for (const rawBlock of value) {
    const block = recordOf(rawBlock)
    if (textOf(block.type) === 'text') {
      const content = firstText(block, ['content', 'text'])
      if (content) return content
    }
  }
  return ''
}

export function normalizeCandidate(data: RawAnalyzeResponse): CandidateObservation {
  const reply = textOf(data.suggested_reply)
    || textOf(data.draft_reply)
    || textBlockReply(data.reply_blocks)
  if (!reply) throw new Error('接口没有返回可展示的候选回复')

  const reviewReasons = [
    ...issueTexts(data.final_answer_audit),
    ...issueTexts(data.final_semantic_fit_audit),
  ]

  return {
    reply,
    returnedCanSend: data.can_send === true,
    requiresHumanReview: true,
    replyStatus: textOf(data.reply_status) || 'needs_human_review',
    riskLevel: textOf(data.risk_level),
    intent: textOf(data.intent),
    evidence: evidenceRows(data).map(normalizeEvidence),
    reviewReasons: [...new Set(reviewReasons)],
  }
}

export async function analyzeForSupervisor(request: AnalyzeRequest): Promise<CandidateObservation> {
  const response = await supervisorAssistClient.post<RawAnalyzeResponse>('/analyze', request)
  return normalizeCandidate(response.data)
}

export function readableAnalyzeError(error: unknown): string {
  if (error instanceof AxiosError) {
    if (error.code === 'ECONNABORTED') return '生成超时，请稍后重试。当前对话仍已保留。'
    if (!error.response) return '无法连接分析服务，请确认本地服务正在运行。'
    if (error.response.status === 401) return '当前登录已失效，请重新登录后重试。'
    if (error.response.status === 403) return '当前账号没有使用体验台的权限。'
    const payload = recordOf(error.response.data)
    return firstText(payload, ['error_reason', 'error', 'message']) || `请求失败（${error.response.status}）`
  }
  return error instanceof Error && error.message ? error.message : '生成失败，请重试。'
}
