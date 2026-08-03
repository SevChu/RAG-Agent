import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  createCourseConversation as createRequest,
  fetchCourseConversation,
  fetchCourseConversations,
  removeCourseConversation,
} from '@/api/conversations'
import type { CourseConversationDetail, CourseConversationSummary } from '@/types/api'

export const useConversationsStore = defineStore('conversations', () => {
  const courseConversations = ref<CourseConversationSummary[]>([])
  const details = ref<Record<string, CourseConversationDetail>>({})
  const loading = ref(false)

  async function loadCourseConversations(): Promise<CourseConversationSummary[]> {
    loading.value = true
    try {
      courseConversations.value = await fetchCourseConversations()
      return courseConversations.value
    } finally {
      loading.value = false
    }
  }

  async function createCourseConversation(courseId: string): Promise<CourseConversationSummary> {
    const conversation = await createRequest(courseId)
    courseConversations.value = [
      conversation,
      ...courseConversations.value.filter((item) => item.id !== conversation.id),
    ]
    return conversation
  }

  async function loadCourseConversation(
    courseId: string,
    conversationId: string,
  ): Promise<CourseConversationDetail> {
    const conversation = await fetchCourseConversation(courseId, conversationId)
    details.value[conversationId] = conversation
    upsertSummary(conversation)
    return conversation
  }

  async function deleteCourseConversation(
    courseId: string,
    conversationId: string,
  ): Promise<void> {
    await removeCourseConversation(courseId, conversationId)
    courseConversations.value = courseConversations.value.filter(
      (conversation) => conversation.id !== conversationId,
    )
    delete details.value[conversationId]
  }

  function upsertSummary(conversation: CourseConversationSummary): void {
    courseConversations.value = [
      conversation,
      ...courseConversations.value.filter((item) => item.id !== conversation.id),
    ].sort((left, right) => {
      const leftTime = left.last_message_at ?? left.created_at
      const rightTime = right.last_message_at ?? right.created_at
      return rightTime.localeCompare(leftTime)
    })
  }

  return {
    courseConversations,
    details,
    loading,
    loadCourseConversations,
    createCourseConversation,
    loadCourseConversation,
    deleteCourseConversation,
  }
})
