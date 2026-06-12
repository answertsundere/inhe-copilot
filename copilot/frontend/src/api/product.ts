import apiClient from './client'

export function getProducts(params: Record<string, any>) {
  return apiClient.get('/products', { params })
}

export function getProductSummary() {
  return apiClient.get('/products/summary')
}

export function getProductCategoryTree() {
  return apiClient.get('/products/category-tree')
}

export function getProductCategories() {
  return apiClient.get('/products/categories')
}

export function getProduct(id: number) {
  return apiClient.get(`/products/${id}`)
}

export function createProduct(data: Record<string, any>) {
  return apiClient.post('/products', data)
}

export function updateProduct(id: number, data: Record<string, any>) {
  return apiClient.put(`/products/${id}`, data)
}

export function getProductQA(id: number) {
  return apiClient.get(`/products/${id}/qa`)
}

export function getProductHealth(id: number) {
  return apiClient.get(`/products/${id}/health`)
}

export function getProductVersions(id: number) {
  return apiClient.get(`/products/${id}/versions`)
}

export function submitProductReview(id: number) {
  return apiClient.post(`/products/${id}/submit-review`)
}

export function publishProduct(id: number) {
  return apiClient.post(`/products/${id}/publish`)
}

export function batchUpdateProducts(ids: number[], action: string, value?: string) {
  return apiClient.post('/products/batch-update', { ids, action, value })
}
