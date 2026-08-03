export interface ApiError {
  code: string
  message: string
}

export interface ApiResponse<T> {
  data: T | null
  error: ApiError | null
}

export interface Course {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export type DocumentStatus = 'pending' | 'processing' | 'completed' | 'failed'
export type DocumentProcessingStage =
  | 'waiting'
  | 'preparing'
  | 'parsing'
  | 'chunking'
  | 'embedding'
  | 'storing'
  | 'completed'
  | 'failed'

export interface CourseDocument {
  id: string
  course_id: string
  original_name: string
  file_type: string
  file_size: number
  sha256: string
  status: DocumentStatus
  error_message: string | null
  progress_percent: number
  processing_stage: DocumentProcessingStage
  progress_detail: string | null
  created_at: string
  updated_at: string
}

export interface DeleteResult {
  id: string
  deleted: boolean
}

export interface BulkDeleteResult {
  deleted_ids: string[]
  deleted_count: number
}

export interface CourseCreatePayload {
  name: string
  description?: string | null
}

export type UploadProgressHandler = (percentage: number) => void

export type AnswerStyle = 'concise' | 'balanced' | 'detailed'
export type AnswerStatus = 'answered' | 'insufficient_evidence'

export interface AnswerCitation {
  source_id: number
  retrieval_rank: number
  score: number
  dense_score: number | null
  reranker_score: number | null
  content_role: string
  document_id: string
  chunk_index: number
  text: string
  file_name: string
  file_type: string
  section_path: string[]
  page_numbers: number[]
  slide_numbers: number[]
  line_start: number | null
  line_end: number | null
}

export interface AnswerRetrieval {
  retrieval_mode: 'dense_rerank'
  requested_top_k: number
  candidate_top_k: number
  candidate_count: number
  returned_count: number
  eligible_evidence_count: number
  rejected_evidence_count: number
  scope_document_count: number
  embedding_device: string | null
  reranker_device: string | null
  fallback_reason: string | null
}

export interface AnswerTokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface CourseAnswer {
  course_id: string
  question: string
  answer: string
  status: AnswerStatus
  answer_style: AnswerStyle
  model: string | null
  elapsed_ms: number
  citations: AnswerCitation[]
  retrieval: AnswerRetrieval
  usage: AnswerTokenUsage | null
}

export interface CourseAnswerPayload {
  question: string
  answer_style: AnswerStyle
  document_ids?: string[]
}

export interface LLMConfiguration {
  provider: string
  base_url: string
  model: string
  available_models: string[]
  configured: boolean
  answer_styles: AnswerStyle[]
}
