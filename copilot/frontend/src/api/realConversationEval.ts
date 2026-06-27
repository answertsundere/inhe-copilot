import apiClient from './client'

export interface RealConversationRun {
  run_uid: string
  status: string
  total_cases: number
  total_turns: number
  passed_turns: number
  failed_turns: number
  requires_review_turns: number
  created_at?: string
  updated_at?: string
}

export interface RealConversationTurnTrace {
  run_uid: string
  case_uid: string
  turn_uid: string
  turn_index: number
  buyer_message: string
  reference_human_reply: string
  agent_reply: string
  query_fact_type: string
  required_fact_types: string[]
  selected_evidence: unknown[]
  rejected_evidence: unknown[]
  turn_understanding?: {
    turn_actionability?: string
    needs_agent_reply?: boolean
    needs_rag?: boolean
    needs_tool?: boolean
    should_score?: boolean
    reply_strategy?: string
    context_dependency?: string
    forbidden_reply_topics?: string[]
    reason?: string
    query_fact_type?: string
    skip_reason?: string
    context_sufficiency?: {
      is_sufficient?: boolean
      reason?: string
      required_context_fields?: string[]
      missing_context_fields?: string[]
      has_product_context?: boolean
      has_order_context?: boolean
      has_media_context?: boolean
      should_count_in_agent_accuracy?: boolean
    }
  }
  answer_trace: Record<string, unknown>
  final_audit: Record<string, unknown>
  semantic_compiler: Record<string, unknown>
  requires_human_review: boolean
  latency_ms: number
  passed: boolean
  failure_labels: string[]
  quality_bucket?: string
  quality_bucket_reason?: string
  quality_bucket_priority?: number
  secondary_buckets?: string[]
  is_auto_sendable?: boolean
  is_safe_handoff?: boolean
  is_context_gap?: boolean
  is_knowledge_gap?: boolean
  is_agent_error?: boolean
  should_count_in_quality_rate?: boolean
}

export interface RealConversationFailure {
  run_uid?: string
  case_uid?: string
  failure_type: string
  severity: string
  message: string
  turn_uid: string
  suggested_fix_area?: string
  suggested_owner?: string
  explanation?: string
}

export interface RealConversationReview {
  run_uid: string
  case_uid: string
  turn_uid: string
  decision: ReviewDecision
  reason?: string
  suggested_fix_area?: string
  reviewer?: string
  created_at?: string
}

export interface RealConversationRunSummary {
  failure_counts_by_type: Record<string, number>
  review_counts_by_decision: Record<string, number>
  avg_latency_ms: number
  requires_review_count: number
  pass_rate: number
  auto_sendable_turns?: number
  safe_handoff_turns?: number
  context_gap_turns?: number
  knowledge_gap_turns?: number
  agent_error_turns?: number
  unscored_turns?: number
  auto_sendable_rate?: number
  safe_handoff_rate?: number
  context_gap_rate?: number
  knowledge_gap_rate?: number
  agent_error_rate?: number
  quality_denominator?: number
  agent_accuracy_denominator?: number
  agent_accuracy_passed?: number
}

export type ReviewDecision =
  | 'correct'
  | 'incorrect'
  | 'needs_knowledge'
  | 'needs_rule'
  | 'needs_media'
  | 'needs_human_policy'

export interface RealConversationRepairTask {
  task_uid: string
  run_uid: string
  failure_type: string
  suggested_fix_area: string
  suggested_owner: string
  title: string
  description: string
  sample_count: number
  related_case_uids: string[]
  related_turn_uids: string[]
  status: 'open' | 'in_progress' | 'resolved' | 'ignored'
  priority: 'low' | 'medium' | 'high'
  created_by?: string
  assigned_to?: string
  resolution_note?: string
  last_verified_at?: string | null
  verification_status: 'not_verified' | 'running' | 'verified_passed' | 'retest_failed' | 'error'
  verification_run_uid?: string
  verification_summary?: {
    total_turns?: number
    passed_turns?: number
    failed_turns?: number
    pass_rate?: number
    remaining_failure_types?: string[]
    checked_turn_uids?: string[]
    started_at?: string
    finished_at?: string
    error_message?: string
  }
  verified_by?: string
  created_at?: string
  updated_at?: string
}

export interface EvalTrendItem {
  date: string
  pass_rate: number
  total_turns: number
  failed_turns: number
  agent_accuracy_turns?: number
  context_gap_turns?: number
}

export interface EvalTrendTopItem {
  name: string
  count: number
}

export interface EvalTrends {
  days: number
  source: string
  daily: EvalTrendItem[]
  failure_type_counts: Record<string, number>
  suggested_fix_area_counts: Record<string, number>
  suggested_owner_counts: Record<string, number>
  repair_task_status_counts: Record<string, number>
  top_failure_types: EvalTrendTopItem[]
  top_fix_areas: EvalTrendTopItem[]
  latest_daily_replay?: Record<string, unknown>
}

export interface KnowledgeGapTask {
  task_uid: string
  gap_type: string
  gap_category?: string
  product_title: string
  product_title_preview?: string
  item_id: string
  item_id_masked?: string
  sku_code: string
  query_fact_type: string
  failure_type: string
  suggested_fix_area: string
  suggested_owner: string
  missing_evidence_type: string
  required_evidence_type?: string
  target_system?: string
  recommended_action?: string
  missing_fields?: string[]
  current_context_summary?: Record<string, unknown>
  media_needed_type: string
  risk_level: 'low' | 'medium' | 'high'
  sample_count: number
  priority: 'low' | 'medium' | 'high'
  status:
    | 'open'
    | 'triaged'
    | 'assigned'
    | 'draft_ready'
    | 'waiting_data'
    | 'rejected'
    | 'resolved_pending_retest'
    | 'verified'
    | 'closed'
    | 'drafting'
    | 'pending_review'
    | 'approved'
    | 'published'
  summary: string
  latest_buyer_questions: string[]
  latest_agent_replies: string[]
  latest_original_cs_replies: string[]
  review_decision?: string
  reviewer?: string
  review_note?: string
  assigned_to?: string
  assigned_team?: string
  due_date?: string
  reviewed_at?: string
  triage_reason?: string
  next_action?: string
  status_history?: Array<Record<string, unknown>>
  verification_status?: string
  verification_run_uid?: string
  last_verified_at?: string
  verified_by?: string
  verification_summary?: Record<string, unknown>
  verification_history?: Array<Record<string, unknown>>
  metadata?: Record<string, unknown>
  draft_count?: number
}

export interface KnowledgeGapSample {
  task_uid: string
  run_uid: string
  case_uid: string
  turn_uid: string
  buyer_message: string
  agent_reply: string
  reference_human_reply: string
  failure_type: string
  query_fact_type: string
  trace_summary?: Record<string, unknown>
}

export interface KnowledgeGapDraft {
  draft_uid: string
  task_uid: string
  draft_type: string
  draft_content: Record<string, unknown>
  generated_by: string
  review_status: string
  reviewer?: string
  publish_target: string
  rejection_reason?: string
}

export interface KnowledgeGapSummary {
  run_uid?: string
  filtered_by_run_uid?: boolean
  total?: number
  by_gap_category?: Record<string, number>
  by_required_evidence_type?: Record<string, number>
  by_target_system?: Record<string, number>
  open_count: number
  high_risk_count: number
  media_gap_count: number
  product_fact_gap_count: number
  product_field_gap_count?: number
  aftersales_policy_gap_count?: number
  promotion_policy_gap_count?: number
  context_extraction_gap_count?: number
  draft_count: number
  pending_review_count: number
  verified_count: number
}

export interface RealConversationQualityTaskSample {
  case_uid: string
  turn_uid: string
  buyer_message_preview: string
  agent_reply_preview: string
  query_fact_type: string
  failure_labels: string[]
  latency_ms?: number
  requires_human_review?: boolean
}

export interface RealConversationQualityTaskGroup {
  task_group_uid: string
  run_uid: string
  quality_bucket: string
  primary_failure_type: string
  suggested_fix_area: string
  suggested_owner: string
  query_fact_type: string
  product_group_key?: string
  priority: 'low' | 'medium' | 'high'
  sample_count: number
  representative_samples: RealConversationQualityTaskSample[]
  recommended_action: string
  next_step: string
}

export interface RealConversationQualityTasks {
  run_uid: string
  summary: Record<string, number>
  counts_by_bucket: Record<string, number>
  counts_by_owner: Record<string, number>
  counts_by_fix_area: Record<string, number>
  task_group_count: number
  task_groups: RealConversationQualityTaskGroup[]
}

export async function fetchRealConversationRuns() {
  const res = await apiClient.get('/eval/real-conversation/runs')
  return (res.data?.items || []) as RealConversationRun[]
}

export async function fetchRealConversationRun(runUid: string) {
  const res = await apiClient.get(`/eval/real-conversation/runs/${runUid}`)
  return res.data as {
    run: RealConversationRun
    turns: RealConversationTurnTrace[]
    failures: RealConversationFailure[]
    reviews?: RealConversationReview[]
    summary?: RealConversationRunSummary
  }
}

export async function fetchRealConversationQualityTasks(runUid: string) {
  const res = await apiClient.get(`/eval/real-conversation/runs/${runUid}/quality-tasks`)
  return res.data as RealConversationQualityTasks
}

export async function generateRealConversationQualityTasks(runUid: string) {
  const res = await apiClient.post(`/eval/real-conversation/runs/${runUid}/quality-tasks/generate`)
  return res.data as {
    generated: number
    updated: number
    skipped: number
    repair_tasks?: Record<string, unknown>
    knowledge_gap_tasks?: Record<string, unknown>
  }
}

export async function submitRealConversationReview(payload: {
  run_uid: string
  case_uid: string
  turn_uid: string
  decision: ReviewDecision
  reason?: string
}) {
  const res = await apiClient.post('/eval/real-conversation/reviews', payload)
  return res.data
}

export async function fetchRepairTasks(params?: {
  status?: string
  suggested_fix_area?: string
  suggested_owner?: string
  run_uid?: string
}) {
  const res = await apiClient.get('/eval/repair-tasks', { params })
  return (res.data?.items || []) as RealConversationRepairTask[]
}

export async function generateRepairTasks(runUid?: string) {
  const res = await apiClient.post('/eval/repair-tasks/generate', { run_uid: runUid })
  return res.data as { tasks: RealConversationRepairTask[]; generated: number; updated: number }
}

export async function fetchRepairTask(taskUid: string) {
  const res = await apiClient.get(`/eval/repair-tasks/${taskUid}`)
  return res.data as {
    task: RealConversationRepairTask
    failures: RealConversationFailure[]
    traces: RealConversationTurnTrace[]
  }
}

export async function updateRepairTask(taskUid: string, payload: {
  status?: RealConversationRepairTask['status']
  priority?: RealConversationRepairTask['priority']
  assigned_to?: string
  resolution_note?: string
  verify_after_resolve?: boolean
}) {
  const res = await apiClient.patch(`/eval/repair-tasks/${taskUid}`, payload)
  return res.data as { task: RealConversationRepairTask; verification?: RealConversationRepairTask['verification_summary'] }
}

export async function verifyRepairTask(taskUid: string, payload?: { dry_run?: boolean; apply?: boolean }) {
  const res = await apiClient.post(`/eval/repair-tasks/${taskUid}/verify`, payload || {})
  return res.data as {
    ok?: boolean
    dry_run?: boolean
    task?: RealConversationRepairTask
    verification?: RealConversationRepairTask['verification_summary']
    checked_turn_uids?: string[]
  }
}

export async function fetchEvalTrends(params?: {
  days?: number
  source?: string
  suggested_fix_area?: string
  suggested_owner?: string
}) {
  const res = await apiClient.get('/eval/trends', { params })
  return res.data as EvalTrends
}

export async function fetchKnowledgeGapTasks(params?: {
  run_uid?: string
  status?: string
  gap_type?: string
  gap_category?: string
  query_fact_type?: string
  required_evidence_type?: string
  target_system?: string
  recommended_action?: string
  suggested_fix_area?: string
  suggested_owner?: string
  risk_level?: string
  product?: string
}) {
  const res = await apiClient.get('/eval/knowledge-gaps', { params })
  return res.data as { items: KnowledgeGapTask[]; summary: KnowledgeGapSummary }
}

export async function generateKnowledgeGapTasks(runUid?: string) {
  const res = await apiClient.post('/eval/knowledge-gaps/generate', { run_uid: runUid })
  return res.data as { tasks: KnowledgeGapTask[]; generated: number; updated: number }
}

export async function fetchKnowledgeGapTask(taskUid: string) {
  const res = await apiClient.get(`/eval/knowledge-gaps/${taskUid}`)
  return res.data as {
    task: KnowledgeGapTask
    samples: KnowledgeGapSample[]
    drafts: KnowledgeGapDraft[]
    review_metadata?: Record<string, unknown>
    status_history?: Array<Record<string, unknown>>
    recommended_next_action?: string
  }
}

export async function generateKnowledgeGapDraft(taskUid: string) {
  const res = await apiClient.post(`/eval/knowledge-gaps/${taskUid}/draft`)
  return res.data as { draft: KnowledgeGapDraft }
}

export async function updateKnowledgeGapTask(taskUid: string, payload: {
  status?: KnowledgeGapTask['status']
  priority?: KnowledgeGapTask['priority']
  suggested_owner?: string
  summary?: string
}) {
  const res = await apiClient.patch(`/eval/knowledge-gaps/${taskUid}`, payload)
  return res.data as { task: KnowledgeGapTask }
}

export async function triageKnowledgeGapTask(taskUid: string, payload: {
  review_decision: string
  status?: KnowledgeGapTask['status']
  assigned_team?: string
  assigned_to?: string
  priority?: KnowledgeGapTask['priority']
  due_date?: string
  review_note?: string
  triage_reason?: string
  next_action?: string
  source_run_uid?: string
}) {
  const res = await apiClient.patch(`/eval/knowledge-gaps/${taskUid}/triage`, payload)
  return res.data as { task: KnowledgeGapTask }
}

export async function updateKnowledgeGapStatus(taskUid: string, payload: {
  status: KnowledgeGapTask['status']
  priority?: KnowledgeGapTask['priority']
  assigned_team?: string
  assigned_to?: string
  due_date?: string
  review_note?: string
  next_action?: string
}) {
  const res = await apiClient.patch(`/eval/knowledge-gaps/${taskUid}/status`, payload)
  return res.data as { task: KnowledgeGapTask }
}

export async function approveKnowledgeGapTask(taskUid: string) {
  const res = await apiClient.post(`/eval/knowledge-gaps/${taskUid}/approve`)
  return res.data as { task: KnowledgeGapTask; drafts: KnowledgeGapDraft[] }
}

export async function rejectKnowledgeGapTask(taskUid: string, reason?: string) {
  const res = await apiClient.post(`/eval/knowledge-gaps/${taskUid}/reject`, { reason })
  return res.data as { task: KnowledgeGapTask; drafts: KnowledgeGapDraft[] }
}

export async function verifyKnowledgeGapTask(taskUid: string) {
  const res = await apiClient.post(`/eval/knowledge-gaps/${taskUid}/verify`)
  return res.data as { task: KnowledgeGapTask }
}

export async function previewKnowledgeGapRetest(taskUid: string) {
  const res = await apiClient.post(`/eval/knowledge-gaps/${taskUid}/retest-preview`)
  return res.data as {
    dry_run: boolean
    task_uid: string
    case_uids: string[]
    checked_turn_uids: string[]
    sample_count: number
    verification_status: string
    error?: string
  }
}

export async function retestKnowledgeGapTask(taskUid: string, payload?: { apply?: boolean; verified_by?: string }) {
  const res = await apiClient.post(`/eval/knowledge-gaps/${taskUid}/retest`, payload || { apply: true })
  return res.data as {
    ok: boolean
    task: KnowledgeGapTask
    verification: {
      verification_status?: string
      verification_run_uid?: string
      summary?: Record<string, unknown>
    } | Record<string, unknown>
  }
}
