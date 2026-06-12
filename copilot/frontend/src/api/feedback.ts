import apiClient from './client'

export function getFeedbacks(params: Record<string, any>) {
  return apiClient.get('/feedback', { params })
}

export function getFeedbackStats() {
  return apiClient.get('/feedback/stats')
}
