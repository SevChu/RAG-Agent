import axios, { AxiosError } from 'axios'

import type { ApiResponse } from '@/types/api'

export interface FriendlyApiError {
  code: string
  message: string
  status?: number
}

export function unwrapResponse<T>(response: ApiResponse<T>): T {
  if (response.data !== null) {
    return response.data
  }

  throw {
    code: response.error?.code ?? 'UNKNOWN_ERROR',
    message: response.error?.message ?? '请求未返回有效数据',
  } satisfies FriendlyApiError
}

export function toFriendlyApiError(error: unknown): FriendlyApiError {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiResponse<unknown>>
    const apiError = axiosError.response?.data?.error

    if (apiError) {
      return {
        code: apiError.code,
        message: translateApiMessage(apiError.code, apiError.message),
        status: axiosError.response?.status,
      }
    }

    if (axiosError.code === 'ECONNABORTED') {
      return { code: 'TIMEOUT', message: '请求超时，请稍后重试' }
    }

    if (!axiosError.response) {
      return {
        code: 'NETWORK_ERROR',
        message: '无法连接到后端服务，请确认后端已启动',
      }
    }
  }

  if (isFriendlyApiError(error)) {
    return error
  }

  return { code: 'UNKNOWN_ERROR', message: '操作失败，请稍后重试' }
}

function isFriendlyApiError(error: unknown): error is FriendlyApiError {
  if (typeof error !== 'object' || error === null) {
    return false
  }
  return 'code' in error && 'message' in error
}

function translateApiMessage(code: string, fallback: string): string {
  const messages: Record<string, string> = {
    CONFLICT: '当前课程中已存在同名课程或内容完全相同的资料',
    FILE_TOO_LARGE: '文件超过 100 MB，无法上传',
    INVALID_INPUT: '文件为空、内容无效或输入信息不完整',
    NOT_FOUND: '目标内容不存在，可能已被删除',
    UNSUPPORTED_FILE_TYPE: '文件格式不受支持，或文件内容与扩展名不一致',
  }
  return messages[code] ?? fallback
}
