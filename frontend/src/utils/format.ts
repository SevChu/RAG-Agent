import type { DocumentStatus } from '@/types/api'

export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024
export const ACCEPTED_FILE_EXTENSIONS = ['pdf', 'docx', 'pptx', 'md', 'txt'] as const

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`
  }
  return `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`
}

export function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '—'
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function statusLabel(status: DocumentStatus): string {
  return {
    pending: '等待处理',
    processing: '处理中',
    completed: '已完成',
    failed: '处理失败',
  }[status]
}

export function statusType(status: DocumentStatus): 'info' | 'warning' | 'success' | 'danger' {
  const types: Record<DocumentStatus, 'info' | 'warning' | 'success' | 'danger'> = {
    pending: 'info',
    processing: 'warning',
    completed: 'success',
    failed: 'danger',
  }
  return types[status]
}

export function fileExtension(fileName: string): string {
  return fileName.split('.').pop()?.toLowerCase() ?? ''
}

export function validateUploadFile(file: File): string | null {
  if (file.size === 0) {
    return '空文件无法上传'
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return '文件超过 100 MB'
  }
  const extension = fileExtension(file.name)
  if (!ACCEPTED_FILE_EXTENSIONS.includes(extension as (typeof ACCEPTED_FILE_EXTENSIONS)[number])) {
    return '仅支持 PDF、DOCX、PPTX、MD 和 TXT'
  }
  return null
}
