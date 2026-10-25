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
    if (!original || err.response?.status !== 401 || original._retry) {
      return Promise.reject(err)
    }

    // Do not attempt to refresh for auth-specific requests (login, refresh, me)
    if (original.url && /[\/=]auth(\/|$)/.test(original.url)) {
      return Promise.reject(err)
    }

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
        } catch (refreshErr) {
          clearTokens()
          // Only redirect if not already on the login or check page
          if (
            typeof window !== 'undefined' &&
            !window.location.pathname.startsWith('/app/login') &&
            !window.location.pathname.startsWith('/check/')
          ) {
            window.location.href = '/app/login'
          }
          throw refreshErr
        } finally {
          refreshing = null
        }
      })()
    }

    try {
      await refreshing
      original.headers.Authorization = `Bearer ${getAccessToken()}`
      return api(original)
    } catch {
      return Promise.reject(err)
    }
  },
)
