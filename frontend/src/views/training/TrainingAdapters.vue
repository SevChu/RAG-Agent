<script setup lang="ts">
import { onMounted, ref } from 'vue'
import * as api from '@/api/training'
import type { Adapter } from '@/types/training'
import { toFriendlyApiError } from '@/api/client'
import { useRequestGate } from '@/utils/training'
const items = ref<Adapter[]>([]),
  offset = ref(0),
  archived = ref(false),
  error = ref(''),
  loading = ref(false),
  gate = useRequestGate()
async function load(page = offset.value) {
  const ticket = gate.next()
  loading.value = true
  error.value = ''
  try {
    const rows = await api.adapters(page, archived.value)
    if (gate.current(ticket)) {
      items.value = rows
      offset.value = page
    }
  } catch (e) {
    if (gate.current(ticket)) error.value = toFriendlyApiError(e).message
  } finally {
    if (gate.current(ticket)) loading.value = false
  }
}
onMounted(() => void load())
</script>
<template>
  <section class="training-card">
    <div class="training-section-title">
      <h2>模拟产物</h2>
      <span class="training-badge">全部不可部署</span>
    </div>
    <p class="training-muted">
      每一份产物都保留任务、参数与数据版本。这里展示模拟 manifest，不是模型权重。
    </p>
    <label class="check-label"
      ><input v-model="archived" type="checkbox" @change="load(0)" />包含已归档产物</label
    >
    <p v-if="error" class="training-error" role="alert">{{ error }}</p>
    <p v-if="!loading && !items.length && !error" class="training-empty">
      暂无模拟产物。完成一次模拟任务后会自动登记。
    </p>
    <div v-if="items.length" class="training-table-wrap">
      <table>
        <thead>
          <tr>
            <th>产物</th>
            <th>目标 / 基础模型</th>
            <th>完整性</th>
            <th>状态</th>
            <th>登记时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <RouterLink :to="'/training/adapters/' + item.id">{{
                item.id.slice(0, 8)
              }}</RouterLink>
            </td>
            <td>
              {{ item.manifest.source.request.target }}<br /><small>{{
                item.manifest.source.request.base_model
              }}</small>
            </td>
            <td>
              <span
                class="training-status"
                :class="item.integrity === 'valid' ? 'approved' : 'invalid'"
                >{{
                  { valid: '文件有效', missing: '文件缺失', invalid: '文件失效' }[item.integrity]
                }}</span
              >
            </td>
            <td>{{ item.archived_at ? '已归档' : '已登记' }} · 未评测</td>
            <td>{{ new Date(item.created_at).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="training-actions">
      <button :disabled="loading || offset === 0" @click="load(offset - 20)">上一页</button
      ><button :disabled="loading || items.length < 20" @click="load(offset + 20)">下一页</button
      ><button :disabled="loading" @click="load()">刷新产物</button
      ><small v-if="loading" role="status">正在读取…</small>
    </div>
  </section>
</template>
