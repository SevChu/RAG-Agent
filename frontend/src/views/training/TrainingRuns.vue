<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import * as api from '@/api/training'
import { toFriendlyApiError } from '@/api/client'
import type { TrainingRun } from '@/types/training'
import { runLabels, useRequestGate } from '@/utils/training'
const items = ref<TrainingRun[]>([]),
  offset = ref(0),
  error = ref(''),
  loading = ref(false),
  gate = useRequestGate()
let timer: ReturnType<typeof setTimeout> | undefined,
  alive = true
async function load(page = offset.value) {
  const ticket = gate.next()
  clearTimeout(timer)
  loading.value = true
  try {
    const rows = await api.runs(page)
    if (gate.current(ticket)) {
      items.value = rows
      offset.value = page
      error.value = ''
    }
  } catch (e) {
    if (gate.current(ticket)) error.value = toFriendlyApiError(e).message
  } finally {
    if (gate.current(ticket)) {
      loading.value = false
      if (alive) timer = setTimeout(() => void load(), 3000)
    }
  }
}
onMounted(() => void load())
onUnmounted(() => {
  alive = false
  clearTimeout(timer)
})
</script>
<template>
  <section class="training-card">
    <div class="training-section-title">
      <h2>模拟任务记录</h2>
      <RouterLink class="training-button primary" to="/training/new">创建模拟任务</RouterLink>
    </div>
    <p v-if="error" class="training-error" role="alert">{{ error }} 将尝试恢复连接。</p>
    <p v-if="!loading && !items.length && !error" class="training-empty">
      还没有任务。选择智能体和已审核数据，开始一次模拟运行。
    </p>
    <div v-if="items.length" class="training-table-wrap">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>状态</th>
            <th>进度</th>
            <th>目标</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <RouterLink :to="'/training/runs/' + item.id">{{ item.id.slice(0, 8) }}</RouterLink
              ><small v-if="item.retry_of"> · 重试任务</small>
            </td>
            <td>
              <span class="training-status" :class="item.status">{{ runLabels[item.status] }}</span>
            </td>
            <td>{{ item.completed_steps }} / {{ item.total_steps }}</td>
            <td>{{ item.source.request.target }}</td>
            <td>{{ new Date(item.created_at).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="training-actions">
      <button :disabled="loading || offset === 0" @click="load(offset - 20)">上一页</button
      ><button :disabled="loading || items.length < 20" @click="load(offset + 20)">下一页</button
      ><button :disabled="loading" @click="load()">刷新任务</button
      ><small v-if="loading" role="status">正在更新…</small>
    </div>
  </section>
</template>
