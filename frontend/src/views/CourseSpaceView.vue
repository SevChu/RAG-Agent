<script setup lang="ts">
import {
  ElAlert,
  ElDialog,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElSkeleton,
} from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { toFriendlyApiError } from '@/api/client'
import { useCoursesStore } from '@/stores/courses'
import type { Course } from '@/types/api'
import { formatDateTime } from '@/utils/format'

const store = useCoursesStore()
const router = useRouter()
const createDialogVisible = ref(false)
const creating = ref(false)
const pageError = ref('')
const createForm = reactive({
  name: '',
  description: '',
})

onMounted(() => {
  void refresh()
})

async function refresh(): Promise<void> {
  pageError.value = ''
  try {
    await store.loadCourses()
  } catch (error) {
    pageError.value = toFriendlyApiError(error).message
  }
}

function openCreateDialog(): void {
  createForm.name = ''
  createForm.description = ''
  createDialogVisible.value = true
}

async function submitCourse(): Promise<void> {
  const name = createForm.name.trim()
  if (!name) {
    ElMessage.warning('请输入资料空间名称')
    return
  }

  creating.value = true
  try {
    const course = await store.addCourse({
      name,
      description: createForm.description.trim() || null,
    })
    createDialogVisible.value = false
    ElMessage.success(`资料空间“${course.name}”已创建`)
  } catch (error) {
    ElMessage.error(toFriendlyApiError(error).message)
  } finally {
    creating.value = false
  }
}

async function confirmDeleteCourse(course: Course): Promise<void> {
  const documentCount = store.documentsFor(course.id).length
  const materialText = documentCount
    ? `该资料空间下的 ${documentCount} 份资料也会一并永久删除。`
    : '该资料空间目前没有资料。'

  try {
    await ElMessageBox.confirm(
      `确定删除资料空间“${course.name}”吗？${materialText}此操作无法恢复。`,
      '删除资料空间',
      {
        type: 'warning',
        confirmButtonText: '删除资料空间',
        cancelButtonText: '取消',
        confirmButtonClass: 'danger-confirm-button',
      },
    )
    await store.deleteCourse(course.id)
    ElMessage.success('资料空间及其资料已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(toFriendlyApiError(error).message)
  }
}

function openCourse(courseId: string): void {
  void router.push({ name: 'course-detail', params: { courseId } })
}
</script>

<template>
  <section class="page-view">
    <header class="page-heading">
      <div>
        <div class="eyebrow"><span /> COURSE HUB</div>
        <h1>资料空间</h1>
        <p>把文档、知识和对话收进独立空间，为智能体建立可靠、可追溯的上下文。</p>
      </div>
      <button type="button" class="primary-button" @click="openCreateDialog">
        <span aria-hidden="true">＋</span>
        新建资料空间
      </button>
    </header>

    <div class="overview-strip" aria-label="资料空间概览">
      <div>
        <strong>{{ store.courseCount }}</strong>
        <span>个空间</span>
      </div>
      <span class="overview-divider" />
      <div>
        <strong>{{ Object.values(store.documentsByCourse).flat().length }}</strong>
        <span>份资料</span>
      </div>
      <p>每个资料空间相互隔离，同一份资料可以加入不同空间。</p>
    </div>

    <el-alert
      v-if="pageError"
      :title="pageError"
      type="error"
      :closable="false"
      show-icon
      class="page-alert"
    >
      <template #default>
        <button type="button" class="text-button" @click="refresh">重新加载</button>
      </template>
    </el-alert>

    <div v-if="store.loading" class="course-grid" aria-label="正在加载资料空间">
      <article v-for="index in 3" :key="index" class="course-card skeleton-card">
        <el-skeleton :rows="3" animated />
      </article>
    </div>

    <div v-else-if="store.courses.length" class="course-grid">
      <article
        v-for="(course, index) in store.courses"
        :key="course.id"
        class="course-card"
        :style="{ '--card-index': index }"
      >
        <div class="course-card-top">
          <span class="course-symbol" aria-hidden="true">{{ course.name.slice(0, 1) }}</span>
          <el-dropdown trigger="click" @command="confirmDeleteCourse(course)">
            <button type="button" class="more-button" :aria-label="`${course.name}更多操作`">
              •••
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="delete">删除资料空间</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <h2>{{ course.name }}</h2>
        <p>{{ course.description || '尚未填写空间说明，可以先上传文档和资料。' }}</p>
        <div class="course-meta">
          <span>{{ store.documentsFor(course.id).length }} 份资料</span>
          <span>更新于 {{ formatDateTime(course.updated_at) }}</span>
        </div>
        <button type="button" class="course-enter-button" @click="openCourse(course.id)">
          进入空间
          <span aria-hidden="true">→</span>
        </button>
      </article>
    </div>

    <div v-else-if="!pageError" class="empty-state">
      <div class="empty-orbit" aria-hidden="true"><span>＋</span></div>
      <span class="soft-label">FIRST COURSE</span>
      <h2>创建你的第一个资料空间</h2>
      <p>资料空间之间相互隔离。创建后即可上传 PDF、课件、文档和笔记。</p>
      <button type="button" class="primary-button" @click="openCreateDialog">
        创建第一个资料空间
      </button>
    </div>

    <el-dialog
      v-model="createDialogVisible"
      title="新建资料空间"
      width="min(480px, calc(100vw - 32px))"
      :close-on-click-modal="!creating"
      :close-on-press-escape="!creating"
      class="youth-dialog"
    >
      <div class="dialog-intro">
        <span class="dialog-icon" aria-hidden="true">✦</span>
        <p>创建独立的资料空间，空间名称不能与现有资料空间重复。</p>
      </div>
      <el-form label-position="top" @submit.prevent="submitCourse">
        <el-form-item label="资料空间名称" required>
          <el-input
            v-model="createForm.name"
            maxlength="100"
            show-word-limit
            placeholder="例如：数据结构"
            autofocus
            @keyup.enter="submitCourse"
          />
        </el-form-item>
        <el-form-item label="空间说明（可选）">
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            placeholder="简单说明资料主题、用途或智能体目标"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <button
          type="button"
          class="secondary-button"
          :disabled="creating"
          @click="createDialogVisible = false"
        >
          取消
        </button>
        <button type="button" class="primary-button" :disabled="creating" @click="submitCourse">
          {{ creating ? '正在创建…' : '创建资料空间' }}
        </button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.overview-strip {
  display: flex;
  min-height: 84px;
  padding: 17px 22px;
  align-items: center;
  gap: 22px;
  margin-bottom: 26px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-soft);
}

.overview-strip > div {
  display: grid;
  min-width: 65px;
  gap: 2px;
}

.overview-strip strong {
  font-size: 25px;
  color: var(--primary-deep);
}

.overview-strip span,
.overview-strip p {
  font-size: 12px;
  color: var(--ink-muted);
}

.overview-strip p {
  margin: 0 0 0 auto;
}

.overview-divider {
  width: 1px;
  height: 36px;
  background: var(--line);
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.course-card {
  position: relative;
  min-height: 255px;
  padding: 22px;
  overflow: hidden;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-card);
  animation: card-enter 420ms both;
  animation-delay: calc(var(--card-index, 0) * 55ms);
  transition:
    transform 180ms ease,
    border-color 180ms ease,
    box-shadow 180ms ease;
}

.course-card:hover {
  border-color: var(--line-strong);
  box-shadow: var(--shadow-hover);
  transform: translateY(-2px);
}

.course-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.course-symbol {
  display: grid;
  width: 42px;
  height: 42px;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  place-items: center;
  font-weight: 600;
}

.more-button {
  min-width: 34px;
  height: 32px;
  padding: 0 8px 5px;
  font-weight: 600;
  letter-spacing: 2px;
  color: var(--ink-faint);
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: var(--radius-base);
}

.more-button:hover {
  color: var(--primary-deep);
  background: var(--primary-soft);
}

.course-card h2 {
  margin: 20px 0 9px;
  font-size: 19px;
  color: var(--ink-strong);
}

.course-card > p {
  display: -webkit-box;
  min-height: 44px;
  margin: 0;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-muted);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.course-meta {
  display: flex;
  margin-top: 18px;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: var(--ink-faint);
}

.course-enter-button {
  display: flex;
  width: 100%;
  padding: 11px 0 2px;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--primary-deep);
  cursor: pointer;
  background: transparent;
  border: 0;
  border-top: 1px solid var(--line-soft);
  margin-top: 12px;
}

.course-enter-button span {
  font-size: 18px;
  transition: transform 160ms ease;
}

.course-enter-button:hover span {
  transform: translateX(4px);
}

.skeleton-card {
  animation: none;
}

.empty-state {
  display: grid;
  min-height: 390px;
  padding: 54px 22px;
  text-align: center;
  background: var(--surface-soft);
  border: 1px dashed var(--line);
  border-radius: var(--radius-base);
  place-items: center;
  align-content: center;
}

.empty-state h2 {
  margin: 13px 0 7px;
  color: var(--ink-strong);
}

.empty-state p {
  max-width: 490px;
  margin: 0 0 24px;
  color: var(--ink-muted);
}

.empty-orbit {
  display: grid;
  width: 68px;
  height: 68px;
  margin-bottom: 15px;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-soft);
  place-items: center;
}

.empty-orbit span {
  font-size: 28px;
}

.dialog-intro {
  display: flex;
  padding: 13px 15px;
  align-items: center;
  gap: 11px;
  margin-bottom: 18px;
  color: var(--ink-muted);
  background: var(--primary-soft);
  border-radius: var(--radius-base);
}

.dialog-intro p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
}

.dialog-icon {
  display: grid;
  width: 31px;
  height: 31px;
  flex: 0 0 31px;
  color: var(--primary-deep);
  background: var(--surface);
  border-radius: var(--radius-base);
  place-items: center;
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 1020px) {
  .course-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 650px) {
  .overview-strip {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .overview-strip p {
    width: 100%;
    margin: 0;
  }

  .course-grid {
    grid-template-columns: 1fr;
  }
}
</style>
