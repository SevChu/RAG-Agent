<script setup lang="ts">
import { ElAlert, ElOption, ElSelect } from 'element-plus'
</script>

<template>
  <section class="page-view">
    <header class="page-heading">
      <div>
        <div class="eyebrow"><span /> SETTINGS</div>
        <h1>设置</h1>
        <p>管理模型偏好和本地学习空间配置。真实密钥不会在页面中展示。</p>
      </div>
    </header>

    <section class="settings-card">
      <div class="setting-icon" aria-hidden="true">AI</div>
      <div>
        <span class="soft-label">MODEL PROVIDER</span>
        <h2>DeepSeek</h2>
        <p>兼容 OpenAI API · https://api.deepseek.com</p>
      </div>
      <el-select model-value="deepseek-v4-flash" disabled class="model-select">
        <el-option label="deepseek-v4-flash" value="deepseek-v4-flash" />
        <el-option label="deepseek-v4-pro" value="deepseek-v4-pro" />
      </el-select>
    </section>

    <el-alert
      title="模型切换将在模型调用阶段接入"
      description="第四日只保留配置入口；API Key 仍仅通过本地环境变量管理。"
      type="info"
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
