import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, type App } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia } from 'pinia'
import TrainingWizard from '@/views/training/TrainingWizard.vue'
import TrainingRunDetail from '@/views/training/TrainingRunDetail.vue'
import TrainingAdapterDetail from '@/views/training/TrainingAdapterDetail.vue'
import { ElMessageBox } from 'element-plus'
import TrainingLayout from '@/views/training/TrainingLayout.vue'
import * as api from '@/api/training'
import * as agents from '@/api/agentProfiles'
import { defaultAgentConfig } from '@/utils/agents'
import { defaultParameters } from '@/utils/training'
import type { AgentProfile } from '@/types/api'
import type { DatasetRevision, TrainingRun } from '@/types/training'
vi.mock('element-plus', () => ({ ElMessageBox: { confirm: vi.fn<typeof ElMessageBox.confirm>() } }))
vi.mock('@/api/training')
vi.mock('@/api/agentProfiles')
let app: App | undefined
function agent(id = 'a', rev = 'r1'): AgentProfile {
  return {
    id,
    name: '合成智能体 ' + id,
    description: null,
    enabled: true,
    deleted_at: null,
    row_version: 1,
    created_at: '',
    updated_at: '',
    current_revision: {
      id: rev,
      agent_profile_id: id,
      revision_number: 1,
      config: defaultAgentConfig(),
      config_sha256: 'a'.repeat(64),
      change_summary: '',
      created_at: '',
    },
  }
}
const revision: DatasetRevision = {
  id: 'r',
  dataset_id: 'd',
  revision_number: 1,
  status: 'approved',
  created_at: '',
  manifest_sha256: 'b',
  manifest: {
    schema_version: 1,
    target: 'reranker',
    source: '合成',
    license_id: 'synthetic-owned',
    license_notes: '自建',
    training_allowed: true,
    pii_status: 'clean',
    pii_notes: '合成',
    source_course_ids: [],
  },
  report: {
    valid: true,
    approvable: true,
    content_sha256: 'c',
    byte_count: 100,
    sample_count: 2,
    splits: { train: { count: 1, sha256: 't' }, validation: { count: 1, sha256: 'v' } },
    issues: [],
    issue_count: 0,
    dedup_method: 'test',
    validator_version: 'test',
  },
}
function run(id = 'run'): TrainingRun {
  return {
    id,
    agent_profile_id: 'a',
    agent_revision_id: 'r1',
    dataset_revision_id: 'r',
    retry_of: null,
    status: 'running',
    completed_steps: 1,
    total_steps: 20,
    last_code: 'SIMULATED_STEP',
    source: {
      request: {
        agent_profile_id: 'a',
        dataset_id: 'd',
        dataset_revision_id: 'r',
        target: 'reranker',
        base_model: 'fake-reranker-v1',
        base_model_revision: 'fake-1',
        trainer: 'fake-v1',
        parameters: defaultParameters(),
        simulation_steps: 20,
      },
      agent_revision_id: 'r1',
      agent_config_sha256: 'a',
      manifest_sha256: 'b',
      content_sha256: 'c',
      splits: {},
      source_course_ids: [],
      dataset_review_sequence: 2,
      code_sha256: 'c',
      python_version: '3.11',
    },
    result: null,
    created_at: '',
    snapshot_sha256: 's',
  }
}
async function mount(component: typeof TrainingWizard, path = '/training/new') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/training/new', component: TrainingWizard },
      { path: '/training/runs/:runId', component: TrainingRunDetail },
      { path: '/training/adapters/:adapterId', component: TrainingAdapterDetail },
      { path: '/product', component: TrainingLayout },
    ],
  })
  await router.push(path)
  await router.isReady()
  const host = document.createElement('div')
  document.body.append(host)
  app = createApp(component)
  app.use(router)
  app.use(createPinia())
  app.mount(host)
  await Promise.resolve()
  return { host, router }
}
function button(host: HTMLElement, label: string): HTMLButtonElement {
  const found = [...host.querySelectorAll('button')].find((b) => b.textContent?.trim() === label)
  if (!found) throw new Error('Missing button ' + label)
  return found
}
async function select(host: HTMLElement, index: number, value: string) {
  const item = host.querySelectorAll('select')[index]!
  item.value = value
  item.dispatchEvent(new Event('change', { bubbles: true }))
  await Promise.resolve()
}
async function toReview(host: HTMLElement) {
  await vi.waitFor(() => expect(host.querySelector('select')?.options.length).toBe(3))
  await select(host, 0, 'a')
  await vi.waitFor(() => expect(host.textContent).toContain('固定版本'))
  button(host, '下一步').click()
  await vi.waitFor(() => expect(host.textContent).toContain('选择获准'))
  await select(host, 0, 'd')
  await vi.waitFor(() => expect(host.querySelectorAll('select')[1]?.options.length).toBe(2))
  await select(host, 1, 'r')
  await vi.waitFor(() => expect(host.textContent).toContain('当前数据具备使用资格'))
  button(host, '下一步').click()
  await vi.waitFor(() => expect(host.textContent).toContain('确认训练目标'))
  button(host, '下一步').click()
  await vi.waitFor(() => expect(host.textContent).toContain('配置模拟参数'))
  button(host, '下一步').click()
  await vi.waitFor(() => expect(host.textContent).toContain('复核后提交'))
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(agents.fetchAgentProfiles).mockResolvedValue([agent(), agent('b')])
  vi.mocked(agents.fetchAgentProfile).mockImplementation(async (id) => agent(id))
  vi.mocked(agents.fetchAgentProfileOptions).mockResolvedValue({
    edition: 'product',
    providers: [],
    evaluation_profiles: [],
    external_search_enabled: false,
  })
  vi.mocked(api.datasets).mockResolvedValue([
    { id: 'd', name: '合成数据', row_version: 4, created_at: '' },
  ])
  vi.mocked(api.revisions).mockResolvedValue([revision])
  vi.mocked(api.revision).mockResolvedValue(revision)
  vi.mocked(api.eligibility).mockResolvedValue({
    revision_id: 'r',
    eligible: true,
    reasons: [],
    report: revision.report,
  })
  vi.mocked(api.options).mockResolvedValue({
    worker_enabled: true,
    mode: 'simulated',
    base_models: [],
    max_simulation_steps: 100,
    checkpoint_interval_seconds: 0.2,
  })
  vi.mocked(api.estimate).mockResolvedValue({
    mode: 'simulated',
    nominal_simulation_seconds: 4,
    available_memory_bytes: null,
    real_training_seconds: null,
    real_vram_bytes: null,
    real_cost: null,
    note: '',
  })
  vi.mocked(api.run).mockResolvedValue(run())
  vi.mocked(api.events).mockResolvedValue([])
})
afterEach(() => {
  app?.unmount()
  app = undefined
  document.body.replaceChildren()
  vi.useRealTimers()
})
describe('training workflow', () => {
  it('ignores a late agent response after a different selection', async () => {
    let resolve!: (value: AgentProfile) => void
    vi.mocked(agents.fetchAgentProfile).mockImplementation((id) =>
      id === 'a'
        ? new Promise((r) => {
            resolve = r
          })
        : Promise.resolve(agent('b', 'r-b')),
    )
    const { host } = await mount(TrainingWizard)
    await vi.waitFor(() => expect(host.querySelector('select')?.options.length).toBe(3))
    await select(host, 0, 'a')
    await select(host, 0, 'b')
    await vi.waitFor(() => expect(host.textContent).toContain('r-b'))
    resolve(agent('a', 'r-old'))
    await Promise.resolve()
    expect(host.textContent).not.toContain('r-old')
  })
  it('preserves review state after network loss and reuses the submission key', async () => {
    vi.mocked(api.createRun).mockRejectedValue({ code: 'NETWORK_ERROR', message: '连接已中断' })
    const { host } = await mount(TrainingWizard)
    await toReview(host)
    button(host, '创建模拟训练任务').click()
    await vi.waitFor(() => expect(host.textContent).toContain('输入已保留'))
    expect(host.textContent).toContain('复核后提交')
    button(host, '创建模拟训练任务').click()
    await vi.waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(2))
    expect(vi.mocked(api.createRun).mock.calls[0]![0].idempotency_key).toBe(
      vi.mocked(api.createRun).mock.calls[1]![0].idempotency_key,
    )
    expect(vi.mocked(api.createRun).mock.calls[0]![0].expected_agent_revision_id).toBe('r1')
  })
  it('prevents a second submit while the first request is pending', async () => {
    vi.mocked(api.createRun).mockImplementation(() => new Promise(() => {}))
    const { host } = await mount(TrainingWizard)
    await toReview(host)
    const submit = button(host, '创建模拟训练任务')
    submit.click()
    submit.click()
    await vi.waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1))
  })
  it('requires re-review when the selected agent revision has changed', async () => {
    const { host } = await mount(TrainingWizard)
    await toReview(host)
    vi.mocked(agents.fetchAgentProfile).mockResolvedValue(agent('a', 'r2'))
    button(host, '创建模拟训练任务').click()
    await vi.waitFor(() => expect(host.textContent).toContain('版本或启用状态已变化'))
    expect(api.createRun).not.toHaveBeenCalled()
  })
  it('stops polling after unmount', async () => {
    vi.useFakeTimers()
    const { host } = await mount(TrainingRunDetail, '/training/runs/run')
    await vi.waitFor(() => expect(host.textContent).toContain('模拟运行中'))
    const count = vi.mocked(api.run).mock.calls.length
    app?.unmount()
    app = undefined
    await vi.advanceTimersByTimeAsync(5000)
    expect(api.run).toHaveBeenCalledTimes(count)
  })
  it('does not show an old cancellation error after changing the task route', async () => {
    let reject!: (reason: unknown) => void
    vi.mocked(api.run).mockImplementation(async (id) => run(id))
    vi.mocked(api.cancel).mockImplementation(
      () =>
        new Promise((_, r) => {
          reject = r
        }),
    )
    const { host, router } = await mount(TrainingRunDetail, '/training/runs/old-run')
    await vi.waitFor(() => expect(host.textContent).toContain('old-run'))
    button(host, '取消模拟任务').click()
    await vi.waitFor(() => expect(api.cancel).toHaveBeenCalledTimes(1))
    await router.push('/training/runs/new-run')
    await vi.waitFor(() => expect(host.textContent).toContain('new-run'))
    reject({ code: 'CONFLICT', message: '旧任务取消失败' })
    await vi.waitFor(() => expect(button(host, '取消模拟任务').disabled).toBe(false))
    expect(host.textContent).not.toContain('旧任务取消失败')
    expect(host.querySelector('[role="alert"]')).toBeNull()
  })
  it('does not archive an old adapter after its confirmation outlives the route', async () => {
    let confirm!: () => void
    vi.mocked(ElMessageBox.confirm).mockImplementation(
      () =>
        new Promise((r) => {
          confirm = () =>
            r(Object.assign('confirm' as const, { value: '', action: 'confirm' as const }))
        }),
    )
    vi.mocked(api.adapter).mockImplementation(async (id) => ({
      id,
      run_id: 'run',
      predecessor_id: null,
      manifest_sha256: 'hash',
      artifact_kind: 'simulated',
      deployable: false,
      evaluation_status: 'not_evaluated',
      integrity: 'valid',
      created_at: '',
      archived_at: null,
      manifest: {
        source: run().source,
        result: {
          artifact_kind: 'simulated',
          deployable: false,
          evaluation_status: 'not_evaluated',
          trainer: 'fake-v1',
          simulation_checksum: 'checksum',
        },
        finished_at: 1,
        run_snapshot_sha256: 'snapshot',
        dataset_schema_version: 1,
      },
    }))
    vi.mocked(api.lineage).mockResolvedValue({ items: [], next_predecessor_id: null })
    const { host, router } = await mount(TrainingAdapterDetail, '/training/adapters/old-adapter')
    await vi.waitFor(() => expect(host.textContent).toContain('old-adapter'))
    button(host, '归档产物').click()
    await vi.waitFor(() => expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1))
    await router.push('/training/adapters/new-adapter')
    await vi.waitFor(() => expect(host.textContent).toContain('new-adapter'))
    confirm()
    await vi.waitFor(() => expect(button(host, '归档产物').disabled).toBe(false))
    expect(api.archive).not.toHaveBeenCalled()
    expect(host.querySelector('[role="alert"]')).toBeNull()
  })
  it('blocks product direct routes before child training requests', async () => {
    const { host } = await mount(TrainingLayout, '/product')
    await vi.waitFor(() => expect(host.textContent).toContain('此功能仅在科研版提供'))
    expect(api.datasets).not.toHaveBeenCalled()
    expect(host.querySelector('.training-tabs')).toBeNull()
  })
})
