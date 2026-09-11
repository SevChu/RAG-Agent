import { http } from './http'
import { unwrapResponse } from './client'
import type {
  ApiResponse,
  AgentProfile,
  AgentProfileCreatePayload,
  AgentProfileUpdatePayload,
  AgentProfileCopyPayload,
  AgentProfileRestorePayload,
  AgentProfileOptions,
  AgentRevision,
} from '@/types/api'

const pathFor = (id: string) => '/agent-profiles/' + encodeURIComponent(id)

export async function fetchAgentProfileOptions(): Promise<AgentProfileOptions> {
  const response = await http.get<ApiResponse<AgentProfileOptions>>('/agent-profiles/options')
  return unwrapResponse(response.data)
}

export async function fetchAgentProfiles(
  params: { enabled?: boolean; limit?: number; offset?: number } = {},
): Promise<AgentProfile[]> {
  const response = await http.get<ApiResponse<AgentProfile[]>>('/agent-profiles', { params })
  return unwrapResponse(response.data)
}

export async function fetchAgentProfile(id: string): Promise<AgentProfile> {
  const response = await http.get<ApiResponse<AgentProfile>>(pathFor(id))
  return unwrapResponse(response.data)
}

export async function createAgentProfile(
  payload: AgentProfileCreatePayload,
): Promise<AgentProfile> {
  const response = await http.post<ApiResponse<AgentProfile>>('/agent-profiles', payload)
  return unwrapResponse(response.data)
}

export async function updateAgentProfile(
  id: string,
  payload: AgentProfileUpdatePayload,
): Promise<AgentProfile> {
  const response = await http.patch<ApiResponse<AgentProfile>>(pathFor(id), payload)
  return unwrapResponse(response.data)
}

export async function copyAgentProfile(
  id: string,
  payload: AgentProfileCopyPayload,
): Promise<AgentProfile> {
  const response = await http.post<ApiResponse<AgentProfile>>(pathFor(id) + '/copy', payload)
  return unwrapResponse(response.data)
}

export async function fetchAgentRevisions(
  id: string,
  params: { limit?: number; offset?: number } = {},
): Promise<AgentRevision[]> {
  const response = await http.get<ApiResponse<AgentRevision[]>>(pathFor(id) + '/revisions', {
    params,
  })
  return unwrapResponse(response.data)
}

export async function fetchAgentRevision(id: string, revisionId: string): Promise<AgentRevision> {
  const response = await http.get<ApiResponse<AgentRevision>>(
    pathFor(id) + '/revisions/' + encodeURIComponent(revisionId),
  )
  return unwrapResponse(response.data)
}

export async function restoreAgentProfile(
  id: string,
  payload: AgentProfileRestorePayload,
): Promise<AgentProfile> {
  const response = await http.post<ApiResponse<AgentProfile>>(pathFor(id) + '/restore', payload)
  return unwrapResponse(response.data)
}

export async function deleteAgentProfile(id: string, expectedRowVersion: number): Promise<void> {
  await http.delete<ApiResponse<null>>(pathFor(id), {
    params: { expected_row_version: expectedRowVersion },
  })
}
