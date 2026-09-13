import { onScopeDispose } from 'vue'
import type { Parameters, ReviewStatus, RunStatus } from '@/types/training'
export const reviewLabels: Record<ReviewStatus, string> = {
  draft: '草稿',
  pending_review: '待审核',
  approved: '已批准',
  rejected: '已拒绝',
  revoked: '已撤销',
}
export const runLabels: Record<RunStatus, string> = {
  queued: '排队中',
  running: '模拟运行中',
  cancelling: '正在取消',
  succeeded: '模拟成功',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
}
export const terminal = (state: RunStatus) =>
  ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(state)
export const defaultParameters = (): Parameters => ({
  method: 'lora',
  rank: 8,
  alpha: 16,
  dropout: 0.05,
  learning_rate: 0.0002,
  batch_size: 4,
  accumulation_steps: 1,
  epochs: 3,
  max_length: 512,
  seed: 42,
})
export const parameterFields = [
  { key: 'rank', label: '秩 rank', min: 1, max: 256, step: 1 },
  { key: 'alpha', label: '缩放 alpha', min: 1, max: 512, step: 1 },
  { key: 'dropout', label: 'Dropout', min: 0, max: 1, step: 'any' },
  { key: 'learning_rate', label: '学习率', min: 0, max: 1, step: 'any' },
  { key: 'batch_size', label: '批量大小', min: 1, max: 64, step: 1 },
  { key: 'accumulation_steps', label: '梯度累积步数', min: 1, max: 64, step: 1 },
  { key: 'epochs', label: '训练轮数', min: 1, max: 20, step: 1 },
  { key: 'max_length', label: '最大长度', min: 32, max: 4096, step: 1 },
  { key: 'seed', label: '随机种子', min: 0, max: 2147483647, step: 1 },
] as const
export function parameterError(parameters: Parameters, steps: number): string {
  if (!['lora', 'qlora'].includes(parameters.method)) return '请选择 LoRA 或 QLoRA。'
  for (const field of parameterFields) {
    const n = parameters[field.key]
    if (
      typeof n !== 'number' ||
      !Number.isFinite(n) ||
      (field.step === 1 && !Number.isInteger(n)) ||
      (field.key === 'learning_rate' ? n <= 0 : n < field.min) ||
      (field.key === 'dropout' ? n >= 1 : n > field.max)
    )
      return `${field.label}超出允许范围。`
  }
  return Number.isInteger(steps) && steps >= 1 && steps <= 100 ? '' : '模拟步数须为 1～100 的整数。'
}
export class RequestGate {
  private serial = 0
  private alive = true
  next(): number {
    return ++this.serial
  }
  current(ticket: number): boolean {
    return this.alive && ticket === this.serial
  }
  dispose(): void {
    this.alive = false
    this.serial++
  }
}
export function useRequestGate(): RequestGate {
  const gate = new RequestGate()
  onScopeDispose(() => gate.dispose())
  return gate
}
export class SubmissionIdentity {
  private content = ''
  private token = ''
  for(payload: unknown): string {
    const content = JSON.stringify(payload)
    if (content !== this.content || !this.token) {
      this.content = content
      this.token = crypto.randomUUID()
    }
    return this.token
  }
}
const codes: Record<string, string> = {
  QUEUED: '等待后台领取',
  SIMULATED_STEP: '已完成一个模拟步骤',
  SIMULATION_SUCCEEDED: '模拟完成，产物不可部署',
  TRAINER_FAILED: '模拟执行或产物保存失败，可检查后重试',
  FINAL_CHECK_FAILED: '完成前来源复核未通过',
  PRECHECK_FAILED: '任务来源或运行代码已变化，请重新创建',
  DATASET_REVOKED: '数据审核资格已撤销',
  AGENT_UNAVAILABLE: '智能体已停用或删除',
  SOURCE_SCOPE_REVOKED: '来源空间权限已收窄',
  SOURCE_DELETED: '来源空间已删除',
  WORKER_LOST: '后台中断，原任务不会自动续训',
  WORKER_SHUTDOWN: '后台关闭，原任务已中断',
  CANCEL_REQUESTED: '已收到取消请求',
  USER_CANCELLED: '用户取消',
  CLAIMED: '后台已领取任务',
}
export const eventLabel = (code: string) => codes[code] ?? '状态已更新'
