import { useEffect, useMemo, useState } from 'react'
import { PageHeader } from '../components/ui/PageHeader'
import { Table } from '../components/ui/Table'
import type { Column } from '../components/ui/Table'
import { Badge, type BadgeProps } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { StatCard } from '../components/ui/StatCard'
import { TimeAgo } from '../components/ui/TimeAgo'
import { useMe } from '../hooks/useMe'
import { useOrgs } from '../hooks/useOrgs'
import { useAuditLog } from '../hooks/useAuditLog'
import type { AuditEvent } from '../hooks/useAuditLog'
import { exportData } from '../lib/export'

const TIME_RANGES = ['24h', '7d', '30d', '90d'] as const
type TimeRange = (typeof TIME_RANGES)[number]

const RANGE_LABELS: Record<TimeRange, string> = {
  '24h': 'Last 24h',
  '7d': 'Last 7d',
  '30d': 'Last 30d',
  '90d': 'Last 90d',
}

const RANGE_HOURS: Record<TimeRange, number> = {
  '24h': 24,
  '7d': 168,
  '30d': 720,
  '90d': 2160,
}

const RESOURCE_TYPE_OPTIONS = [
  { value: '', label: 'All Resources' },
  { value: 'orgs', label: 'Organizations' },
  { value: 'users', label: 'Users' },
  { value: 'models', label: 'Models' },
  { value: 'mcp-servers', label: 'MCP Servers' },
  { value: 'settings', label: 'Settings' },
  { value: 'auth', label: 'Auth' },
]

const ACTION_OPTIONS = [
  { value: '', label: 'All Actions' },
  { value: 'create', label: 'Create' },
  { value: 'update', label: 'Update' },
  { value: 'replace', label: 'Replace' },
  { value: 'delete', label: 'Delete' },
  { value: 'auth.login', label: 'Login' },
]

const PAGE_SIZE_OPTIONS = [
  { value: '25', label: '25 / page' },
  { value: '50', label: '50 / page' },
  { value: '100', label: '100 / page' },
]

const EXPORT_HEADERS = [
  { key: 'timestamp', label: 'Time' },
  { key: 'actor_type', label: 'Actor Type' },
  { key: 'actor_id', label: 'Actor ID' },
  { key: 'action', label: 'Action' },
  { key: 'resource_type', label: 'Resource Type' },
  { key: 'resource_id', label: 'Resource ID' },
  { key: 'description', label: 'Details' },
  { key: 'ip_address', label: 'IP' },
  { key: 'status_code', label: 'Status' },
  { key: 'request_id', label: 'Request ID' },
]

function getTimeRange(range: TimeRange): { from: string; to: string } {
  const now = new Date()
  const from = new Date(now.getTime() - RANGE_HOURS[range] * 3_600_000)
  return { from: from.toISOString(), to: now.toISOString() }
}

type BadgeVariant = NonNullable<BadgeProps['variant']>

const ACTION_BADGE: Record<string, BadgeVariant> = {
  create: 'success',
  update: 'info',
  replace: 'info',
  delete: 'error',
  revoke: 'warning',
  activate: 'success',
  deactivate: 'muted',
  login: 'default',
}

function actionBadgeVariant(action: string): BadgeVariant {
  const verb = action.split('.').pop() ?? action
  return ACTION_BADGE[verb.toLowerCase()] ?? 'muted'
}

function statusBadgeVariant(code: number): BadgeVariant {
  if (code >= 200 && code < 300) return 'success'
  if (code >= 400 && code < 500) return 'warning'
  if (code >= 500) return 'error'
  return 'muted'
}

function shortenId(id: string): string {
  if (!id) return '—'
  if (id.length <= 12) return id
  return `${id.slice(0, 8)}…`
}

function IconList() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <line x1="3" y1="6" x2="3.01" y2="6" />
      <line x1="3" y1="12" x2="3.01" y2="12" />
      <line x1="3" y1="18" x2="3.01" y2="18" />
    </svg>
  )
}

function IconUser() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  )
}

function IconActivity() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  )
}

function IconDownload() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

const columns: Column<AuditEvent>[] = [
  {
    key: 'timestamp',
    header: 'Time',
    render: (row) => <TimeAgo date={row.timestamp} />,
  },
  {
    key: 'actor',
    header: 'Actor',
    render: (row) => (
      <span className="font-mono text-xs text-text-secondary" title={row.actor_id}>
        <span className="text-text-tertiary mr-1">{row.actor_type}</span>
        {shortenId(row.actor_id)}
      </span>
    ),
  },
  {
    key: 'action',
    header: 'Action',
    render: (row) => (
      <Badge variant={actionBadgeVariant(row.action)}>
        {row.action}
      </Badge>
    ),
  },
  {
    key: 'resource_type',
    header: 'Resource',
    render: (row) => (
      <div className="flex flex-col gap-0.5">
        <Badge variant="muted">{row.resource_type}</Badge>
        {row.resource_id && (
          <span className="font-mono text-[11px] text-text-tertiary" title={row.resource_id}>
            {shortenId(row.resource_id)}
          </span>
        )}
      </div>
    ),
  },
  {
    key: 'description',
    header: 'Details',
    render: (row) => (
      row.description
        ? <code className="text-xs font-mono bg-bg-tertiary px-1.5 py-0.5 rounded text-text-secondary">{row.description}</code>
        : <span className="text-text-tertiary">—</span>
    ),
  },
  {
    key: 'ip_address',
    header: 'IP',
    render: (row) => (
      <span className="font-mono text-xs text-text-tertiary">
        {row.ip_address || '—'}
      </span>
    ),
  },
  {
    key: 'request_id',
    header: 'Request',
    render: (row) => (
      <span className="font-mono text-[11px] text-text-tertiary" title={row.request_id}>
        {row.request_id ? shortenId(row.request_id) : '—'}
      </span>
    ),
  },
  {
    key: 'status_code',
    header: 'Status',
    align: 'right',
    render: (row) => (
      <Badge variant={statusBadgeVariant(row.status_code)}>
        {row.status_code}
      </Badge>
    ),
  },
]

export default function AuditLogPage() {
  const [range, setRange] = useState<TimeRange>('7d')
  const [resourceType, setResourceType] = useState('')
  const [action, setAction] = useState('')
  const [actorId, setActorId] = useState('')
  const [pageSize, setPageSize] = useState(50)
  const [cursors, setCursors] = useState<string[]>([''])
  const currentCursor = cursors[cursors.length - 1]

  const { data: me } = useMe()
  const isSystemAdmin = me?.is_system_admin === true
  const [selectedOrgId, setSelectedOrgId] = useState('')
  const { data: orgsData } = useOrgs(undefined)
  const orgId = isSystemAdmin ? selectedOrgId : (me?.org_id ?? '')

  const { from, to } = useMemo(() => getTimeRange(range), [range])

  const canQuery = !!me && (isSystemAdmin || !!orgId)

  const { data, isLoading } = useAuditLog({
    orgId,
    actorId: actorId.trim(),
    resourceType,
    action,
    from,
    to,
    limit: pageSize,
    cursor: currentCursor,
    enabled: canQuery,
  })

  useEffect(() => {
    setCursors([''])
  }, [orgId, actorId, resourceType, action, range, pageSize])

  const events = data?.data ?? []
  const hasPrevious = cursors.length > 1
  const hasNext = data?.has_more ?? false
  const uniqueActors = new Set(events.map((e) => e.actor_id).filter(Boolean)).size
  const activeFilterCount = [resourceType, action, actorId.trim(), isSystemAdmin && selectedOrgId].filter(Boolean).length

  const orgOptions = useMemo(() => {
    const orgs = orgsData?.data ?? []
    return [
      { value: '', label: 'All organizations' },
      ...orgs.map((org) => ({ value: org.id, label: org.name })),
    ]
  }, [orgsData])

  function handleNext() {
    if (data?.cursor) {
      setCursors((prev) => [...prev, data.cursor!])
    }
  }

  function handlePrevious() {
    setCursors((prev) => (prev.length > 1 ? prev.slice(0, -1) : prev))
  }

  const isDataLoading = isLoading && canQuery

  const emptyMessage = activeFilterCount > 0
    ? 'No audit events match the selected filters'
    : `No audit events found for the ${RANGE_LABELS[range].toLowerCase()} time range`

  return (
    <>
      <PageHeader
        title="Audit Log"
        description="Full audit trail of admin actions across your organization"
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <StatCard
          label="Events on Page"
          value={isDataLoading ? '—' : events.length}
          icon={<IconList />}
          iconColor="purple"
        />
        <StatCard
          label="Unique Actors"
          value={isDataLoading ? '—' : uniqueActors}
          icon={<IconUser />}
          iconColor="blue"
        />
        <StatCard
          label="Active Filters"
          value={activeFilterCount}
          icon={<IconActivity />}
          iconColor={activeFilterCount > 0 ? 'yellow' : 'purple'}
        />
      </div>

      <div className="flex flex-col gap-4 mb-6">
        <div className="flex flex-col lg:flex-row lg:items-end gap-4">
          <div className="flex items-center gap-1 p-1 rounded-lg bg-bg-tertiary w-fit">
            {TIME_RANGES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRange(r)}
                className={[
                  'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                  range === r
                    ? 'bg-bg-secondary text-text-primary shadow-sm'
                    : 'text-text-tertiary hover:text-text-secondary',
                ].join(' ')}
              >
                {RANGE_LABELS[r]}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-end gap-3 lg:ml-auto">
            {isSystemAdmin && (
              <div className="w-52">
                <Select
                  label="Organization"
                  value={selectedOrgId}
                  onChange={setSelectedOrgId}
                  options={orgOptions}
                  fullWidth
                />
              </div>
            )}
            <div className="w-44">
              <Select
                label="Resource"
                value={resourceType}
                onChange={setResourceType}
                options={RESOURCE_TYPE_OPTIONS}
                fullWidth
              />
            </div>
            <div className="w-40">
              <Select
                label="Action"
                value={action}
                onChange={setAction}
                options={ACTION_OPTIONS}
                fullWidth
              />
            </div>
            <div className="w-52">
              <Input
                label="Actor ID"
                value={actorId}
                onChange={(e) => setActorId(e.target.value)}
                placeholder="Filter by actor UUID"
              />
            </div>
          </div>
        </div>

        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<IconDownload />}
            onClick={() => exportData(events as unknown as Record<string, unknown>[], EXPORT_HEADERS, `wai-audit-log-${range}`, 'csv')}
            disabled={events.length === 0}
          >
            CSV
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<IconDownload />}
            onClick={() => exportData(events as unknown as Record<string, unknown>[], EXPORT_HEADERS, `wai-audit-log-${range}`, 'json')}
            disabled={events.length === 0}
          >
            JSON
          </Button>
        </div>
      </div>

      <Table<AuditEvent>
        columns={columns}
        data={events}
        keyExtractor={(row) => row.id}
        loading={isDataLoading}
        emptyMessage={emptyMessage}
      />

      {events.length > 0 && (
        <div className="flex items-center justify-between mt-4">
          <div className="flex items-center gap-3">
            <span className="text-sm text-text-tertiary">
              {events.length} events on this page
              {hasNext ? ' (more available)' : ''}
            </span>
            <div className="w-32">
              <Select
                value={String(pageSize)}
                onChange={(value) => setPageSize(Number(value))}
                options={PAGE_SIZE_OPTIONS}
                fullWidth
              />
            </div>
          </div>

          {(hasPrevious || hasNext) && (
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                disabled={!hasPrevious || isDataLoading}
                onClick={handlePrevious}
              >
                Previous
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={!hasNext || isDataLoading}
                onClick={handleNext}
              >
                Next
              </Button>
            </div>
          )}
        </div>
      )}
    </>
  )
}
