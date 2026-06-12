import apiClient from './client'

export function getDashboardStats() {
  return apiClient.get('/dashboard/stats')
}
