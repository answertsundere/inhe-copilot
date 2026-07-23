import apiClient from './client'

export type ReviewDecision = {
  gold_reply_revised: string
  fact_correct: boolean
  business_action_correct: boolean
  safety_boundary_correct: boolean
  human_tone_correct: boolean
  notes: string
  version: number
}

export function getHighQualityReviewQueue(params: Record<string, string> = {}) {
  return apiClient.get('/hq-long-conversation-review', { params })
}

export function getHighQualityReviewScenario(scenarioUid: string) {
  return apiClient.get(`/hq-long-conversation-review/${encodeURIComponent(scenarioUid)}`)
}

export function saveHighQualityReview(
  scenarioUid: string,
  action: 'draft' | 'submit' | 'approve' | 'reject',
  payload: ReviewDecision,
) {
  return apiClient.post(`/hq-long-conversation-review/${encodeURIComponent(scenarioUid)}/${action}`, payload)
}

export function getHighQualityReviewProgress() {
  return apiClient.get('/hq-long-conversation-review/progress')
}
