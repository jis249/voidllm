import { twMerge } from 'tailwind-merge'
import { USD_TO_INR_RATE } from './constants'

/** Merge class names using tailwind-merge to resolve conflicting Tailwind classes. */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return twMerge(classes.filter(Boolean).join(' '))
}

/** Format a number with locale-aware separators. */
export function formatNumber(n: number): string {
  return new Intl.NumberFormat().format(n)
}

/** Format a token count with locale-aware separators. */
export function formatTokens(n: number): string {
  return new Intl.NumberFormat().format(n)
}

/** Format a byte count using binary units. */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let value = n
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`
}

export type CostCurrency = 'USD' | 'INR'

/** Convert a USD cost amount for display in the selected currency. */
export function convertCostFromUsd(amountUsd: number, currency: CostCurrency): number {
  return currency === 'INR' ? amountUsd * USD_TO_INR_RATE : amountUsd
}

/** Format a USD cost amount for cost reports (6 decimal places). */
export function formatReportCost(amountUsd: number, currency: CostCurrency = 'USD'): string {
  const amount = convertCostFromUsd(amountUsd, currency)
  const locale = currency === 'INR' ? 'en-IN' : 'en-US'
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: 6,
    maximumFractionDigits: 6,
  }).format(amount)
}

/** Format a number as USD currency. */
export function formatCost(n: number): string {
  // Show more decimals for small amounts (LLM costs are often fractions of a cent)
  const decimals = Math.abs(n) < 0.01 ? 6 : Math.abs(n) < 1 ? 4 : 2
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: decimals,
  }).format(n)
}

/** Format an ISO UTC timestamp in the user's local timezone. */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString()
}
