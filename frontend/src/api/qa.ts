import { unwrapResponse } from './client'
import { http } from './http'
import { postEventStream } from './stream'

import type {
  ApiResponse,
  CourseAnswer,
  CourseAnswerPayload,
  LLMConfiguration,
  TokenUsageSummary,
} from '@/types/api'
import type { StreamHandlers } from './stream'

export async function fetchLLMConfiguration(): Promise<LLMConfiguration> {
  const response = await http.get<ApiResponse<LLMConfiguration>>('/llm/config')
  return unwrapResponse(response.data)
}

export async function fetchTokenUsage(): Promise<TokenUsageSummary> {
  const response = await http.get<ApiResponse<TokenUsageSummary>>('/llm/token-usage')
  return unwrapResponse(response.data)
}

export async function resetTokenUsage(): Promise<TokenUsageSummary> {
  const response = await http.delete<ApiResponse<TokenUsageSummary>>('/llm/token-usage')
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

export async function streamCourseQuestion(
  courseId: string,
  payload: CourseAnswerPayload,
  signal: AbortSignal,
  handlers: StreamHandlers<CourseAnswer>,
): Promise<void> {
  await postEventStream(
    `/courses/${courseId}/answers/stream`,
    payload,
    signal,
    handlers,
  )
}

export async function streamQuickChat(
  conversationId: string,
  payload: { message: string; model?: string; web_search?: boolean },
  signal: AbortSignal,
  handlers: StreamHandlers<import('@/types/api').QuickChatComplete>,
): Promise<void> {
  await postEventStream(
    `/quick-conversations/${conversationId}/messages/stream`,
    payload,
    signal,
    handlers,
  )
}
