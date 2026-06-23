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
  failure_type: string
  severity: string
  message: string
  turn_uid: string
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
  }
}

export async function submitRealConversationReview(payload: {
  run_uid: string
  case_uid: string
  turn_uid: string
  decision: 'correct' | 'incorrect' | 'needs_review'
  reason?: string
}) {
  const res = await apiClient.post('/eval/real-conversation/reviews', payload)
  return res.data
}
