<script setup lang="ts">
import DOMPurify from 'dompurify'
import { ElAlert, ElOption, ElSelect } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { toFriendlyApiError } from '@/api/client'
import { streamCourseQuestion } from '@/api/qa'
import { useConversationsStore } from '@/stores/conversations'
import { useCoursesStore } from '@/stores/courses'
import { useLLMStore } from '@/stores/llm'
import type {
  AnswerCitation,
  AnswerScope,
  AnswerStyle,
  CourseConversationMessage,
} from '@/types/api'
import { formatCitationLocation } from '@/utils/format'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
const route = useRoute()
const router = useRouter()
const store = useCoursesStore()
const conversationsStore = useConversationsStore()
const llmStore = useLLMStore()
const { configuration: llmConfiguration, selectedModel } = storeToRefs(llmStore)
const selectedCourseId = ref('')
const answerStyle = ref<AnswerStyle>('balanced')
const answerScope = ref<AnswerScope>('course_and_external')
const question = ref('')
const activeConversationId = ref('')
const errorMessage = ref('')
const loading = ref(false)
const restoring = ref(false)
const streamingQuestion = ref('')
const streamingAnswer = ref('')
const streamingCitations = ref<AnswerCitation[]>([])
const streamState = ref<'idle' | 'streaming' | 'interrupted' | 'error'>('idle')
let abortController: AbortController | null = null

const selectedCourse = computed(() =>
  store.courses.find((course) => course.id === selectedCourseId.value),
)
const activeConversation = computed(() =>
  activeConversationId.value
    ? conversationsStore.details[activeConversationId.value] ?? null
    : null,
)
const messages = computed(() => activeConversation.value?.messages ?? [])
const canSubmit = computed(
  () =>
    Boolean(selectedCourseId.value) &&
    Boolean(question.value.trim()) &&
    Boolean(selectedModel.value) &&
    Boolean(llmConfiguration.value?.configured) &&
    !loading.value,
)

const styleOptions: Array<{ value: AnswerStyle; label: string; detail: string }> = [
  { value: 'concise', label: '简洁', detail: '单段或至多 3 个短要点，只保留核心依据' },
  { value: 'balanced', label: '均衡', detail: '结论 + 2～4 个关键要点 + 必要边界' },
  { value: 'detailed', label: '详细', detail: '资料依据 + 推导与延伸 + 边界和易错点' },
]

const scopeOptions: Array<{ value: AnswerScope; label: string; detail: string }> = [
  {
    value: 'course_and_external',
    label: '课程资料 + 外部补充',
    detail: '默认范围；课程证据不足、问题有时效性或明确要求时自动搜索',
  },
  {
    value: 'course_only',
    label: '仅课程资料',
    detail: '完全关闭 Web Search，只允许已入库课程资料支撑回答',
  },
]

const contentRoleLabels: Record<string, string> = {
  exposition: '正文',
  example: '已讲解示例',
  exercise_question: '未作答题干',
  exercise_answer: '答案或解析',
  code: '代码',
  unknown: '角色未知',
}

function contentRoleLabel(role: string): string {
  return contentRoleLabels[role] ?? role
}

function citationLabel(citation: AnswerCitation): string {
  return `[${citation.source_type === 'external' ? '外' : '课'}${citation.source_id}]`
}

function citationTitle(citation: AnswerCitation): string {
  return citation.source_type === 'external'
    ? citation.title || citation.publisher || '外部资料'
    : citation.file_name
}

function externalSearchSummary(message: CourseConversationMessage): string {
  const search = message.retrieval?.external_search
  if (!search) return ''
  if (!search.decision_reason && search.failure_reason) {
    return `历史回答记录：${search.failure_reason}`
  }
  if (search.fallback_applied) {
    return `外部检索未能提供合格证据，已降级为课程回答。${search.failure_reason || ''}`
  }
  if (search.status === 'succeeded') {
    return `外部检索完成：取得 ${search.result_count} 条合格来源，正文采用 ${search.used_result_count} 条。`
  }
  if (search.status === 'failed' || search.status === 'no_qualified_results') {
    return search.failure_reason || '外部检索没有取得合格来源。'
  }
  return search.decision_reason || search.failure_reason || '本次未触发外部检索。'
}

function externalSearchTitle(message: CourseConversationMessage): string {
  const search = message.retrieval?.external_search
  if (!search?.decision_reason && search?.failure_reason) return '历史回答状态'
  if (search?.fallback_applied) return '已安全降级'
  if (search?.status === 'succeeded') return '外部检索已完成'
  return '条件搜索判断'
}

onMounted(async () => {
  try {
    await Promise.all([
      store.loadCourses(false),
      llmStore.loadConfiguration(),
      conversationsStore.loadCourseConversations(),
    ])
    selectedCourseId.value = store.courses[0]?.id ?? ''
    await restoreConversationFromRoute()
  } catch (error) {
    errorMessage.value = toFriendlyApiError(error).message
  }
})

onBeforeUnmount(() => abortController?.abort())

watch(
  () => route.params.conversationId,
  async () => {
    if (!restoring.value) {
      await restoreConversationFromRoute()
    }
  },
)

async function restoreConversationFromRoute(): Promise<void> {
  const conversationId = String(route.params.conversationId ?? '')
  if (!conversationId) {
    activeConversationId.value = ''
    return
  }
  restoring.value = true
  errorMessage.value = ''
  try {
    let summary = conversationsStore.courseConversations.find(
      (conversation) => conversation.id === conversationId,
    )
    if (!summary) {
      await conversationsStore.loadCourseConversations()
      summary = conversationsStore.courseConversations.find(
        (conversation) => conversation.id === conversationId,
      )
    }
    if (!summary) {
      throw {
        code: 'NOT_FOUND',
        message: '找不到该课程对话，记录可能已经被删除。',
      }
    }
    selectedCourseId.value = summary.course_id
    await conversationsStore.loadCourseConversation(summary.course_id, summary.id)
    activeConversationId.value = summary.id
  } catch (error) {
    activeConversationId.value = ''
    errorMessage.value = toFriendlyApiError(error).message
  } finally {
    restoring.value = false
  }
}

async function startNewConversation(): Promise<void> {
  stopStreaming()
  streamingQuestion.value = ''
  streamingAnswer.value = ''
  streamingCitations.value = []
  streamState.value = 'idle'
  activeConversationId.value = ''
  errorMessage.value = ''
  question.value = ''
  if (route.params.conversationId) {
    await router.push('/assistant')
  }
}

async function submitQuestion(): Promise<void> {
  if (!canSubmit.value) {
    return
  }
  loading.value = true
  errorMessage.value = ''
  const submittedQuestion = question.value.trim()
  streamingQuestion.value = submittedQuestion
  streamingAnswer.value = ''
  streamingCitations.value = []
  streamState.value = 'streaming'
  abortController = new AbortController()
  try {
    let conversationId = activeConversationId.value
    if (!conversationId) {
      const conversation = await conversationsStore.createCourseConversation(
        selectedCourseId.value,
      )
      conversationId = conversation.id
      activeConversationId.value = conversation.id
      await router.replace(`/assistant/${conversation.id}`)
    }
    await streamCourseQuestion(
      selectedCourseId.value,
      {
        question: submittedQuestion,
        answer_style: answerStyle.value,
        answer_scope: answerScope.value,
        conversation_id: conversationId,
        model: selectedModel.value,
      },
      abortController.signal,
      {
        onDelta: (delta) => {
          streamingAnswer.value += delta
        },
        onCitations: (data) => {
          streamingCitations.value = (data as { citations: AnswerCitation[] }).citations
        },
        onComplete: async (result) => {
          await conversationsStore.loadCourseConversation(
            selectedCourseId.value,
            result.conversation_id,
          )
          await conversationsStore.loadCourseConversations()
          question.value = ''
          streamState.value = 'idle'
          streamingQuestion.value = ''
          streamingAnswer.value = ''
          streamingCitations.value = []
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

function renderAnswer(message: CourseConversationMessage): string {
  return DOMPurify.sanitize(markdown.render(message.content))
}

function submitWithKeyboard(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    void submitQuestion()
  }
}
</script>

<template>
  <section class="page-view assistant-page">
    <header class="page-heading">
      <div>
        <div class="eyebrow"><span /> GROUNDED COURSE Q&amp;A</div>
        <h1>课程学习助手</h1>
        <p>优先检索课程证据，并按回答范围补充可核验外部来源。</p>
      </div>
      <span class="context-pill">有限上下文 · 改写后逐题检索</span>
    </header>

    <el-alert
      v-if="llmConfiguration && !llmConfiguration.configured"
      title="尚未配置 LLM API Key"
      description="请在项目根目录 .env 中填写 LLM_API_KEY 并重启后端；密钥不会发送到前端。"
      type="warning"
      :closable="false"
      show-icon
      class="page-alert"
    />
    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <div class="assistant-workspace">
      <aside class="control-panel">
        <span class="soft-label">ANSWER SETTINGS</span>
        <h2>回答设置</h2>

        <label for="assistant-course">课程范围</label>
        <el-select
          id="assistant-course"
          v-model="selectedCourseId"
          placeholder="请选择课程"
          size="large"
          class="control-select"
          @change="startNewConversation"
        >
          <el-option
            v-for="course in store.courses"
            :key="course.id"
            :label="course.name"
            :value="course.id"
          />
        </el-select>

        <label for="answer-scope">回答范围</label>
        <el-select
          id="answer-scope"
          v-model="answerScope"
          size="large"
          class="control-select"
        >
          <el-option
            v-for="option in scopeOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <p class="style-detail">
          {{ scopeOptions.find((option) => option.value === answerScope)?.detail }}
        </p>

        <label for="answer-style">回答风格</label>
        <el-select
          id="answer-style"
          v-model="answerStyle"
          size="large"
          class="control-select"
        >
          <el-option
            v-for="option in styleOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <p class="style-detail">
          {{ styleOptions.find((option) => option.value === answerStyle)?.detail }}
        </p>

        <label for="answer-model">生成模型</label>
        <el-select
          id="answer-model"
          v-model="selectedModel"
          size="large"
          class="control-select"
        >
          <el-option
            v-for="model in llmConfiguration?.available_models ?? []"
            :key="model"
            :label="model"
            :value="model"
          />
        </el-select>

        <div class="model-card">
          <div>
            <span>本次请求模型</span>
            <strong>{{ selectedModel || '正在读取配置' }}</strong>
          </div>
          <span
            class="config-status"
            :class="{ ready: llmConfiguration?.configured }"
          >
            {{ llmConfiguration?.configured ? '已配置' : '待配置' }}
          </span>
        </div>

        <button
          v-if="activeConversationId"
          type="button"
          class="secondary-button new-conversation-button"
          @click="startNewConversation"
        >
          新建课程对话
        </button>

        <div class="guardrail-note">
          <strong>回答边界</strong>
          <p v-if="answerScope === 'course_only'">
            仅使用已完成入库的课程资料；不会发起 Web Search。
          </p>
          <p v-else>
            先检查课程证据覆盖度；必要时自动搜索并生成 [课n]、[外n] 独立引用。
            搜索失败会保留可用的课程回答。
          </p>
        </div>
      </aside>

      <main class="answer-panel">
        <div v-if="!messages.length && !loading" class="empty-answer">
          <span class="assistant-mark" aria-hidden="true">AI</span>
          <span class="soft-label">READY FOR YOUR QUESTION</span>
          <h2>{{ selectedCourse?.name || '请选择一门课程' }}</h2>
          <p>
            输入课程知识问题。课程引用使用 [课1]，外部引用使用 [外1]，两类来源独立编号。
          </p>
        </div>

        <div v-if="messages.length" class="message-thread">
          <template v-for="message in messages" :key="message.id">
            <div v-if="message.role === 'user'" class="question-bubble">
              {{ message.content }}
            </div>
            <article v-else class="answer-result">
              <div class="answer-heading">
                <div>
                  <span class="soft-label">GROUNDED ANSWER</span>
                  <h2>资料依据回答</h2>
                </div>
                <span
                  class="answer-status"
                  :class="{
                    refused: message.answer_status === 'insufficient_evidence',
                    conflict: message.retrieval?.source_conflict_detected,
                  }"
                >
                  {{
                    message.retrieval?.source_conflict_detected
                      ? '资料存在差异'
                      : message.answer_status === 'answered'
                        ? '证据已引用'
                        : '资料不足'
                  }}
                </span>
              </div>
              <div class="markdown-answer" v-html="renderAnswer(message)" />

              <div
                v-if="message.retrieval?.answer_scope === 'course_and_external'"
                class="search-status-note"
                :class="{
                  fallback: message.retrieval.external_search.fallback_applied,
                  searched: message.retrieval.external_search.status === 'succeeded',
                }"
              >
                <strong>
                  {{ externalSearchTitle(message) }}
                </strong>
                <span>{{ externalSearchSummary(message) }}</span>
              </div>

              <section v-if="message.citations.length" class="citation-section">
                <div class="citation-title">
                  <h3>引用资料</h3>
                  <span>{{ message.citations.length }} 条已使用证据</span>
                </div>
                <details
                  v-for="citation in message.citations"
                  :key="`${message.id}-${citation.source_type}-${citation.source_id}`"
                  class="citation-card"
                  :class="citation.source_type"
                >
                  <summary>
                    <span class="citation-number">{{ citationLabel(citation) }}</span>
                    <span class="citation-summary">
                      <strong>{{ citationTitle(citation) }}</strong>
                      <small v-if="citation.source_type === 'course'">
                        {{ formatCitationLocation(citation) }}
                      </small>
                      <small v-else>{{ citation.publisher }} · {{ citation.url }}</small>
                    </span>
                    <span v-if="citation.score !== null" class="citation-score">
                      重排 {{ (citation.score * 100).toFixed(1) }}%
                    </span>
                  </summary>
                  <p>{{ citation.text }}</p>
                  <small v-if="citation.source_type === 'course'">
                    重排排名 #{{ citation.retrieval_rank }} ·
                    {{ contentRoleLabel(citation.content_role) }} · Dense
                    {{ citation.dense_score === null ? '—' : `${(citation.dense_score * 100).toFixed(1)}%` }}
                    · Chunk {{ citation.chunk_index }}
                  </small>
                  <small v-else>
                    访问时间 {{ citation.accessed_at || '未记录' }} ·
                    <a v-if="citation.url" :href="citation.url" target="_blank" rel="noopener noreferrer">
                      打开来源
                    </a>
                  </small>
                </details>
              </section>

              <footer v-if="message.retrieval" class="answer-meta">
                <span>{{ message.model || '未调用模型' }}</span>
                <span>
                  候选 {{ message.retrieval.candidate_count }} → 重排
                  {{ message.retrieval.returned_count }}
                </span>
                <span>合格证据 {{ message.retrieval.eligible_evidence_count }} 条</span>
                <span>上下文 {{ message.retrieval.context_message_count }} 条</span>
                <span v-if="message.retrieval.rejected_evidence_count">
                  排除不合格候选 {{ message.retrieval.rejected_evidence_count }} 条
                </span>
                <span v-if="message.elapsed_ms !== null">
                  {{ (message.elapsed_ms / 1000).toFixed(2) }} s
                </span>
                <span v-if="message.usage">{{ message.usage.total_tokens }} tokens</span>
                <span v-if="message.retrieval.rewrite_applied">
                  已改写检索：{{ message.retrieval.rewritten_query }}
                </span>
                <span>
                  {{ message.retrieval.answer_scope === 'course_only' ? '仅课程资料' : '课程 + 外部补充' }}
                </span>
                <span v-if="message.retrieval.external_search.decision_reason">
                  {{ message.retrieval.external_search.decision_reason }}
                </span>
              </footer>
            </article>
          </template>
        </div>

        <div v-if="streamingQuestion" class="message-thread live-thread" aria-live="polite">
          <div class="question-bubble">{{ streamingQuestion }}</div>
          <article class="answer-result live-answer">
            <div class="answer-heading">
              <div>
                <span class="soft-label">STREAMING ANSWER</span>
                <h2>资料依据回答</h2>
              </div>
              <span class="answer-status" :class="{ refused: streamState !== 'streaming' }">
                {{
                  streamState === 'streaming'
                    ? '正在生成'
                    : streamState === 'interrupted'
                      ? '已中断 · 未保存'
                      : '生成失败 · 未保存'
                }}
              </span>
            </div>
            <div
              v-if="streamingAnswer"
              class="markdown-answer"
              v-html="DOMPurify.sanitize(markdown.render(streamingAnswer))"
            />
            <div v-else class="loading-answer compact" role="status">
              <span class="thinking-orbit" aria-hidden="true" />
              <strong>正在改写问题、召回并校验证据…</strong>
              <p>正文通过引用一致性校验后开始流式显示。</p>
            </div>
            <p v-if="streamingCitations.length" class="stream-citation-note">
              已校验 {{ streamingCitations.length }} 条引用，正在保存完整回答…
            </p>
          </article>
        </div>

        <form class="question-composer" @submit.prevent="submitQuestion">
          <label for="course-question" class="sr-only">课程问题</label>
          <textarea
            id="course-question"
            v-model="question"
            maxlength="2000"
            rows="3"
            placeholder="例如：Dijkstra 算法的执行过程是什么？"
            @keydown="submitWithKeyboard"
          />
          <div class="composer-footer">
            <span>Ctrl / ⌘ + Enter 发送</span>
            <button
              v-if="loading"
              type="button"
              class="secondary-button stop-button"
              @click="stopStreaming"
            >
              停止生成
            </button>
            <button v-else type="submit" class="primary-button" :disabled="!canSubmit">
              检索并回答
            </button>
          </div>
        </form>
      </main>
    </div>
  </section>
</template>

<style scoped>
.assistant-workspace {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 650px;
  overflow: hidden;
  background: rgb(255 255 255 / 72%);
  border: 1px solid var(--line);
  border-radius: 26px;
  box-shadow: var(--shadow-card);
}

.control-panel {
  padding: 28px 24px;
  background:
    radial-gradient(circle at 15% 0%, rgb(73 190 255 / 13%), transparent 32%),
    linear-gradient(165deg, rgb(247 252 255 / 96%), rgb(247 245 255 / 90%));
  border-right: 1px solid var(--line);
}

.control-panel h2 {
  margin: 10px 0 28px;
  color: var(--ink-strong);
}

.control-panel > label {
  display: block;
  margin: 20px 0 8px;
  font-size: 12px;
  font-weight: 750;
  color: var(--ink);
}

.control-select {
  width: 100%;
}

.style-detail {
  margin: 7px 2px 0;
  font-size: 11px;
  color: var(--ink-faint);
}

.model-card,
.guardrail-note {
  margin-top: 24px;
  padding: 15px;
  background: rgb(255 255 255 / 72%);
  border: 1px solid var(--line);
  border-radius: 16px;
}

.model-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.model-card div {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.model-card span,
.guardrail-note p {
  font-size: 11px;
  color: var(--ink-muted);
}

.new-conversation-button {
  width: 100%;
  margin-top: 14px;
}

.model-card strong {
  overflow: hidden;
  font-size: 12px;
  color: var(--ink-strong);
  text-overflow: ellipsis;
}

.config-status {
  padding: 5px 8px;
  white-space: nowrap;
  background: #fff5df;
  border-radius: 999px;
}

.config-status.ready {
  color: #168466;
  background: #e3fbf3;
}

.guardrail-note strong {
  font-size: 12px;
  color: var(--ink-strong);
}

.guardrail-note p {
  margin: 7px 0 0;
  line-height: 1.65;
}

.answer-panel {
  display: flex;
  min-width: 0;
  padding: 28px;
  flex-direction: column;
}

.empty-answer,
.loading-answer {
  display: grid;
  min-height: 390px;
  max-width: 640px;
  margin: auto;
  text-align: center;
  place-items: center;
  align-content: center;
}

.assistant-mark {
  display: grid;
  width: 70px;
  height: 70px;
  margin-bottom: 18px;
  font-size: 15px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(145deg, var(--primary), var(--violet));
  border-radius: 24px;
  box-shadow: 0 18px 42px rgb(72 126 247 / 24%);
  place-items: center;
}

.empty-answer h2 {
  margin: 13px 0 8px;
  color: var(--ink-strong);
}

.empty-answer p,
.loading-answer p {
  margin: 0;
  line-height: 1.75;
  color: var(--ink-muted);
}

.thinking-orbit {
  width: 42px;
  height: 42px;
  margin-bottom: 18px;
  border: 4px solid var(--primary-soft);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 800ms linear infinite;
}

.loading-answer strong {
  margin-bottom: 8px;
  color: var(--ink-strong);
}

.message-thread {
  display: grid;
  gap: 18px;
  padding-bottom: 22px;
}

.answer-result {
  padding: 20px;
  background: rgb(255 255 255 / 72%);
  border: 1px solid var(--line-soft);
  border-radius: 18px;
}

.loading-answer.compact {
  min-height: 170px;
  margin-block: 14px;
}

.question-bubble {
  max-width: 78%;
  padding: 12px 16px;
  margin: 0 0 24px auto;
  line-height: 1.6;
  color: #fff;
  background: linear-gradient(120deg, #4b9cf4, #706ff1);
  border-radius: 17px 17px 5px;
  box-shadow: 0 10px 22px rgb(65 125 221 / 18%);
}

.answer-heading,
.citation-title,
.answer-meta,
.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.answer-heading h2 {
  margin: 5px 0 0;
  font-size: 20px;
  color: var(--ink-strong);
}

.answer-status {
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 750;
  color: #168466;
  background: #e3fbf3;
  border-radius: 999px;
}

.answer-status.refused {
  color: #986315;
  background: #fff3da;
}

.answer-status.conflict {
  color: #8b5b12;
  background: #fff0c9;
}

.markdown-answer {
  padding: 20px 0;
  font-size: 14px;
  line-height: 1.85;
  color: var(--ink);
}

.markdown-answer :deep(p:first-child) {
  margin-top: 0;
}

.search-status-note {
  display: grid;
  gap: 4px;
  padding: 11px 13px;
  margin-bottom: 18px;
  font-size: 11px;
  color: var(--ink-muted);
  background: rgb(244 248 252 / 88%);
  border: 1px solid var(--line-soft);
  border-radius: 12px;
}

.search-status-note strong {
  color: var(--ink-strong);
}

.search-status-note.searched {
  background: rgb(239 250 247 / 92%);
  border-color: rgb(36 153 121 / 20%);
}

.search-status-note.fallback {
  background: rgb(255 248 232 / 94%);
  border-color: rgb(196 135 32 / 24%);
}

.citation-section {
  padding-top: 20px;
  border-top: 1px solid var(--line-soft);
}

.citation-title h3 {
  margin: 0;
  font-size: 14px;
  color: var(--ink-strong);
}

.citation-title span {
  font-size: 11px;
  color: var(--ink-faint);
}

.citation-card {
  margin-top: 10px;
  background: rgb(247 251 255 / 88%);
  border: 1px solid var(--line);
  border-radius: 15px;
}

.citation-card.external {
  background: rgb(249 247 255 / 92%);
  border-color: rgb(121 94 214 / 24%);
}

.citation-card.external .citation-number {
  color: #6548b8;
  background: #eee8ff;
}

.citation-card summary {
  display: flex;
  padding: 13px 14px;
  align-items: center;
  gap: 11px;
  cursor: pointer;
  list-style: none;
}

.citation-number {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  font-size: 12px;
  font-weight: 800;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border-radius: 10px;
  place-items: center;
}

.citation-summary {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 3px;
}

.citation-summary strong,
.citation-summary small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.citation-summary strong {
  font-size: 12px;
  color: var(--ink-strong);
}

.citation-summary small,
.citation-score,
.citation-card > small {
  font-size: 10px;
  color: var(--ink-faint);
}

.citation-card > small a {
  color: var(--primary-deep);
}

.citation-card > p {
  margin: 0;
  padding: 13px 15px 8px;
  line-height: 1.75;
  white-space: pre-wrap;
  border-top: 1px solid var(--line-soft);
}

.citation-card > small {
  display: block;
  padding: 0 15px 13px;
}

.answer-meta {
  flex-wrap: wrap;
  justify-content: flex-start;
  margin-top: 16px;
  font-size: 10px;
  color: var(--ink-faint);
}

.answer-meta span + span::before {
  margin-right: 12px;
  content: '·';
}

.live-thread {
  margin-top: 14px;
}

.live-answer {
  border-color: rgb(62 155 255 / 28%);
}

.stream-citation-note {
  margin: 0;
  padding-top: 12px;
  font-size: 11px;
  color: var(--ink-faint);
  border-top: 1px solid var(--line-soft);
}

.stop-button {
  color: var(--danger);
}

.question-composer {
  margin-top: auto;
  padding: 12px;
  background: rgb(255 255 255 / 92%);
  border: 1px solid rgb(83 137 197 / 20%);
  border-radius: 18px;
  box-shadow: 0 14px 34px rgb(65 105 156 / 10%);
}

.question-composer textarea {
  width: 100%;
  min-height: 72px;
  padding: 6px;
  resize: vertical;
  color: var(--ink);
  background: transparent;
  border: 0;
  outline: none;
}

.composer-footer {
  padding-top: 8px;
  border-top: 1px solid var(--line-soft);
}

.composer-footer > span {
  font-size: 10px;
  color: var(--ink-faint);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 920px) {
  .assistant-workspace {
    grid-template-columns: 1fr;
  }

  .control-panel {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .model-card,
  .guardrail-note {
    margin-top: 14px;
  }
}

@media (max-width: 620px) {
  .answer-panel,
  .control-panel {
    padding: 20px;
  }

  .question-bubble {
    max-width: 92%;
  }

  .citation-score,
  .composer-footer > span {
    display: none;
  }
}
</style>
