import apiClient from './client'

export function getReviews(params: Record<string, any>) {
  return apiClient.get('/reviews', { params })
}

export function getReview(id: number) {
  return apiClient.get(`/reviews/${id}`)
}

export function approveReview(id: number) {
  return apiClient.post(`/reviews/${id}/approve`)
}

export function rejectReview(id: number, opinion: string) {
  return apiClient.post(`/reviews/${id}/reject`, { opinion })
}

export function getReviewStats() {
  return apiClient.get('/reviews/stats')
}
