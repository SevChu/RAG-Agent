import { fetchEventSource } from '@microsoft/fetch-event-source'

import type { StreamError, StreamStart } from '@/types/api'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api'

export interface StreamHandlers<TComplete> {
  onStart?: (data: StreamStart) => void | Promise<void>
  onDelta: (text: string) => void | Promise<void>
  onCitations?: (data: unknown) => void | Promise<void>
  onComplete: (data: TComplete) => void | Promise<void>
  onError: (error: StreamError) => void | Promise<void>
}

export async function postEventStream<TComplete>(
  path: string,
  payload: object,
  signal: AbortSignal,
  handlers: StreamHandlers<TComplete>,
): Promise<void> {
  await fetchEventSource(`${apiBaseUrl}${path}`, {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    signal,
    openWhenHidden: true,
    async onopen(response) {
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as {
          error?: StreamError
        } | null
        throw (
          body?.error ?? {
            code: `HTTP_${response.status}`,
            message: `流式请求失败（HTTP ${response.status}）`,
          }
        )
      }
    },
    async onmessage(message) {
      const data = JSON.parse(message.data) as unknown
      if (message.event === 'start') {
        await handlers.onStart?.(data as StreamStart)
      } else if (message.event === 'delta') {
        await handlers.onDelta((data as { text: string }).text)
      } else if (message.event === 'citations') {
        await handlers.onCitations?.(data)
      } else if (message.event === 'complete') {
        await handlers.onComplete(data as TComplete)
      } else if (message.event === 'error') {
        await handlers.onError(data as StreamError)
      }
    },
    onerror(error) {
      throw error
    },
  })
}
