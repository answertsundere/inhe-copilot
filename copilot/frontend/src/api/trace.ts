import apiClient from './client'

export function getTraces(params: Record<string, any>) {
  return apiClient.get('/traces', { params })
}

export function getTrace(id: number) {
  return apiClient.get(`/traces/${id}`)
}

export function getTraceStats() {
  return apiClient.get('/traces/stats')
}
