<script setup lang="ts">
import { ElAlert, ElOption, ElSelect } from 'element-plus'
import { storeToRefs } from 'pinia'
import { onMounted, ref } from 'vue'

import { toFriendlyApiError } from '@/api/client'
import { useLLMStore } from '@/stores/llm'

const llmStore = useLLMStore()
const { configuration, selectedModel, loading } = storeToRefs(llmStore)
const errorMessage = ref('')

onMounted(async () => {
  try {
    await llmStore.loadConfiguration()
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

@media (max-width: 680px) {
  .settings-card {
    grid-template-columns: auto 1fr;
  }

  .model-select {
    grid-column: 1 / -1;
  }
}
</style>
