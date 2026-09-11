<script setup lang="ts">
import DOMPurify from 'dompurify'
import { ElOption, ElOptionGroup, ElSelect, ElSwitch } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ConversationAgentControl from '@/components/ConversationAgentControl.vue'
import { toFriendlyApiError } from '@/api/client'
import { streamQuickChat } from '@/api/qa'
import { useConversationsStore } from '@/stores/conversations'
import { useLLMStore } from '@/stores/llm'
import type { ConversationAgentState, CourseConversationMessage } from '@/types/api'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
const route = useRoute()
const router = useRouter()
const conversationsStore = useConversationsStore()
const llmStore = useLLMStore()
const { configuration, selectedModel, selectedModelConfigured } = storeToRefs(llmStore)
const selectedAgentId = ref(String(route.query.agent ?? ''))
const agentState = ref<ConversationAgentState>({ ready: false, profileId: null, config: null })
const restoring = ref(Boolean(route.params.conversationId && route.params.conversationId !== 'new'))
const activeConversationId = ref('')
const message = ref('')
const streamingQuestion = ref('')
const streamingAnswer = ref('')
const streamState = ref<'idle' | 'streaming' | 'interrupted' | 'error'>('idle')
const errorMessage = ref('')
const loading = ref(false)
const webSearchEnabled = ref(true)
let abortController: AbortController | null = null
let restoreSequence = 0

const activeConversation = computed(() =>
  activeConversationId.value
    ? (conversationsStore.quickDetails[activeConversationId.value] ?? null)
    : null,
)
const messages = computed<CourseConversationMessage[]>(
  () => activeConversation.value?.messages ?? [],
)
const canSubmit = computed(
  () =>
    (!route.params.conversationId ||
      route.params.conversationId === 'new' ||
      Boolean(activeConversationId.value)) &&
    Boolean(message.value.trim()) &&
    agentState.value.ready &&
    (agentState.value.profileId
      ? true
      : Boolean(selectedModel.value) && selectedModelConfigured.value) &&
    !restoring.value &&
    !loading.value,
)

onMounted(async () => {
  try {
    await Promise.all([llmStore.loadConfiguration(), conversationsStore.loadQuickConversations()])
    await restoreFromRoute()
  } catch (error) {
    errorMessage.value = toFriendlyApiError(error).message
  }
})

onBeforeUnmount(() => {
  restoreSequence++
  stopStreaming()
})

watch(
  () => [route.params.conversationId, route.query.agent],
  () => restoreFromRoute(),
)

async function restoreFromRoute(): Promise<void> {
  const conversationId = String(route.params.conversationId ?? '')
  if (loading.value && conversationId === activeConversationId.value) return
  const ticket = ++restoreSequence
  restoring.value = false
  errorMessage.value = ''
  stopStreaming()
  streamingQuestion.value = ''
  streamingAnswer.value = ''
  streamState.value = 'idle'
  if (!conversationId || conversationId === 'new') {
    activeConversationId.value = ''
    selectedAgentId.value = String(route.query.agent ?? '')
    return
  }
  errorMessage.value = ''
  selectedAgentId.value = ''
  restoring.value = true
  activeConversationId.value = conversationId
  try {
    await conversationsStore.loadQuickConversation(conversationId)
    if (ticket !== restoreSequence) return
    activeConversationId.value = conversationId
  } catch (error) {
    if (ticket !== restoreSequence) return
    activeConversationId.value = ''
    errorMessage.value = toFriendlyApiError(error).message
  } finally {
    if (ticket === restoreSequence) restoring.value = false
  }
}

async function newAgentConversation(): Promise<void> {
  await router.push('/chat/new')
}

async function submitMessage(): Promise<void> {
  if (!canSubmit.value) return
  const submitted = message.value.trim()
  const requestModel = agentState.value.profileId ? undefined : selectedModel.value
  const requestWeb = webSearchEnabled.value && (agentState.value.config?.tools.web_search ?? true)
  loading.value = true
  errorMessage.value = ''
  streamingQuestion.value = submitted
  streamingAnswer.value = ''
  streamState.value = 'streaming'
  const controller = new AbortController()
  abortController = controller
  try {
    let conversationId = activeConversationId.value
    if (!conversationId) {
      const conversation = await conversationsStore.createQuickConversation(
        selectedAgentId.value || undefined,
      )
      if (controller.signal.aborted) return
      conversationId = conversation.id
      activeConversationId.value = conversation.id
      await router.replace(`/chat/${conversation.id}`)
    }
    await streamQuickChat(
      conversationId,
      {
        message: submitted,
        model: requestModel,
        web_search: requestWeb,
      },
      controller.signal,
      {
        onDelta: (delta) => {
          if (controller.signal.aborted) return
          streamingAnswer.value += delta
        },
        onComplete: async (result) => {
          if (controller.signal.aborted) return
          await conversationsStore.loadQuickConversation(result.conversation_id)
          await conversationsStore.loadQuickConversations()
          if (controller.signal.aborted) return
          message.value = ''
          streamingQuestion.value = ''
          streamingAnswer.value = ''
          streamState.value = 'idle'
        },
        onError: (error) => {
          if (controller.signal.aborted) return
          streamState.value = 'error'
          errorMessage.value = error.message
        },
      },
    )
  } catch (error) {
    if (abortController !== controller) return
    if (controller.signal.aborted) {
      streamState.value = 'interrupted'
    } else {
      streamState.value = 'error'
      errorMessage.value = toFriendlyApiError(error).message
    }
  } finally {
    if (abortController === controller) {
      loading.value = false
      abortController = null
    }
  }
}

function stopStreaming(): void {
  if (abortController) {
    abortController.abort()
    abortController = null
    streamState.value = 'interrupted'
    loading.value = false
  }
}

function render(content: string): string {
  return DOMPurify.sanitize(markdown.render(content))
}

function quickSearchStatus(item: CourseConversationMessage): string {
  const search = item.retrieval?.external_search
  if (!search || item.retrieval?.retrieval_mode !== 'external_web') return ''
  if (search.status === 'succeeded') {
    return `已联网检索 ${search.result_count} 个合格来源`
  }
  if (search.fallback_applied) {
    return `联网未取得可用来源，已降级回答：${search.failure_reason ?? '未找到合格结果'}`
  }
  return search.decision_reason ?? '本轮未联网'
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
        <p>适合临时问题；保留当前会话的有限上下文，默认自动联网，但不检索资料空间内容。</p>
      </div>
      <span class="context-pill temporary-pill">独立有限上下文</span>
    </header>

    <ConversationAgentControl
      v-model="selectedAgentId"
      :locked="Boolean(activeConversationId)"
      :binding="activeConversation"
      :busy="loading || restoring"
      @state="agentState = $event"
      @new="newAgentConversation"
    />
    <div v-if="errorMessage" class="quick-error" role="alert">{{ errorMessage }}</div>

    <div class="conversation-stage">
      <div class="chat-toolbar">
        <div>
          <strong>{{ activeConversation?.title ?? '新快速对话' }}</strong>
          <small>不使用资料空间知识库 · 信息型问题自动联网</small>
        </div>
        <div class="toolbar-actions">
          <label class="search-toggle">
            <span>自动联网</span>
            <el-switch
              :model-value="
                webSearchEnabled &&
                Boolean(configuration?.external_search_enabled) &&
                agentState.config?.tools.web_search !== false
              "
              @update:model-value="webSearchEnabled = Boolean($event)"
              aria-label="自动联网搜索"
              :disabled="
                loading ||
                !configuration?.external_search_enabled ||
                agentState.config?.tools.web_search === false
              "
            />
          </label>
          <span v-if="agentState.profileId" class="context-pill">{{
            agentState.config?.model.model || '固定模型'
          }}</span>
          <el-select v-else v-model="selectedModel" aria-label="快速对话模型" class="model-select">
            <el-option-group
              v-for="provider in configuration?.providers.filter((item) => item.models.length) ??
              []"
              :key="provider.id"
              :label="provider.name"
            >
              <el-option
                v-for="model in provider.models"
                :key="`${provider.id}:${model}`"
                :label="model"
                :value="model"
                :disabled="!provider.configured"
              />
            </el-option-group>
          </el-select>
        </div>
      </div>

      <div class="chat-thread" aria-live="polite">
        <div v-if="!messages.length && !streamingQuestion" class="conversation-hero">
          <span class="conversation-symbol" aria-hidden="true">⌁</span>
          <span class="soft-label">LIGHTWEIGHT CONVERSATION</span>
          <h2>有什么临时问题？</h2>
          <p>新信息会自动检索并标注外部来源；普通寒暄和纯创作会直接回答。</p>
        </div>

        <template v-for="item in messages" :key="item.id">
          <div v-if="item.role === 'user'" class="quick-message user-message">
            {{ item.content }}
          </div>
          <article v-else class="quick-message assistant-message">
            <div v-html="render(item.content)" />
            <p v-if="quickSearchStatus(item)" class="web-status">
              {{ quickSearchStatus(item) }}
            </p>
            <div v-if="item.citations.length" class="web-sources">
              <a
                v-for="citation in item.citations"
                :key="`${item.id}-${citation.source_id}`"
                :href="citation.url ?? undefined"
                target="_blank"
                rel="noopener noreferrer"
              >
                <strong>[外{{ citation.source_id }}] {{ citation.title ?? '外部来源' }}</strong>
                <small>{{ citation.publisher ?? citation.url }}</small>
              </a>
            </div>
            <footer>
              {{ item.model }} ·
              {{ item.elapsed_ms ? `${(item.elapsed_ms / 1000).toFixed(2)} s` : '' }}
            </footer>
          </article>
        </template>

        <template v-if="streamingQuestion">
          <div class="quick-message user-message">{{ streamingQuestion }}</div>
          <article class="quick-message assistant-message live-message">
            <div v-if="streamingAnswer" v-html="render(streamingAnswer)" />
            <p v-else>
              {{
                webSearchEnabled ? '正在判断并检索联网信息…' : '正在连接模型并读取有限会话上下文…'
              }}
            </p>
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
.conversation-page {
  min-height: calc(100vh - 104px);
}
.conversation-stage {
  display: flex;
  min-height: 620px;
  padding: 24px;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-card);
}
.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--line-soft);
}
.chat-toolbar div {
  display: grid;
  gap: 4px;
}
.chat-toolbar .toolbar-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.search-toggle {
  display: flex;
  padding: 7px 10px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ink-muted);
  background: var(--surface-soft);
  border-radius: var(--radius-base);
}
.chat-toolbar strong {
  color: var(--ink-strong);
}
.chat-toolbar small,
.availability-note {
  font-size: 11px;
  color: var(--ink-faint);
}
.model-select {
  width: 220px;
}
.chat-thread {
  display: flex;
  padding: 26px 4px;
  overflow: auto;
  flex: 1;
  flex-direction: column;
  gap: 15px;
}
.conversation-hero {
  display: grid;
  max-width: 560px;
  margin: auto;
  text-align: center;
  place-items: center;
}
.conversation-symbol {
  display: grid;
  width: 64px;
  height: 64px;
  margin-bottom: 18px;
  font-size: 28px;
  color: var(--on-primary);
  background: var(--primary);
  border-radius: var(--radius-base);
  place-items: center;
}
.conversation-hero h2 {
  margin: 13px 0 8px;
  color: var(--ink-strong);
}
.conversation-hero p {
  margin: 0;
  line-height: 1.8;
  color: var(--ink-muted);
}
.quick-message {
  max-width: min(760px, 88%);
  padding: 14px 17px;
  line-height: 1.75;
  border-radius: var(--radius-base);
}
.user-message {
  align-self: flex-end;
  color: var(--ink-strong);
  background: var(--primary-soft);
  border-bottom-right-radius: var(--radius-small);
  border: 1px solid var(--line);
}
.assistant-message {
  align-self: flex-start;
  background: var(--surface);
  border: 1px solid var(--line);
  border-bottom-left-radius: var(--radius-small);
  box-shadow: var(--shadow-soft);
}
.assistant-message :deep(p:first-child) {
  margin-top: 0;
}
.assistant-message :deep(p:last-child) {
  margin-bottom: 0;
}
.assistant-message footer {
  margin-top: 10px;
  font-size: 10px;
  color: var(--ink-faint);
}
.web-status {
  padding: 8px 10px;
  margin: 12px 0 0;
  font-size: 11px;
  color: var(--success);
  background: var(--success-soft);
  border-radius: var(--radius-base);
}
.web-sources {
  display: grid;
  margin-top: 10px;
  gap: 7px;
}
.web-sources a {
  display: grid;
  padding: 9px 10px;
  gap: 2px;
  color: var(--ink);
  text-decoration: none;
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-base);
}
.web-sources a:hover {
  border-color: var(--line);
}
.web-sources strong {
  font-size: 11px;
}
.web-sources small {
  overflow: hidden;
  font-size: 10px;
  color: var(--ink-faint);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.live-message {
  border-color: var(--line);
}
.composer-shell {
  display: flex;
  padding: 10px;
  align-items: flex-end;
  gap: 10px;
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-soft);
}
.composer-shell textarea {
  min-height: 58px;
  padding: 10px;
  flex: 1;
  resize: vertical;
  color: var(--ink);
  background: transparent;
  border: 0;
  outline: none;
}
.composer-shell button {
  width: 42px;
  height: 42px;
  color: var(--on-primary);
  cursor: pointer;
  background: var(--primary);
  border: 0;
  border-radius: var(--radius-base);
}
.composer-shell button:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}
.composer-shell .stop-send {
  background: var(--danger);
}
.availability-note {
  margin: 10px 4px 0;
  text-align: right;
}
.temporary-pill {
  color: var(--secondary-accent);
  background: var(--secondary-soft);
}
.quick-error {
  padding: 12px 15px;
  margin-bottom: 18px;
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: var(--radius-base);
}
@media (max-width: 650px) {
  .chat-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .chat-toolbar .toolbar-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .search-toggle {
    justify-content: space-between;
  }
  .model-select {
    width: 100%;
  }
  .conversation-stage {
    padding: 16px;
  }
  .quick-message {
    max-width: 94%;
  }
}
.composer-shell:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--focus-ring);
}
</style>
