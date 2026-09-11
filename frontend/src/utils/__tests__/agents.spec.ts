import { describe, expect, it } from 'vitest'
import { configChanges, defaultAgentConfig, modelAvailable, validateAgentConfig } from '../agents'
import type { AgentProfileOptions } from '@/types/api'
const options: AgentProfileOptions = {
  edition: 'research',
  providers: [{ id: 'test', name: '测试', models: ['a'], configured: true }],
  evaluation_profiles: [],
  external_search_enabled: false,
}
function config() {
  const value = defaultAgentConfig()
  value.model = { provider: 'test', model: 'a' }
  return value
}
describe('agent editor contracts', () => {
  it('does not require a research catalog to edit historical product settings', () => {
    const value = config()
    value.evaluation_profiles = [
      {
        profile_id: 'old-research',
        registry_version: '1',
        registry_sha256: 'a'.repeat(64),
        usage: 'offline',
      },
    ]
    expect(
      validateAgentConfig(value, { ...options, edition: 'product', evaluation_profiles: [] }),
    ).toBe('')
    expect(validateAgentConfig(value, options)).toContain('评测引用已失效')
  })
  it('creates independent drafts without sharing nested mutable configuration', () => {
    const a = config(),
      b = config()
    a.tools.web_search = false
    a.allowed_course_ids.push('space')
    expect(b.tools.web_search).toBe(true)
    expect(b.allowed_course_ids).toEqual([])
  })
  it('rejects missing credentials and ambiguous model routes', () => {
    expect(modelAvailable(config(), options)).toBe(true)
    expect(
      modelAvailable(config(), {
        ...options,
        providers: [{ ...options.providers[0]!, configured: false }],
      }),
    ).toBe(false)
    expect(
      modelAvailable(config(), {
        ...options,
        providers: [
          ...options.providers,
          { id: 'other', name: 'Other', models: ['a'], configured: true },
        ],
      }),
    ).toBe(false)
  })
  it.each(['answer', 'summary', 'exam'] as const)('validates %s candidate bounds', (task) => {
    const value = config()
    value.retrieval[`${task}_candidate_k`] = 1
    expect(validateAgentConfig(value, options)).toContain('返回数量')
  })
  it('rejects stale offline registry grants and unsupported usage', () => {
    const value = config()
    value.evaluation_profiles = [
      { profile_id: 'p', registry_version: 'v1', registry_sha256: 'old', usage: 'advisory' },
    ]
    const available = {
      ...options,
      evaluation_profiles: [
        {
          profile_id: 'p',
          registry_version: 'v1',
          registry_sha256: 'new',
          allowed_usages: ['offline' as const],
        },
      ],
    }
    expect(validateAgentConfig(value, available)).toContain('评测引用已失效')
    value.evaluation_profiles[0]!.registry_sha256 = 'new'
    value.evaluation_profiles[0]!.usage = 'offline'
    expect(validateAgentConfig(value, available)).toBe('')
  })
  it('shows independent changed groups for historical comparison', () => {
    const before = config(),
      after = config()
    after.model.model = 'b'
    after.context.quick_max_messages = 2
    after.system_prompt = 'new'
    expect(configChanges(before, after)).toEqual(['系统提示', '供应商 / 模型', '上下文预算'])
    expect(before.model.model).toBe('a')
  })
})
