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

export interface CourseDocument {
  id: string
  course_id: string
  original_name: string
  file_type: string
  file_size: number
  sha256: string
  status: DocumentStatus
  error_message: string | null
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
