<script setup lang="ts">
import {
  ElAlert,
  ElDialog,
  ElMessage,
  ElMessageBox,
  ElProgress,
  ElSkeleton,
  ElTag,
} from 'element-plus'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { toFriendlyApiError } from '@/api/client'
import { uploadDocument } from '@/api/courses'
import { useCoursesStore } from '@/stores/courses'
import type { Course, CourseDocument } from '@/types/api'
import {
  ACCEPTED_FILE_EXTENSIONS,
  formatDateTime,
  formatFileSize,
  processingStageLabel,
  statusLabel,
  statusType,
  validateUploadFile,
} from '@/utils/format'

type UploadState = 'waiting' | 'uploading' | 'success' | 'error'

interface UploadItem {
  id: string
  file: File
  progress: number
  state: UploadState
  error: string
}

const route = useRoute()
const router = useRouter()
const store = useCoursesStore()
const courseId = computed(() => String(route.params.courseId))
const course = ref<Course | null>(null)
const documents = computed(() => store.documentsFor(courseId.value))
const loading = ref(true)
const pageError = ref('')
const uploadDialogVisible = ref(false)
const uploadQueue = ref<UploadItem[]>([])
const uploading = ref(false)
const dragActive = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedDocumentIds = ref<string[]>([])
const bulkDeleting = ref(false)
const retryingDocumentIds = ref<Set<string>>(new Set())
let statusPollTimer: number | undefined

const acceptedTypesText = ACCEPTED_FILE_EXTENSIONS.map((item) => item.toUpperCase()).join(' / ')
const allDocumentsSelected = computed(
  () => documents.value.length > 0 && selectedDocumentIds.value.length === documents.value.length,
)
const someDocumentsSelected = computed(
  () => selectedDocumentIds.value.length > 0 && !allDocumentsSelected.value,
)
const hasActiveIndexing = computed(() =>
  documents.value.some(
    (document) => document.status === 'pending' || document.status === 'processing',
  ),
)

onMounted(() => {
  void loadPage()
})

onUnmounted(() => {
  if (statusPollTimer !== undefined) {
    window.clearTimeout(statusPollTimer)
  }
})

watch(documents, (currentDocuments) => {
  const availableIds = new Set(currentDocuments.map((document) => document.id))
  selectedDocumentIds.value = selectedDocumentIds.value.filter((id) => availableIds.has(id))
})

watch(
  hasActiveIndexing,
  (active) => {
    if (active) {
      scheduleStatusPoll()
    } else if (statusPollTimer !== undefined) {
      window.clearTimeout(statusPollTimer)
      statusPollTimer = undefined
    }
  },
  { immediate: true },
)

function scheduleStatusPoll(): void {
  if (statusPollTimer !== undefined) {
    return
  }
  statusPollTimer = window.setTimeout(async () => {
    statusPollTimer = undefined
    try {
      await store.loadDocuments(courseId.value)
    } catch {
      // A manual refresh remains available; transient polling errors stay unobtrusive.
    }
    if (hasActiveIndexing.value) {
      scheduleStatusPoll()
    }
  }, 2000)
}

async function loadPage(): Promise<void> {
  loading.value = true
  pageError.value = ''
  try {
    const [loadedCourse] = await Promise.all([
      store.loadCourse(courseId.value),
      store.loadDocuments(courseId.value),
    ])
    course.value = loadedCourse
  } catch (error) {
    pageError.value = toFriendlyApiError(error).message
  } finally {
    loading.value = false
  }
}

function openUploadDialog(): void {
  uploadQueue.value = []
  uploadDialogVisible.value = true
}

function openFilePicker(): void {
  fileInput.value?.click()
}

function onFileInput(event: Event): void {
  const target = event.target as HTMLInputElement
  addFiles(target.files ? Array.from(target.files) : [])
  target.value = ''
}

function onDrop(event: DragEvent): void {
  dragActive.value = false
  addFiles(event.dataTransfer?.files ? Array.from(event.dataTransfer.files) : [])
}

function addFiles(files: File[]): void {
  const knownKeys = new Set(uploadQueue.value.map((item) => `${item.file.name}:${item.file.size}`))
  const newItems = files
    .filter((file) => !knownKeys.has(`${file.name}:${file.size}`))
    .map<UploadItem>((file) => {
      const validationError = validateUploadFile(file)
      return {
        id: `${file.name}-${file.size}-${file.lastModified}`,
        file,
        progress: 0,
        state: validationError ? 'error' : 'waiting',
        error: validationError ?? '',
      }
    })
  uploadQueue.value.push(...newItems)
}

function removeUploadItem(itemId: string): void {
  uploadQueue.value = uploadQueue.value.filter((item) => item.id !== itemId)
}

async function startUpload(): Promise<void> {
  const waitingItems = uploadQueue.value.filter((item) => item.state === 'waiting')
  if (!waitingItems.length) {
    ElMessage.warning('请选择可以上传的文件')
    return
  }

  uploading.value = true
  for (const item of waitingItems) {
    item.state = 'uploading'
    item.progress = 0
    try {
      await uploadDocument(courseId.value, item.file, (progress) => {
        item.progress = progress
      })
      item.state = 'success'
      item.progress = 100
    } catch (error) {
      item.state = 'error'
      item.error = toFriendlyApiError(error).message
    }
  }

  await store.loadDocuments(courseId.value)
  uploading.value = false

  const failedCount = uploadQueue.value.filter((item) => item.state === 'error').length
  if (failedCount) {
    ElMessage.warning(`${failedCount} 个文件上传失败，请查看具体原因`)
  } else {
    ElMessage.success('资料上传完成，正在后台加入知识库')
    uploadDialogVisible.value = false
  }
}

async function reindexDocument(document: CourseDocument): Promise<void> {
  if (retryingDocumentIds.value.has(document.id)) {
    return
  }
  retryingDocumentIds.value = new Set(retryingDocumentIds.value).add(document.id)
  try {
    await store.reindexDocument(courseId.value, document.id)
    ElMessage.success(
      document.status === 'failed' ? '已重新开始处理，请稍候' : '已开始重新索引，请稍候',
    )
  } catch (error) {
    ElMessage.error(toFriendlyApiError(error).message)
  } finally {
    const remaining = new Set(retryingDocumentIds.value)
    remaining.delete(document.id)
    retryingDocumentIds.value = remaining
  }
}

async function confirmDeleteDocument(document: CourseDocument): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除“${document.original_name}”吗？删除后无法恢复。`,
      '删除资料',
      {
        type: 'warning',
        confirmButtonText: '删除资料',
        cancelButtonText: '取消',
        confirmButtonClass: 'danger-confirm-button',
      },
    )
    await store.deleteDocument(courseId.value, document.id)
    ElMessage.success('资料已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(toFriendlyApiError(error).message)
  }
}

function toggleAllDocuments(event: Event): void {
  const target = event.target as HTMLInputElement
  selectedDocumentIds.value = target.checked ? documents.value.map((document) => document.id) : []
}

async function confirmBulkDelete(): Promise<void> {
  const selectedIds = [...selectedDocumentIds.value]
  if (!selectedIds.length) {
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedIds.length} 份资料吗？删除后无法恢复。`,
      '批量删除资料',
      {
        type: 'warning',
        confirmButtonText: `删除 ${selectedIds.length} 份资料`,
        cancelButtonText: '取消',
        confirmButtonClass: 'danger-confirm-button',
      },
    )
    bulkDeleting.value = true
    await store.deleteDocuments(courseId.value, selectedIds)
    selectedDocumentIds.value = []
    ElMessage.success(`已删除 ${selectedIds.length} 份资料`)
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(toFriendlyApiError(error).message)
  } finally {
    bulkDeleting.value = false
  }
}

function uploadStateLabel(item: UploadItem): string {
  return {
    waiting: '等待上传',
    uploading: `上传中 ${item.progress}%`,
    success: '上传成功',
    error: item.error || '上传失败',
  }[item.state]
}
</script>

<template>
  <section class="page-view">
    <button type="button" class="back-button" @click="router.push('/courses')">
      <span aria-hidden="true">←</span>
      返回资料空间
    </button>

    <el-skeleton v-if="loading" :rows="6" animated class="detail-skeleton" />

    <el-alert
      v-else-if="pageError"
      :title="pageError"
      type="error"
      :closable="false"
      show-icon
      class="page-alert"
    >
      <template #default>
        <button type="button" class="text-button" @click="loadPage">重新加载</button>
      </template>
    </el-alert>

    <template v-else-if="course">
      <header class="page-heading course-heading">
        <div>
          <div class="eyebrow"><span /> COURSE MATERIALS</div>
          <h1>{{ course.name }}</h1>
          <p>{{ course.description || '管理此空间的文档、资料和知识库内容。' }}</p>
        </div>
        <button type="button" class="primary-button" @click="openUploadDialog">
          <span aria-hidden="true">↑</span>
          上传资料
        </button>
      </header>

      <div class="material-summary">
        <div class="summary-mark" aria-hidden="true">▤</div>
        <div>
          <strong>{{ documents.length }} 份空间资料</strong>
          <span>支持 {{ acceptedTypesText }}，单个文件最大 100 MB</span>
        </div>
        <span class="course-memory-label">资料隔离空间</span>
      </div>

      <section class="material-panel" aria-labelledby="materials-heading">
        <div class="panel-heading">
          <div>
            <span class="soft-label">MATERIAL LIBRARY</span>
            <h2 id="materials-heading">资料库</h2>
          </div>
          <div class="material-actions">
            <span v-if="selectedDocumentIds.length" class="selected-count">
              已选 {{ selectedDocumentIds.length }} 项
            </span>
            <button
              type="button"
              class="batch-delete-button"
              :disabled="!selectedDocumentIds.length || bulkDeleting"
              @click="confirmBulkDelete"
            >
              {{ bulkDeleting ? '正在删除…' : '批量删除' }}
            </button>
            <button
              type="button"
              class="text-button"
              :disabled="bulkDeleting"
              @click="store.loadDocuments(courseId)"
            >
              刷新状态
            </button>
          </div>
        </div>

        <div v-if="documents.length" class="material-table-wrap">
          <table class="material-table">
            <thead>
              <tr>
                <th class="selection-cell">
                  <input
                    type="checkbox"
                    :checked="allDocumentsSelected"
                    :indeterminate="someDocumentsSelected"
                    aria-label="选择全部资料"
                    @change="toggleAllDocuments"
                  />
                </th>
                <th>资料名称</th>
                <th>类型</th>
                <th>大小</th>
                <th>状态</th>
                <th>上传时间</th>
                <th><span class="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="document in documents" :key="document.id">
                <td class="selection-cell">
                  <input
                    v-model="selectedDocumentIds"
                    type="checkbox"
                    :value="document.id"
                    :aria-label="`选择${document.original_name}`"
                    :disabled="bulkDeleting"
                  />
                </td>
                <td>
                  <div class="file-name-cell">
                    <span class="file-type-icon" aria-hidden="true">{{
                      document.file_type.slice(0, 2)
                    }}</span>
                    <div>
                      <strong>{{ document.original_name }}</strong>
                      <small v-if="document.error_message" class="index-error-message">
                        <b>失败原因：</b>{{ document.error_message }}
                      </small>
                    </div>
                  </div>
                </td>
                <td class="uppercase-cell">{{ document.file_type }}</td>
                <td>{{ formatFileSize(document.file_size) }}</td>
                <td class="status-cell">
                  <el-tag :type="statusType(document.status)" effect="light" round>
                    {{ statusLabel(document.status) }}
                  </el-tag>
                  <div
                    v-if="document.status === 'processing'"
                    class="indexing-progress"
                    :aria-label="`处理进度 ${document.progress_percent}%`"
                  >
                    <el-progress
                      :percentage="document.progress_percent"
                      :show-text="false"
                      :stroke-width="6"
                    />
                    <small>
                      <b>{{ document.progress_percent }}%</b>
                      {{
                        document.progress_detail || processingStageLabel(document.processing_stage)
                      }}
                    </small>
                  </div>
                </td>
                <td>{{ formatDateTime(document.created_at) }}</td>
                <td class="action-cell">
                  <div class="row-actions">
                    <button
                      v-if="document.status === 'failed' || document.status === 'completed'"
                      type="button"
                      class="reindex-file-button"
                      :disabled="retryingDocumentIds.has(document.id)"
                      @click="reindexDocument(document)"
                    >
                      {{
                        retryingDocumentIds.has(document.id)
                          ? '提交中…'
                          : document.status === 'failed'
                            ? '重新处理'
                            : '重新索引'
                      }}
                    </button>
                    <button
                      type="button"
                      class="delete-file-button"
                      :aria-label="`删除${document.original_name}`"
                      @click="confirmDeleteDocument(document)"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-else class="materials-empty">
          <span aria-hidden="true">↥</span>
          <h3>资料空间还是空的</h3>
          <p>上传文档、报告、课件或笔记，为智能体建立可检索知识库。</p>
          <button type="button" class="secondary-button" @click="openUploadDialog">选择资料</button>
        </div>
      </section>
    </template>

    <el-dialog
      v-model="uploadDialogVisible"
      title="上传空间资料"
      width="min(640px, calc(100vw - 28px))"
      :close-on-click-modal="!uploading"
      :close-on-press-escape="!uploading"
      :show-close="!uploading"
      class="youth-dialog upload-dialog"
    >
      <div
        class="upload-drop-zone"
        :class="{ 'drag-active': dragActive }"
        role="button"
        tabindex="0"
        @click="openFilePicker"
        @keydown.enter="openFilePicker"
        @keydown.space.prevent="openFilePicker"
        @dragenter.prevent="dragActive = true"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="onDrop"
      >
        <input
          ref="fileInput"
          class="sr-only"
          type="file"
          multiple
          accept=".pdf,.docx,.pptx,.md,.txt"
          @change="onFileInput"
        />
        <span class="upload-orbit" aria-hidden="true">↑</span>
        <strong>拖入文件，或点击选择</strong>
        <p>{{ acceptedTypesText }} · 单个文件最大 100 MB</p>
      </div>

      <div v-if="uploadQueue.length" class="upload-queue" aria-live="polite">
        <article v-for="item in uploadQueue" :key="item.id" class="upload-item">
          <div class="upload-item-heading">
            <div>
              <strong>{{ item.file.name }}</strong>
              <small>{{ formatFileSize(item.file.size) }}</small>
            </div>
            <button
              v-if="item.state === 'waiting' || item.state === 'error'"
              type="button"
              class="queue-remove-button"
              :disabled="uploading"
              :aria-label="`移除${item.file.name}`"
              @click="removeUploadItem(item.id)"
            >
              ×
            </button>
          </div>
          <el-progress
            v-if="item.state === 'uploading' || item.state === 'success'"
            :percentage="item.progress"
            :status="item.state === 'success' ? 'success' : undefined"
            :stroke-width="7"
          />
          <p :class="{ 'upload-error': item.state === 'error' }">
            {{ uploadStateLabel(item) }}
          </p>
        </article>
      </div>

      <template #footer>
        <button
          type="button"
          class="secondary-button"
          :disabled="uploading"
          @click="uploadDialogVisible = false"
        >
          关闭
        </button>
        <button
          type="button"
          class="primary-button"
          :disabled="uploading || !uploadQueue.some((item) => item.state === 'waiting')"
          @click="startUpload"
        >
          {{
            uploading
              ? '正在上传…'
              : `开始上传${uploadQueue.length ? `（${uploadQueue.length}）` : ''}`
          }}
        </button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.back-button {
  display: inline-flex;
  padding: 7px 0;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-muted);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.back-button:hover {
  color: var(--primary-deep);
}

.back-button span {
  font-size: 18px;
}

.material-summary {
  display: flex;
  padding: 17px 20px;
  align-items: center;
  gap: 13px;
  margin-bottom: 22px;
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
}

.summary-mark {
  display: grid;
  width: 40px;
  height: 40px;
  color: var(--primary-deep);
  background: var(--surface);
  border-radius: var(--radius-base);
  place-items: center;
}

.material-summary > div:nth-child(2) {
  display: grid;
  gap: 3px;
}

.material-summary strong {
  font-size: 14px;
  color: var(--ink-strong);
}

.material-summary span {
  font-size: 11px;
  color: var(--ink-muted);
}

.course-memory-label {
  padding: 6px 10px;
  margin-left: auto;
  background: var(--surface);
  border-radius: var(--radius-base);
}

.material-panel {
  overflow: hidden;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-card);
}

.panel-heading {
  display: flex;
  padding: 20px 22px 16px;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  border-bottom: 1px solid var(--line-soft);
}

.panel-heading h2 {
  margin: 5px 0 0;
  font-size: 18px;
  color: var(--ink-strong);
}

.material-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.selected-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary-deep);
}

.batch-delete-button {
  padding: 7px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--danger);
  cursor: pointer;
  background: var(--danger-soft);
  border: 1px solid var(--danger-line);
  border-radius: var(--radius-base);
}

.batch-delete-button:hover:not(:disabled) {
  background: var(--danger-soft);
  border-color: var(--danger-line);
}

.batch-delete-button:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.material-table-wrap {
  position: relative;
  overflow-x: auto;
}

.material-table {
  width: 100%;
  min-width: 960px;
  border-collapse: collapse;
}

.material-table th,
.material-table td {
  padding: 15px 18px;
  text-align: left;
  border-bottom: 1px solid var(--line-soft);
}

.material-table th {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--ink-faint);
  background: var(--surface-soft);
}

.material-table td {
  font-size: 12px;
  color: var(--ink-muted);
}

.material-table tbody tr {
  transition: background 150ms ease;
}

.material-table tbody tr:hover {
  background: var(--surface-soft);
}

.material-table tbody tr:last-child td {
  border-bottom: 0;
}

.selection-cell {
  width: 44px;
  padding-right: 4px !important;
  text-align: center !important;
}

.selection-cell input {
  width: 15px;
  height: 15px;
  accent-color: var(--primary);
  cursor: pointer;
}

.file-name-cell {
  display: flex;
  max-width: 330px;
  align-items: center;
  gap: 10px;
}

.file-type-icon {
  display: grid;
  width: 34px;
  height: 38px;
  flex: 0 0 34px;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border-radius: var(--radius-base);
  place-items: center;
}

.file-name-cell > div {
  min-width: 0;
}

.file-name-cell strong,
.file-name-cell small {
  display: block;
}

.file-name-cell strong {
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-name-cell .index-error-message {
  max-width: 360px;
  margin-top: 3px;
  line-height: 1.5;
  color: var(--danger);
  white-space: normal;
}

.index-error-message b {
  font-weight: 600;
}

.uppercase-cell {
  text-transform: uppercase;
}

.status-cell {
  min-width: 210px;
}

.indexing-progress {
  width: 190px;
  margin-top: 9px;
}

.indexing-progress small {
  display: block;
  margin-top: 5px;
  overflow: hidden;
  font-size: 10px;
  line-height: 1.4;
  color: var(--ink-faint);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.indexing-progress small b {
  margin-right: 4px;
  color: var(--primary-deep);
}

.action-cell {
  text-align: right !important;
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.reindex-file-button,
.delete-file-button {
  white-space: nowrap;
}

.reindex-file-button {
  padding: 6px 9px;
  font-size: 12px;
  color: var(--primary-deep);
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: var(--radius-base);
}

.reindex-file-button:hover {
  background: var(--primary-soft);
}

.reindex-file-button:disabled {
  cursor: wait;
  opacity: 0.55;
}

.delete-file-button {
  padding: 6px 9px;
  font-size: 12px;
  color: var(--ink-faint);
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: var(--radius-base);
}

.delete-file-button:hover {
  color: var(--danger);
  background: var(--danger-soft);
}

.materials-empty {
  display: grid;
  min-height: 300px;
  padding: 45px 20px;
  text-align: center;
  place-items: center;
  align-content: center;
}

.materials-empty > span {
  display: grid;
  width: 56px;
  height: 56px;
  margin-bottom: 12px;
  font-size: 24px;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border-radius: var(--radius-base);
  place-items: center;
}

.materials-empty h3 {
  margin: 0 0 7px;
  color: var(--ink-strong);
}

.materials-empty p {
  margin: 0 0 18px;
  color: var(--ink-muted);
}

.upload-drop-zone {
  display: grid;
  min-height: 190px;
  padding: 28px;
  cursor: pointer;
  text-align: center;
  background: var(--surface-soft);
  border: 1px dashed var(--line);
  border-radius: var(--radius-base);
  place-items: center;
  align-content: center;
  transition:
    border-color 160ms ease,
    background 160ms ease,
    transform 160ms ease;
}

.upload-drop-zone:hover,
.upload-drop-zone.drag-active {
  background: var(--primary-soft);
  border-color: var(--primary);
  transform: translateY(-1px);
}

.upload-orbit {
  display: grid;
  width: 48px;
  height: 48px;
  margin-bottom: 12px;
  font-size: 22px;
  color: var(--on-primary);
  background: var(--primary);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-soft);
  place-items: center;
}

.upload-drop-zone strong {
  font-size: 15px;
  color: var(--ink-strong);
}

.upload-drop-zone p {
  margin: 7px 0 0;
  font-size: 12px;
  color: var(--ink-muted);
}

.upload-queue {
  display: grid;
  max-height: 300px;
  gap: 9px;
  margin-top: 14px;
  overflow-y: auto;
}

.upload-item {
  padding: 12px 14px;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-base);
}

.upload-item-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.upload-item-heading > div {
  min-width: 0;
}

.upload-item strong,
.upload-item small {
  display: block;
}

.upload-item strong {
  overflow: hidden;
  font-size: 12px;
  color: var(--ink-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-item small {
  margin-top: 2px;
  font-size: 10px;
  color: var(--ink-faint);
}

.upload-item p {
  margin: 7px 0 0;
  font-size: 11px;
  color: var(--ink-faint);
}

.upload-item :deep(.el-progress) {
  margin-top: 9px;
}

.upload-error {
  color: var(--danger) !important;
}

.queue-remove-button {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  color: var(--ink-faint);
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: var(--radius-base);
}

.queue-remove-button:hover {
  color: var(--danger);
  background: var(--danger-soft);
}

.detail-skeleton {
  padding: 30px;
  background: var(--surface);
  border-radius: var(--radius-base);
}

@media (max-width: 620px) {
  .material-summary {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .course-memory-label {
    width: fit-content;
    margin-left: 53px;
  }

  .panel-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .material-actions {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}
</style>
