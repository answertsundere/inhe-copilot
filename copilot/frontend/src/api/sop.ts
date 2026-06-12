import apiClient from './client'

export function getSOPList(params: Record<string, any>) {
  return apiClient.get('/sop', { params })
}

export function getSOP(id: number) {
  return apiClient.get(`/sop/${id}`)
}

export function createSOP(data: Record<string, any>) {
  return apiClient.post('/sop', data)
}

export function updateSOP(id: number, data: Record<string, any>) {
  return apiClient.put(`/sop/${id}`, data)
}

export function deleteSOP(id: number) {
  return apiClient.delete(`/sop/${id}`)
}

export function submitSOPReview(id: number) {
  return apiClient.post(`/sop/${id}/submit-review`)
}

export function publishSOP(id: number) {
  return apiClient.post(`/sop/${id}/publish`)
}
