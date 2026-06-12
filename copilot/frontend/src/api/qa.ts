import apiClient from './client'

export function getQAList(params: Record<string, any>) {
  return apiClient.get('/qa', { params })
}

export function getQASummary() {
  return apiClient.get('/qa/summary')
}

export function getQA(id: number) {
  return apiClient.get(`/qa/${id}`)
}

export function createQA(data: Record<string, any>) {
  return apiClient.post('/qa', data)
}

export function updateQA(id: number, data: Record<string, any>) {
  return apiClient.put(`/qa/${id}`, data)
}

export function deleteQA(id: number) {
  return apiClient.delete(`/qa/${id}`)
}

export function getQAHealth(id: number) {
  return apiClient.get(`/qa/${id}/health`)
}

export function getQAProduct(id: number) {
  return apiClient.get(`/qa/${id}/product`)
}

export function getQAVariants(id: number) {
  return apiClient.get(`/qa/${id}/variants`)
}

export function addVariant(qaId: number, data: { variant_text: string; source?: string }) {
  return apiClient.post(`/qa/${qaId}/variants`, data)
}

export function removeVariant(qaId: number, variantId: number) {
  return apiClient.delete(`/qa/${qaId}/variants/${variantId}`)
}

export function submitQAReview(id: number) {
  return apiClient.post(`/qa/${id}/submit-review`)
}

export function publishQA(id: number) {
  return apiClient.post(`/qa/${id}/publish`)
}

export function getQAVersions(id: number) {
  return apiClient.get(`/qa/${id}/versions`)
}

export function getQAIntents() {
  return apiClient.get('/qa/intents')
}

export function batchUpdateQA(ids: number[], action: string, value?: any) {
  return apiClient.post('/qa/batch-update', { ids, action, value })
}

// Navigation trees
export function getQAProductTree() {
  return apiClient.get('/qa/navigation/product-tree')
}

export function getQAScenarioTree() {
  return apiClient.get('/qa/navigation/scenario-tree')
}

export function getQARiskTree() {
  return apiClient.get('/qa/navigation/risk-tree')
}

// SOP linking
export function getQASOP(id: number) {
  return apiClient.get(`/qa/${id}/sop`)
}

export function linkQASOP(qaId: number, sopId: number) {
  return apiClient.post(`/qa/${qaId}/link-sop`, { sop_id: sopId })
}

// SOP navigation
export function getSOPRiskTree() {
  return apiClient.get('/sop/navigation/risk-tree')
}

export function getSOPList(params: Record<string, any>) {
  return apiClient.get('/sop', { params })
}

export function getSOP(id: number) {
  return apiClient.get(`/sop/${id}`)
}

export function getSOPQA(sopId: number) {
  return apiClient.get(`/sop/${sopId}/qa`)
}

// Risk control
export function getQARiskControl() {
  return apiClient.get('/qa/risk-control')
}
