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
    ElMessage.warning('请输入课程名称')
    return
  }

  creating.value = true
  try {
    const course = await store.addCourse({
      name,
      description: createForm.description.trim() || null,
    })
    createDialogVisible.value = false
    ElMessage.success(`课程“${course.name}”已创建`)
  } catch (error) {
    ElMessage.error(toFriendlyApiError(error).message)
  } finally {
    creating.value = false
  }
}

async function confirmDeleteCourse(course: Course): Promise<void> {
  const documentCount = store.documentsFor(course.id).length
  const materialText = documentCount
    ? `该课程下的 ${documentCount} 份资料也会一并永久删除。`
    : '该课程目前没有资料。'

  try {
    await ElMessageBox.confirm(
      `确定删除课程“${course.name}”吗？${materialText}此操作无法恢复。`,
      '删除课程',
      {
        type: 'warning',
        confirmButtonText: '删除课程',
        cancelButtonText: '取消',
        confirmButtonClass: 'danger-confirm-button',
      },
    )
    await store.deleteCourse(course.id)
    ElMessage.success('课程及其资料已删除')
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
        <h1>课程空间</h1>
        <p>把课程资料和学习轨迹收进独立空间，为后续智能学习建立可靠上下文。</p>
      </div>
      <button type="button" class="primary-button" @click="openCreateDialog">
        <span aria-hidden="true">＋</span>
        新建课程
      </button>
    </header>

    <div class="overview-strip" aria-label="课程空间概览">
      <div>
        <strong>{{ store.courseCount }}</strong>
        <span>门课程</span>
      </div>
      <span class="overview-divider" />
      <div>
        <strong>{{ Object.values(store.documentsByCourse).flat().length }}</strong>
        <span>份资料</span>
      </div>
      <p>每个课程空间相互隔离，同一份资料可以加入不同课程。</p>
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

    <div v-if="store.loading" class="course-grid" aria-label="正在加载课程">
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
                <el-dropdown-item command="delete">删除课程</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <h2>{{ course.name }}</h2>
        <p>{{ course.description || '尚未填写课程简介，可以先上传教材和课件。' }}</p>
        <div class="course-meta">
          <span>{{ store.documentsFor(course.id).length }} 份资料</span>
          <span>更新于 {{ formatDateTime(course.updated_at) }}</span>
        </div>
        <button type="button" class="course-enter-button" @click="openCourse(course.id)">
          进入课程
          <span aria-hidden="true">→</span>
        </button>
      </article>
    </div>

    <div v-else-if="!pageError" class="empty-state">
      <div class="empty-orbit" aria-hidden="true"><span>＋</span></div>
      <span class="soft-label">FIRST COURSE</span>
      <h2>创建你的第一门课程</h2>
      <p>课程之间相互隔离。创建后即可上传 PDF、课件、文档和学习笔记。</p>
      <button type="button" class="primary-button" @click="openCreateDialog">创建第一门课程</button>
    </div>

    <el-dialog
      v-model="createDialogVisible"
      title="新建课程"
      width="min(480px, calc(100vw - 32px))"
      :close-on-click-modal="!creating"
      :close-on-press-escape="!creating"
      class="youth-dialog"
    >
      <div class="dialog-intro">
        <span class="dialog-icon" aria-hidden="true">✦</span>
        <p>为这门课程创建独立资料空间，课程名称不能与现有课程重复。</p>
      </div>
      <el-form label-position="top" @submit.prevent="submitCourse">
        <el-form-item label="课程名称" required>
          <el-input
            v-model="createForm.name"
            maxlength="100"
            show-word-limit
            placeholder="例如：数据结构"
            autofocus
            @keyup.enter="submitCourse"
          />
        </el-form-item>
        <el-form-item label="课程简介（可选）">
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            placeholder="简单说明课程内容或学习目标"
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
          {{ creating ? '正在创建…' : '创建课程' }}
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
  background:
    linear-gradient(120deg, rgb(255 255 255 / 80%), rgb(239 248 255 / 74%)), var(--surface);
  border: 1px solid var(--line);
  border-radius: 20px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(16px);
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
  background: rgb(255 255 255 / 82%);
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(18px);
  animation: card-enter 420ms both;
  animation-delay: calc(var(--card-index, 0) * 55ms);
  transition:
    transform 180ms ease,
    border-color 180ms ease,
    box-shadow 180ms ease;
}

.course-card::before {
  position: absolute;
  top: -30px;
  right: -26px;
  width: 112px;
  height: 112px;
  pointer-events: none;
  content: '';
  background: radial-gradient(circle, rgb(77 183 255 / 15%), transparent 68%);
}

.course-card:hover {
  border-color: rgb(67 151 255 / 28%);
  box-shadow: 0 24px 50px rgb(65 110 170 / 14%);
  transform: translateY(-3px);
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
  background: linear-gradient(145deg, var(--primary-soft), var(--violet-soft));
  border: 1px solid rgb(80 150 255 / 14%);
  border-radius: 14px;
  place-items: center;
  font-weight: 800;
}

.more-button {
  min-width: 34px;
  height: 32px;
  padding: 0 8px 5px;
  font-weight: 800;
  letter-spacing: 2px;
  color: var(--ink-faint);
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 10px;
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
  font-weight: 700;
  color: var(--primary-deep);
  cursor: pointer;
  background: transparent;
  border: 0;
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
  background:
    radial-gradient(circle at 50% 30%, rgb(87 199 255 / 12%), transparent 24%),
    rgb(255 255 255 / 62%);
  border: 1px dashed rgb(83 151 234 / 30%);
  border-radius: 24px;
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
  background: linear-gradient(145deg, var(--primary-soft), var(--violet-soft));
  border-radius: 24px;
  box-shadow: 0 16px 38px rgb(64 135 255 / 16%);
  place-items: center;
  transform: rotate(-5deg);
}

.empty-orbit span {
  font-size: 28px;
  transform: rotate(5deg);
}

.dialog-intro {
  display: flex;
  padding: 13px 15px;
  align-items: center;
  gap: 11px;
  margin-bottom: 18px;
  color: var(--ink-muted);
  background: linear-gradient(120deg, var(--primary-soft), var(--violet-soft));
  border-radius: 14px;
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
  background: rgb(255 255 255 / 75%);
  border-radius: 10px;
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
