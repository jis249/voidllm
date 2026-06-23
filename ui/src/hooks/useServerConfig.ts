import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'

export interface ServerConfig {
  fallback_max_depth: number
}

export function useServerConfig(enabled = true) {
  return useQuery({
    queryKey: ['server-config'],
    queryFn: () => apiClient<ServerConfig>('/server-config'),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}
