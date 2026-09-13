import { http } from './http'
import { unwrapResponse } from './client'
import type { ApiResponse } from '@/types/api'
import type {
  Adapter,
  Dataset,
  DatasetRevision,
  Eligibility,
  Estimate,
  Manifest,
  Review,
  ReviewStatus,
  RunInput,
  TrainingEvent,
  TrainingOptions,
  TrainingRun,
  ValidationReport,
} from '@/types/training'
const id = encodeURIComponent
async function get<T>(path: string, params = {}): Promise<T> {
  return unwrapResponse((await http.get<ApiResponse<T>>(path, { params })).data)
}
async function post<T>(path: string, body?: unknown): Promise<T> {
  return unwrapResponse((await http.post<ApiResponse<T>>(path, body)).data)
}
export const datasets = (offset = 0) => get<Dataset[]>('/training-datasets', { limit: 20, offset })
export const dataset = (key: string) => get<Dataset>('/training-datasets/' + id(key))
export const createDataset = (name: string) => post<Dataset>('/training-datasets', { name })
export const revisions = (key: string, offset = 0) =>
  get<DatasetRevision[]>('/training-datasets/' + id(key) + '/revisions', { limit: 20, offset })
const revPath = (key: string, rev: string) => `/training-datasets/${id(key)}/revisions/${id(rev)}`
export const revision = (key: string, rev: string) => get<DatasetRevision>(revPath(key, rev))
export const reviews = (key: string, rev: string, offset = 0) =>
  get<Review[]>(revPath(key, rev) + '/reviews', { limit: 20, offset })
export const review = (
  key: string,
  rev: string,
  expected_row_version: number,
  status: Exclude<ReviewStatus, 'draft'>,
  reviewer: string,
  note: string,
) => post<Review>(revPath(key, rev) + '/reviews', { expected_row_version, status, reviewer, note })
export const eligibility = (key: string, rev: string, agent: string) =>
  get<Eligibility>(revPath(key, rev) + '/eligibility', { agent_profile_id: agent })
function form(manifest: Manifest, file: File, version?: number): FormData {
  const data = new FormData()
  data.append('manifest', JSON.stringify(manifest))
  data.append('file', file)
  if (version !== undefined) data.append('expected_row_version', String(version))
  return data
}
export const validate = (manifest: Manifest, file: File) =>
  post<ValidationReport>('/training-datasets/validate', form(manifest, file))
export const upload = (key: string, version: number, manifest: Manifest, file: File) =>
  post<DatasetRevision>(
    '/training-datasets/' + id(key) + '/revisions',
    form(manifest, file, version),
  )
export const options = () => get<TrainingOptions>('/training-runs/options')
export const estimate = (input: RunInput) => post<Estimate>('/training-runs/estimate', input)
export const createRun = (input: RunInput) => post<TrainingRun>('/training-runs', input)
export const runs = (offset = 0, agent?: string) =>
  get<TrainingRun[]>('/training-runs', { limit: 20, offset, agent_profile_id: agent || undefined })
export const run = (key: string) => get<TrainingRun>('/training-runs/' + id(key))
export const events = (key: string, after = 0) =>
  get<TrainingEvent[]>('/training-runs/' + id(key) + '/events', { after, limit: 100 })
export const cancel = (key: string) => post<TrainingRun>('/training-runs/' + id(key) + '/cancel')
export const retry = (key: string, token: string) =>
  post<TrainingRun>('/training-runs/' + id(key) + '/retry', { idempotency_key: token })
export const adapters = (offset = 0, include_archived = false, agent?: string) =>
  get<Adapter[]>('/model-adapters', {
    offset,
    limit: 20,
    include_archived,
    agent_profile_id: agent || undefined,
  })
export const adapter = (key: string) => get<Adapter>('/model-adapters/' + id(key))
export const fromRun = (key: string) => post<Adapter>('/model-adapters/from-run/' + id(key))
export const archive = (key: string) => post<Adapter>('/model-adapters/' + id(key) + '/archive')
export const lineage = (key: string) =>
  get<{ items: Adapter[]; next_predecessor_id: string | null }>(
    '/model-adapters/' + id(key) + '/lineage',
  )
