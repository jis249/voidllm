import { useEffect } from 'react'
import { LOCAL_STORAGE_KEY } from '../../lib/constants'

export default function CallbackPage() {
  useEffect(() => {
    fetch('/api/v1/auth/oidc/exchange', { method: 'POST', credentials: 'include' })
      .then(async (res) => {
        if (!res.ok) throw new Error('exchange failed')
        const data = (await res.json()) as { token: string }
        localStorage.setItem(LOCAL_STORAGE_KEY, data.token)
        window.location.href = '/'
      })
      .catch(() => {
        window.location.href = '/login?error=sso_error'
      })
  }, [])

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-primary">
      <div className="text-center">
        <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent mb-4" />
        <p className="text-sm text-text-tertiary">Authenticating...</p>
      </div>
    </div>
  )
}
