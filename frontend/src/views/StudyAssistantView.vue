<script setup lang="ts">
import DOMPurify from 'dompurify'
import { ElAlert, ElOption, ElOptionGroup, ElSelect } from 'element-plus'
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
const {
  configuration: llmConfiguration,
  selectedModel,
  selectedProvider,
  selectedModelConfigured,
} = storeToRefs(llmStore)
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
    ? (conversationsStore.details[activeConversationId.value] ?? null)
    : null,
)
const messages = computed(() => activeConversation.value?.messages ?? [])
const canSubmit = computed(
  () =>
    Boolean(selectedCourseId.value) &&
    Boolean(question.value.trim()) &&
    Boolean(selectedModel.value) &&
    selectedModelConfigured.value &&
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
    label: '空间资料 + 外部补充',
    detail: '默认范围；空间证据不足、问题有时效性或明确要求时自动搜索',
  },
  {
    value: 'course_only',
    label: '仅空间资料',
    detail: '完全关闭 Web Search，只允许已入库空间资料支撑回答',
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
    return `外部检索未能提供合格证据，已降级为资料回答。${search.failure_reason || ''}`
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

function isSummary(message: CourseConversationMessage): boolean {
  return message.retrieval?.task_type === 'summary'
}

function isExam(message: CourseConversationMessage): boolean {
  return message.retrieval?.task_type === 'exam'
}

function resultEyebrow(message: CourseConversationMessage): string {
  if (isSummary(message)) return 'COURSE SUMMARY'
  if (isExam(message)) return 'GROUNDED EXAM'
  return 'GROUNDED ANSWER'
}

function resultTitle(message: CourseConversationMessage): string {
  if (isSummary(message)) return '资料总结'
  if (isExam(message)) return '内容生成结果'
  return '资料依据回答'
}

function quotaSummary(quotas: { key: string; count: number }[]): string {
  const labels: Record<string, string> = {
    single_choice: '单选',
    multiple_choice: '多选',
    true_false: '判断',
    short_answer: '简答',
    programming: '编程',
    easy: '基础',
    medium: '中等',
    hard: '困难',
  }
  return quotas
    .filter((item) => item.count > 0)
    .map((item) => `${labels[item.key] ?? item.key} ${item.count}`)
    .join(' / ')
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
        message: '找不到该空间对话，记录可能已经被删除。',
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
      const conversation = await conversationsStore.createCourseConversation(selectedCourseId.value)
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
        <div class="eyebrow"><span /> ROUTED KNOWLEDGE AGENT</div>
        <h1>智能体对话</h1>
        <p>直接输入问题、总结或内容生成要求，Agent 会识别任务并选择对应资料链路。</p>
      </div>
      <span class="context-pill">有限上下文 · 改写后逐题检索</span>
    </header>

    <el-alert
      v-if="selectedProvider && !selectedModelConfigured"
      :title="`${selectedProvider.name} 接口待配置`"
      :description="`请在项目根目录 .env 中填写 ${selectedProvider.api_key_env} 和 ${selectedProvider.models_env} 并重启后端；密钥不会发送到前端。`"
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

        <label for="assistant-course">资料空间</label>
        <el-select
          id="assistant-course"
          v-model="selectedCourseId"
          placeholder="请选择资料空间"
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

        <label for="answer-scope">问答来源范围</label>
        <el-select id="answer-scope" v-model="answerScope" size="large" class="control-select">
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

        <label for="answer-style">问答回答风格</label>
        <el-select id="answer-style" v-model="answerStyle" size="large" class="control-select">
          <el-option
            v-for="option in styleOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <p class="style-detail">
          {{
            styleOptions.find((option) => option.value === answerStyle)?.detail
          }}；总结与内容生成使用独立结构
        </p>

        <label for="answer-model">生成模型</label>
        <el-select id="answer-model" v-model="selectedModel" size="large" class="control-select">
          <el-option-group
            v-for="provider in llmConfiguration?.providers.filter((item) => item.models.length) ??
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

        <div class="model-card">
          <div>
            <span>本次请求模型</span>
            <strong>{{ selectedModel || '正在读取配置' }}</strong>
          </div>
          <span class="config-status" :class="{ ready: selectedModelConfigured }">
            {{ selectedModelConfigured ? '已配置' : '待配置' }}
          </span>
        </div>

        <button
          v-if="activeConversationId"
          type="button"
          class="secondary-button new-conversation-button"
          @click="startNewConversation"
        >
          新建空间对话
        </button>

        <div class="guardrail-note">
          <strong>自动路由边界</strong>
          <p v-if="answerScope === 'course_only'">
            仅使用已完成入库的空间资料；不会发起 Web Search。
          </p>
          <p v-else>
            先检查空间证据覆盖度；必要时自动搜索并生成 [课n]、[外n] 独立引用。
            总结请求始终只使用空间资料；内容生成最多采用 20% 外部补充，搜索失败会降级为仅空间资料。
          </p>
        </div>
      </aside>

      <main class="answer-panel">
        <div v-if="!messages.length && !loading" class="empty-answer">
          <span class="assistant-mark" aria-hidden="true">AI</span>
          <span class="soft-label">READY FOR YOUR REQUEST</span>
          <h2>{{ selectedCourse?.name || '请选择一个资料空间' }}</h2>
          <p>可直接提问、总结或输入“比较两份方案并生成检查清单”。总结默认仅引用空间资料。</p>
        </div>

        <div v-if="messages.length" class="message-thread">
          <template v-for="message in messages" :key="message.id">
            <div v-if="message.role === 'user'" class="question-bubble">
              {{ message.content }}
            </div>
            <article v-else class="answer-result">
              <div class="answer-heading">
                <div>
                  <span class="soft-label">{{ resultEyebrow(message) }}</span>
                  <h2>{{ resultTitle(message) }}</h2>
                </div>
                <span
                  class="answer-status"
                  :class="{
                    refused: message.answer_status === 'insufficient_evidence',
                    conflict: message.retrieval?.source_conflict_detected,
                  }"
                >
                  {{
                    isExam(message)
                      ? '内容生成'
                      : isSummary(message)
                        ? '资料总结'
                        : message.retrieval?.source_conflict_detected
                          ? '资料存在差异'
                          : message.answer_status === 'answered'
                            ? '证据已引用'
                            : '资料不足'
                  }}
                </span>
              </div>

              <div
                v-if="isExam(message) && message.retrieval?.exam_plan"
                class="search-status-note searched"
              >
                <strong>内容生成计划与硬性校验</strong>
                <span>
                  {{ message.retrieval.exam_plan.question_count }} 题 ·
                  {{ message.retrieval.exam_plan.programming_language }} · 题型
                  {{ quotaSummary(message.retrieval.exam_plan.type_distribution) }} · 难度
                  {{ quotaSummary(message.retrieval.exam_plan.difficulty_distribution) }}
                </span>
                <span>
                  空间资料直接采用 ≤ {{ message.retrieval.exam_plan.max_course_adapted_count }} 题 ·
                  外部补充 ≤ {{ message.retrieval.exam_plan.max_external_count }} 题
                </span>
                <span v-if="message.retrieval.exam_quality">
                  实际 {{ message.retrieval.exam_quality.generated_question_count }} 题 · 资料原创
                  {{ message.retrieval.exam_quality.course_generated_count }} · 教材改编
                  {{ message.retrieval.exam_quality.course_adapted_count }} · 外部补充
                  {{ message.retrieval.exam_quality.external_supplement_count }} · 校验{{
                    message.retrieval.exam_quality.passed ? '通过' : '未通过'
                  }}
                  <template v-if="message.retrieval.exam_quality.grounding_verified">
                    · 逐题证据审查通过
                  </template>
                  <template
                    v-if="message.retrieval.exam_quality.grounding_repaired_questions.length"
                  >
                    · 已重生成第
                    {{ message.retrieval.exam_quality.grounding_repaired_questions.join('、') }} 题
                  </template>
                  <template v-if="message.retrieval.exam_quality.duplicates_detected">
                    · 第
                    {{ message.retrieval.exam_quality.duplicate_question_numbers?.join('、') }}
                    题重复改写已达上限，请人工复核
                  </template>
                  <template v-if="message.retrieval.exam_quality.external_fallback_applied">
                    · 外部搜索失败后已降级
                  </template>
                </span>
              </div>
              <div class="markdown-answer" v-html="renderAnswer(message)" />

              <div
                v-if="isSummary(message) && message.retrieval?.summary_scope_description"
                class="search-status-note searched"
              >
                <strong>
                  {{ message.retrieval.summary_plan?.is_default ? '综合总结计划' : '动态总结计划' }}
                </strong>
                <span>{{ message.retrieval.summary_scope_description }}</span>
                <span v-if="message.retrieval.summary_plan">
                  目标：{{ message.retrieval.summary_plan.goal }} ·
                  {{ message.retrieval.summary_plan.sections.length }} 个定向章节 ·
                  {{ message.retrieval.summary_plan.output_format }}
                </span>
                <span v-if="message.retrieval.summary_quality">
                  质量校验：{{ message.retrieval.summary_quality.passed ? '通过' : '存在限制' }} ·
                  {{ message.retrieval.summary_quality.evidence_backed_section_count }}/{{
                    message.retrieval.summary_quality.planned_section_count
                  }}
                  节有空间证据
                  <template v-if="message.retrieval.summary_quality.rewritten_sections.length">
                    · 已局部修复
                    {{ message.retrieval.summary_quality.rewritten_sections.length }} 节
                  </template>
                  <template
                    v-if="message.retrieval.summary_quality.cross_section_evidence_reuse.length"
                  >
                    · 安全复用跨节证据
                    {{ message.retrieval.summary_quality.cross_section_evidence_reuse.length }} 节
                  </template>
                  <template
                    v-if="message.retrieval.summary_quality.normalized_source_declarations.length"
                  >
                    · 已校正引用声明
                    {{ message.retrieval.summary_quality.normalized_source_declarations.length }} 节
                  </template>
                  <template
                    v-if="message.retrieval.summary_quality.normalized_section_metadata.length"
                  >
                    · 已校正章节元数据
                    {{ message.retrieval.summary_quality.normalized_section_metadata.length }} 节
                  </template>
                  <template
                    v-if="message.retrieval.summary_quality.normalized_citation_namespaces.length"
                  >
                    · 已补全资料引用标记
                    {{ message.retrieval.summary_quality.normalized_citation_namespaces.length }} 节
                  </template>
                  <template v-if="message.retrieval.summary_quality.coverage_warnings.length">
                    ·
                    {{
                      message.retrieval.summary_quality.coverage_warnings.length
                    }}
                    项表达需人工确认
                  </template>
                  <template
                    v-if="message.retrieval.summary_quality.grounding_fallback_sections.length"
                  >
                    ·
                    {{
                      message.retrieval.summary_quality.grounding_fallback_sections.length
                    }}
                    节已按资料不足处理
                  </template>
                </span>
              </div>

              <div
                v-if="
                  !isSummary(message) && message.retrieval?.answer_scope === 'course_and_external'
                "
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
                    {{
                      citation.dense_score === null
                        ? '—'
                        : `${(citation.dense_score * 100).toFixed(1)}%`
                    }}
                    · Chunk {{ citation.chunk_index }}
                  </small>
                  <small v-else>
                    访问时间 {{ citation.accessed_at || '未记录' }} ·
                    <a
                      v-if="citation.url"
                      :href="citation.url"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      打开来源
                    </a>
                  </small>
                </details>
              </section>

              <footer v-if="message.retrieval" class="answer-meta">
                <span>{{ message.model || '未调用模型' }}</span>
                <span>{{
                  isExam(message) ? '资料生成' : isSummary(message) ? '资料总结' : '资料问答'
                }}</span>
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
                  {{
                    message.retrieval.answer_scope === 'course_only'
                      ? '仅空间资料'
                      : '空间资料 + 外部补充'
                  }}
                </span>
                <span v-if="message.retrieval.external_search.decision_reason">
                  {{ message.retrieval.external_search.decision_reason }}
                </span>
                <span v-if="message.retrieval.router_reason">
                  {{ message.retrieval.router_reason }}
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
                <span class="soft-label">ROUTING &amp; GENERATING</span>
                <h2>正在识别任务</h2>
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
              <strong>正在识别任务、召回并校验证据或内容配额…</strong>
              <p>正文通过引用一致性校验后开始流式显示。</p>
            </div>
            <p v-if="streamingCitations.length" class="stream-citation-note">
              已校验 {{ streamingCitations.length }} 条引用，正在保存完整回答…
            </p>
          </article>
        </div>

        <form class="question-composer" @submit.prevent="submitQuestion">
          <label for="course-question" class="sr-only">智能体请求</label>
          <textarea
            id="course-question"
            v-model="question"
            maxlength="2000"
            rows="3"
            placeholder="例如：解释这份规范；总结第二节；或比较两份方案并生成检查清单"
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
              提交给 Agent
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
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-card);
}

.control-panel {
  padding: 28px 24px;
  background: var(--surface-soft);
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
  font-weight: 600;
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
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
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
  background: var(--warning-soft);
  border-radius: var(--radius-base);
  color: var(--warning);
}

.config-status.ready {
  color: var(--success);
  background: var(--success-soft);
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
  font-weight: 600;
  color: var(--on-primary);
  background: var(--primary);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-soft);
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
  background: var(--surface);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-base);
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
  color: var(--ink-strong);
  background: var(--primary-soft);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-soft);
  border: 1px solid var(--line);
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
  font-weight: 600;
  color: var(--success);
  background: var(--success-soft);
  border-radius: var(--radius-base);
}

.answer-status.refused {
  color: var(--warning);
  background: var(--warning-soft);
}

.answer-status.conflict {
  color: var(--warning);
  background: var(--warning-soft);
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
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-base);
}

.search-status-note strong {
  color: var(--ink-strong);
}

.search-status-note.searched {
  background: var(--success-soft);
  border-color: var(--success-line);
}

.search-status-note.fallback {
  background: var(--warning-soft);
  border-color: var(--warning-line);
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
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
}

.citation-card.external {
  background: var(--secondary-soft);
  border-color: var(--secondary-line);
}

.citation-card.external .citation-number {
  color: var(--secondary-accent);
  background: var(--secondary-soft);
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
  font-weight: 600;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border-radius: var(--radius-base);
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
  border-color: var(--line);
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
  background: var(--surface-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-soft);
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

.question-composer:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--focus-ring);
}
</style>
