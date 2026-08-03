<script setup lang="ts">
import DOMPurify from 'dompurify'
import { ElAlert, ElOption, ElSelect } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { computed, onMounted, ref, watch } from 'vue'

import { toFriendlyApiError } from '@/api/client'
import { askCourseQuestion, fetchLLMConfiguration } from '@/api/qa'
import { useCoursesStore } from '@/stores/courses'
import type { AnswerStyle, CourseAnswer, LLMConfiguration } from '@/types/api'
import { formatCitationLocation } from '@/utils/format'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
const store = useCoursesStore()
const selectedCourseId = ref('')
const answerStyle = ref<AnswerStyle>('balanced')
const question = ref('')
const result = ref<CourseAnswer | null>(null)
const llmConfiguration = ref<LLMConfiguration | null>(null)
const errorMessage = ref('')
const loading = ref(false)

const selectedCourse = computed(() =>
  store.courses.find((course) => course.id === selectedCourseId.value),
)
const canSubmit = computed(
  () =>
    Boolean(selectedCourseId.value) &&
    Boolean(question.value.trim()) &&
    Boolean(llmConfiguration.value?.configured) &&
    !loading.value,
)
const answerHtml = computed(() => {
  if (!result.value) {
    return ''
  }
  return DOMPurify.sanitize(markdown.render(result.value.answer))
})

const styleOptions: Array<{ value: AnswerStyle; label: string; detail: string }> = [
  { value: 'concise', label: '简洁', detail: '结论优先，保留必要解释' },
  { value: 'balanced', label: '均衡', detail: '结论、原因与要点兼顾' },
  { value: 'detailed', label: '详细', detail: '分层展开步骤与边界' },
]

onMounted(async () => {
  try {
    const [, configuration] = await Promise.all([
      store.loadCourses(false),
      fetchLLMConfiguration(),
    ])
    llmConfiguration.value = configuration
    selectedCourseId.value = store.courses[0]?.id ?? ''
  } catch (error) {
    errorMessage.value = toFriendlyApiError(error).message
  }
})

watch(selectedCourseId, () => {
  result.value = null
  errorMessage.value = ''
})

async function submitQuestion(): Promise<void> {
  if (!canSubmit.value) {
    return
  }
  loading.value = true
  errorMessage.value = ''
  result.value = null
  try {
    result.value = await askCourseQuestion(selectedCourseId.value, {
      question: question.value.trim(),
      answer_style: answerStyle.value,
    })
  } catch (error) {
    errorMessage.value = toFriendlyApiError(error).message
  } finally {
    loading.value = false
  }
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
        <p>从所选课程资料中检索证据，再生成带页码、幻灯片号或文本行号的可追溯回答。</p>
      </div>
      <span class="context-pill">单轮课程问答</span>
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
        >
          <el-option
            v-for="course in store.courses"
            :key="course.id"
            :label="course.name"
            :value="course.id"
          />
        </el-select>

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

        <div class="model-card">
          <div>
            <span>当前模型</span>
            <strong>{{ llmConfiguration?.model || '正在读取配置' }}</strong>
          </div>
          <span
            class="config-status"
            :class="{ ready: llmConfiguration?.configured }"
          >
            {{ llmConfiguration?.configured ? '已配置' : '待配置' }}
          </span>
        </div>

        <div class="guardrail-note">
          <strong>回答边界</strong>
          <p>只使用已完成入库的课程资料。证据不足时明确拒答，不用模型常识补齐。</p>
        </div>
      </aside>

      <main class="answer-panel">
        <div v-if="!result && !loading" class="empty-answer">
          <span class="assistant-mark" aria-hidden="true">AI</span>
          <span class="soft-label">READY FOR YOUR QUESTION</span>
          <h2>{{ selectedCourse?.name || '请选择一门课程' }}</h2>
          <p>
            输入课程知识问题。每条可核查结论会使用 [1]、[2] 等编号关联下方原文证据。
          </p>
        </div>

        <div v-if="loading" class="loading-answer" role="status" aria-live="polite">
          <span class="thinking-orbit" aria-hidden="true" />
          <strong>正在检索课程资料并组织引用…</strong>
          <p>首次检索可能需要加载本地 Embedding 模型，请稍候。</p>
        </div>

        <article v-if="result" class="answer-result">
          <div class="question-bubble">{{ result.question }}</div>
          <div class="answer-heading">
            <div>
              <span class="soft-label">GROUNDED ANSWER</span>
              <h2>资料依据回答</h2>
            </div>
            <span
              class="answer-status"
              :class="{ refused: result.status === 'insufficient_evidence' }"
            >
              {{ result.status === 'answered' ? '证据已引用' : '资料不足' }}
            </span>
          </div>
          <div class="markdown-answer" v-html="answerHtml" />

          <section v-if="result.citations.length" class="citation-section">
            <div class="citation-title">
              <h3>引用资料</h3>
              <span>{{ result.citations.length }} 条已使用证据</span>
            </div>
            <details
              v-for="citation in result.citations"
              :key="`${citation.document_id}-${citation.chunk_index}`"
              class="citation-card"
            >
              <summary>
                <span class="citation-number">[{{ citation.source_id }}]</span>
                <span class="citation-summary">
                  <strong>{{ citation.file_name }}</strong>
                  <small>{{ formatCitationLocation(citation) }}</small>
                </span>
                <span class="citation-score">{{ (citation.score * 100).toFixed(1) }}%</span>
              </summary>
              <p>{{ citation.text }}</p>
              <small>检索排名 #{{ citation.retrieval_rank }} · Chunk {{ citation.chunk_index }}</small>
            </details>
          </section>

          <footer class="answer-meta">
            <span>{{ result.model || '未调用模型' }}</span>
            <span>检索 {{ result.retrieval.returned_count }} 条</span>
            <span>合格证据 {{ result.retrieval.eligible_evidence_count }} 条</span>
            <span>{{ (result.elapsed_ms / 1000).toFixed(2) }} s</span>
            <span v-if="result.usage">{{ result.usage.total_tokens }} tokens</span>
          </footer>
        </article>

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
            <button type="submit" class="primary-button" :disabled="!canSubmit">
              {{ loading ? '正在回答…' : '检索并回答' }}
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

.answer-result {
  flex: 1;
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

.markdown-answer {
  padding: 20px 0;
  font-size: 14px;
  line-height: 1.85;
  color: var(--ink);
}

.markdown-answer :deep(p:first-child) {
  margin-top: 0;
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
