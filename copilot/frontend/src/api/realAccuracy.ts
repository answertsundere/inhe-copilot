import apiClient from './client'

export type AccuracyClaim = {
  claim_uid: string
  claim_kind: string
  query_fact_type: string
  attribute_key: string
  expected_status: string
  acceptable_values: string[]
  normalized_value: string | null
  unit: string | null
  required_terms: string[]
  supporting_evidence_uids: string[]
  required_tool: string | null
  required_action_points: string[]
  must_handoff: boolean
  forbidden_claims: string[]
  partial_answer_allowed: boolean
  review_status: string
}

export function getRealAccuracyCases() {
  return apiClient.get('/real-accuracy/cases')
}

export function saveRealAccuracyLabel(caseUid: string, payload: Record<string, unknown>) {
  return apiClient.post(`/real-accuracy/cases/${encodeURIComponent(caseUid)}/labels`, payload)
}
