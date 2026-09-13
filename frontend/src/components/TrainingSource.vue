<script setup lang="ts">
import type { TrainingSource as Source } from '@/types/training'
import { parameterFields } from '@/utils/training'
defineProps<{ source: Source }>()
</script>
<template>
  <section class="training-source">
    <h3>冻结来源</h3>
    <dl class="training-facts">
      <dt>智能体</dt>
      <dd>
        <RouterLink :to="{ path: '/agents', query: { agent: source.request.agent_profile_id } }">{{
          source.request.agent_profile_id
        }}</RouterLink>
      </dd>
      <dt>智能体版本</dt>
      <dd>{{ source.agent_revision_id }}</dd>
      <dt>数据版本</dt>
      <dd>{{ source.request.dataset_revision_id }}</dd>
      <dt>目标 / 模拟基础模型</dt>
      <dd>
        {{ source.request.target }} / {{ source.request.base_model }} ·
        {{ source.request.base_model_revision }}
      </dd>
      <dt>训练 / 验证样本</dt>
      <dd>{{ source.splits.train?.count ?? 0 }} / {{ source.splits.validation?.count ?? 0 }}</dd>
      <dt>审核序号</dt>
      <dd>{{ source.dataset_review_sequence }}</dd>
      <dt>方式 / 模拟步数</dt>
      <dd>
        {{ source.request.parameters.method.toUpperCase() }} / {{ source.request.simulation_steps }}
      </dd>
      <template v-for="field in parameterFields" :key="field.key"
        ><dt>{{ field.label }}</dt>
        <dd>{{ source.request.parameters[field.key] }}</dd></template
      >
    </dl>
    <details>
      <summary>查看来源哈希与运行标识</summary>
      <dl class="training-facts">
        <dt>配置 SHA-256</dt>
        <dd>{{ source.agent_config_sha256 }}</dd>
        <dt>Manifest SHA-256</dt>
        <dd>{{ source.manifest_sha256 }}</dd>
        <dt>内容 SHA-256</dt>
        <dd>{{ source.content_sha256 }}</dd>
        <dt>代码 SHA-256</dt>
        <dd>{{ source.code_sha256 }}</dd>
        <dt>Python</dt>
        <dd>{{ source.python_version }}</dd>
      </dl>
    </details>
  </section>
</template>
