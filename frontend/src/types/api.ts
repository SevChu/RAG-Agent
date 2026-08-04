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
export type AnswerScope = 'course_and_external' | 'course_only'
export type CitationSourceType = 'course' | 'external'
export type ExternalSearchStatus =
  | 'not_requested'
  | 'succeeded'
  | 'no_qualified_results'
  | 'failed'

export interface AnswerCitation {
  source_id: number
  source_type: CitationSourceType
  retrieval_rank: number | null
  score: number | null
  dense_score: number | null
  reranker_score: number | null
  content_role: string
  document_id: string | null
  chunk_index: number | null
  text: string
  file_name: string
  file_type: string
  section_path: string[]
  page_numbers: number[]
  slide_numbers: number[]
  line_start: number | null
  line_end: number | null
  title: string | null
  publisher: string | null
  url: string | null
  accessed_at: string | null
}

export interface ExternalSearchInfo {
  triggered: boolean
  status: ExternalSearchStatus
  query: string | null
  result_count: number
  used_result_count: number
  failure_reason: string | null
  decision_reason: string | null
  fallback_applied: boolean
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
  original_question: string
  rewritten_query: string
  context_message_count: number
  rewrite_applied: boolean
  answer_scope: AnswerScope
  external_search: ExternalSearchInfo
  source_conflict_detected: boolean
}

export interface AnswerTokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface CourseAnswer {
  conversation_id: string
  user_message_id: string
  assistant_message_id: string
  course_id: string
  question: string
  answer: string
  status: AnswerStatus
  answer_style: AnswerStyle
  answer_scope: AnswerScope
  model: string | null
  elapsed_ms: number
  citations: AnswerCitation[]
  retrieval: AnswerRetrieval
  usage: AnswerTokenUsage | null
  external_search: ExternalSearchInfo
}

export interface CourseAnswerPayload {
  question: string
  answer_style: AnswerStyle
  answer_scope: AnswerScope
  document_ids?: string[]
  conversation_id?: string
  model?: string
}

export interface LLMConfiguration {
  provider: string
  base_url: string
  model: string
  available_models: string[]
  configured: boolean
  answer_styles: AnswerStyle[]
  rag_context_max_messages: number
  quick_chat_context_max_messages: number
  external_search_enabled: boolean
}

export type ConversationMessageRole = 'user' | 'assistant'
export type ConversationMessageStatus = 'completed' | 'pending' | 'failed' | 'interrupted'

export interface CourseConversationSummary {
  id: string
  course_id: string
  course_name: string
  title: string
  created_at: string
  updated_at: string
  last_message_at: string | null
}

export interface CourseConversationMessage {
  id: string
  sequence_number: number
  role: ConversationMessageRole
  status: ConversationMessageStatus
  content: string
  answer_status: AnswerStatus | null
  answer_style: AnswerStyle | null
  model: string | null
  citations: AnswerCitation[]
  retrieval: AnswerRetrieval | null
  usage: AnswerTokenUsage | null
  elapsed_ms: number | null
  created_at: string
}

export interface CourseConversationDetail extends CourseConversationSummary {
  messages: CourseConversationMessage[]
}

export interface QuickConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  last_message_at: string | null
}

export interface QuickConversationDetail extends QuickConversationSummary {
  messages: CourseConversationMessage[]
}

export interface StreamError {
  code: string
  message: string
}

export interface StreamStart {
  conversation_id: string
  model: string
  context_max_messages: number
}

export interface QuickChatComplete {
  conversation_id: string
  user_message_id: string
  assistant_message_id: string
  model: string
  usage: AnswerTokenUsage | null
  elapsed_ms: number
  context_message_count: number
}
