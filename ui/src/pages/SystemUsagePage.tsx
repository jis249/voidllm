import type { ReactNode } from 'react'
import { PageHeader } from '../components/ui/PageHeader'
import { StatCard } from '../components/ui/StatCard'
import { useMe } from '../hooks/useMe'
import { useSystemUsage } from '../hooks/useSystemUsage'
import type { SystemStorageInfo } from '../hooks/useSystemUsage'
import { formatBytes, formatNumber, formatDate } from '../lib/utils'

function IconCpu() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" />
    </svg>
  )
}

function IconStorage() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </svg>
  )
}

function IconMemory() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <rect x="5" y="7" width="14" height="10" rx="2" />
      <path d="M8 3v4M12 3v4M16 3v4M8 17v4M12 17v4M16 17v4M2 10h3M2 14h3M19 10h3M19 14h3" />
    </svg>
  )
}

function formatDuration(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

function percent(value: number | undefined): string {
  if (value == null || !Number.isFinite(value)) return '0%'
  return `${Math.round(value)}%`
}

function Meter({ value }: { value: number }) {
  const safeValue = Math.max(0, Math.min(100, value || 0))
  return (
    <div className="h-2 rounded-full bg-bg-tertiary overflow-hidden">
      <div className="h-full rounded-full bg-accent" style={{ width: `${safeValue}%` }} />
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-bg-secondary p-6">
      <h2 className="mb-4 text-lg font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  )
}

function StorageRow({ disk }: { disk: SystemStorageInfo }) {
  return (
    <div className="rounded-lg border border-border bg-bg-primary p-4">
      <div className="mb-3 flex items-center justify-between gap-4">
        <div>
          <div className="font-mono text-sm text-text-primary">{disk.name}</div>
          <div className="text-xs text-text-tertiary">
            {[disk.volume_name, disk.file_system].filter(Boolean).join(' · ') || 'Local disk'}
          </div>
        </div>
        <div className="text-right text-sm text-text-secondary">
          {formatBytes(disk.used_bytes)} / {formatBytes(disk.total_bytes)}
        </div>
      </div>
      <Meter value={disk.used_percent} />
      <div className="mt-2 flex justify-between text-xs text-text-tertiary">
        <span>{percent(disk.used_percent)} used</span>
        <span>{formatBytes(disk.free_bytes)} free</span>
      </div>
    </div>
  )
}

export default function SystemUsagePage() {
  const { data: me } = useMe()
  const { data, isLoading, error } = useSystemUsage(me?.is_system_admin === true)

  if (me && !me.is_system_admin) {
    return (
      <>
        <PageHeader title="System Usage" description="Host resource usage and runtime configuration" />
        <div className="rounded-lg border border-border bg-bg-secondary p-12 text-center">
          <p className="text-sm text-text-tertiary">You need system admin permissions to view system usage.</p>
        </div>
      </>
    )
  }

  const memoryUsed = data?.memory?.used_percent ?? 0
  const storageTotal = data?.storage?.reduce((sum, d) => sum + d.total_bytes, 0) ?? 0
  const storageUsed = data?.storage?.reduce((sum, d) => sum + d.used_bytes, 0) ?? 0
  const storagePercent = storageTotal > 0 ? (storageUsed / storageTotal) * 100 : 0

  return (
    <>
      <PageHeader
        title="System Usage"
        description="Admin-only host resource usage, hardware inventory, and safe runtime configuration."
      />

      {error instanceof Error && (
        <div className="mb-6 rounded-lg border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error.message}
        </div>
      )}

      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="CPU Threads"
            value={isLoading ? '...' : formatNumber(data?.runtime.num_cpu ?? 0)}
            icon={<IconCpu />}
            iconColor="purple"
          />
          <StatCard
            label="Memory Used"
            value={isLoading ? '...' : percent(memoryUsed)}
            icon={<IconMemory />}
            iconColor="blue"
          />
          <StatCard
            label="Storage Used"
            value={isLoading ? '...' : percent(storagePercent)}
            icon={<IconStorage />}
            iconColor="green"
          />
          <StatCard
            label="Backend Uptime"
            value={isLoading ? '...' : formatDuration(data?.runtime.uptime_seconds ?? 0)}
            icon={<IconCpu />}
            iconColor="pink"
          />
        </div>

        <Section title="System">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Info label="OS" value={data?.os.name || data?.os.goos || 'Unknown'} />
            <Info label="Version" value={data?.os.version || 'Unknown'} />
            <Info label="Architecture" value={data?.os.architecture || data?.os.goarch || 'Unknown'} />
            <Info label="Collected" value={data?.collected_at ? formatDate(data.collected_at) : '...'} />
          </div>
        </Section>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Section title="CPU">
            <div className="space-y-3">
              {(data?.cpu ?? []).length > 0 ? data?.cpu.map((cpu) => (
                <div key={cpu.name} className="rounded-lg border border-border bg-bg-primary p-4">
                  <div className="text-sm font-medium text-text-primary">{cpu.name}</div>
                  <div className="mt-2 text-sm text-text-secondary">
                    {formatNumber(cpu.cores)} cores · {formatNumber(cpu.logical_processors)} logical processors
                  </div>
                </div>
              )) : <p className="text-sm text-text-tertiary">CPU inventory unavailable.</p>}
            </div>
          </Section>

          <Section title="Memory">
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-text-secondary">Used</span>
                <span className="text-text-primary">
                  {formatBytes(data?.memory.used_bytes ?? 0)} / {formatBytes(data?.memory.total_bytes ?? 0)}
                </span>
              </div>
              <Meter value={memoryUsed} />
              <div className="text-xs text-text-tertiary">
                {formatBytes(data?.memory.available_bytes ?? 0)} available
              </div>
              <div className="pt-3 text-sm text-text-secondary">
                Backend process heap: <span className="text-text-primary">{formatBytes(data?.runtime.process_heap_alloc_bytes ?? 0)}</span>
              </div>
            </div>
          </Section>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Section title="GPU">
            <DeviceList devices={data?.gpu ?? []} empty="No GPU devices reported." />
          </Section>
          <Section title="NPU">
            <DeviceList devices={data?.npu ?? []} empty="No NPU devices reported." />
          </Section>
        </div>

        <Section title="Storage">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {(data?.storage ?? []).length > 0
              ? data?.storage.map((disk) => <StorageRow key={disk.name} disk={disk} />)
              : <p className="text-sm text-text-tertiary">Storage inventory unavailable.</p>}
          </div>
        </Section>

        <Section title="Configuration">
          {Object.keys(data?.configuration ?? {}).length > 0 ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {Object.entries(data?.configuration ?? {}).map(([key, value]) => (
                <Info key={key} label={key} value={value} monospace />
              ))}
            </div>
          ) : (
            <p className="text-sm text-text-tertiary">No safe runtime configuration values are set.</p>
          )}
        </Section>
      </div>
    </>
  )
}

function Info({ label, value, monospace = false }: { label: string; value: string; monospace?: boolean }) {
  return (
    <div className="rounded-lg border border-border bg-bg-primary p-4">
      <div className="text-xs uppercase tracking-wide text-text-tertiary">{label}</div>
      <div className={monospace ? 'mt-1 font-mono text-sm text-text-primary' : 'mt-1 text-sm text-text-primary'}>
        {value}
      </div>
    </div>
  )
}

function DeviceList({ devices, empty }: { devices: { name: string; memory_bytes?: number }[]; empty: string }) {
  if (devices.length === 0) {
    return <p className="text-sm text-text-tertiary">{empty}</p>
  }
  return (
    <div className="space-y-3">
      {devices.map((device) => (
        <div key={device.name} className="rounded-lg border border-border bg-bg-primary p-4">
          <div className="text-sm font-medium text-text-primary">{device.name}</div>
          {device.memory_bytes != null && device.memory_bytes > 0 && (
            <div className="mt-2 text-sm text-text-secondary">Memory: {formatBytes(device.memory_bytes)}</div>
          )}
        </div>
      ))}
    </div>
  )
}
