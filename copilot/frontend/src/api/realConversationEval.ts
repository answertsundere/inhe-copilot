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
  created_at?: string
  updated_at?: string
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
}) {
  const res = await apiClient.patch(`/eval/repair-tasks/${taskUid}`, payload)
  return res.data as { task: RealConversationRepairTask }
}
