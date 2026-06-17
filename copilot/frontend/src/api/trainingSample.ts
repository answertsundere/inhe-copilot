import apiClient from './client'

export interface TrainingSample {
  id: number
  collected_at: string
  csr_name: string
  shop_platform: string
  customer_quote: string
  full_context: string
  product_title: string
  sku: string
  order_no: string
  question_type: string
  difficulty_reason: string
  csr_actual_reply: string
  correct_answer: string
  need_knowledge_base: boolean
  target_knowledge_base: string
  need_media: boolean
  media_links: string[]
  risk_level: string
  auto_reply_type: string
  review_status: string
  owner: string
  notes: string
  created_by: string
  created_at: string
  updated_at: string
  attachments: TrainingSampleAttachment[]
}

export interface TrainingSampleAttachment {
  id: number
  sample_id: number
  field_name: string
  original_filename: string
  stored_filename: string
  file_size: number
  mime_type: string
  created_at: string
}

export interface CreateTrainingSamplePayload {
  collected_at?: string
  csr_name?: string
  shop_platform?: string
  customer_quote: string
  full_context?: string
  product_title?: string
  sku?: string
  order_no?: string
  question_type?: string
  difficulty_reason?: string
  csr_actual_reply?: string
  correct_answer?: string
  need_knowledge_base?: boolean
  target_knowledge_base?: string
  need_media?: boolean
  media_links?: string[]
  risk_level?: string
  auto_reply_type?: string
  review_status?: string
  owner?: string
  notes?: string
}

export interface UpdateTrainingSamplePayload extends Partial<CreateTrainingSamplePayload> {}

export function createTrainingSample(data: CreateTrainingSamplePayload) {
  return apiClient.post('/training-samples', data)
}

export function getTrainingSamples(params: Record<string, any>) {
  return apiClient.get('/training-samples', { params })
}

export function getTrainingSample(id: number) {
  return apiClient.get(`/training-samples/${id}`)
}

export function updateTrainingSample(id: number, data: UpdateTrainingSamplePayload) {
  return apiClient.patch(`/training-samples/${id}`, data)
}

export function deleteTrainingSampleAttachment(sampleId: number, attachmentId: number) {
  return apiClient.delete(`/training-samples/${sampleId}/attachments/${attachmentId}`)
}

export function deleteTrainingSample(id: number) {
  return apiClient.delete(`/training-samples/${id}`)
}

export function getTrainingSampleAttachmentUrl(sampleId: number, attachmentId: number) {
  return `${apiClient.defaults.baseURL}/training-samples/${sampleId}/attachments/${attachmentId}`
}

export function uploadTrainingSampleMedia(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post('/training-samples/media/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
