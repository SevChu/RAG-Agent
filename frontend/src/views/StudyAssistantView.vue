<script setup lang="ts">
import { ElAlert, ElOption, ElSelect } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { toFriendlyApiError } from '@/api/client'
import { useCoursesStore } from '@/stores/courses'

const store = useCoursesStore()
const selectedCourseId = ref('')
const errorMessage = ref('')

const selectedCourse = computed(() =>
  store.courses.find((course) => course.id === selectedCourseId.value),
)

onMounted(async () => {
  try {
    await store.loadCourses(false)
    selectedCourseId.value = store.courses[0]?.id ?? ''
  } catch (error) {
    errorMessage.value = toFriendlyApiError(error).message
  }
})
</script>

<template>
  <section class="page-view">
    <header class="page-heading">
      <div>
        <div class="eyebrow"><span /> STUDY ASSISTANT</div>
        <h1>课程学习助手</h1>
        <p>进入指定课程的长期学习上下文，持续使用课程资料和既有学习轨迹。</p>
      </div>
      <span class="context-pill">课程长期上下文</span>
    </header>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <div class="assistant-layout">
      <section class="assistant-selection">
        <span class="soft-label">SELECT CONTEXT</span>
        <h2>选择课程上下文</h2>
        <p>学习助手后续会读取所选课程的资料、历史对话与学习状态。</p>
        <label for="assistant-course">课程</label>
        <el-select
          id="assistant-course"
          v-model="selectedCourseId"
          placeholder="请选择课程"
          size="large"
          class="course-select"
        >
          <el-option
            v-for="course in store.courses"
            :key="course.id"
            :label="course.name"
            :value="course.id"
          />
        </el-select>
      </section>

      <section class="memory-preview">
        <span class="memory-light" aria-hidden="true" />
        <div class="memory-icon" aria-hidden="true">AI</div>
        <span class="soft-label">LONG-TERM MEMORY</span>
        <h2>{{ selectedCourse?.name || '尚未选择课程' }}</h2>
        <p v-if="selectedCourse">
          已选择课程空间。模型接入后，将在回答中继承这门课程的资料和学习上下文。
        </p>
        <p v-else>先在课程空间中创建课程，再从这里开始长期学习对话。</p>
        <button type="button" class="primary-button" disabled>开始课程学习对话</button>
        <small>对话能力将在后续 RAG 阶段接入</small>
      </section>
    </div>
  </section>
</template>

<style scoped>
.assistant-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(300px, 1.1fr);
  gap: 20px;
}

.assistant-selection,
.memory-preview {
  min-height: 390px;
  padding: 30px;
  background: rgb(255 255 255 / 78%);
  border: 1px solid var(--line);
  border-radius: 24px;
  box-shadow: var(--shadow-card);
}

.assistant-selection {
  display: flex;
  flex-direction: column;
}

.assistant-selection h2,
.memory-preview h2 {
  margin: 12px 0 8px;
  color: var(--ink-strong);
}

.assistant-selection p,
.memory-preview p {
  margin: 0;
  line-height: 1.75;
  color: var(--ink-muted);
}

.assistant-selection label {
  margin: auto 0 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--ink);
}

.course-select {
  width: 100%;
}

.memory-preview {
  position: relative;
  display: grid;
  overflow: hidden;
  text-align: center;
  place-items: center;
  align-content: center;
  background:
    radial-gradient(circle at 50% 25%, rgb(79 191 255 / 16%), transparent 30%),
    linear-gradient(145deg, rgb(255 255 255 / 84%), rgb(244 241 255 / 74%));
}

.memory-light {
  position: absolute;
  top: -80px;
  width: 220px;
  height: 220px;
  pointer-events: none;
  background: radial-gradient(circle, rgb(113 92 255 / 13%), transparent 65%);
}

.memory-icon {
  display: grid;
  width: 68px;
  height: 68px;
  margin-bottom: 18px;
  font-size: 16px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(145deg, var(--primary), var(--violet));
  border-radius: 23px;
  box-shadow: 0 18px 40px rgb(75 121 255 / 24%);
  place-items: center;
}

.memory-preview .primary-button {
  margin-top: 25px;
}

.memory-preview small {
  margin-top: 10px;
  color: var(--ink-faint);
}

@media (max-width: 780px) {
  .assistant-layout {
    grid-template-columns: 1fr;
  }

  .assistant-selection,
  .memory-preview {
    min-height: 320px;
  }
}
</style>
