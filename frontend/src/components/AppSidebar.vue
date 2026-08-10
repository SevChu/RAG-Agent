<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { toFriendlyApiError } from '@/api/client'
import { useConversationsStore } from '@/stores/conversations'

defineProps<{
  collapsed: boolean
  mobileOpen: boolean
}>()

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
  'update:mobileOpen': [value: boolean]
}>()

const route = useRoute()
const router = useRouter()
const conversationsStore = useConversationsStore()
const quickHistoryExpanded = ref(true)
const assistantHistoryExpanded = ref(true)

const isCourses = computed(() => route.path.startsWith('/courses'))
const isQuickChat = computed(() => route.path.startsWith('/chat'))
const isAssistant = computed(() => route.path.startsWith('/assistant'))
const isSettings = computed(() => route.path.startsWith('/settings'))

onMounted(async () => {
  try {
    await Promise.all([
      conversationsStore.loadCourseConversations(),
      conversationsStore.loadQuickConversations(),
    ])
  } catch (error) {
    ElMessage.error(toFriendlyApiError(error).message)
  }
})

function closeMobile(): void {
  emit('update:mobileOpen', false)
}

async function deleteQuickConversation(conversationId: string): Promise<void> {
  try {
    await ElMessageBox.confirm('删除后将移除该快速对话的全部消息。', '删除对话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'danger-confirm-button',
    })
    await conversationsStore.deleteQuickConversation(conversationId)
    if (route.params.conversationId === conversationId && isQuickChat.value) {
      await router.push('/chat/new')
    }
    ElMessage.success('快速对话已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(toFriendlyApiError(error).message)
    }
  }
}

async function deleteConversation(courseId: string, conversationId: string): Promise<void> {
  try {
    await ElMessageBox.confirm('删除后将同时移除该课程对话的全部消息与引用记录。', '删除对话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'danger-confirm-button',
    })
    await conversationsStore.deleteCourseConversation(courseId, conversationId)
    if (route.params.conversationId === conversationId) {
      await router.push('/assistant')
    }
    ElMessage.success('课程对话已删除')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(toFriendlyApiError(error).message)
    }
  }
}
</script>

<template>
  <div
    class="sidebar-backdrop"
    :class="{ visible: mobileOpen }"
    aria-hidden="true"
    @click="closeMobile"
  />
  <aside
    class="app-sidebar"
    :class="{ collapsed, 'mobile-open': mobileOpen }"
    aria-label="应用侧边栏"
  >
    <div class="brand-row">
      <span class="brand-orbit" aria-hidden="true">
        <span>CM</span>
      </span>
      <div v-show="!collapsed" class="brand-copy">
        <strong>CourseMind</strong>
        <small>智能课程学习空间</small>
      </div>
      <button
        v-if="!collapsed"
        type="button"
        class="icon-button collapse-button"
        aria-label="收起侧边栏"
        @click="emit('update:collapsed', true)"
      >
        ‹
      </button>
      <button
        type="button"
        class="icon-button mobile-close-button"
        aria-label="关闭侧边栏"
        @click="closeMobile"
      >
        ×
      </button>
    </div>

    <RouterLink
      to="/chat/new"
      class="sidebar-link create-chat"
      :class="{ active: isQuickChat }"
      @click="closeMobile"
    >
      <span class="nav-icon" aria-hidden="true">＋</span>
      <span v-show="!collapsed">新建快速对话</span>
    </RouterLink>

    <nav class="primary-navigation" aria-label="主要功能">
      <RouterLink
        to="/assistant"
        class="sidebar-link"
        :class="{ active: isAssistant }"
        @click="closeMobile"
      >
        <span class="nav-icon nav-icon-ai" aria-hidden="true">AI</span>
        <span v-show="!collapsed">课程学习助手</span>
      </RouterLink>
      <RouterLink
        to="/courses"
        class="sidebar-link"
        :class="{ active: isCourses }"
        @click="closeMobile"
      >
        <span class="nav-icon" aria-hidden="true">▦</span>
        <span v-show="!collapsed">课程空间</span>
      </RouterLink>
    </nav>

    <div v-show="!collapsed || mobileOpen" class="sidebar-history-scroll">
      <section class="history-section" aria-labelledby="quick-history-heading">
        <button
          type="button"
          class="history-heading"
          :aria-expanded="quickHistoryExpanded"
          aria-controls="quick-history-list"
          @click="quickHistoryExpanded = !quickHistoryExpanded"
        >
          <span id="quick-history-heading">最近对话</span>
          <span aria-hidden="true">{{ quickHistoryExpanded ? '⌄' : '›' }}</span>
        </button>
        <div v-show="quickHistoryExpanded" id="quick-history-list" class="history-list">
          <p v-if="!conversationsStore.quickConversations.length" class="history-empty">
            暂无临时对话
          </p>
          <div
            v-for="conversation in conversationsStore.quickConversations"
            :key="conversation.id"
            class="history-item"
            :class="{
              active: isQuickChat && route.params.conversationId === conversation.id,
            }"
          >
            <RouterLink
              :to="`/chat/${conversation.id}`"
              :title="conversation.title"
              @click="closeMobile"
            >
              <strong>{{ conversation.title }}</strong>
              <small>快速对话</small>
            </RouterLink>
            <button
              type="button"
              aria-label="删除快速对话"
              title="删除对话"
              @click="deleteQuickConversation(conversation.id)"
            >
              ×
            </button>
          </div>
        </div>
      </section>

      <section class="history-section" aria-labelledby="assistant-history-heading">
        <button
          type="button"
          class="history-heading"
          :aria-expanded="assistantHistoryExpanded"
          aria-controls="assistant-history-list"
          @click="assistantHistoryExpanded = !assistantHistoryExpanded"
        >
          <span id="assistant-history-heading">学习助手对话</span>
          <span aria-hidden="true">{{ assistantHistoryExpanded ? '⌄' : '›' }}</span>
        </button>
        <div v-show="assistantHistoryExpanded" id="assistant-history-list" class="history-list">
          <p v-if="!conversationsStore.courseConversations.length" class="history-empty">
            暂无课程对话
          </p>
          <div
            v-for="conversation in conversationsStore.courseConversations"
            :key="conversation.id"
            class="history-item"
            :class="{ active: route.params.conversationId === conversation.id }"
          >
            <RouterLink
              :to="`/assistant/${conversation.id}`"
              :title="`${conversation.course_name} · ${conversation.title}`"
              @click="closeMobile"
            >
              <strong>{{ conversation.title }}</strong>
              <small>{{ conversation.course_name }}</small>
            </RouterLink>
            <button
              type="button"
              aria-label="删除课程对话"
              title="删除对话"
              @click="deleteConversation(conversation.course_id, conversation.id)"
            >
              ×
            </button>
          </div>
        </div>
      </section>
    </div>

    <div class="sidebar-footer">
      <button
        v-if="collapsed"
        type="button"
        class="sidebar-link sidebar-collapse-link"
        aria-label="展开侧边栏"
        @click="emit('update:collapsed', false)"
      >
        <span class="nav-icon" aria-hidden="true">›</span>
      </button>

      <RouterLink
        to="/settings"
        class="sidebar-link settings-link"
        :class="{ active: isSettings }"
        @click="closeMobile"
      >
        <span class="nav-icon" aria-hidden="true">⚙</span>
        <span v-show="!collapsed">设置</span>
      </RouterLink>
    </div>
  </aside>
</template>

<style scoped>
.sidebar-backdrop {
  display: none;
}

.app-sidebar {
  position: fixed;
  z-index: 20;
  inset: 0 auto 0 0;
  display: flex;
  width: var(--sidebar-width);
  padding: 18px 14px 16px;
  overflow: hidden;
  flex-direction: column;
  color: var(--ink-strong);
  background:
    radial-gradient(circle at 20% 0%, rgb(87 199 255 / 18%), transparent 28%),
    linear-gradient(180deg, rgb(255 255 255 / 92%), rgb(245 250 255 / 90%));
  border-right: 1px solid rgb(132 160 196 / 18%);
  box-shadow: 14px 0 42px rgb(83 115 157 / 8%);
  backdrop-filter: blur(24px);
  transition:
    width 180ms ease,
    transform 180ms ease;
}

.app-sidebar::after {
  position: absolute;
  right: -38px;
  bottom: 80px;
  width: 110px;
  height: 110px;
  pointer-events: none;
  content: '';
  background: radial-gradient(circle, rgb(125 92 255 / 12%), transparent 68%);
}

.app-sidebar.collapsed {
  width: var(--sidebar-collapsed-width);
  align-items: center;
  padding-inline: 10px;
}

.brand-row {
  display: flex;
  width: 100%;
  min-height: 48px;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}

.brand-orbit {
  position: relative;
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  place-items: center;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #fff;
  background: linear-gradient(145deg, var(--primary), var(--violet));
  border-radius: 15px;
  box-shadow: 0 10px 24px rgb(64 135 255 / 24%);
}

.brand-orbit::after {
  position: absolute;
  inset: -4px;
  pointer-events: none;
  content: '';
  border: 1px solid rgb(64 135 255 / 20%);
  border-radius: 18px;
  transform: rotate(8deg);
}

.brand-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.brand-copy strong {
  font-size: 15px;
  letter-spacing: -0.01em;
}

.brand-copy small {
  overflow: hidden;
  font-size: 11px;
  color: var(--ink-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.icon-button {
  display: grid;
  width: 30px;
  height: 30px;
  padding: 0;
  color: var(--ink-muted);
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 10px;
  place-items: center;
}

.icon-button:hover {
  color: var(--primary-deep);
  background: var(--primary-soft);
}

.collapse-button {
  margin-left: auto;
  font-size: 22px;
}

.mobile-close-button {
  display: none;
}

.primary-navigation {
  display: grid;
  gap: 5px;
  margin-top: 10px;
}

.sidebar-link {
  display: flex;
  width: 100%;
  min-height: 42px;
  padding: 8px 10px;
  align-items: center;
  gap: 10px;
  color: var(--ink);
  text-decoration: none;
  border: 1px solid transparent;
  border-radius: 13px;
  transition:
    color 160ms ease,
    background 160ms ease,
    border-color 160ms ease,
    transform 160ms ease;
}

.sidebar-link:hover {
  color: var(--primary-deep);
  background: rgb(234 246 255 / 72%);
}

.sidebar-link.active {
  color: var(--primary-deep);
  background: linear-gradient(120deg, rgb(224 244 255 / 92%), rgb(239 236 255 / 78%));
  border-color: rgb(68 155 255 / 14%);
}

.create-chat {
  min-height: 46px;
  color: #fff;
  background: linear-gradient(120deg, var(--primary), #5d8cff 55%, var(--violet));
  border: 0;
  box-shadow: 0 12px 25px rgb(73 137 255 / 22%);
}

.create-chat:hover,
.create-chat.active {
  color: #fff;
  background: linear-gradient(120deg, var(--primary-deep), #536fff 58%, #805df5);
  border-color: transparent;
  transform: translateY(-1px);
}

.nav-icon {
  display: grid;
  width: 23px;
  height: 23px;
  flex: 0 0 23px;
  font-size: 16px;
  font-weight: 700;
  place-items: center;
}

.nav-icon-ai {
  font-size: 9px;
  letter-spacing: -0.06em;
  border: 1px solid currentcolor;
  border-radius: 8px;
}

.collapsed .sidebar-link {
  width: 46px;
  justify-content: center;
  padding-inline: 0;
}

.history-section {
  margin-top: 15px;
}

.sidebar-history-scroll {
  min-height: 0;
  padding-right: 4px;
  margin-right: -4px;
  overflow-x: hidden;
  overflow-y: auto;
  flex: 1 1 auto;
  overscroll-behavior: contain;
  scrollbar-color: rgb(142 167 199 / 62%) transparent;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
}

.sidebar-history-scroll::-webkit-scrollbar {
  width: 6px;
}

.sidebar-history-scroll::-webkit-scrollbar-thumb {
  background: rgb(142 167 199 / 48%);
  border-radius: 999px;
}

.sidebar-history-scroll::-webkit-scrollbar-thumb:hover {
  background: rgb(104 139 181 / 68%);
}

.sidebar-history-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.history-heading {
  display: flex;
  width: 100%;
  padding: 4px 7px;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--ink-faint);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.history-heading:hover {
  color: var(--ink);
}

.history-empty {
  margin: 3px 7px 0;
  padding: 9px 10px;
  font-size: 12px;
  color: var(--ink-faint);
  background: rgb(230 239 249 / 48%);
  border-radius: 10px;
}

.history-list {
  display: grid;
  gap: 4px;
  margin-top: 3px;
}

.history-item {
  display: flex;
  min-width: 0;
  align-items: center;
  background: rgb(238 246 255 / 54%);
  border: 1px solid transparent;
  border-radius: 10px;
}

.history-item:hover,
.history-item.active {
  background: rgb(226 242 255 / 82%);
  border-color: rgb(62 155 255 / 13%);
}

.history-item > a {
  display: grid;
  min-width: 0;
  padding: 8px 4px 8px 10px;
  flex: 1;
  gap: 2px;
  color: var(--ink);
  text-decoration: none;
}

.history-item strong,
.history-item small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-item strong {
  font-size: 11px;
}

.history-item small {
  font-size: 9px;
  color: var(--ink-faint);
}

.history-item > button {
  width: 28px;
  height: 30px;
  padding: 0;
  flex: 0 0 28px;
  color: var(--ink-faint);
  cursor: pointer;
  background: transparent;
  border: 0;
}

.history-item > button:hover {
  color: var(--danger);
}

.sidebar-footer {
  display: grid;
  flex: 0 0 auto;
  gap: 4px;
  margin-top: auto;
  padding-top: 10px;
}

.settings-link {
  margin-top: 0;
}

.sidebar-collapse-link {
  margin-top: 0;
  color: var(--ink-muted);
  cursor: pointer;
  background: transparent;
}

.sidebar-collapse-link:hover {
  color: var(--primary-deep);
  background: rgb(234 246 255 / 72%);
}

@media (max-width: 820px) {
  .sidebar-backdrop {
    position: fixed;
    z-index: 19;
    inset: 0;
    display: block;
    pointer-events: none;
    background: rgb(24 41 68 / 32%);
    opacity: 0;
    backdrop-filter: blur(2px);
    transition: opacity 180ms ease;
  }

  .sidebar-backdrop.visible {
    pointer-events: auto;
    opacity: 1;
  }

  .app-sidebar,
  .app-sidebar.collapsed {
    width: min(286px, calc(100vw - 48px));
    align-items: stretch;
    padding: 18px 14px 16px;
    visibility: hidden;
    transform: translateX(-105%);
    transition:
      transform 180ms ease,
      visibility 0s linear 180ms;
  }

  .app-sidebar.mobile-open {
    visibility: visible;
    transform: translateX(0);
    transition-delay: 0s;
  }

  .app-sidebar.mobile-open .brand-copy,
  .app-sidebar.mobile-open .sidebar-history-scroll,
  .app-sidebar.mobile-open .sidebar-link span:last-child {
    display: block !important;
  }

  .app-sidebar.mobile-open .sidebar-link {
    width: 100%;
    justify-content: flex-start;
    padding-inline: 10px;
  }

  .collapse-button,
  .sidebar-collapse-link {
    display: none;
  }

  .mobile-close-button {
    display: grid;
    margin-left: auto;
    font-size: 20px;
  }
}
</style>
