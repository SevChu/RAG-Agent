<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as api from '@/api/training'
import { toFriendlyApiError } from '@/api/client'
import type { TrainingEvent, TrainingRun } from '@/types/training'
import { eventLabel, runLabels, terminal, useRequestGate } from '@/utils/training'
import TrainingSource from '@/components/TrainingSource.vue'
const route = useRoute(),
  router = useRouter(),
  item = ref<TrainingRun | null>(null),
  events = ref<TrainingEvent[]>([]),
  error = ref(''),
  busy = ref(false),
  loading = ref(false),
  gate = useRequestGate(),
  actionGate = useRequestGate()
let timer: ReturnType<typeof setTimeout> | undefined,
  alive = true,
  retryKey = crypto.randomUUID()
async function load() {
  const key = String(route.params.runId),
    ticket = gate.next()
  clearTimeout(timer)
  loading.value = true
  try {
    const run = await api.run(key)
    const rows = await api.events(key, events.value[events.value.length - 1]?.sequence ?? 0)
    if (!gate.current(ticket)) return
    item.value = run
    events.value.push(...rows)
    error.value = ''
    if (rows.length === 100) {
      const tail = await api.events(key, events.value[events.value.length - 1]?.sequence ?? 0)
      if (gate.current(ticket)) events.value.push(...tail)
    }
  } catch (e) {
    if (gate.current(ticket)) error.value = toFriendlyApiError(e).message
  } finally {
    if (gate.current(ticket)) {
      loading.value = false
      if (alive && (!item.value || !terminal(item.value.status) || error.value))
        timer = setTimeout(() => void load(), 900)
    }
  }
}
watch(
  () => route.params.runId,
  () => {
    gate.next()
    actionGate.next()
    clearTimeout(timer)
    item.value = null
    events.value = []
    error.value = ''
    retryKey = crypto.randomUUID()
    void load()
  },
  { immediate: true },
)
onUnmounted(() => {
  alive = false
  clearTimeout(timer)
})
async function action(kind: 'cancel' | 'retry' | 'adapter') {
  if (busy.value || !item.value) return
  busy.value = true
  error.value = ''
  const key = item.value.id,
    ticket = actionGate.next()
  try {
    if (kind === 'cancel') {
      await api.cancel(key)
      if (alive && String(route.params.runId) === key) await load()
    } else if (kind === 'retry') {
      const result = await api.retry(key, retryKey)
      if (alive && String(route.params.runId) === key)
        await router.push('/training/runs/' + result.id)
    } else {
      const adapter = await api.fromRun(key)
      if (alive && String(route.params.runId) === key)
        await router.push('/training/adapters/' + adapter.id)
    }
  } catch (e) {
    if (actionGate.current(ticket)) error.value = toFriendlyApiError(e).message
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <RouterLink to="/training/runs">← 返回任务记录</RouterLink>
  <section class="training-card" style="margin-top: 16px">
    <div class="training-section-title">
      <h2>模拟任务详情</h2>
      <button :disabled="loading || busy" @click="load">刷新详情</button>
    </div>
    <p v-if="error" class="training-error" role="alert">{{ error }}</p>
    <p v-if="!item" role="status">
      {{ loading ? '正在读取任务…' : '暂时无法读取任务，可重试连接。' }}
    </p>
    <template v-if="item"
      ><p class="training-muted">任务 {{ item.id }}</p>
      <span class="training-status" :class="item.status" role="status">{{
        runLabels[item.status]
      }}</span>
      <div class="training-metric">
        {{ item.completed_steps }} <small>/ {{ item.total_steps }} 步</small>
      </div>
      <progress :value="item.completed_steps" :max="item.total_steps" aria-label="模拟进度" />
      <p>{{ eventLabel(item.last_code) }}</p>
      <p v-if="item.status === 'queued'" class="training-note">
        等待后台领取。未启用模拟后台时会持续排队；本页不会开启后台。
      </p>
      <p v-if="item.status === 'succeeded'" class="training-note">
        模拟运行完成。产物没有模型权重，不能用于回答或检索，尚未评测模型质量。
      </p>
      <p v-if="item.status === 'interrupted'" class="training-note">
        任务已中断，不会从旧进度自动续训。重试会新建任务并保留本次记录。
      </p>
      <p v-if="item.retry_of">
        重试来源：<RouterLink :to="'/training/runs/' + item.retry_of">{{
          item.retry_of
        }}</RouterLink>
      </p>
      <div class="training-actions">
        <button
          v-if="['queued', 'running'].includes(item.status)"
          :disabled="busy"
          @click="action('cancel')"
        >
          取消模拟任务</button
        ><button
          v-if="['failed', 'cancelled', 'interrupted'].includes(item.status)"
          class="primary"
          :disabled="busy"
          @click="action('retry')"
        >
          重试为新任务</button
        ><button
          v-if="item.status === 'succeeded'"
          class="primary"
          :disabled="busy"
          @click="action('adapter')"
        >
          查看模拟产物</button
        ><small v-if="busy">正在处理…</small>
      </div>
      <h3>进度与事件</h3>
      <div class="training-table-wrap">
        <table>
          <thead>
            <tr>
              <th>序号</th>
              <th>阶段</th>
              <th>进度</th>
              <th>事件</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="event in events" :key="event.sequence">
              <td>{{ event.sequence }}</td>
              <td>{{ runLabels[event.phase] }}</td>
              <td>{{ event.completed_steps }} / {{ event.total_steps }}</td>
              <td>{{ eventLabel(event.code) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <details>
        <summary>查看任务来源与参数</summary>
        <TrainingSource :source="item.source" />
        <p class="training-muted">
          任务快照 SHA-256：<code>{{ item.snapshot_sha256 }}</code>
        </p>
      </details></template
    >
  </section>
</template>
