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

export function createProductQA(id: number, data: Record<string, any>) {
  return apiClient.post(`/products/${id}/qa`, data)
}

export function linkProductQA(id: number, qaId: number) {
  return apiClient.post(`/products/${id}/qa/link`, { qa_id: qaId })
}

export function unlinkProductQA(id: number, qaId: number) {
  return apiClient.delete(`/products/${id}/qa/${qaId}`)
}

export function linkProductMedia(id: number, assetId: number) {
  return apiClient.post(`/products/${id}/media/link`, { asset_id: assetId })
}

export function unlinkProductMedia(id: number, assetId: number) {
  return apiClient.delete(`/products/${id}/media/${assetId}`)
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

export function getProductActivityRules(productId: number) {
  return apiClient.get(`/products/${productId}/activity-rules`)
}

// 注意：本阶段不提供 /products/{id}/agent-test 接口。
// 商品详情抽屉中的“资料命中预检”为纯前端模拟，不调用后端 Agent。
