import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, reactive, type App } from 'vue'
import ConversationAgentControl from '../ConversationAgentControl.vue'
import * as api from '@/api/agentProfiles'
import { fetchCourses } from '@/api/courses'
import { defaultAgentConfig } from '@/utils/agents'
import type { AgentProfile, AgentRevision, ConversationAgentState } from '@/types/api'

vi.mock('@/api/agentProfiles', () => ({
  fetchAgentProfile: vi.fn<typeof api.fetchAgentProfile>(),
  fetchAgentProfiles: vi.fn<typeof api.fetchAgentProfiles>(),
  fetchAgentProfileOptions: vi.fn<typeof api.fetchAgentProfileOptions>(),
  fetchAgentRevision: vi.fn<typeof api.fetchAgentRevision>(),
}))
vi.mock('@/api/courses', () => ({ fetchCourses: vi.fn<typeof fetchCourses>() }))
let app: App | undefined
function revision(id: string, n: number, model: string): AgentRevision {
  const config = defaultAgentConfig()
  config.model = { provider: 'test', model }
  return {
    id,
    agent_profile_id: 'p',
    revision_number: n,
    config,
    config_sha256: 'a'.repeat(64),
    change_summary: 'test',
    created_at: '2026-09-09T00:00:00Z',
  }
}
function profile(id = 'p'): AgentProfile {
  return {
    id,
    name: '智能体 ' + id,
    description: null,
    enabled: true,
    deleted_at: null,
    row_version: 2,
    created_at: '2026-09-09T00:00:00Z',
    updated_at: '2026-09-09T00:00:00Z',
    current_revision: revision('r2', 2, 'b'),
  }
}
function mount(locked = false) {
  const props = reactive({
    modelValue: 'p',
    locked,
    busy: false,
    binding: locked
      ? { agent_profile_id: 'p', agent_profile_revision_id: 'r1' }
      : (null as { agent_profile_id: string; agent_profile_revision_id: string } | null),
  })
  const states: ConversationAgentState[] = []
  const host = document.createElement('div')
  document.body.append(host)
  app = createApp({
    render: () =>
      h(ConversationAgentControl, {
        ...props,
        onState: (state: ConversationAgentState) => states.push(state),
      }),
  })
  app.component('RouterLink', { render: () => h('a', '管理智能体') })
  app.mount(host)
  return { props, states, host }
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.fetchAgentProfiles).mockResolvedValue([profile()])
  vi.mocked(api.fetchAgentProfile).mockImplementation(async (id) => profile(id))
  vi.mocked(api.fetchAgentRevision).mockResolvedValue(revision('r1', 1, 'a'))
  vi.mocked(api.fetchAgentProfileOptions).mockResolvedValue({
    edition: 'product',
    providers: [{ id: 'test', name: 'Test', models: ['a', 'b'], configured: true }],
    evaluation_profiles: [],
    external_search_enabled: true,
  })
  vi.mocked(fetchCourses).mockResolvedValue([])
})
afterEach(() => {
  app?.unmount()
  app = undefined
  document.body.replaceChildren()
})
describe('conversation agent binding', () => {
  it('loads pinned r1 while the profile current version is r2', async () => {
    const { states, host } = mount(true)
    await vi.waitFor(() => expect(states[states.length - 1]?.ready).toBe(true))
    expect(api.fetchAgentRevision).toHaveBeenCalledWith('p', 'r1')
    expect(states[states.length - 1]?.config?.model.model).toBe('a')
    expect(host.textContent).toContain('固定版本 r1')
    expect(host.querySelector('select')).toBeNull()
  })
  it('keeps history identity visible but disables a stopped profile', async () => {
    vi.mocked(api.fetchAgentProfile).mockResolvedValue({ ...profile(), enabled: false })
    const { states, host } = mount(true)
    await vi.waitFor(() => expect(host.textContent).toContain('已停用'))
    expect(states[states.length - 1]?.ready).toBe(false)
    expect(states[states.length - 1]?.config?.model.model).toBe('a')
  })
  it('keeps a deleted profile revision visible without offering reactivation', async () => {
    vi.mocked(api.fetchAgentProfile).mockResolvedValue({
      ...profile(),
      enabled: false,
      deleted_at: '2026-09-10T00:00:00Z',
    })
    vi.mocked(api.fetchAgentProfiles).mockResolvedValue([])
    const { states, host } = mount(true)
    await vi.waitFor(() => expect(host.textContent).toContain('已删除'))
    expect(states[states.length - 1]?.ready).toBe(false)
    expect(host.textContent).toContain('固定版本 r1')
    expect(host.textContent).not.toContain('重新启用后')
  })
  it('ignores a delayed response after selecting another agent', async () => {
    let finish!: (value: AgentProfile) => void
    vi.mocked(api.fetchAgentProfile).mockImplementation((id) =>
      id === 'p'
        ? new Promise((resolve) => {
            finish = resolve
          })
        : Promise.resolve(profile(id)),
    )
    const { props, states } = mount()
    props.modelValue = 'other'
    await vi.waitFor(() => expect(states[states.length - 1]?.profileId).toBe('other'))
    await vi.waitFor(() => expect(states[states.length - 1]?.ready).toBe(true))
    finish(profile())
    await Promise.resolve()
    await Promise.resolve()
    expect(states[states.length - 1]?.profileId).toBe('other')
  })
  it('blocks sending when bound model validation cannot load', async () => {
    vi.mocked(api.fetchAgentProfileOptions).mockRejectedValue({
      code: 'NETWORK_ERROR',
      message: '模型配置读取失败',
    })
    const { states, host } = mount(true)
    await vi.waitFor(() => expect(host.textContent).toContain('模型配置读取失败'))
    expect(states[states.length - 1]?.ready).toBe(false)
  })
})
