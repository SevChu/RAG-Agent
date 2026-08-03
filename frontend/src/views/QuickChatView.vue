<script setup lang="ts">
import DOMPurify from 'dompurify'
import { ElOption, ElSelect } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { toFriendlyApiError } from '@/api/client'
import { streamQuickChat } from '@/api/qa'
import { useConversationsStore } from '@/stores/conversations'
import { useLLMStore } from '@/stores/llm'
import type { CourseConversationMessage } from '@/types/api'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
const route = useRoute()
const router = useRouter()
const conversationsStore = useConversationsStore()
const llmStore = useLLMStore()
const { configuration, selectedModel } = storeToRefs(llmStore)
const activeConversationId = ref('')
const message = ref('')
const streamingQuestion = ref('')
const streamingAnswer = ref('')
const streamState = ref<'idle' | 'streaming' | 'interrupted' | 'error'>('idle')
const errorMessage = ref('')
const loading = ref(false)
let abortController: AbortController | null = null

const activeConversation = computed(() =>
  activeConversationId.value
    ? conversationsStore.quickDetails[activeConversationId.value] ?? null
    : null,
)
const messages = computed<CourseConversationMessage[]>(
  () => activeConversation.value?.messages ?? [],
)
const canSubmit = computed(
  () =>
    Boolean(message.value.trim()) &&
    Boolean(selectedModel.value) &&
    Boolean(configuration.value?.configured) &&
    !loading.value,
)

onMounted(async () => {
  try {
    await Promise.all([
      llmStore.loadConfiguration(),
      conversationsStore.loadQuickConversations(),
    ])
    await restoreFromRoute()
  } catch (error) {
    errorMessage.value = toFriendlyApiError(error).message
  }
})

onBeforeUnmount(() => abortController?.abort())

watch(
  () => route.params.conversationId,
  () => restoreFromRoute(),
)

async function restoreFromRoute(): Promise<void> {
  const conversationId = String(route.params.conversationId ?? '')
  if (loading.value && conversationId === activeConversationId.value) return
  stopStreaming()
  streamingQuestion.value = ''
  streamingAnswer.value = ''
  streamState.value = 'idle'
  if (!conversationId || conversationId === 'new') {
    activeConversationId.value = ''
    return
  }
  errorMessage.value = ''
  try {
    await conversationsStore.loadQuickConversation(conversationId)
    activeConversationId.value = conversationId
  } catch (error) {
    activeConversationId.value = ''
    errorMessage.value = toFriendlyApiError(error).message
  }
}

async function submitMessage(): Promise<void> {
  if (!canSubmit.value) return
  const submitted = message.value.trim()
  loading.value = true
  errorMessage.value = ''
  streamingQuestion.value = submitted
  streamingAnswer.value = ''
  streamState.value = 'streaming'
  abortController = new AbortController()
  try {
    let conversationId = activeConversationId.value
    if (!conversationId) {
      const conversation = await conversationsStore.createQuickConversation()
      conversationId = conversation.id
      activeConversationId.value = conversation.id
      await router.replace(`/chat/${conversation.id}`)
    }
    await streamQuickChat(
      conversationId,
      { message: submitted, model: selectedModel.value },
      abortController.signal,
      {
        onDelta: (delta) => {
          streamingAnswer.value += delta
        },
        onComplete: async (result) => {
          await conversationsStore.loadQuickConversation(result.conversation_id)
          await conversationsStore.loadQuickConversations()
          message.value = ''
          streamingQuestion.value = ''
          streamingAnswer.value = ''
          streamState.value = 'idle'
        },
        onError: (error) => {
          streamState.value = 'error'
          errorMessage.value = error.message
        },
      },
    )
  } catch (error) {
    if (abortController?.signal.aborted) {
      streamState.value = 'interrupted'
    } else {
      streamState.value = 'error'
      errorMessage.value = toFriendlyApiError(error).message
    }
  } finally {
    loading.value = false
    abortController = null
  }
}

function stopStreaming(): void {
  if (abortController) {
    abortController.abort()
    streamState.value = 'interrupted'
    loading.value = false
  }
}

function render(content: string): string {
  return DOMPurify.sanitize(markdown.render(content))
}

function submitWithKeyboard(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    void submitMessage()
  }
}
</script>

<template>
  <section class="page-view conversation-page">
    <header class="page-heading">
      <div>
        <div class="eyebrow"><span /> QUICK CHAT</div>
        <h1>快速对话</h1>
        <p>适合临时问题；保留当前会话的有限上下文，但不检索课程资料，也不写入课程对话。</p>
      </div>
      <span class="context-pill temporary-pill">独立有限上下文</span>
    </header>

    <div v-if="errorMessage" class="quick-error" role="alert">{{ errorMessage }}</div>

    <div class="conversation-stage">
      <div class="chat-toolbar">
        <div>
          <strong>{{ activeConversation?.title ?? '新快速对话' }}</strong>
          <small>不使用课程知识库 · 不调用外部搜索</small>
        </div>
        <el-select v-model="selectedModel" aria-label="快速对话模型" class="model-select">
          <el-option
            v-for="model in configuration?.available_models ?? []"
            :key="model"
            :label="model"
            :value="model"
          />
        </el-select>
      </div>

      <div class="chat-thread" aria-live="polite">
        <div v-if="!messages.length && !streamingQuestion" class="conversation-hero">
          <span class="conversation-symbol" aria-hidden="true">⌁</span>
          <span class="soft-label">LIGHTWEIGHT CONVERSATION</span>
          <h2>有什么临时问题？</h2>
          <p>回答来自模型的一般能力，不会伪装成课程资料结论。</p>
        </div>

        <template v-for="item in messages" :key="item.id">
          <div v-if="item.role === 'user'" class="quick-message user-message">
            {{ item.content }}
          </div>
          <article v-else class="quick-message assistant-message">
            <div v-html="render(item.content)" />
            <footer>{{ item.model }} · {{ item.elapsed_ms ? `${(item.elapsed_ms / 1000).toFixed(2)} s` : '' }}</footer>
          </article>
        </template>

        <template v-if="streamingQuestion">
          <div class="quick-message user-message">{{ streamingQuestion }}</div>
          <article class="quick-message assistant-message live-message">
            <div v-if="streamingAnswer" v-html="render(streamingAnswer)" />
            <p v-else>正在连接模型并读取有限会话上下文…</p>
            <footer>
              {{
                streamState === 'streaming'
                  ? '正在流式生成'
                  : streamState === 'interrupted'
                    ? '已中断 · 未保存'
                    : '生成失败 · 未保存'
              }}
            </footer>
          </article>
        </template>
      </div>

      <form class="composer-shell" @submit.prevent="submitMessage">
        <textarea
          v-model="message"
          aria-label="快速对话消息"
          maxlength="4000"
          placeholder="输入一个临时问题……"
          @keydown="submitWithKeyboard"
        />
        <button v-if="loading" type="button" class="stop-send" @click="stopStreaming">■</button>
        <button v-else type="submit" :disabled="!canSubmit" aria-label="发送消息">↑</button>
      </form>
      <p class="availability-note">Ctrl / ⌘ + Enter 发送；刷新后可从“最近对话”恢复。</p>
    </div>
  </section>
</template>

<style scoped>
.conversation-page { min-height: calc(100vh - 104px); }
.conversation-stage { display: flex; min-height: 620px; padding: 24px; flex-direction: column; background: rgb(255 255 255 / 72%); border: 1px solid var(--line); border-radius: 26px; box-shadow: var(--shadow-card); }
.chat-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding-bottom: 18px; border-bottom: 1px solid var(--line-soft); }
.chat-toolbar div { display: grid; gap: 4px; }
.chat-toolbar strong { color: var(--ink-strong); }
.chat-toolbar small, .availability-note { font-size: 11px; color: var(--ink-faint); }
.model-select { width: 220px; }
.chat-thread { display: flex; padding: 26px 4px; overflow: auto; flex: 1; flex-direction: column; gap: 15px; }
.conversation-hero { display: grid; max-width: 560px; margin: auto; text-align: center; place-items: center; }
.conversation-symbol { display: grid; width: 64px; height: 64px; margin-bottom: 18px; font-size: 28px; color: #fff; background: linear-gradient(145deg, var(--primary), var(--violet)); border-radius: 22px; place-items: center; }
.conversation-hero h2 { margin: 13px 0 8px; color: var(--ink-strong); }
.conversation-hero p { margin: 0; line-height: 1.8; color: var(--ink-muted); }
.quick-message { max-width: min(760px, 88%); padding: 14px 17px; line-height: 1.75; border-radius: 17px; }
.user-message { align-self: flex-end; color: #fff; background: linear-gradient(120deg, var(--primary), #7182f3); border-bottom-right-radius: 5px; }
.assistant-message { align-self: flex-start; background: #fff; border: 1px solid var(--line); border-bottom-left-radius: 5px; box-shadow: var(--shadow-soft); }
.assistant-message :deep(p:first-child) { margin-top: 0; }
.assistant-message :deep(p:last-child) { margin-bottom: 0; }
.assistant-message footer { margin-top: 10px; font-size: 10px; color: var(--ink-faint); }
.live-message { border-color: rgb(62 155 255 / 32%); }
.composer-shell { display: flex; padding: 10px; align-items: flex-end; gap: 10px; background: #fff; border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 16px 38px rgb(71 113 168 / 10%); }
.composer-shell textarea { min-height: 58px; padding: 10px; flex: 1; resize: vertical; color: var(--ink); background: transparent; border: 0; outline: none; }
.composer-shell button { width: 42px; height: 42px; color: #fff; cursor: pointer; background: var(--primary); border: 0; border-radius: 13px; }
.composer-shell button:disabled { cursor: not-allowed; opacity: .42; }
.composer-shell .stop-send { background: var(--danger); }
.availability-note { margin: 10px 4px 0; text-align: right; }
.temporary-pill { color: #6a58c9; background: var(--violet-soft); }
.quick-error { padding: 12px 15px; margin-bottom: 18px; color: #a52f4c; background: #fff0f4; border-radius: 13px; }
@media (max-width: 650px) { .chat-toolbar { align-items: stretch; flex-direction: column; } .model-select { width: 100%; } .conversation-stage { padding: 16px; } .quick-message { max-width: 94%; } }
</style>
