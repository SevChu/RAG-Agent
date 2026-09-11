<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  fetchAgentProfile,
  fetchAgentProfileOptions,
  fetchAgentProfiles,
  fetchAgentRevision,
} from '@/api/agentProfiles'
import { fetchCourses } from '@/api/courses'
import { toFriendlyApiError } from '@/api/client'
import { modelAvailable } from '@/utils/agents'
import type { AgentProfile, AgentRevision, ConversationAgentState } from '@/types/api'

const props = defineProps<{
  modelValue: string
  locked: boolean
  busy: boolean
  binding: { agent_profile_id?: string | null; agent_profile_revision_id?: string | null } | null
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  state: [value: ConversationAgentState]
  new: []
}>()
const profiles = ref<AgentProfile[]>([])
const profile = ref<AgentProfile | null>(null)
const revision = ref<AgentRevision | null>(null)
const error = ref('')
const pending = ref(true)
let sequence = 0
let alive = true
async function list(): Promise<void> {
  try {
    const items: AgentProfile[] = []
    for (let offset = 0; ; offset += 100) {
      const page = await fetchAgentProfiles({ limit: 100, offset })
      items.push(...page)
      if (page.length < 100) break
    }
    if (alive) profiles.value = items
  } catch (e) {
    if (alive) error.value = toFriendlyApiError(e).message
  }
}
async function resolve(): Promise<void> {
  const ticket = ++sequence
  const id = props.locked ? (props.binding?.agent_profile_id ?? '') : props.modelValue
  const revisionId = props.locked ? props.binding?.agent_profile_revision_id : null
  pending.value = true
  error.value = ''
  profile.value = null
  revision.value = null
  emit('state', { ready: false, profileId: id || null, config: null })
  if (props.locked && !props.binding) return
  if (!id) {
    pending.value = false
    emit('state', { ready: true, profileId: null, config: null })
    return
  }
  try {
    const [current, options, courses] = await Promise.all([
      fetchAgentProfile(id),
      fetchAgentProfileOptions(),
      fetchCourses(),
    ])
    const pinned = revisionId ? await fetchAgentRevision(id, revisionId) : current.current_revision
    if (ticket !== sequence || !alive) return
    profile.value = current
    revision.value = pinned
    if (current.deleted_at)
      error.value = '此智能体已删除。历史和固定版本仍可查看，请新建会话选择其他智能体。'
    else if (!current.enabled) error.value = '此智能体已停用。历史仍可查看，重新启用后可继续对话。'
    else if (!modelAvailable(pinned.config, options))
      error.value = '固定版本的模型未配置或已失效，请检查模型设置。'
    else if (
      pinned.config.allowed_course_ids.some((id) => !courses.some((course) => course.id === id))
    )
      error.value = '固定版本引用的资料空间已删除，请编辑智能体并新建会话。'
    emit('state', { ready: !error.value, profileId: id, config: pinned.config })
  } catch (e) {
    if (ticket === sequence && alive) error.value = toFriendlyApiError(e).message
  } finally {
    if (ticket === sequence && alive) pending.value = false
  }
}
function refresh(): void {
  if (!props.busy) {
    void list()
    void resolve()
  }
}
onMounted(() => {
  void list()
  window.addEventListener('focus', refresh)
})
onBeforeUnmount(() => {
  alive = false
  sequence++
  window.removeEventListener('focus', refresh)
})
watch(
  () => [
    props.modelValue,
    props.locked,
    props.binding?.agent_profile_id,
    props.binding?.agent_profile_revision_id,
    Boolean(props.binding),
  ],
  resolve,
  { immediate: true, flush: 'sync' },
)
</script>

<template>
  <section class="conversation-agent" aria-label="会话智能体">
    <div class="agent-control-row">
      <label v-if="!locked"
        >选择智能体<select
          aria-label="选择智能体"
          :value="modelValue"
          :disabled="busy"
          @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
        >
          <option value="">默认对话（不绑定智能体）</option>
          <option
            v-for="item in profiles"
            :key="item.id"
            :value="item.id"
            :disabled="!item.enabled"
          >
            {{ item.name }} · r{{ item.current_revision.revision_number
            }}{{ item.enabled ? '' : '（已停用）' }}
          </option>
          <option
            v-if="modelValue && !profiles.some((p) => p.id === modelValue)"
            :value="modelValue"
          >
            {{ profile?.name ?? '正在读取所选智能体' }}
          </option>
        </select></label
      >
      <strong v-else>{{
        profile?.name ?? (binding?.agent_profile_id ? '读取智能体…' : '默认对话')
      }}</strong>
      <button type="button" :disabled="busy || pending" @click="refresh">刷新状态</button>
      <button v-if="locked" type="button" :disabled="busy" @click="emit('new')">
        更换智能体并新建会话
      </button>
      <RouterLink to="/agents">管理智能体</RouterLink>
    </div>
    <p v-if="revision">
      {{ locked ? '固定版本' : '新会话使用' }} r{{ revision.revision_number }} ·
      {{ revision.config.model.model }} ·
      {{ revision.config.tools.web_search ? '允许联网（仍受服务端限制）' : '禁止联网' }}
    </p>
    <p v-else-if="!pending && !modelValue && !binding?.agent_profile_id">
      沿用全局模型选择，使用默认上下文与检索设置。
    </p>
    <p v-if="pending" role="status">正在核对版本与权限…</p>
    <p v-if="error" role="alert" class="agent-control-error">{{ error }}</p>
  </section>
</template>

<style scoped>
.conversation-agent {
  border: 1px solid var(--line);
  background: var(--surface);
  padding: 16px;
  margin-bottom: 20px;
  border-radius: var(--radius-base);
}
.agent-control-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.agent-control-row label {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.agent-control-row select {
  max-width: 100%;
  min-width: 190px;
  padding: 9px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink);
  font: inherit;
}
.agent-control-row button {
  padding: 8px 10px;
  border: 1px solid var(--line);
  background: var(--surface-soft);
  color: var(--ink);
  cursor: pointer;
  font: inherit;
}
.agent-control-row button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.conversation-agent p {
  margin: 10px 0 0;
  font-size: 13px;
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}
.conversation-agent .agent-control-error {
  color: var(--danger);
}
@media (max-width: 600px) {
  .agent-control-row label {
    width: 100%;
  }
  .agent-control-row select {
    width: 100%;
    min-width: 0;
  }
}
</style>
