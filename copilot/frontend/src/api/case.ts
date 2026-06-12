import apiClient from './client'

export function getCases(params: Record<string, any>) {
  return apiClient.get('/cases', { params })
}

export function getCase(id: number) {
  return apiClient.get(`/cases/${id}`)
}

export function createCase(data: Record<string, any>) {
  return apiClient.post('/cases', data)
}

export function updateCase(id: number, data: Record<string, any>) {
  return apiClient.put(`/cases/${id}`, data)
}
