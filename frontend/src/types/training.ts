export type Target = 'scorer' | 'reranker'
export type ReviewStatus = 'draft' | 'pending_review' | 'approved' | 'rejected' | 'revoked'
export type RunStatus =
  'queued' | 'running' | 'cancelling' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted'
export interface Manifest {
  schema_version: 1
  target: Target
  source: string
  license_id: string
  license_notes: string
  training_allowed: boolean
  pii_status: 'pending' | 'clean' | 'redacted'
  pii_notes: string
  source_course_ids: string[]
}
export interface SplitSummary {
  count: number
  sha256: string
}
export interface ValidationReport {
  valid: boolean
  approvable: boolean
  content_sha256: string
  byte_count: number
  sample_count: number
  splits: Partial<Record<'train' | 'validation', SplitSummary>>
  issues: { code: string; line: number | null; related_line: number | null }[]
  issue_count: number
  dedup_method: string
  validator_version: string
}
export interface Dataset {
  id: string
  name: string
  row_version: number
  created_at: string
}
export interface DatasetRevision {
  id: string
  dataset_id: string
  revision_number: number
  manifest: Manifest
  manifest_sha256: string
  report: ValidationReport
  status: ReviewStatus
  created_at: string
}
export interface Review {
  id: string
  sequence: number
  status: ReviewStatus
  reviewer: string
  note: string
  created_at: string
}
export interface Eligibility {
  revision_id: string
  eligible: boolean
  reasons: string[]
  report: ValidationReport | null
}
export interface Parameters {
  method: 'lora' | 'qlora'
  rank: number
  alpha: number
  dropout: number
  learning_rate: number
  batch_size: number
  accumulation_steps: number
  epochs: number
  max_length: number
  seed: number
}
export interface RunInput {
  idempotency_key: string
  agent_profile_id: string
  expected_agent_revision_id?: string | null
  dataset_id: string
  dataset_revision_id: string
  target: Target
  base_model: string
  base_model_revision: 'fake-1'
  trainer: 'fake-v1'
  parameters: Parameters
  simulation_steps: number
  predecessor_adapter_id?: string | null
}
export interface TrainingSource {
  request: Omit<RunInput, 'idempotency_key'>
  agent_revision_id: string
  agent_config_sha256: string
  manifest_sha256: string
  content_sha256: string
  splits: Partial<Record<'train' | 'validation', SplitSummary>>
  source_course_ids: string[]
  dataset_review_sequence: number
  code_sha256: string
  python_version: string
}
export interface SimulationResult {
  artifact_kind: 'simulated'
  deployable: false
  evaluation_status: 'not_evaluated'
  trainer: 'fake-v1'
  simulation_checksum: string
}
export interface TrainingRun {
  id: string
  agent_profile_id: string
  agent_revision_id: string
  dataset_revision_id: string
  retry_of: string | null
  status: RunStatus
  completed_steps: number
  total_steps: number
  last_code: string
  source: TrainingSource
  result: SimulationResult | null
  created_at: string
  snapshot_sha256: string
}
export interface TrainingEvent {
  run_id: string
  sequence: number
  phase: RunStatus
  code: string
  completed_steps: number
  total_steps: number
  created_at: string
}
export interface TrainingOptions {
  worker_enabled: boolean
  mode: 'simulated'
  base_models: string[]
  max_simulation_steps: number
  checkpoint_interval_seconds: number
}
export interface Estimate {
  mode: 'simulated'
  nominal_simulation_seconds: number
  available_memory_bytes: number | null
  real_training_seconds: null
  real_vram_bytes: null
  real_cost: null
  note: string
}
export interface Adapter {
  id: string
  run_id: string
  predecessor_id: string | null
  manifest_sha256: string
  artifact_kind: 'simulated'
  deployable: false
  evaluation_status: 'not_evaluated'
  integrity: 'valid' | 'missing' | 'invalid'
  created_at: string
  archived_at: string | null
  manifest: {
    source: TrainingSource
    result: SimulationResult
    finished_at: number
    run_snapshot_sha256: string
    dataset_schema_version: 1
  }
}
