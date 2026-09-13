<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import * as api from '@/api/training'
import type { Adapter } from '@/types/training'
import { toFriendlyApiError } from '@/api/client'
import { useRequestGate } from '@/utils/training'
import TrainingSource from '@/components/TrainingSource.vue'
const route = useRoute(),
  item = ref<Adapter | null>(null),
  chain = ref<Adapter[]>([]),
  next = ref<string | null>(null),
  error = ref(''),
  busy = ref(false),
  gate = useRequestGate()
async function load() {
  const ticket = gate.next()
  error.value = ''
  try {
    const [result, history] = await Promise.all([
      api.adapter(String(route.params.adapterId)),
      api.lineage(String(route.params.adapterId)),
    ])
    if (gate.current(ticket)) {
      item.value = result
      chain.value = history.items
      next.value = history.next_predecessor_id
    }
  } catch (e) {
    if (gate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
watch(
  () => route.params.adapterId,
  () => {
    item.value = null
    chain.value = []
    next.value = null
    void load()
  },
  { immediate: true },
)
async function more() {
  if (!next.value || busy.value) return
  const ticket = gate.next()
  busy.value = true
  try {
    const result = await api.lineage(next.value)
    if (gate.current(ticket)) {
      chain.value.push(...result.items)
      next.value = result.next_predecessor_id
    }
  } catch (e) {
    if (gate.current(ticket)) error.value = toFriendlyApiError(e).message
  } finally {
    busy.value = false
  }
}
async function archive() {
  if (!item.value || busy.value) return
  const key = item.value.id,
    ticket = gate.next()
  busy.value = true
  try {
    await ElMessageBox.confirm(
      '归档后从默认列表隐藏，文件和来源历史仍保留。本周不提供取消归档。',
      '归档模拟产物',
      { confirmButtonText: '确认归档', cancelButtonText: '暂不归档' },
    )
    if (!gate.current(ticket)) return
    await api.archive(key)
    if (gate.current(ticket)) await load()
  } catch (e) {
    if (gate.current(ticket) && e !== 'cancel' && e !== 'close')
      error.value = toFriendlyApiError(e).message
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <RouterLink to="/training/adapters">← 返回模拟产物</RouterLink>
  <section class="training-card" style="margin-top: 16px">
    <div class="training-section-title">
      <h2>模拟产物详情</h2>
      <button :disabled="busy" @click="load">刷新完整性</button>
    </div>
    <p v-if="error" class="training-error" role="alert">{{ error }}</p>
    <p v-if="!item && !error" role="status">正在读取产物…</p>
    <template v-if="item"
      ><p class="training-note">
        模拟产物 · 不可部署 · 未评测。没有模型权重，不会改变智能体的实际模型。
      </p>
      <dl class="training-facts">
        <dt>产物 ID</dt>
        <dd>{{ item.id }}</dd>
        <dt>文件完整性</dt>
        <dd>
          <span
            class="training-status"
            :class="item.integrity === 'valid' ? 'approved' : 'invalid'"
            >{{
              { valid: '文件有效', missing: '文件缺失', invalid: '文件失效' }[item.integrity]
            }}</span
          >
        </dd>
        <dt>任务来源</dt>
        <dd>
          <RouterLink :to="'/training/runs/' + item.run_id">{{ item.run_id }}</RouterLink>
        </dd>
        <dt>登记状态</dt>
        <dd>{{ item.archived_at ? '已归档' : '已登记' }}</dd>
        <dt>Manifest SHA-256</dt>
        <dd>{{ item.manifest_sha256 }}</dd>
        <dt>模拟校验值</dt>
        <dd>{{ item.manifest.result.simulation_checksum }}</dd>
      </dl>
      <p v-if="item.integrity !== 'valid'" class="training-error">
        文件缺失或内容不匹配，产物已失效。历史记录仍保留，系统不会自动覆盖文件。
      </p>
      <div class="training-actions">
        <button v-if="!item.archived_at" :disabled="busy" @click="archive">归档产物</button>
      </div>
      <TrainingSource :source="item.manifest.source" />
      <h3>前驱来源链</h3>
      <p v-if="chain.length === 1 && !next" class="training-muted">
        本产物没有前驱。前驱关系只用于追踪，不代表部署或续训。
      </p>
      <ol>
        <li v-for="entry in chain" :key="entry.id">
          <RouterLink :to="'/training/adapters/' + entry.id">{{ entry.id }}</RouterLink> ·
          {{ entry.archived_at ? '已归档' : '已登记' }}
        </li>
      </ol>
      <button v-if="next" :disabled="busy" @click="more">继续查看前驱</button></template
    >
  </section>
</template>
