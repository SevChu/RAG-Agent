<script setup lang="ts">
import { ElAlert, ElMessage, ElMessageBox, ElOption, ElSelect } from 'element-plus'
import { storeToRefs } from 'pinia'
import { onMounted, ref } from 'vue'

import { toFriendlyApiError } from '@/api/client'
import { fetchTokenUsage, resetTokenUsage } from '@/api/qa'
import { useLLMStore } from '@/stores/llm'
import type { TokenUsageSummary } from '@/types/api'

const llmStore = useLLMStore()
const { configuration, selectedModel, loading } = storeToRefs(llmStore)
const errorMessage = ref('')
const tokenUsage = ref<TokenUsageSummary | null>(null)
const usageLoading = ref(false)
const resetting = ref(false)

const tokenFormatter = new Intl.NumberFormat('zh-CN')

function formatTokens(value: number | undefined): string {
  return tokenFormatter.format(value ?? 0)
}

async function loadUsage(): Promise<void> {
  usageLoading.value = true
  try {
    tokenUsage.value = await fetchTokenUsage()
  } finally {
    usageLoading.value = false
  }
}

async function handleReset(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '此操作只清零累计 token 统计，不会删除课程、资料或对话。清零后无法恢复。',
      '确认清零 token 统计？',
      {
        confirmButtonText: '确认清零',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  resetting.value = true
  errorMessage.value = ''
  try {
    tokenUsage.value = await resetTokenUsage()
    ElMessage.success('Token 统计已清零')
  } catch (error) {
    errorMessage.value = toFriendlyApiError(error).message
  } finally {
    resetting.value = false
  }
}

onMounted(async () => {
  try {
    await Promise.all([llmStore.loadConfiguration(), loadUsage()])
  } catch (error) {
    errorMessage.value = toFriendlyApiError(error).message
  }
})
</script>

<template>
  <section class="page-view">
    <header class="page-heading">
      <div>
        <div class="eyebrow"><span /> SETTINGS</div>
        <h1>设置</h1>
        <p>选择本次浏览器会话使用的生成模型。真实密钥不会在页面中展示。</p>
      </div>
    </header>

    <section class="settings-card">
      <div class="setting-icon" aria-hidden="true">AI</div>
      <div>
        <span class="soft-label">MODEL PROVIDER</span>
        <h2>{{ configuration?.provider || 'DeepSeek' }}</h2>
        <p>兼容 OpenAI API · {{ configuration?.base_url || '正在读取配置' }}</p>
      </div>
      <el-select
        v-model="selectedModel"
        :loading="loading"
        :disabled="!configuration"
        class="model-select"
        aria-label="默认生成模型"
      >
        <el-option
          v-for="model in configuration?.available_models ?? []"
          :key="model"
          :label="model"
          :value="model"
        />
      </el-select>
    </section>

    <section class="usage-card" :aria-busy="usageLoading">
      <div class="usage-heading">
        <div>
          <span class="soft-label">TOKEN USAGE</span>
          <h2>累计 Token 消耗</h2>
          <p>统计所有已返回 usage 的模型调用，包括生成、总结、出题、内部修复与外部搜索。</p>
        </div>
        <div class="usage-total">
          <span>全部模型</span>
          <strong>{{ formatTokens(tokenUsage?.total.total_tokens) }}</strong>
          <small>tokens</small>
        </div>
      </div>

      <div v-if="usageLoading && !tokenUsage" class="usage-empty">正在读取累计统计…</div>
      <div v-else class="model-usage-list">
        <article
          v-for="item in tokenUsage?.models ?? []"
          :key="item.model"
          class="model-usage-item"
        >
          <div class="model-usage-title">
            <div>
              <span class="model-dot" aria-hidden="true" />
              <strong>{{ item.model }}</strong>
            </div>
            <span v-if="item.model === selectedModel" class="active-model">当前选择</span>
          </div>

          <div class="usage-metrics">
            <div class="usage-metric input-metric">
              <span>输入 Token</span>
              <strong>{{ formatTokens(item.input_tokens) }}</strong>
              <div class="cache-breakdown">
                <span>缓存命中 <b>{{ formatTokens(item.input_cache_hit_tokens) }}</b></span>
                <span>缓存未命中 <b>{{ formatTokens(item.input_cache_miss_tokens) }}</b></span>
              </div>
            </div>
            <div class="usage-metric">
              <span>输出 Token</span>
              <strong>{{ formatTokens(item.output_tokens) }}</strong>
            </div>
            <div class="usage-metric total-metric">
              <span>合计</span>
              <strong>{{ formatTokens(item.total_tokens) }}</strong>
            </div>
          </div>
        </article>
      </div>

      <div class="usage-footer">
        <p>未返回 usage 的失败请求无法计入；旧版本产生的历史调用不会追溯补记。</p>
        <button
          type="button"
          class="reset-button"
          :disabled="resetting || usageLoading"
          @click="handleReset"
        >
          {{ resetting ? '清零中…' : 'Reset（清零）' }}
        </button>
      </div>
    </section>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      v-else
      title="模型切换已生效"
      :description="`课程学习助手的后续请求会使用 ${selectedModel || '后端默认模型'}；刷新页面后恢复后端默认值 ${configuration?.model || ''}。API Key 仍仅通过本地环境变量管理。`"
      type="success"
      :closable="false"
      show-icon
    />
  </section>
</template>

<style scoped>
.settings-card {
  display: grid;
  grid-template-columns: auto 1fr minmax(220px, 0.4fr);
  padding: 25px;
  align-items: center;
  gap: 18px;
  margin-bottom: 18px;
  background: rgb(255 255 255 / 80%);
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: var(--shadow-card);
}

.setting-icon {
  display: grid;
  width: 48px;
  height: 48px;
  font-size: 11px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(145deg, var(--primary), var(--violet));
  border-radius: 16px;
  place-items: center;
}

.settings-card h2 {
  margin: 6px 0 3px;
  color: var(--ink-strong);
}

.settings-card p {
  margin: 0;
  font-size: 12px;
  color: var(--ink-muted);
}

.model-select {
  width: 100%;
}

.usage-card {
  padding: 25px;
  margin-bottom: 18px;
  background: rgb(255 255 255 / 80%);
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: var(--shadow-card);
}

.usage-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line-soft);
}

.usage-heading h2 {
  margin: 6px 0 4px;
  color: var(--ink-strong);
}

.usage-heading p,
.usage-footer p {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ink-muted);
}

.usage-total {
  display: grid;
  min-width: 150px;
  text-align: right;
}

.usage-total span,
.usage-total small {
  font-size: 10px;
  font-weight: 700;
  color: var(--ink-muted);
}

.usage-total strong {
  margin: 2px 0;
  font-size: 28px;
  color: var(--ink-strong);
}

.model-usage-list {
  display: grid;
  gap: 12px;
  padding: 18px 0;
}

.model-usage-item {
  overflow: hidden;
  background: rgb(247 251 255 / 72%);
  border: 1px solid var(--line-soft);
  border-radius: 16px;
}

.model-usage-title {
  display: flex;
  padding: 13px 16px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--line-soft);
}

.model-usage-title > div {
  display: flex;
  align-items: center;
  gap: 9px;
}

.model-usage-title strong {
  font-size: 13px;
  color: var(--ink-strong);
}

.model-dot {
  width: 8px;
  height: 8px;
  background: linear-gradient(135deg, var(--primary), var(--violet));
  border-radius: 50%;
  box-shadow: 0 0 0 4px rgb(62 155 255 / 10%);
}

.active-model {
  padding: 4px 8px;
  font-size: 9px;
  font-weight: 800;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border-radius: 999px;
}

.usage-metrics {
  display: grid;
  grid-template-columns: 1.5fr 1fr 1fr;
}

.usage-metric {
  display: grid;
  min-height: 98px;
  padding: 16px;
  align-content: center;
  border-right: 1px solid var(--line-soft);
}

.usage-metric:last-child {
  border-right: 0;
}

.usage-metric > span {
  font-size: 10px;
  font-weight: 700;
  color: var(--ink-muted);
}

.usage-metric > strong {
  margin-top: 4px;
  font-size: 21px;
  color: var(--ink-strong);
}

.total-metric > strong {
  color: var(--primary-deep);
}

.cache-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 8px;
}

.cache-breakdown span {
  font-size: 10px;
  color: var(--ink-muted);
}

.cache-breakdown b {
  color: var(--ink);
}

.usage-empty {
  padding: 36px 0;
  font-size: 13px;
  text-align: center;
  color: var(--ink-muted);
}

.usage-footer {
  display: flex;
  padding-top: 18px;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  border-top: 1px solid var(--line-soft);
}

.reset-button {
  min-width: 118px;
  min-height: 38px;
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 750;
  color: var(--danger);
  cursor: pointer;
  background: rgb(255 255 255 / 82%);
  border: 1px solid rgb(233 79 112 / 24%);
  border-radius: 11px;
}

.reset-button:hover:not(:disabled) {
  color: #fff;
  background: var(--danger);
}

.reset-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

@media (max-width: 680px) {
  .settings-card {
    grid-template-columns: auto 1fr;
  }

  .model-select {
    grid-column: 1 / -1;
  }

  .usage-heading,
  .usage-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .usage-total {
    min-width: 0;
    text-align: left;
  }

  .usage-metrics {
    grid-template-columns: 1fr;
  }

  .usage-metric {
    min-height: 0;
    border-right: 0;
    border-bottom: 1px solid var(--line-soft);
  }

  .usage-metric:last-child {
    border-bottom: 0;
  }
}
</style>
