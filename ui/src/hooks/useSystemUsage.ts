import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'

export interface SystemOSInfo {
  goos: string
  goarch: string
  name?: string
  version?: string
  architecture?: string
}

export interface SystemRuntimeInfo {
  go_version: string
  num_cpu: number
  uptime_seconds: number
  process_alloc_bytes: number
  process_sys_bytes: number
  process_heap_alloc_bytes: number
}

export interface SystemMemoryInfo {
  total_bytes: number
  available_bytes: number
  used_bytes: number
  used_percent: number
}

export interface SystemCPUInfo {
  name: string
  cores: number
  logical_processors: number
}

export interface SystemDeviceInfo {
  name: string
  memory_bytes?: number
}

export interface SystemStorageInfo {
  name: string
  total_bytes: number
  free_bytes: number
  used_bytes: number
  used_percent: number
  file_system?: string
  volume_name?: string
}

export interface SystemUsage {
  collected_at: string
  os: SystemOSInfo
  runtime: SystemRuntimeInfo
  memory: SystemMemoryInfo
  cpu: SystemCPUInfo[]
  gpu: SystemDeviceInfo[]
  npu: SystemDeviceInfo[]
  storage: SystemStorageInfo[]
  configuration: Record<string, string>
}

export function useSystemUsage() {
  return useQuery({
    queryKey: ['system-usage'],
    queryFn: () => apiClient<SystemUsage>('/system/usage'),
    refetchInterval: 15_000,
  })
}
