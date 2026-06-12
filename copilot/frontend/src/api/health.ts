import apiClient from './client'

export function getHealthReport() {
  return apiClient.get('/health/report')
}

export function getHealthIssues(params: Record<string, any>) {
  return apiClient.get('/health/issues', { params })
}
