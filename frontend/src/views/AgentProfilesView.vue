<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElDialog, ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/agentProfiles'
import { toFriendlyApiError } from '@/api/client'
import { useCoursesStore } from '@/stores/courses'
import type {
  AgentConfiguration,
  AgentProfile,
  AgentProfileOptions,
  AgentRevision,
} from '@/types/api'
import {
  configChanges,
  defaultAgentConfig,
  modelAvailable,
  validateAgentConfig,
} from '@/utils/agents'

const router = useRouter()
const courses = useCoursesStore()
const profiles = ref<AgentProfile[]>([])
const options = ref<AgentProfileOptions | null>(null)
const error = ref('')
const busy = ref(false)
const loading = ref(true)
const offset = ref(0)
const editor = ref(false)
const editing = ref<AgentProfile | null>(null)
const name = ref('')
const description = ref('')
const summary = ref('')
const config = ref<AgentConfiguration>(defaultAgentConfig())
const formError = ref('')
const conflicted = ref(false)
const versionsOpen = ref(false)
const versionProfile = ref<AgentProfile | null>(null)
const revisions = ref<AgentRevision[]>([])
const selectedRevision = ref<AgentRevision | null>(null)
const versionsMore = ref(false)
const versionsLoading = ref(false)
const versionError = ref('')
const providerModels = computed(
  () => options.value?.providers.find((p) => p.id === config.value.model.provider)?.models ?? [],
)
const differences = computed(() =>
  selectedRevision.value && versionProfile.value
    ? configChanges(selectedRevision.value.config, versionProfile.value.current_revision.config)
    : [],
)
const contextFields = [
  { key: 'rag_max_messages', label: '资料对话消息数', min: 1, max: 20 },
  { key: 'rag_max_chars', label: '资料对话字符数', min: 500, max: 30000 },
  { key: 'quick_max_messages', label: '快速对话消息数', min: 1, max: 30 },
  { key: 'quick_max_chars', label: '快速对话字符数', min: 500, max: 40000 },
] as const
const retrievalFields = [
  { key: 'answer_top_k', label: '问答返回数', min: 1, max: 20 },
  { key: 'answer_candidate_k', label: '问答候选数', min: 1, max: 100 },
  { key: 'summary_top_k', label: '总结返回数', min: 1, max: 30 },
  { key: 'summary_candidate_k', label: '总结候选数', min: 1, max: 100 },
  { key: 'summary_max_sources', label: '总结来源上限', min: 1, max: 30 },
  { key: 'summary_context_max_chars', label: '总结证据字符数', min: 2000, max: 50000 },
  { key: 'exam_top_k', label: '组卷返回数', min: 1, max: 30 },
  { key: 'exam_candidate_k', label: '组卷候选数', min: 1, max: 100 },
  { key: 'exam_max_sources', label: '组卷来源上限', min: 1, max: 30 },
  { key: 'exam_context_max_chars', label: '组卷证据字符数', min: 2000, max: 50000 },
] as const

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [items, available] = await Promise.all([
      api.fetchAgentProfiles({ limit: 20, offset: offset.value }),
      api.fetchAgentProfileOptions(),
      courses.loadCourses(false),
    ])
    profiles.value = items
    options.value = available
  } catch (e) {
    error.value = toFriendlyApiError(e).message
  } finally {
    loading.value = false
  }
}
onMounted(load)
function setEditor(profile: AgentProfile | null): void {
  editing.value = profile
  name.value = profile?.name ?? ''
  description.value = profile?.description ?? ''
  summary.value = ''
  config.value = profile
    ? JSON.parse(JSON.stringify(profile.current_revision.config))
    : defaultAgentConfig()
  formError.value = ''
  conflicted.value = false
  editor.value = true
}
async function edit(profile: AgentProfile): Promise<void> {
  busy.value = true
  try {
    setEditor(await api.fetchAgentProfile(profile.id))
  } catch (e) {
    error.value = toFriendlyApiError(e).message
  } finally {
    busy.value = false
  }
}
async function reloadEditor(): Promise<void> {
  if (!editing.value) return
  try {
    await ElMessageBox.confirm('重新载入会替换当前未保存的编辑内容。', '载入最新版本', {
      confirmButtonText: '载入',
      cancelButtonText: '保留编辑',
    })
    await edit(editing.value)
  } catch {
    /* User keeps the draft. */
  }
}
async function save(): Promise<void> {
  if (!options.value || busy.value) return
  formError.value = validateAgentConfig(config.value, options.value)
  if (!name.value.trim()) formError.value = '名称不能为空。'
  if (formError.value) return
  busy.value = true
  try {
    if (editing.value) {
      const changed = configChanges(editing.value.current_revision.config, config.value).length > 0
      await api.updateAgentProfile(editing.value.id, {
        expected_row_version: editing.value.row_version,
        name: name.value.trim(),
        description: description.value.trim() || null,
        ...(changed
          ? { config: config.value, change_summary: summary.value.trim() || '更新配置' }
          : {}),
      })
    } else {
      await api.createAgentProfile({
        name: name.value.trim(),
        description: description.value.trim() || null,
        config: config.value,
        change_summary: summary.value.trim() || '初始配置',
      })
    }
    editor.value = false
    ElMessage.success('已保存；新配置只用于新会话')
    await load()
  } catch (e) {
    const failure = toFriendlyApiError(e)
    formError.value = failure.message
    conflicted.value = failure.code === 'CONFLICT'
  } finally {
    busy.value = false
  }
}
async function copy(profile: AgentProfile): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('为独立副本输入名称', '复制智能体', {
      inputValue: `${profile.name} 副本`,
      inputValidator: (v: string) => Boolean(v.trim()) && v.length <= 100,
      confirmButtonText: '复制',
      cancelButtonText: '取消',
    })
    busy.value = true
    await api.copyAgentProfile(profile.id, {
      name: value.trim(),
      description: profile.description,
      revision_id: profile.current_revision.id,
    })
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') error.value = toFriendlyApiError(e).message
  } finally {
    busy.value = false
  }
}
async function toggle(profile: AgentProfile): Promise<void> {
  try {
    await ElMessageBox.confirm(
      profile.enabled
        ? '停用后不能新建会话或继续生成，已有历史仍可查看。'
        : '启用后可以继续使用已有会话的固定版本。',
      profile.enabled ? '停用智能体' : '启用智能体',
      { confirmButtonText: '确认', cancelButtonText: '取消' },
    )
    busy.value = true
    await api.updateAgentProfile(profile.id, {
      expected_row_version: profile.row_version,
      enabled: !profile.enabled,
    })
    await load()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      error.value = toFriendlyApiError(e).message
      await refreshList()
    }
  } finally {
    busy.value = false
  }
}
async function remove(profile: AgentProfile): Promise<void> {
  if (busy.value) return
  try {
    await ElMessageBox.confirm(
      `删除“${profile.name}”后将从列表和新会话选择中移除，且无法重新启用。已有会话和配置版本保留，只可查看；原名称仍保留用于历史记录。`,
      '删除智能体',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    busy.value = true
    await api.deleteAgentProfile(profile.id, profile.row_version)
    if (profiles.value.length === 1 && offset.value > 0) offset.value -= 20
    await load()
    ElMessage.success('智能体已删除，已有历史已保留')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      error.value = toFriendlyApiError(e).message
      await refreshList()
    }
  } finally {
    busy.value = false
  }
}
async function refreshList(): Promise<void> {
  try {
    profiles.value = await api.fetchAgentProfiles({ limit: 20, offset: offset.value })
  } catch {
    /* Preserve the original action error. */
  }
}
async function versions(profile: AgentProfile): Promise<void> {
  busy.value = true
  versionError.value = ''
  revisions.value = []
  selectedRevision.value = null
  versionsOpen.value = true
  try {
    versionProfile.value = await api.fetchAgentProfile(profile.id)
    await moreVersions()
    selectedRevision.value = revisions.value[0] ?? null
  } catch (e) {
    versionError.value = toFriendlyApiError(e).message
  } finally {
    busy.value = false
  }
}
async function moreVersions(): Promise<void> {
  if (!versionProfile.value || versionsLoading.value) return
  versionsLoading.value = true
  try {
    const items = await api.fetchAgentRevisions(versionProfile.value.id, {
      limit: 20,
      offset: revisions.value.length,
    })
    revisions.value.push(...items)
    versionsMore.value = items.length === 20
  } catch (e) {
    versionError.value = toFriendlyApiError(e).message
  } finally {
    versionsLoading.value = false
  }
}
async function restore(): Promise<void> {
  if (!versionProfile.value || !selectedRevision.value || busy.value) return
  try {
    await ElMessageBox.confirm(
      `将 r${selectedRevision.value.revision_number} 的配置另存为新版本，已有会话继续使用原版本。`,
      '恢复配置',
      { confirmButtonText: '创建新版本', cancelButtonText: '取消' },
    )
    busy.value = true
    await api.restoreAgentProfile(versionProfile.value.id, {
      expected_row_version: versionProfile.value.row_version,
      revision_id: selectedRevision.value.id,
      change_summary: `恢复 r${selectedRevision.value.revision_number}`,
    })
    await versions(versionProfile.value)
    await load()
    ElMessage.success('已从历史配置创建新版本')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') versionError.value = toFriendlyApiError(e).message
  } finally {
    busy.value = false
  }
}
function setEvaluation(id: string, usage: string): void {
  config.value.evaluation_profiles = config.value.evaluation_profiles.filter(
    (ref) => ref.profile_id !== id,
  )
  const option = options.value?.evaluation_profiles.find((item) => item.profile_id === id)
  if (option && (usage === 'offline' || usage === 'advisory'))
    config.value.evaluation_profiles.push({
      profile_id: id,
      usage,
      registry_version: option.registry_version,
      registry_sha256: option.registry_sha256,
    })
}
async function page(delta: number): Promise<void> {
  offset.value = Math.max(0, offset.value + delta * 20)
  await load()
}
</script>

<template>
  <section class="page-view agents-page">
    <header class="page-heading">
      <div>
        <div class="eyebrow"><span /> AGENT PROFILES</div>
        <h1>智能体管理</h1>
        <p>为不同任务配置独立智能体。每个会话始终使用创建时选定的版本。</p>
      </div>
      <button
        class="primary-button"
        :disabled="loading || busy || !options"
        @click="setEditor(null)"
      >
        创建智能体
      </button>
    </header>
    <div v-if="error" class="agent-notice" role="alert">
      {{ error }} <button @click="load">重新加载</button>
    </div>
    <p v-if="loading" role="status">正在加载智能体…</p>
    <div v-else-if="!profiles.length && !error" class="agent-empty">
      <h2>让智能体各有所长</h2>
      <p>创建第一个智能体，设定模型、可用资料和回答方式。</p>
    </div>
    <div class="agent-grid">
      <article v-for="profile in profiles" :key="profile.id" class="agent-card">
        <div class="agent-card-heading">
          <h2>{{ profile.name }}</h2>
          <span :class="['agent-status', { off: !profile.enabled }]">{{
            profile.enabled ? '已启用' : '已停用'
          }}</span>
        </div>
        <p>{{ profile.description || '暂无描述' }}</p>
        <dl>
          <dt>模型</dt>
          <dd>{{ profile.current_revision.config.model.model }}</dd>
          <dt>当前版本</dt>
          <dd>r{{ profile.current_revision.revision_number }}</dd>
          <dt>允许空间</dt>
          <dd>{{ profile.current_revision.config.allowed_course_ids.length }} 个</dd>
        </dl>
        <p
          v-if="options && !modelAvailable(profile.current_revision.config, options)"
          class="agent-notice"
        >
          模型未配置或已失效，请检查模型设置。
        </p>
        <div class="agent-actions">
          <button :disabled="busy" @click="edit(profile)">编辑</button
          ><button :disabled="busy" @click="versions(profile)">版本记录</button>
          <button :disabled="busy" @click="copy(profile)">复制</button
          ><button :disabled="busy" @click="toggle(profile)">
            {{ profile.enabled ? '停用' : '启用' }}
          </button>
          <button class="agent-delete" :disabled="busy" @click="remove(profile)">删除</button>
          <button
            :disabled="busy || !profile.enabled"
            @click="router.push({ path: '/chat/new', query: { agent: profile.id } })"
          >
            快速对话
          </button>
          <button
            :disabled="
              busy || !profile.enabled || !profile.current_revision.config.allowed_course_ids.length
            "
            @click="router.push({ path: '/assistant', query: { agent: profile.id } })"
          >
            资料对话
          </button>
        </div>
      </article>
    </div>
    <div class="agent-actions agent-pagination">
      <button :disabled="!offset || loading" @click="page(-1)">上一页</button
      ><span>第 {{ offset / 20 + 1 }} 页</span
      ><button :disabled="profiles.length < 20 || loading" @click="page(1)">下一页</button>
    </div>

    <el-dialog
      append-to-body
      v-model="editor"
      :title="editing ? '编辑智能体' : '创建智能体'"
      width="min(860px, 94vw)"
      :close-on-click-modal="false"
      :close-on-press-escape="!busy"
      :show-close="!busy"
      class="agent-dialog"
    >
      <form class="agent-form" @submit.prevent="save">
        <p
          v-if="!options?.providers.some((p) => p.configured && p.models.length)"
          class="agent-notice"
          role="alert"
        >
          当前没有已配置的模型，请先在模型设置中配置供应商。
        </p>
        <div v-if="formError" class="agent-notice" role="alert">
          {{ formError }}
          <button v-if="conflicted" type="button" @click="reloadEditor">重新载入最新版本</button>
        </div>
        <fieldset :disabled="busy">
          <legend>身份与回答方式</legend>
          <label>名称<input v-model="name" required maxlength="100" /></label>
          <label>描述<textarea v-model="description" maxlength="2000" rows="2" /></label>
          <label
            >系统提示<textarea
              v-model="config.system_prompt"
              maxlength="20000"
              rows="5"
              placeholder="描述任务目标、语气和回答要求"
            />
          </label>
        </fieldset>
        <fieldset :disabled="busy">
          <legend>模型与资料权限</legend>
          <div class="agent-fields">
            <label
              >供应商<select
                aria-label="供应商"
                v-model="config.model.provider"
                required
                @change="config.model.model = ''"
              >
                <option value="">请选择</option>
                <option
                  v-for="provider in options?.providers"
                  :key="provider.id"
                  :value="provider.id"
                  :disabled="!provider.configured"
                >
                  {{ provider.name }}{{ provider.configured ? '' : '（未配置）' }}
                </option>
              </select></label
            >
            <label
              >模型<select aria-label="模型" v-model="config.model.model" required>
                <option value="">请选择</option>
                <option v-for="model in providerModels" :key="model" :value="model">
                  {{ model }}
                </option>
              </select></label
            >
          </div>
          <p>每个资料会话只使用下列一个空间；不选空间时仅可快速对话。</p>
          <label v-for="course in courses.courses" :key="course.id" class="agent-check"
            ><input v-model="config.allowed_course_ids" type="checkbox" :value="course.id" />{{
              course.name
            }}</label
          >
          <label
            v-for="id in config.allowed_course_ids.filter(
              (id) => !courses.courses.some((c) => c.id === id),
            )"
            :key="id"
            class="agent-check"
            ><input v-model="config.allowed_course_ids" type="checkbox" :value="id" />已删除的空间
            {{ id }}（请取消）</label
          >
          <label class="agent-check"
            ><input v-model="config.tools.web_search" type="checkbox" />允许联网搜索</label
          >
          <p v-if="!options?.external_search_enabled">
            服务端已关闭联网，保存允许权限也不会启用搜索。
          </p>
        </fieldset>
        <fieldset :disabled="busy">
          <legend>上下文预算</legend>
          <p>实际使用量还受服务端上限限制。</p>
          <div class="agent-fields">
            <label v-for="field in contextFields" :key="field.key"
              >{{ field.label
              }}<input
                v-model.number="config.context[field.key]"
                type="number"
                required
                :min="field.min"
                :max="field.max"
                step="1"
            /></label>
          </div>
        </fieldset>
        <fieldset :disabled="busy">
          <legend>检索预算</legend>
          <div class="agent-fields">
            <label v-for="field in retrievalFields" :key="field.key"
              >{{ field.label
              }}<input
                v-model.number="config.retrieval[field.key]"
                type="number"
                required
                :min="field.min"
                :max="field.max"
                step="1" /></label
            ><label
              >问答相似度下限<input
                v-model.number="config.retrieval.min_similarity_score"
                type="number"
                required
                min="-1"
                max="1"
                step="0.01"
            /></label>
          </div>
        </fieldset>
        <fieldset v-if="options?.edition === 'research'" :disabled="busy">
          <legend>研究记录（仅研发/科研模式）</legend>
          <p>
            仅保存研究关联，不影响回答。选择引用不表示当前智能体已通过评测，也不代表其他部署能达到相同结果。
          </p>
          <label v-for="option in options?.evaluation_profiles" :key="option.profile_id"
            >{{ option.profile_id
            }}<select
              :value="
                config.evaluation_profiles.find((ref) => ref.profile_id === option.profile_id)
                  ?.usage ?? ''
              "
              @change="setEvaluation(option.profile_id, ($event.target as HTMLSelectElement).value)"
            >
              <option value="">不绑定</option>
              <option v-for="usage in option.allowed_usages" :key="usage" :value="usage">
                {{ usage === 'offline' ? '离线评测' : '辅助分析' }}
              </option>
            </select></label
          >
          <p
            v-for="reference in config.evaluation_profiles.filter(
              (ref) => !options?.evaluation_profiles.some((o) => o.profile_id === ref.profile_id),
            )"
            :key="reference.profile_id"
          >
            已失效：{{ reference.profile_id }}
            <button type="button" @click="setEvaluation(reference.profile_id, '')">移除引用</button>
          </p>
        </fieldset>
        <label>变更说明<input v-model="summary" maxlength="500" /></label>
        <p>保存配置会追加新版本，只影响新会话。已有会话保持原版本。</p>
        <div class="agent-actions">
          <button type="button" :disabled="busy" @click="editor = false">取消</button
          ><button class="primary-button" type="submit" :disabled="busy">
            {{ busy ? '保存中…' : '保存智能体' }}
          </button>
        </div>
      </form>
    </el-dialog>
    <el-dialog
      append-to-body
      v-model="versionsOpen"
      title="版本记录"
      width="min(920px, 94vw)"
      class="agent-dialog"
    >
      <div v-if="versionError" class="agent-notice" role="alert">
        {{ versionError
        }}<button v-if="versionProfile" @click="versions(versionProfile)">刷新版本</button>
      </div>
      <div class="agent-version-layout">
        <nav aria-label="历史版本" class="agent-version-list">
          <button
            v-for="revision in revisions"
            :key="revision.id"
            :aria-pressed="selectedRevision?.id === revision.id"
            @click="selectedRevision = revision"
          >
            r{{ revision.revision_number }} · {{ revision.change_summary
            }}<small>{{ new Date(revision.created_at).toLocaleString() }}</small></button
          ><button v-if="versionsMore" :disabled="busy" @click="moreVersions">加载更早版本</button>
        </nav>
        <div v-if="selectedRevision" class="agent-version-detail">
          <h3>r{{ selectedRevision.revision_number }}</h3>
          <p>与当前版本相比：{{ differences.join('、') || '执行配置相同' }}</p>
          <dl>
            <dt>模型</dt>
            <dd>
              {{ selectedRevision.config.model.provider }} /
              {{ selectedRevision.config.model.model }}
            </dd>
            <dt>系统提示</dt>
            <dd class="agent-pre">
              {{ selectedRevision.config.system_prompt || '未添加补充提示' }}
            </dd>
          </dl>
          <details>
            <summary>完整配置与哈希</summary>
            <pre>{{ JSON.stringify(selectedRevision.config, null, 2) }}</pre>
            <p class="agent-hash">{{ selectedRevision.config_sha256 }}</p>
          </details>
          <button class="primary-button" :disabled="busy" @click="restore">
            从此配置创建新版本
          </button>
        </div>
      </div>
    </el-dialog>
  </section>
</template>

<style>
.agent-actions .agent-delete {
  color: var(--danger);
}
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(330px, 100%), 1fr));
  gap: 20px;
}
.agent-card,
.agent-empty {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  padding: 24px;
}
.agent-card-heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 12px;
}
.agent-card h2 {
  margin: 0;
  overflow-wrap: anywhere;
}
.agent-card p {
  color: var(--ink-muted);
  overflow-wrap: anywhere;
}
.agent-status {
  white-space: nowrap;
  background: var(--success-soft);
  color: var(--success);
  padding: 4px 8px;
  font-size: 12px;
}
.agent-status.off {
  background: var(--surface-soft);
  color: var(--ink-muted);
}
.agent-card dl,
.agent-version-detail dl {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr);
  gap: 8px;
}
.agent-card dd,
.agent-version-detail dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.agent-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.agent-actions button,
.agent-notice button,
.agent-version-list button,
.agent-form button {
  min-height: 36px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink);
  border-radius: var(--radius-base);
  cursor: pointer;
}
.agent-actions .primary-button,
.agent-form .primary-button {
  background: var(--primary);
  color: var(--on-primary);
}
.agents-page button:disabled,
.agent-dialog button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.agent-pagination {
  margin-top: 24px;
}
.agent-notice {
  padding: 12px;
  background: var(--warning-soft);
  color: var(--ink);
  margin-bottom: 16px;
  overflow-wrap: anywhere;
}
.agent-form {
  display: grid;
  gap: 20px;
}
.agent-form fieldset {
  min-width: 0;
  margin: 0;
  padding: 16px;
  border: 1px solid var(--line);
}
.agent-form legend {
  font-weight: 700;
  padding: 0 8px;
}
.agent-form label {
  display: grid;
  gap: 6px;
  margin: 10px 0;
}
.agent-form input:not([type='checkbox']),
.agent-form select,
.agent-form textarea {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 10px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-base);
  color: var(--ink);
  font: inherit;
}
.agent-form textarea {
  resize: vertical;
}
.agent-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 20px;
}
.agent-form .agent-check {
  display: flex;
  align-items: center;
  gap: 8px;
}
.agent-form p {
  color: var(--ink-muted);
}
.agent-version-layout {
  display: grid;
  grid-template-columns: minmax(150px, 220px) minmax(0, 1fr);
  gap: 24px;
}
.agent-version-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.agent-version-list button {
  text-align: left;
  overflow-wrap: anywhere;
}
.agent-version-list button[aria-pressed='true'] {
  border-color: var(--primary);
  background: var(--primary-soft);
}
.agent-version-list small {
  display: block;
  margin-top: 4px;
}
.agent-version-detail {
  min-width: 0;
}
.agent-version-detail pre {
  overflow: auto;
  max-height: 350px;
  background: var(--surface-soft);
  padding: 12px;
}
.agent-pre {
  white-space: pre-wrap;
}
.agent-hash {
  overflow-wrap: anywhere;
}
@media (max-width: 650px) {
  .agent-fields,
  .agent-version-layout {
    grid-template-columns: 1fr;
  }
  .agent-version-list {
    max-height: 180px;
    overflow: auto;
  }
  .agent-card {
    padding: 18px;
  }
  .agents-page .page-heading {
    flex-wrap: wrap;
  }
}
</style>
