import { useMemo, type ReactNode } from 'react'
import { Dialog } from '../components/ui/Dialog'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import type { ModelResponse, DeploymentResponse } from '../hooks/useModels'
import type { ModelHealthInfo } from '../hooks/useModelHealth'
import { useCrossOrgUsage } from '../hooks/useUsage'
import { providerBadgeVariant, isKnownProvider } from '../lib/providers'
import type { ProviderKey } from '../lib/providers'
import { cn, formatCost, formatDate, formatNumber } from '../lib/utils'

const providerLabels: Record<ProviderKey, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  azure: 'Azure',
  vllm: 'vLLM',
  ollama: 'Ollama',
  custom: 'Custom',
}

const typeLabels: Record<string, string> = {
  chat: 'Chat',
  embedding: 'Embedding',
  reranking: 'Reranking',
  completion: 'Completion',
  image: 'Image',
  audio_transcription: 'Audio',
  tts: 'TTS',
}

const healthConfig: Record<
  ModelHealthInfo['status'],
  { dotClass: string; label: string; badge: 'success' | 'warning' | 'error' | 'muted' }
> = {
  healthy: { dotClass: 'bg-success', label: 'Healthy', badge: 'success' },
  degraded: { dotClass: 'bg-warning', label: 'Degraded', badge: 'warning' },
  unhealthy: { dotClass: 'bg-error', label: 'Unhealthy', badge: 'error' },
  unknown: { dotClass: 'bg-text-tertiary', label: 'Unknown', badge: 'muted' },
}

function PerfBadge({ ms }: { ms: number }) {
  if (ms <= 0) return null
  if (ms < 100) {
    return <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium bg-success/10 text-success">Fast</span>
  }
  if (ms < 500) {
    return <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium bg-warning/10 text-warning">Normal</span>
  }
  return <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium bg-error/10 text-error">Slow</span>
}

function DetailItem({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wider text-text-tertiary mb-1">{label}</dt>
      <dd className={cn('text-sm text-text-primary break-all', mono && 'font-mono text-xs')}>
        {value ?? <span className="text-text-tertiary">—</span>}
      </dd>
    </div>
  )
}

function CheckStatus({ label, ok }: { label: string; ok: boolean | null | undefined }) {
  const text = ok === true ? 'Pass' : ok === false ? 'Fail' : '—'
  const color = ok === true ? 'text-success' : ok === false ? 'text-error' : 'text-text-tertiary'
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-bg-tertiary/40 px-3 py-2">
      <span className="text-xs text-text-secondary">{label}</span>
      <span className={cn('text-xs font-medium', color)}>{text}</span>
    </div>
  )
}

export function resolveModelHealth(
  model: ModelResponse,
  healthByName: Map<string, ModelHealthInfo>,
): ModelHealthInfo | undefined {
  if (model.deployments?.length) {
    const depHealths = model.deployments
      .map((d) => healthByName.get(`${model.name}/${d.name}`))
      .filter((h): h is ModelHealthInfo => h != null)
    if (depHealths.length === 0) return undefined
    const allUnhealthy = depHealths.every((h) => h.status === 'unhealthy')
    const allHealthy = depHealths.every((h) => h.status === 'healthy')
    const allUnknown = depHealths.every((h) => h.status === 'unknown')
    const status = allUnknown ? 'unknown' : allUnhealthy ? 'unhealthy' : allHealthy ? 'healthy' : 'degraded'
    const avgLatency = Math.round(
      depHealths.reduce((sum, h) => sum + (h.latency_ms ?? 0), 0) / depHealths.length,
    )
    const lastCheck = depHealths
      .map((h) => h.last_check)
      .filter(Boolean)
      .sort()
      .pop() ?? ''
    const lastError = depHealths.find((h) => h.last_error)?.last_error
    const aggregate = (key: 'health_ok' | 'models_ok' | 'functional_ok') => {
      if (depHealths.some((h) => h[key] === false)) return false
      if (depHealths.every((h) => h[key] === true)) return true
      return null
    }
    return {
      name: model.name,
      status,
      latency_ms: avgLatency,
      last_check: lastCheck,
      last_error: lastError,
      health_ok: aggregate('health_ok'),
      models_ok: aggregate('models_ok'),
      functional_ok: aggregate('functional_ok'),
    }
  }
  return healthByName.get(model.name)
}

function computeTps(requests: number, totalTokens: number, avgDurationMs: number): number {
  if (requests <= 0 || avgDurationMs <= 0) return 0
  return Math.round((totalTokens / requests) / (avgDurationMs / 1000))
}

function UsageStatCard({
  label,
  requests,
  tokens,
  avgDurationMs,
  cost,
}: {
  label: string
  requests: number
  tokens: number
  avgDurationMs: number
  cost: number
}) {
  const tps = computeTps(requests, tokens, avgDurationMs)
  return (
    <div className="rounded-lg border border-border bg-bg-secondary p-4">
      <div className="text-[11px] font-medium uppercase tracking-wider text-text-tertiary mb-3">{label}</div>
      <div className="grid grid-cols-2 gap-3">
        <DetailItem label="Requests" value={formatNumber(requests)} />
        <DetailItem label="Tokens" value={formatNumber(tokens)} />
        <DetailItem
          label="Avg Duration"
          value={avgDurationMs > 0 ? `${Math.round(avgDurationMs)} ms` : '—'}
        />
        <DetailItem label="Throughput" value={tps > 0 ? `${formatNumber(tps)} tok/s` : '—'} />
        <DetailItem label="Est. Cost" value={cost > 0 ? formatCost(cost) : '—'} />
      </div>
    </div>
  )
}

function DeploymentHealthRow({
  deployment,
  health,
}: {
  deployment: DeploymentResponse
  health: ModelHealthInfo | undefined
}) {
  const providerKey = isKnownProvider(deployment.provider) ? deployment.provider : 'custom'
  const status = health?.status ?? 'unknown'
  const cfg = healthConfig[status]

  return (
    <tr className="border-b border-border/30 last:border-b-0">
      <td className="px-3 py-2.5 text-sm font-mono text-text-primary">{deployment.name}</td>
      <td className="px-3 py-2.5 text-sm">
        <Badge variant={providerBadgeVariant[providerKey]}>
          {providerLabels[providerKey]}
        </Badge>
      </td>
      <td className="px-3 py-2.5 text-sm">
        <div className="flex items-center gap-2">
          <span className={cn('w-2 h-2 rounded-full shrink-0', cfg.dotClass)} />
          <Badge variant={cfg.badge}>{cfg.label}</Badge>
          {health && health.latency_ms > 0 && (
            <span className="text-xs text-text-tertiary tabular-nums">{health.latency_ms}ms</span>
          )}
        </div>
      </td>
      <td className="px-3 py-2.5 text-xs font-mono text-text-tertiary max-w-[200px] truncate" title={deployment.base_url}>
        {deployment.base_url}
      </td>
      <td className="px-3 py-2.5 text-sm text-text-secondary">{deployment.weight}</td>
      <td className="px-3 py-2.5 text-sm text-text-secondary">{deployment.priority}</td>
      <td className="px-3 py-2.5 text-xs text-text-tertiary">
        {health?.last_error ? (
          <span className="text-error" title={health.last_error}>{health.last_error}</span>
        ) : (
          '—'
        )}
      </td>
    </tr>
  )
}

export interface ModelDetailDialogProps {
  model: ModelResponse | null
  healthByName: Map<string, ModelHealthInfo>
  onClose: () => void
  onEdit?: (model: ModelResponse) => void
}

export function ModelDetailDialog({ model, healthByName, onClose, onEdit }: ModelDetailDialogProps) {
  const nowIso = useMemo(() => new Date().toISOString(), [model?.id])
  const from24h = useMemo(() => new Date(Date.now() - 86_400_000).toISOString(), [model?.id])
  const from7d = useMemo(() => new Date(Date.now() - 7 * 86_400_000).toISOString(), [model?.id])

  const { data: usage24hData, isLoading: usage24hLoading } = useCrossOrgUsage(
    { from: from24h, to: nowIso, groupBy: 'model' },
    model != null,
  )
  const { data: usage7dData, isLoading: usage7dLoading } = useCrossOrgUsage(
    { from: from7d, to: nowIso, groupBy: 'model' },
    model != null,
  )

  if (!model) return null

  const health = resolveModelHealth(model, healthByName)
  const healthCfg = healthConfig[health?.status ?? 'unknown']
  const providerKey = isKnownProvider(model.provider) ? model.provider : 'custom'
  const usage24h = usage24hData?.data.find((d) => d.group_key === model.name)
  const usage7d = usage7dData?.data.find((d) => d.group_key === model.name)
  const canEdit = model.source === 'api'

  return (
    <Dialog
      open={model != null}
      onClose={onClose}
      title={model.name}
      className="max-w-4xl w-full"
      footer={
        <div className="flex items-center justify-end gap-2">
          {canEdit && onEdit && (
            <Button
              variant="secondary"
              onClick={() => {
                onEdit(model)
                onClose()
              }}
            >
              Edit Model
            </Button>
          )}
          <Button onClick={onClose}>Close</Button>
        </div>
      }
    >
      <div className="space-y-6 max-h-[70vh] overflow-y-auto pr-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={model.is_active ? 'success' : 'muted'}>
            {model.is_active ? 'Active' : 'Inactive'}
          </Badge>
          <Badge variant={providerBadgeVariant[providerKey]}>
            {providerLabels[providerKey]}
          </Badge>
          <Badge variant="info">{typeLabels[model.type] ?? model.type}</Badge>
          <Badge variant={model.source === 'yaml' ? 'muted' : 'default'}>{model.source}</Badge>
          <div className="flex items-center gap-2 ml-1">
            <span className={cn('w-2 h-2 rounded-full', healthCfg.dotClass)} />
            <Badge variant={healthCfg.badge}>{healthCfg.label}</Badge>
            {health && health.latency_ms > 0 && (
              <>
                <span className="text-sm text-text-secondary tabular-nums">{health.latency_ms}ms</span>
                <PerfBadge ms={health.latency_ms} />
              </>
            )}
          </div>
        </div>

        <section>
          <h3 className="text-sm font-semibold text-text-secondary mb-3">Performance & Health</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
            <CheckStatus label="Upstream reachable" ok={health?.health_ok} />
            <CheckStatus label="Models endpoint" ok={health?.models_ok} />
            <CheckStatus label="Functional probe" ok={health?.functional_ok} />
          </div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <DetailItem
              label="Probe Latency"
              value={health && health.latency_ms > 0 ? `${health.latency_ms} ms` : '—'}
            />
            <DetailItem
              label="Last Health Check"
              value={health?.last_check ? formatDate(health.last_check) : '—'}
            />
            <DetailItem
              label="Last Error"
              value={health?.last_error ? (
                <span className="text-error text-xs">{health.last_error}</span>
              ) : '—'}
            />
            <DetailItem
              label="Fallback Model"
              value={model.fallback_model_name || '—'}
              mono
            />
          </dl>
        </section>

        <section>
          <h3 className="text-sm font-semibold text-text-secondary mb-3">Usage</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {usage24hLoading ? (
              <div className="rounded-lg border border-border bg-bg-secondary p-4 text-sm text-text-tertiary">Loading 24h usage…</div>
            ) : (
              <UsageStatCard
                label="Last 24 hours"
                requests={usage24h?.total_requests ?? 0}
                tokens={usage24h?.total_tokens ?? 0}
                avgDurationMs={usage24h?.avg_duration_ms ?? 0}
                cost={usage24h?.cost_estimate ?? 0}
              />
            )}
            {usage7dLoading ? (
              <div className="rounded-lg border border-border bg-bg-secondary p-4 text-sm text-text-tertiary">Loading 7d usage…</div>
            ) : (
              <UsageStatCard
                label="Last 7 days"
                requests={usage7d?.total_requests ?? 0}
                tokens={usage7d?.total_tokens ?? 0}
                avgDurationMs={usage7d?.avg_duration_ms ?? 0}
                cost={usage7d?.cost_estimate ?? 0}
              />
            )}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-semibold text-text-secondary mb-3">Configuration</h3>
          <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <DetailItem label="Model ID" value={model.id} mono />
            <DetailItem label="Base URL" value={model.base_url} mono />
            <DetailItem
              label="Context Window"
              value={model.max_context_tokens > 0 ? formatNumber(model.max_context_tokens) : '—'}
            />
            <DetailItem
              label="Input Price / 1M"
              value={model.input_price_per_1m > 0 ? formatCost(model.input_price_per_1m) : '—'}
            />
            <DetailItem
              label="Output Price / 1M"
              value={model.output_price_per_1m > 0 ? formatCost(model.output_price_per_1m) : '—'}
            />
            <DetailItem label="Timeout" value={model.timeout || '—'} />
            <DetailItem label="Azure Deployment" value={model.azure_deployment || '—'} mono />
            <DetailItem label="Azure API Version" value={model.azure_api_version || '—'} mono />
            <DetailItem label="Load Strategy" value={model.strategy || '—'} />
            <DetailItem label="Max Retries" value={model.max_retries != null ? String(model.max_retries) : '—'} />
            <DetailItem
              label="Aliases"
              value={
                model.aliases?.length ? (
                  <div className="flex flex-wrap gap-1">
                    {model.aliases.map((a) => (
                      <Badge key={a} variant="muted">{a}</Badge>
                    ))}
                  </div>
                ) : '—'
              }
            />
            <DetailItem label="Created" value={formatDate(model.created_at)} />
            <DetailItem label="Updated" value={formatDate(model.updated_at)} />
          </dl>
        </section>

        {model.deployments && model.deployments.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-text-secondary mb-3">
              Deployments ({model.deployments.length})
            </h3>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="min-w-full">
                <thead>
                  <tr className="border-b border-border bg-bg-tertiary/50">
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-text-tertiary uppercase tracking-wider">Name</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-text-tertiary uppercase tracking-wider">Provider</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-text-tertiary uppercase tracking-wider">Health</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-text-tertiary uppercase tracking-wider">Base URL</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-text-tertiary uppercase tracking-wider">Weight</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-text-tertiary uppercase tracking-wider">Priority</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-text-tertiary uppercase tracking-wider">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {model.deployments.map((dep) => (
                    <DeploymentHealthRow
                      key={dep.id}
                      deployment={dep}
                      health={healthByName.get(`${model.name}/${dep.name}`)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </Dialog>
  )
}
