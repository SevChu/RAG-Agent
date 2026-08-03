import { describe, expect, it } from 'vitest'

import {
  formatFileSize,
  processingStageLabel,
  statusLabel,
  validateUploadFile,
} from '@/utils/format'

describe('file presentation helpers', () => {
  it('formats common file sizes', () => {
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(2048)).toBe('2.0 KB')
    expect(formatFileSize(5 * 1024 * 1024)).toBe('5.0 MB')
  })

  it('uses the completed product label', () => {
    expect(statusLabel('completed')).toBe('已完成')
    expect(statusLabel('processing')).toBe('处理中')
  })

  it('presents indexing stages in Chinese', () => {
    expect(processingStageLabel('parsing')).toBe('正在解析内容')
    expect(processingStageLabel('embedding')).toBe('正在生成向量')
    expect(processingStageLabel('storing')).toBe('正在写入知识库')
  })

  it('checks extension, empty files and the 100 MB boundary', () => {
    expect(validateUploadFile(new File(['content'], 'note.md'))).toBeNull()
    expect(validateUploadFile(new File([], 'empty.txt'))).toBe('空文件无法上传')
    expect(validateUploadFile(new File(['a'], 'table.csv'))).toContain('仅支持')

    const oversized = new File(['x'], 'large.pdf')
    Object.defineProperty(oversized, 'size', { value: 100 * 1024 * 1024 + 1 })
    expect(validateUploadFile(oversized)).toBe('文件超过 100 MB')
  })
})
