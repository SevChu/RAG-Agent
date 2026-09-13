<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as api from '@/api/training'
import * as agentsApi from '@/api/agentProfiles'
import { toFriendlyApiError } from '@/api/client'
import type { AgentProfile } from '@/types/api'
import type {
  Dataset,
  DatasetRevision,
  Eligibility,
  Estimate,
  RunInput,
  TrainingOptions,
} from '@/types/training'
import {
  defaultParameters,
  parameterError,
  parameterFields,
  SubmissionIdentity,
  useRequestGate,
} from '@/utils/training'
const route = useRoute(),
  router = useRouter(),
  gate = useRequestGate(),
  revisionGate = useRequestGate(),
  eligibilityGate = useRequestGate(),
  agentListGate = useRequestGate(),
  dataListGate = useRequestGate()
const step = ref(0),
  agents = ref<AgentProfile[]>([]),
  agentId = ref(''),
  selectedAgent = ref<AgentProfile | null>(null),
  agentOffset = ref(0),
  data = ref<Dataset[]>([]),
  dataOffset = ref(0),
  datasetId = ref(''),
  revisions = ref<DatasetRevision[]>([]),
  moreRevisions = ref(false),
  revisionId = ref(''),
  eligible = ref<Eligibility | null>(null),
  eligibilityBusy = ref(false),
  options = ref<TrainingOptions | null>(null),
  estimate = ref<Estimate | null>(null),
  busy = ref(false),
  error = ref(''),
  steps = ref(20)
const parameters = reactive(defaultParameters()),
  identity = new SubmissionIdentity()
const selectedRevision = computed(
  () => revisions.value.find((r) => r.id === revisionId.value) ?? null,
)
const target = computed(() => selectedRevision.value?.manifest.target ?? 'reranker')
const baseModel = computed(() => `fake-${target.value}-v1`)
const labels = ['选择智能体', '选择数据', '选择目标', '配置参数', '复核提交']
function input(): RunInput {
  return {
    idempotency_key: '',
    agent_profile_id: agentId.value,
    expected_agent_revision_id: selectedAgent.value?.current_revision.id ?? null,
    dataset_id: datasetId.value,
    dataset_revision_id: revisionId.value,
    target: target.value,
    base_model: baseModel.value,
    base_model_revision: 'fake-1',
    trainer: 'fake-v1',
    parameters: { ...parameters },
    simulation_steps: steps.value,
  }
}
watch(
  [agentId, datasetId, revisionId, parameters, steps],
  () => {
    estimate.value = null
  },
  { deep: true },
)
async function loadAgents(offset: number) {
  const ticket = agentListGate.next()
  try {
    const rows = await agentsApi.fetchAgentProfiles({ enabled: true, limit: 20, offset })
    if (agentListGate.current(ticket)) {
      agents.value = rows
      agentOffset.value = offset
    }
  } catch (e) {
    if (agentListGate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
async function loadData(offset: number) {
  const ticket = dataListGate.next()
  try {
    const rows = await api.datasets(offset)
    if (dataListGate.current(ticket)) {
      data.value = rows
      dataOffset.value = offset
    }
  } catch (e) {
    if (dataListGate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
async function chooseAgent() {
  const ticket = gate.next()
  eligibilityGate.next()
  eligibilityBusy.value = false
  selectedAgent.value = null
  eligible.value = null
  error.value = ''
  if (!agentId.value) return
  try {
    const item = await agentsApi.fetchAgentProfile(agentId.value)
    if (gate.current(ticket)) {
      selectedAgent.value = item
      if (revisionId.value) await checkEligibility()
    }
  } catch (e) {
    if (gate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
async function chooseDataset() {
  const ticket = revisionGate.next()
  eligibilityGate.next()
  eligibilityBusy.value = false
  eligible.value = null
  revisions.value = []
  revisionId.value = ''
  error.value = ''
  if (!datasetId.value) return
  try {
    const rows = await api.revisions(datasetId.value)
    if (revisionGate.current(ticket)) {
      revisions.value = rows
      moreRevisions.value = rows.length === 20
    }
  } catch (e) {
    if (revisionGate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
async function more() {
  const ticket = revisionGate.next()
  try {
    const rows = await api.revisions(datasetId.value, revisions.value.length)
    if (revisionGate.current(ticket)) {
      revisions.value.push(...rows)
      moreRevisions.value = rows.length === 20
    }
  } catch (e) {
    if (revisionGate.current(ticket)) error.value = toFriendlyApiError(e).message
  }
}
async function checkEligibility() {
  const ticket = eligibilityGate.next()
  eligible.value = null
  eligibilityBusy.value = true
  error.value = ''
  if (!revisionId.value || !agentId.value) {
    eligibilityBusy.value = false
    return
  }
  try {
    const result = await api.eligibility(datasetId.value, revisionId.value, agentId.value)
    if (eligibilityGate.current(ticket)) eligible.value = result
  } catch (e) {
    if (eligibilityGate.current(ticket)) error.value = toFriendlyApiError(e).message
  } finally {
    if (eligibilityGate.current(ticket)) eligibilityBusy.value = false
  }
}
function validateStep(): string {
  if (!selectedAgent.value?.enabled || selectedAgent.value.deleted_at)
    return '请选择启用中的智能体。'
  if (step.value >= 1 && (!selectedRevision.value || !eligible.value?.eligible))
    return '请选择已审核且具备使用资格的数据版本。'
  if (step.value >= 3) return parameterError(parameters, steps.value)
  return ''
}
async function recheck() {
  const chosen = selectedAgent.value,
    rev = selectedRevision.value
  if (!chosen || !rev) throw { code: 'INVALID_INPUT', message: '请重新选择智能体与数据。' }
  const [current, currentRevision, eligibility] = await Promise.all([
    agentsApi.fetchAgentProfile(chosen.id),
    api.revision(datasetId.value, rev.id),
    api.eligibility(datasetId.value, rev.id, chosen.id),
  ])
  if (
    current.current_revision.id !== chosen.current_revision.id ||
    !current.enabled ||
    current.deleted_at
  ) {
    step.value = 0
    throw {
      code: 'CONFLICT',
      message: '智能体版本或启用状态已变化。请重新选择智能体并复核；参数已保留。',
    }
  }
  if (currentRevision.status !== 'approved' || !eligibility.eligible) {
    eligible.value = eligibility
    step.value = 1
    throw { code: 'CONFLICT', message: '数据审核或使用权限已变化，请重新选择数据；参数已保留。' }
  }
}
function back() {
  step.value--
  error.value = ''
}
async function next() {
  if (busy.value) return
  error.value = validateStep()
  if (error.value) return
  if (step.value === 3) {
    busy.value = true
    try {
      await recheck()
      const payload = input()
      payload.idempotency_key = identity.for(payload)
      estimate.value = await api.estimate(payload)
      step.value = 4
    } catch (e) {
      error.value = toFriendlyApiError(e).message
    } finally {
      busy.value = false
    }
  } else step.value++
}
async function submit() {
  if (busy.value) return
  error.value = validateStep()
  if (error.value) return
  busy.value = true
  try {
    await recheck()
    const payload = input()
    payload.idempotency_key = identity.for(payload)
    const result = await api.createRun(payload)
    await router.push('/training/runs/' + result.id)
  } catch (e) {
    error.value = toFriendlyApiError(e).message + ' 输入已保留，连接中断后重试不会重复创建任务。'
  } finally {
    busy.value = false
  }
}
onMounted(async () => {
  await Promise.all([
    loadAgents(0),
    loadData(0),
    api
      .options()
      .then((value) => {
        options.value = value
      })
      .catch((e) => {
        error.value = toFriendlyApiError(e).message
      }),
  ])
  if (typeof route.query.agent === 'string') {
    agentId.value = route.query.agent
    await chooseAgent()
    if (selectedAgent.value && !agents.value.some((a) => a.id === agentId.value))
      agents.value.unshift(selectedAgent.value)
  }
})
</script>
<template>
  <section class="training-card">
    <div class="training-section-title">
      <h2>创建模拟训练任务</h2>
      <span class="training-badge">不产生模型权重</span>
    </div>
    <ol class="training-steps" aria-label="创建步骤">
      <li
        v-for="(label, index) in labels"
        :key="label"
        :class="{ current: step === index, done: step > index }"
        :aria-current="step === index ? 'step' : undefined"
      >
        {{ index + 1 }} · {{ label }}
      </li>
    </ol>
    <p v-if="error" class="training-error" role="alert">{{ error }}</p>
    <fieldset :disabled="busy">
      <section v-if="step === 0">
        <h3>选择要关联的智能体</h3>
        <label
          >智能体<select aria-label="智能体" v-model="agentId" @change="chooseAgent">
            <option value="">请选择智能体</option>
            <option v-for="item in agents" :key="item.id" :value="item.id">
              {{ item.name }} · r{{ item.current_revision.revision_number }}
            </option>
          </select></label
        >
        <div class="training-actions">
          <button :disabled="agentOffset === 0" @click="loadAgents(agentOffset - 20)">
            上一组智能体</button
          ><button :disabled="agents.length < 20" @click="loadAgents(agentOffset + 20)">
            下一组智能体</button
          ><button @click="chooseAgent">重新读取所选版本</button>
        </div>
        <p v-if="!agents.length" class="training-empty">
          没有可选的启用智能体。<RouterLink to="/agents">前往智能体管理</RouterLink>
        </p>
        <dl v-if="selectedAgent" class="training-facts">
          <dt>固定版本</dt>
          <dd>
            r{{ selectedAgent.current_revision.revision_number }} ·
            {{ selectedAgent.current_revision.id }}
          </dd>
          <dt>允许的数据空间</dt>
          <dd>
            {{
              selectedAgent.current_revision.config.allowed_course_ids.length
                ? selectedAgent.current_revision.config.allowed_course_ids.join('、')
                : '无资料空间授权；可使用独立合成来源'
            }}
          </dd>
          <dt>对话模型</dt>
          <dd>{{ selectedAgent.current_revision.config.model.model }}（与本次模拟基础模型分开）</dd>
        </dl>
      </section>
      <section v-if="step === 1">
        <h3>选择获准的数据版本</h3>
        <div class="training-fields">
          <label
            >数据集<select aria-label="数据集" v-model="datasetId" @change="chooseDataset">
              <option value="">请选择数据集</option>
              <option v-for="item in data" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select></label
          ><label
            >已审核版本<select
              aria-label="已审核版本"
              v-model="revisionId"
              @change="checkEligibility"
            >
              <option value="">请选择已审核版本</option>
              <option
                v-for="item in revisions.filter((r) => r.status === 'approved')"
                :key="item.id"
                :value="item.id"
              >
                版本 {{ item.revision_number }} · {{ item.manifest.target }} ·
                {{ item.report.sample_count }} 条
              </option>
            </select></label
          >
        </div>
        <div class="training-actions">
          <button :disabled="dataOffset === 0" @click="loadData(dataOffset - 20)">上一组数据</button
          ><button :disabled="data.length < 20" @click="loadData(dataOffset + 20)">
            下一组数据</button
          ><button v-if="moreRevisions" @click="more">更多版本</button
          ><button :disabled="!revisionId || eligibilityBusy" @click="checkEligibility">
            重新检查资格
          </button>
        </div>
        <p
          v-if="datasetId && !revisions.some((r) => r.status === 'approved')"
          class="training-empty"
        >
          当前没有已审核版本。<RouterLink to="/training/datasets">前往训练数据完成审核</RouterLink>
        </p>
        <p class="training-note">仅使用 train / validation。test 与封存测试集不可选择。</p>
        <p v-if="eligibilityBusy" role="status">正在复核数据与权限…</p>
        <p
          v-else-if="eligible"
          :class="eligible.eligible ? 'training-note' : 'training-error'"
          role="status"
        >
          {{
            eligible.eligible
              ? '当前数据具备使用资格'
              : '当前数据不可使用：' + eligible.reasons.join('、')
          }}
        </p>
        <dl v-if="selectedRevision" class="training-facts">
          <dt>来源</dt>
          <dd>{{ selectedRevision.manifest.source }}</dd>
          <dt>许可</dt>
          <dd>
            {{ selectedRevision.manifest.license_id }} ·
            {{ selectedRevision.manifest.license_notes }}
          </dd>
          <dt>隐私核对</dt>
          <dd>{{ selectedRevision.manifest.pii_notes }}</dd>
          <dt>训练 / 验证样本</dt>
          <dd>
            {{ selectedRevision.report.splits.train?.count ?? 0 }} /
            {{ selectedRevision.report.splits.validation?.count ?? 0 }}
          </dd>
          <dt>审核 / 去重摘要</dt>
          <dd>
            已批准 ·
            {{ selectedRevision.report.issue_count }} 项校验问题；已执行来源分组、精确及近重复检查
          </dd>
        </dl>
      </section>
      <section v-if="step === 2">
        <h3>确认训练目标</h3>
        <label
          >训练目标<select :value="target" disabled>
            <option value="reranker">Reranker · 重排序</option>
            <option value="scorer">Scorer · 评分</option>
          </select></label
        >
        <p class="training-muted">目标与所选数据标签一致。要更换目标，请返回上一步选择对应数据。</p>
        <dl class="training-facts">
          <dt>模拟基础模型</dt>
          <dd>{{ baseModel }} · fake-1</dd>
          <dt>执行方式</dt>
          <dd>Fake Trainer · 离线模拟</dd>
        </dl>
        <p class="training-note">
          本周不支持生成大模型微调。模拟结果不能用于回答、评分或检索，也不代表模型质量提升。
        </p>
      </section>
      <section v-if="step === 3">
        <h3>配置模拟参数</h3>
        <div class="training-fields">
          <label
            >训练方式<select aria-label="训练方式" v-model="parameters.method">
              <option value="lora">LoRA</option>
              <option value="qlora">QLoRA</option>
            </select></label
          ><label
            >模拟步数<input
              v-model.number="steps"
              type="number"
              min="1"
              max="100"
              step="1" /></label
          ><label v-for="field in parameterFields" :key="field.key"
            >{{ field.label
            }}<input
              v-model.number="parameters[field.key]"
              type="number"
              :min="field.min"
              :max="field.max"
              :step="field.step"
          /></label>
        </div>
        <p class="training-muted">
          参数保存到任务来源中。本次不会分配训练显存；参数校验通过不代表真实硬件支持。
        </p>
      </section>
      <section v-if="step === 4">
        <h3>复核后提交</h3>
        <dl class="training-facts">
          <dt>智能体</dt>
          <dd>
            {{ selectedAgent?.name }} · r{{ selectedAgent?.current_revision.revision_number }}
          </dd>
          <dt>数据版本</dt>
          <dd>版本 {{ selectedRevision?.revision_number }} · {{ revisionId }}</dd>
          <dt>目标 / 基础模型</dt>
          <dd>{{ target }} / {{ baseModel }} · fake-1</dd>
          <dt>参数</dt>
          <dd>{{ parameters.method.toUpperCase() }} · {{ steps }} 个模拟步骤</dd>
          <template v-for="field in parameterFields" :key="field.key"
            ><dt>{{ field.label }}</dt>
            <dd>{{ parameters[field.key] }}</dd></template
          >
          <dt>预计模拟耗时</dt>
          <dd>{{ estimate?.nominal_simulation_seconds.toFixed(2) ?? '—' }} 秒（不含排队与校验）</dd>
          <dt>可用内存</dt>
          <dd>
            {{
              estimate?.available_memory_bytes != null
                ? (estimate.available_memory_bytes / 1024 ** 3).toFixed(1) + ' GiB'
                : '未知'
            }}
          </dd>
          <dt>真实显存 / 耗时 / 成本</dt>
          <dd>待评估</dd>
        </dl>
        <p class="training-note">
          {{
            options?.worker_enabled
              ? '模拟后台已配置启用，任务会进入队列。'
              : '模拟后台未启用，提交后会保持排队。'
          }}成功只会生成不可部署的模拟产物。
        </p>
      </section>
      <div class="training-actions">
        <button v-if="step > 0" @click="back">上一步</button
        ><button v-if="step < 4" class="primary" :disabled="eligibilityBusy" @click="next">
          {{ busy ? '正在复核…' : '下一步' }}</button
        ><button v-else class="primary" @click="submit">
          {{ busy ? '正在提交…' : '创建模拟训练任务' }}
        </button>
      </div>
    </fieldset>
  </section>
</template>
