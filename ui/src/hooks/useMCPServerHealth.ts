import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'

export interface MCPServerHealth {
  server_id: string
  server_name: string
  alias: string
  status: 'healthy' | 'unhealthy' | 'unknown'
  last_check: string
  last_error?: string
  latency_ms: number
  tool_count: number
}

export function useMCPServerHealth() {
  return useQuery<MCPServerHealth[]>({
    queryKey: ['mcp-server-health'],
    queryFn: async () => {
      const data = await apiClient<MCPServerHealth[] | { servers?: MCPServerHealth[] }>(
        '/mcp-servers/health',
      )
      return Array.isArray(data) ? data : (data.servers ?? [])
    },
    refetchInterval: 15_000,
  })
}
