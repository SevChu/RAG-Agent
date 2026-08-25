import { http } from './http'
import { unwrapResponse } from './client'

import type {
  ApiResponse,
  BulkDeleteResult,
  Course,
  CourseCreatePayload,
  CourseDocument,
  DeleteResult,
  UploadProgressHandler,
} from '@/types/api'

export async function fetchCourses(): Promise<Course[]> {
  const response = await http.get<ApiResponse<Course[]>>('/courses')
  return unwrapResponse(response.data)
}

export async function fetchCourse(courseId: string): Promise<Course> {
  const response = await http.get<ApiResponse<Course>>(`/courses/${courseId}`)
  return unwrapResponse(response.data)
}

export async function createCourse(payload: CourseCreatePayload): Promise<Course> {
  const response = await http.post<ApiResponse<Course>>('/courses', payload)
  return unwrapResponse(response.data)
}

export async function removeCourse(courseId: string): Promise<DeleteResult> {
  const response = await http.delete<ApiResponse<DeleteResult>>(`/courses/${courseId}`)
  return unwrapResponse(response.data)
}

export async function fetchDocuments(courseId: string): Promise<CourseDocument[]> {
  const response = await http.get<ApiResponse<CourseDocument[]>>(`/courses/${courseId}/documents`)
  return unwrapResponse(response.data)
}

export async function uploadDocument(
  courseId: string,
  file: File,
  onProgress?: UploadProgressHandler,
): Promise<CourseDocument> {
  const body = new FormData()
  body.append('file', file)

  const response = await http.post<ApiResponse<CourseDocument>>(
    `/courses/${courseId}/documents`,
    body,
    {
      timeout: 0,
      onUploadProgress(event) {
        if (!onProgress || !event.total) {
          return
        }
        onProgress(Math.min(99, Math.round((event.loaded / event.total) * 100)))
      },
    },
  )
  onProgress?.(100)
  return unwrapResponse(response.data)
}

export async function removeDocument(documentId: string): Promise<DeleteResult> {
  const response = await http.delete<ApiResponse<DeleteResult>>(`/documents/${documentId}`)
  return unwrapResponse(response.data)
}

export async function reindexDocument(documentId: string): Promise<CourseDocument> {
  const response = await http.post<ApiResponse<CourseDocument>>(`/documents/${documentId}/reindex`)
  return unwrapResponse(response.data)
}

export async function removeDocuments(
  courseId: string,
  documentIds: string[],
): Promise<BulkDeleteResult> {
  const response = await http.post<ApiResponse<BulkDeleteResult>>(
    `/courses/${courseId}/documents/bulk-delete`,
    { document_ids: documentIds },
  )
  return unwrapResponse(response.data)
}
