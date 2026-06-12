import apiClient from './client'

export function optimizeTone(answer: string, tone: string = 'professional') {
  return apiClient.post('/ai/optimize-tone', { answer, tone })
}

export function generateVariants(question: string, count: number = 10) {
  return apiClient.post('/ai/generate-variants', { question, count })
}

export function checkViolations(answer: string) {
  return apiClient.post('/ai/check-violations', { answer })
}

export function suggestKeywords(question: string, answer: string) {
  return apiClient.post('/ai/suggest-keywords', { question, answer })
}

export function generateVersions(question: string, answer: string, style: string) {
  return apiClient.post('/ai/generate-versions', { question, answer, style })
}
