import { describe, expect, it } from 'vitest'

import { toFriendlyApiError, unwrapResponse } from '@/api/client'

describe('API response helpers', () => {
  it('unwraps successful responses', () => {
    expect(unwrapResponse({ data: { id: 'course-1' }, error: null })).toEqual({
      id: 'course-1',
    })
  })

  it('rejects an error response', () => {
    expect(() =>
      unwrapResponse({
        data: null,
        error: { code: 'CONFLICT', message: 'duplicate' },
      }),
    ).toThrow('duplicate')
  })

  it('returns a safe fallback for unknown errors', () => {
    expect(toFriendlyApiError(new Error('internal details'))).toEqual({
      code: 'UNKNOWN_ERROR',
      message: '操作失败，请稍后重试',
    })
  })

  it.each([
    ['A course with this name already exists.', '资料空间名称已存在，请使用其他名称'],
    ['This file already exists in the course.', '该资料空间中已存在内容完全相同的资料'],
  ])('distinguishes conflict messages by resource', (apiMessage, expectedMessage) => {
    expect(
      toFriendlyApiError({
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            data: null,
            error: { code: 'CONFLICT', message: apiMessage },
          },
        },
      }),
    ).toEqual({
      code: 'CONFLICT',
      message: expectedMessage,
      status: 409,
    })
  })
})
