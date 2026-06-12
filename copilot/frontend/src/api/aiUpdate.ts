import apiClient from './client'

export function getAIUpdateTasks() {
  return apiClient.get('/ai-update/tasks')
}

export function updateAIUpdateTask(id: string, data: Record<string, any>) {
  return apiClient.put(`/ai-update/tasks/${id}`, data)
}

export function getAICenterOverview() {
  return apiClient.get('/ai-center/overview')
}

export function rebuildRagIndex() {
  return apiClient.post('/ai-center/rebuild-rag')
}

export function getBadCaseDetail(id: string) {
  return apiClient.get(`/ai-center/bad-cases/${id}`)
}

export function deleteBadCase(id: string) {
  return apiClient.delete(`/ai-center/bad-cases/${id}`)
}
