import { unwrapResponse } from './client'
import { http } from './http'

import type {
  ApiResponse,
  CourseAnswer,
  CourseAnswerPayload,
  LLMConfiguration,
} from '@/types/api'

export async function fetchLLMConfiguration(): Promise<LLMConfiguration> {
  const response = await http.get<ApiResponse<LLMConfiguration>>('/llm/config')
  return unwrapResponse(response.data)
}

export async function askCourseQuestion(
  courseId: string,
  payload: CourseAnswerPayload,
): Promise<CourseAnswer> {
  const response = await http.post<ApiResponse<CourseAnswer>>(
    `/courses/${courseId}/answers`,
    payload,
    { timeout: 120_000 },
  )
  return unwrapResponse(response.data)
}
