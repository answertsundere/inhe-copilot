import apiClient from './client'

const OPS_CONFIG = { baseURL: '/ask' }

export function getModelCalls(params: Record<string, any>) {
  return apiClient.get('/api/model-ops/calls', { ...OPS_CONFIG, params })
}

export function getModelSummary(params: Record<string, any> = {}) {
  return apiClient.get('/api/model-ops/summary', { ...OPS_CONFIG, params })
}

export function getToolCalls(params: Record<string, any>) {
  return apiClient.get('/api/tool-ops/calls', { ...OPS_CONFIG, params })
}

export function getToolSummary(params: Record<string, any> = {}) {
  return apiClient.get('/api/tool-ops/summary', { ...OPS_CONFIG, params })
}

export function getEvalRuns(params: Record<string, any>) {
  return apiClient.get('/api/eval/runs', { ...OPS_CONFIG, params })
}

export function getEvalRunDetail(runUid: string) {
  return apiClient.get(`/api/eval/runs/${runUid}`, OPS_CONFIG)
}

export function getEvalFailures(params: Record<string, any>) {
  return apiClient.get('/api/eval/failures', { ...OPS_CONFIG, params })
}

export function getEvalRepairTasks(params: Record<string, any>) {
  return apiClient.get('/api/eval/repair-tasks', { ...OPS_CONFIG, params })
}

export function createEvalRun(payload: Record<string, any>) {
  return apiClient.post('/api/eval/runs', payload, OPS_CONFIG)
}

export function createEvalCase(payload: Record<string, any>) {
  return apiClient.post('/api/eval/cases', payload, OPS_CONFIG)
}
