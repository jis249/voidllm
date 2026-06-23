import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'

export interface AuditEvent {
  id: string
  timestamp: string
  org_id: string
  actor_id: string
  actor_type: string
  actor_key_id: string
  action: string
  resource_type: string
  resource_id: string
  description: string
  ip_address: string
  status_code: number
  request_id: string
}

export interface AuditLogResponse {
  data: AuditEvent[]
  has_more: boolean
  cursor?: string
}

export interface AuditLogParams {
  orgId: string
  actorId: string
  resourceType: string
  action: string
  from: string
  to: string
  limit: number
  cursor: string
  enabled?: boolean
}

export function useAuditLog(params: AuditLogParams) {
  const { orgId, actorId, resourceType, action, from, to, limit, cursor, enabled = true } = params

  const query = new URLSearchParams({
    limit: String(limit),
  })
  if (orgId) query.set('org_id', orgId)
  if (cursor) query.set('cursor', cursor)
  if (actorId) query.set('actor_id', actorId)
  if (resourceType) query.set('resource_type', resourceType)
  if (action) query.set('action', action)
  if (from) query.set('from', from)
  if (to) query.set('to', to)

  return useQuery({
    queryKey: ['audit-log', orgId, actorId, resourceType, action, from, to, limit, cursor],
    queryFn: () => apiClient<AuditLogResponse>(`/audit-logs?${query.toString()}`),
    enabled,
    staleTime: 30_000,
  })
}
