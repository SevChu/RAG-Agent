<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand">
        <span class="brand-mark">CS</span>
        <div>
          <p class="brand-title">课程学习 Agent</p>
          <p class="brand-caption">基于课程资料的智能学习工作台</p>
        </div>
      </div>
      <span class="stage-badge">工程骨架</span>
    </header>

    <main class="app-content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 72px;
  padding: 0 32px;
  color: #f8fafc;
  background: #14213d;
  box-shadow: 0 8px 24px rgb(15 23 42 / 12%);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  font-weight: 800;
  color: #14213d;
  background: #fca311;
  border-radius: 12px;
}

.brand-title,
.brand-caption {
  margin: 0;
}

.brand-title {
  font-size: 17px;
  font-weight: 700;
}

.brand-caption {
  margin-top: 2px;
  font-size: 12px;
  color: #cbd5e1;
}

.stage-badge {
  padding: 6px 12px;
  font-size: 12px;
  color: #fde68a;
  background: rgb(252 163 17 / 14%);
  border: 1px solid rgb(252 163 17 / 35%);
  border-radius: 999px;
}

.app-content {
  width: min(1120px, calc(100% - 40px));
  margin: 0 auto;
  padding: 56px 0;
}

@media (max-width: 640px) {
  .app-header {
    padding: 0 20px;
  }

  .brand-caption {
    display: none;
  }

  .app-content {
    width: min(100% - 28px, 1120px);
    padding: 32px 0;
  }
}
</style>
