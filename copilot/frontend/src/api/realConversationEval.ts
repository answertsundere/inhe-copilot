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
  }
  answer_trace: Record<string, unknown>
  final_audit: Record<string, unknown>
  semantic_compiler: Record<string, unknown>
  requires_human_review: boolean
  latency_ms: number
  passed: boolean
  failure_labels: string[]
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
