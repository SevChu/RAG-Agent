<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useEditionStore } from '@/stores/edition'
import { toFriendlyApiError } from '@/api/client'
import '@/assets/training.css'
const edition = useEditionStore()
const loading = ref(true)
const error = ref('')
async function check() {
  loading.value = true
  error.value = ''
  try {
    await edition.load(true)
  } catch (e) {
    error.value = toFriendlyApiError(e).message
  } finally {
    loading.value = false
  }
}
onMounted(check)
</script>
<template>
  <main class="training-shell">
    <header class="training-heading">
      <div>
        <p class="training-kicker">RESEARCH / 科研工作区</p>
        <h1>微调实验室 <span class="training-badge">模拟模式</span></h1>
        <p>整理数据、运行模拟任务，追溯每一份产物。</p>
      </div>
    </header>
    <p v-if="loading" role="status">正在确认工作区能力…</p>
    <section v-else-if="error" class="training-card">
      <p role="alert">{{ error }}</p>
      <button @click="check">重新连接</button>
    </section>
    <section v-else-if="edition.edition !== 'research'" class="training-card">
      <h2>此功能仅在科研版提供</h2>
      <p>当前工作区不提供训练数据、模拟任务或 Adapter 管理。</p>
      <RouterLink to="/agents">返回智能体管理</RouterLink>
    </section>
    <template v-else
      ><nav class="training-tabs" aria-label="微调工作区">
        <RouterLink to="/training/datasets">训练数据</RouterLink
        ><RouterLink to="/training/new">创建模拟任务</RouterLink
        ><RouterLink to="/training/runs">任务记录</RouterLink
        ><RouterLink to="/training/adapters">模拟产物</RouterLink>
      </nav>
      <RouterView
    /></template>
  </main>
</template>
