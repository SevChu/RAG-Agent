<script setup lang="ts">
import { ElAlert, ElMessage, ElMessageBox, ElOption, ElOptionGroup, ElSelect } from 'element-plus'
import { storeToRefs } from 'pinia'
import { onMounted, ref } from 'vue'

import { toFriendlyApiError } from '@/api/client'
import { fetchTokenUsage, resetTokenUsage } from '@/api/qa'
import { useLLMStore } from '@/stores/llm'
import type { TokenUsageSummary } from '@/types/api'

const llmStore = useLLMStore()
const { configuration, selectedModel, selectedProvider, selectedModelConfigured, loading } =
  storeToRefs(llmStore)
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
      '此操作只清零累计 token 统计，不会删除资料空间、资料或对话。清零后无法恢复。',
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
        <span class="soft-label">CURRENT PROVIDER</span>
        <h2>{{ selectedProvider?.name || '正在读取供应商' }}</h2>
        <p>兼容 OpenAI API · {{ selectedProvider?.base_url || '正在读取配置' }}</p>
      </div>
      <el-select
        v-model="selectedModel"
        :loading="loading"
        :disabled="!configuration"
        class="model-select"
        aria-label="默认生成模型"
      >
        <el-option-group
          v-for="provider in configuration?.providers.filter((item) => item.models.length) ?? []"
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
    </section>

    <section class="provider-grid" aria-label="模型供应商接口状态">
      <article
        v-for="provider in configuration?.providers ?? []"
        :key="provider.id"
        class="provider-card"
        :class="{ ready: provider.configured }"
      >
        <div class="provider-heading">
          <div class="provider-mark">{{ provider.name.slice(0, 2).toUpperCase() }}</div>
          <div>
            <span>OPENAI COMPATIBLE</span>
            <h3>{{ provider.name }}</h3>
          </div>
          <span class="provider-status">{{ provider.configured ? '已配置' : '待配置' }}</span>
        </div>
        <p class="provider-url">{{ provider.base_url }}</p>
        <p v-if="provider.models.length" class="provider-models">
          {{ provider.models.join(' · ') }}
        </p>
        <p v-else class="provider-models muted">尚未指定模型</p>
        <small>{{ provider.api_key_env }} + {{ provider.models_env }}</small>
      </article>
    </section>

    <section class="usage-card" :aria-busy="usageLoading">
      <div class="usage-heading">
        <div>
          <span class="soft-label">TOKEN USAGE</span>
          <h2>累计 Token 消耗</h2>
          <p>统计所有已返回 usage 的模型调用，包括回答、总结、内容生成、内部修复与外部搜索。</p>
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
                <span
                  >缓存命中 <b>{{ formatTokens(item.input_cache_hit_tokens) }}</b></span
                >
                <span
                  >缓存未命中 <b>{{ formatTokens(item.input_cache_miss_tokens) }}</b></span
                >
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

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
    <el-alert
      v-else-if="selectedProvider && !selectedModelConfigured"
      :title="`${selectedProvider.name} 接口待配置`"
      :description="`请在项目根目录 .env 中填写 ${selectedProvider.api_key_env} 和 ${selectedProvider.models_env}，然后重启后端。密钥不会返回前端。`"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-alert
      v-else
      title="模型切换已生效"
      :description="`智能体对话的后续请求会使用 ${selectedModel || '后端默认模型'}；刷新页面后恢复后端默认值 ${configuration?.model || ''}。API Key 仍仅通过本地环境变量管理。`"
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
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  box-shadow: var(--shadow-card);
}

.setting-icon {
  display: grid;
  width: 48px;
  height: 48px;
  font-size: 11px;
  font-weight: 600;
  color: var(--on-primary);
  background: var(--primary);
  border-radius: var(--radius-base);
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

.provider-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.provider-card {
  min-width: 0;
  padding: 17px;
  background: var(--surface);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-base);
}

.provider-card.ready {
  background: var(--surface-soft);
  border-color: var(--line);
}

.provider-heading {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 10px;
}

.provider-mark {
  display: grid;
  width: 34px;
  height: 34px;
  font-size: 9px;
  font-weight: 600;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border-radius: var(--radius-base);
  place-items: center;
}

.provider-heading span,
.provider-card small {
  font-size: 8px;
  font-weight: 600;
  color: var(--ink-muted);
}

.provider-heading h3 {
  margin: 2px 0 0;
  font-size: 14px;
  color: var(--ink-strong);
}

.provider-status {
  padding: 4px 7px;
  color: var(--ink-muted);
  background: var(--surface-soft);
  border-radius: var(--radius-base);
}

.provider-card.ready .provider-status {
  color: var(--success);
  background: var(--success-soft);
}

.provider-url,
.provider-models {
  overflow: hidden;
  margin: 12px 0 0;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-muted);
}

.provider-models {
  margin: 6px 0 10px;
  color: var(--ink);
}

.provider-models.muted {
  color: var(--ink-muted);
}

.usage-card {
  padding: 25px;
  margin-bottom: 18px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
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
  font-weight: 600;
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
  background: var(--surface-soft);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-base);
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
  background: var(--primary);
  border-radius: 50%;
  box-shadow: 0 0 0 4px var(--focus-ring);
}

.active-model {
  padding: 4px 8px;
  font-size: 9px;
  font-weight: 600;
  color: var(--primary-deep);
  background: var(--primary-soft);
  border-radius: var(--radius-base);
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
  font-weight: 600;
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
  font-weight: 600;
  color: var(--danger);
  cursor: pointer;
  background: var(--surface);
  border: 1px solid var(--danger-line);
  border-radius: var(--radius-base);
}

.reset-button:hover:not(:disabled) {
  color: var(--on-primary);
  background: var(--danger);
}

.reset-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

@media (max-width: 980px) {
  .provider-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .settings-card {
    grid-template-columns: auto 1fr;
  }

  .model-select {
    grid-column: 1 / -1;
  }

  .provider-grid {
    grid-template-columns: 1fr;
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
