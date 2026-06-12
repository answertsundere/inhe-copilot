import apiClient from './client'

export function getRAGEntries(params: Record<string, any>) {
  return apiClient.get('/knowledge/entries', { params })
}

export function getRAGEntry(id: number) {
  return apiClient.get(`/knowledge/entries/${id}`)
}

export function submitRAGEntryReview(id: number) {
  return apiClient.post(`/knowledge/entries/${id}/submit-review`)
}

export function reviewRAGEntry(id: number, data: { approved: boolean; reason?: string }) {
  return apiClient.post(`/knowledge/entries/${id}/review`, data)
}

export function publishRAGEntry(id: number) {
  return apiClient.post(`/knowledge/entries/${id}/publish`)
}

export function archiveRAGEntry(id: number) {
  return apiClient.delete(`/knowledge/entries/${id}`)
}

export function rollbackRAGEntry(id: number, version: number) {
  return apiClient.post(`/knowledge/entries/${id}/rollback`, { version })
}

export function getRAGEntryVersions(id: number) {
  return apiClient.get(`/knowledge/entries/${id}/versions`)
}

export function getRAGEntryAuditLog(id: number) {
  return apiClient.get(`/knowledge/entries/${id}/audit-log`)
}

export function getIndexStatus(id: number) {
  return apiClient.get(`/knowledge/entries/${id}/index-status`)
}

export function reindexEntry(id: number) {
  return apiClient.post(`/knowledge/entries/${id}/reindex`)
}

export function createRevision(id: number) {
  return apiClient.post(`/knowledge/entries/${id}/revision`)
}

export function batchSubmitReview(entryIds: number[]) {
  return apiClient.post('/knowledge/entries/batch-submit-review', { entry_ids: entryIds })
}

export function getRAGSummary() {
  return apiClient.get('/knowledge/summary')
}
