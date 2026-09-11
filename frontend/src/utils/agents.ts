import type { AgentConfiguration, AgentProfileOptions } from '@/types/api'

export function defaultAgentConfig(): AgentConfiguration {
  return {
    schema_version: 1,
    system_prompt: '',
    model: { provider: '', model: '' },
    allowed_course_ids: [],
    tools: { web_search: true },
    context: {
      strategy: 'bounded-history-v1',
      rag_max_messages: 6,
      rag_max_chars: 6000,
      quick_max_messages: 10,
      quick_max_chars: 8000,
    },
    retrieval: {
      strategy: 'course-rag-v1',
      answer_top_k: 6,
      answer_candidate_k: 20,
      summary_top_k: 12,
      summary_candidate_k: 40,
      summary_max_sources: 10,
      summary_context_max_chars: 8000,
      exam_top_k: 12,
      exam_candidate_k: 40,
      exam_max_sources: 10,
      exam_context_max_chars: 8000,
      min_similarity_score: 0.3,
    },
    evaluation_profiles: [],
  }
}

export function modelAvailable(config: AgentConfiguration, options: AgentProfileOptions): boolean {
  const provider = options.providers.find((item) => item.id === config.model.provider)
  return Boolean(
    provider?.configured &&
    provider.models.includes(config.model.model) &&
    options.providers.filter((item) => item.models.includes(config.model.model)).length === 1,
  )
}

export function validateAgentConfig(
  config: AgentConfiguration,
  options: AgentProfileOptions,
): string {
  if (!modelAvailable(config, options)) return '请选择已配置且无路由歧义的供应商和模型。'
  for (const task of ['answer', 'summary', 'exam'] as const) {
    if (config.retrieval[`${task}_top_k`] > config.retrieval[`${task}_candidate_k`]) {
      return '返回数量不能超过对应的候选数量。'
    }
  }
  for (const ref of options.edition === 'research' ? config.evaluation_profiles : []) {
    const option = options.evaluation_profiles.find((item) => item.profile_id === ref.profile_id)
    if (
      !option ||
      option.registry_sha256 !== ref.registry_sha256 ||
      option.registry_version !== ref.registry_version ||
      !option.allowed_usages.includes(ref.usage)
    ) {
      return '评测引用已失效，请取消后重新选择。'
    }
  }
  return ''
}

export function configChanges(before: AgentConfiguration, after: AgentConfiguration): string[] {
  const labels: Record<keyof AgentConfiguration, string> = {
    schema_version: '配置格式',
    system_prompt: '系统提示',
    model: '供应商 / 模型',
    allowed_course_ids: '允许空间',
    tools: '工具权限',
    context: '上下文预算',
    retrieval: '检索策略',
    evaluation_profiles: '研究评测引用',
  }
  return (Object.keys(labels) as (keyof AgentConfiguration)[])
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => labels[key])
}
