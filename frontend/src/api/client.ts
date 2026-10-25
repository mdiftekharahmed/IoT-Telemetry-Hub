import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

export const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
})

// ── Auth token helpers ──────────────────────────────────────────────────────

export const getAccessToken  = () => localStorage.getItem('cc_access')
export const getRefreshToken = () => localStorage.getItem('cc_refresh')
export const setTokens = (access: string, refresh: string) => {
  localStorage.setItem('cc_access',  access)
  localStorage.setItem('cc_refresh', refresh)
}
export const clearTokens = () => {
  localStorage.removeItem('cc_access')
  localStorage.removeItem('cc_refresh')
}

// ── Request interceptor: add Bearer token ───────────────────────────────────

api.interceptors.request.use(config => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ── Response interceptor: auto-refresh on 401 ──────────────────────────────

let refreshing: Promise<void> | null = null

api.interceptors.response.use(
  res => res,
  async err => {
    const original = err.config
    if (err.response?.status !== 401 || original._retry) throw err
    original._retry = true

    if (!refreshing) {
      refreshing = (async () => {
        try {
          const refresh = getRefreshToken()
          if (!refresh) throw new Error('no refresh token')
          const { data } = await axios.post(`${API_BASE}/api/cc/auth/refresh`, {
            refresh_token: refresh,
          })
          setTokens(data.access_token, data.refresh_token)
        } catch {
          clearTokens()
          window.location.href = '/app/login'
        } finally {
          refreshing = null
        }
      })()
    }

    await refreshing
    original.headers.Authorization = `Bearer ${getAccessToken()}`
    return api(original)
  },
)
