export const LOCAL_STORAGE_KEY = 'wai_session'

/** Maps backend key_type values to their display prefixes. */
export const KEY_PREFIXES: Record<string, string> = {
  user_key: 'wa_uk_',
  team_key: 'wa_tk_',
  sa_key: 'wa_sa_',
  session_key: 'wa_sk_',
} as const

export type KeyType = 'user_key' | 'team_key' | 'sa_key' | 'session_key'
