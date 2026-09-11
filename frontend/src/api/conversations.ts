import { unwrapResponse } from './client'
import { http } from './http'

import type {
  ApiResponse,
  CourseConversationDetail,
  CourseConversationSummary,
  DeleteResult,
  QuickConversationDetail,
  QuickConversationSummary,
} from '@/types/api'

export async function fetchCourseConversations(): Promise<CourseConversationSummary[]> {
  const response = await http.get<ApiResponse<CourseConversationSummary[]>>('/conversations')
  return unwrapResponse(response.data)
}

export async function fetchQuickConversations(): Promise<QuickConversationSummary[]> {
  const response = await http.get<ApiResponse<QuickConversationSummary[]>>('/quick-conversations')
  return unwrapResponse(response.data)
}

export async function createQuickConversation(
  title?: string,
  agentProfileId?: string,
): Promise<QuickConversationSummary> {
  const response = await http.post<ApiResponse<QuickConversationSummary>>(
    '/quick-conversations',
    { title, agent_profile_id: agentProfileId },
  )
  return unwrapResponse(response.data)
}

export async function fetchQuickConversation(
  conversationId: string,
): Promise<QuickConversationDetail> {
  const response = await http.get<ApiResponse<QuickConversationDetail>>(
    `/quick-conversations/${conversationId}`,
  )
  return unwrapResponse(response.data)
}

export async function removeQuickConversation(conversationId: string): Promise<DeleteResult> {
  const response = await http.delete<ApiResponse<DeleteResult>>(
    `/quick-conversations/${conversationId}`,
  )
  return unwrapResponse(response.data)
}

export async function createCourseConversation(
  courseId: string,
  title?: string,
  agentProfileId?: string,
): Promise<CourseConversationSummary> {
  const response = await http.post<ApiResponse<CourseConversationSummary>>(
    `/courses/${courseId}/conversations`,
    { title, agent_profile_id: agentProfileId },
  )
  return unwrapResponse(response.data)
}

export async function fetchCourseConversation(
  courseId: string,
  conversationId: string,
): Promise<CourseConversationDetail> {
  const response = await http.get<ApiResponse<CourseConversationDetail>>(
    `/courses/${courseId}/conversations/${conversationId}`,
  )
  return unwrapResponse(response.data)
}

export async function removeCourseConversation(
  courseId: string,
  conversationId: string,
): Promise<DeleteResult> {
  const response = await http.delete<ApiResponse<DeleteResult>>(
    `/courses/${courseId}/conversations/${conversationId}`,
  )
  return unwrapResponse(response.data)
}
