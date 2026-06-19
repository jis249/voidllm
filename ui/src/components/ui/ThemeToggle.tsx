import { cn } from '../../lib/utils'
import { useTheme, type Theme } from '../../hooks/useTheme'

const iconProps = {
  className: 'h-4 w-4 shrink-0',
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

function IconSun() {
  return (
    <svg {...iconProps}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  )
}

function IconMoon() {
  return (
    <svg {...iconProps}>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

interface ThemeToggleProps {
  className?: string
  compact?: boolean
}

export function ThemeToggle({ className, compact = false }: ThemeToggleProps) {
  const { theme, setTheme } = useTheme()

  function select(next: Theme) {
    setTheme(next)
  }

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {!compact && (
        <span className="text-[11px] uppercase tracking-wider text-text-tertiary/70">
          Appearance
        </span>
      )}
      <div
        className="flex rounded-md border border-border bg-bg-tertiary/50 p-0.5"
        role="group"
        aria-label="Color theme"
      >
        {(['light', 'dark'] as const).map((option) => {
          const active = theme === option
          return (
            <button
              key={option}
              type="button"
              aria-pressed={active}
              onClick={() => select(option)}
              className={cn(
                'flex flex-1 items-center justify-center gap-1.5 rounded px-2 py-1.5 text-xs font-medium transition-colors',
                active
                  ? 'bg-bg-secondary text-text-primary shadow-sm'
                  : 'text-text-tertiary hover:text-text-secondary',
              )}
            >
              {option === 'light' ? <IconSun /> : <IconMoon />}
              {option === 'light' ? 'Light' : 'Dark'}
            </button>
          )
        })}
      </div>
    </div>
  )
}
