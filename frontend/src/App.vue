<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterView } from 'vue-router'

import AppSidebar from '@/components/AppSidebar.vue'

const SIDEBAR_STORAGE_KEY = 'agentic.sidebar-collapsed'
const sidebarCollapsed = ref(false)
const mobileSidebarOpen = ref(false)

onMounted(() => {
  sidebarCollapsed.value = window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true'
})

function updateSidebarCollapsed(value: boolean): void {
  sidebarCollapsed.value = value
  window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(value))
}
</script>

<template>
  <div class="app-layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <AppSidebar
      :collapsed="sidebarCollapsed"
      :mobile-open="mobileSidebarOpen"
      @update:collapsed="updateSidebarCollapsed"
      @update:mobile-open="mobileSidebarOpen = $event"
    />

    <section class="workspace">
      <header class="mobile-header">
        <button
          type="button"
          class="mobile-menu-button"
          aria-label="打开侧边栏"
          @click="mobileSidebarOpen = true"
        >
          ☰
        </button>
        <span>Agentic</span>
        <span class="online-dot" aria-label="本地服务模式" />
      </header>
      <main class="workspace-content">
        <RouterView />
      </main>
    </section>
  </div>
</template>

<style scoped>
.app-layout {
  min-height: 100vh;
}

.workspace {
  min-height: 100vh;
  margin-left: var(--sidebar-width);
  transition: margin-left 180ms ease;
}

.sidebar-collapsed .workspace {
  margin-left: var(--sidebar-collapsed-width);
}

.workspace-content {
  width: min(1180px, calc(100% - 64px));
  margin: 0 auto;
  padding: 38px 0 64px;
}

.mobile-header {
  display: none;
}

@media (max-width: 820px) {
  .workspace,
  .sidebar-collapsed .workspace {
    margin-left: 0;
  }

  .mobile-header {
    position: sticky;
    z-index: 10;
    top: 0;
    display: flex;
    min-height: 58px;
    padding: 0 18px;
    align-items: center;
    justify-content: space-between;
    font-size: 14px;
    font-weight: 600;
    color: var(--ink-strong);
    background: var(--surface-soft);
    border-bottom: 1px solid var(--line);
  }

  .mobile-menu-button {
    width: 38px;
    height: 38px;
    color: var(--primary-deep);
    cursor: pointer;
    background: var(--primary-soft);
    border: 0;
    border-radius: var(--radius-base);
  }

  .online-dot {
    width: 8px;
    height: 8px;
    background: var(--success);
    border-radius: 50%;
    box-shadow: 0 0 0 5px var(--success-soft);
  }

  .workspace-content {
    width: min(100% - 30px, 1180px);
    padding: 24px 0 46px;
  }
}
</style>
