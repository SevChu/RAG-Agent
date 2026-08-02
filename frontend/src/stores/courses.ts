import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  createCourse as createCourseRequest,
  fetchCourse,
  fetchCourses,
  fetchDocuments,
  removeCourse as removeCourseRequest,
  removeDocument as removeDocumentRequest,
  removeDocuments as removeDocumentsRequest,
  reindexDocument as reindexDocumentRequest,
} from '@/api/courses'
import type { Course, CourseCreatePayload, CourseDocument } from '@/types/api'

export const useCoursesStore = defineStore('courses', () => {
  const courses = ref<Course[]>([])
  const documentsByCourse = ref<Record<string, CourseDocument[]>>({})
  const loading = ref(false)

  const courseCount = computed(() => courses.value.length)

  function documentsFor(courseId: string): CourseDocument[] {
    return documentsByCourse.value[courseId] ?? []
  }

  async function loadCourses(withDocumentCounts = true): Promise<void> {
    loading.value = true
    try {
      courses.value = await fetchCourses()
      if (withDocumentCounts) {
        await Promise.all(
          courses.value.map(async (course) => {
            try {
              documentsByCourse.value[course.id] = await fetchDocuments(course.id)
            } catch {
              documentsByCourse.value[course.id] = []
            }
          }),
        )
      }
    } finally {
      loading.value = false
    }
  }

  async function loadCourse(courseId: string): Promise<Course> {
    const cached = courses.value.find((course) => course.id === courseId)
    if (cached) {
      return cached
    }
    const course = await fetchCourse(courseId)
    courses.value = [...courses.value, course]
    return course
  }

  async function loadDocuments(courseId: string): Promise<CourseDocument[]> {
    const documents = await fetchDocuments(courseId)
    documentsByCourse.value[courseId] = documents
    return documents
  }

  async function addCourse(payload: CourseCreatePayload): Promise<Course> {
    const course = await createCourseRequest(payload)
    courses.value = [course, ...courses.value]
    documentsByCourse.value[course.id] = []
    return course
  }

  async function deleteCourse(courseId: string): Promise<void> {
    await removeCourseRequest(courseId)
    courses.value = courses.value.filter((course) => course.id !== courseId)
    delete documentsByCourse.value[courseId]
  }

  async function deleteDocument(courseId: string, documentId: string): Promise<void> {
    await removeDocumentRequest(documentId)
    documentsByCourse.value[courseId] = documentsFor(courseId).filter(
      (document) => document.id !== documentId,
    )
  }

  async function deleteDocuments(courseId: string, documentIds: string[]): Promise<void> {
    await removeDocumentsRequest(courseId, documentIds)
    const deletedIds = new Set(documentIds)
    documentsByCourse.value[courseId] = documentsFor(courseId).filter(
      (document) => !deletedIds.has(document.id),
    )
  }

  async function reindexDocument(courseId: string, documentId: string): Promise<void> {
    const updated = await reindexDocumentRequest(documentId)
    documentsByCourse.value[courseId] = documentsFor(courseId).map((document) =>
      document.id === documentId ? updated : document,
    )
  }

  return {
    courses,
    courseCount,
    documentsByCourse,
    loading,
    documentsFor,
    loadCourses,
    loadCourse,
    loadDocuments,
    addCourse,
    deleteCourse,
    deleteDocument,
    deleteDocuments,
    reindexDocument,
  }
})
