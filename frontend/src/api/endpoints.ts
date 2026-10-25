import { api } from './client'

// ── Auth ────────────────────────────────────────────────────────────────────

export const ccLogin = (username: string, password: string) =>
  api.post('/api/cc/auth/login', { username, password }).then(r => r.data)

export const ccMe = () => api.get('/api/cc/me').then(r => r.data)

// ── Dashboard ───────────────────────────────────────────────────────────────

export const getDashboard = () =>
  api.get('/api/dashboard/summary').then(r => r.data)

export const getReport = () =>
  api.get('/api/report/summary').then(r => r.data)

// ── Fridges ─────────────────────────────────────────────────────────────────

export const getFridges = () => api.get('/api/fridges').then(r => r.data)

export const getFridgeLive = (id: number) =>
  api.get(`/api/fridges/${id}/live`).then(r => r.data)

export const getFridgeReadings = (
  id: number,
  params?: { limit?: number; from_ts?: string; to_ts?: string },
) => api.get(`/api/fridges/${id}/readings`, { params }).then(r => r.data)

export const createFridge = (body: { name: string; capacity_slots?: number; location?: string; device_id?: string }) =>
  api.post('/api/fridges', body).then(r => r.data)

// ── Batches ─────────────────────────────────────────────────────────────────

export const getBatches = () => api.get('/api/batches').then(r => r.data)

export const createBatch = (body: {
  code: string; vaccine_name: string; qty: number;
  expiry_date?: string; fridge_id?: number
}) => api.post('/api/batches', body).then(r => r.data)

export const updateBatch = (id: number, body: Partial<{
  vaccine_name: string; qty: number; fridge_id: number
}>) => api.patch(`/api/batches/${id}`, body).then(r => r.data)

export const moveBatch = (id: number, to_fridge_id: number, reason = 'manual') =>
  api.post(`/api/batches/${id}/move`, { to_fridge_id, reason }).then(r => r.data)

export const resetBatchDiscard = (id: number, reason: string) =>
  api.post(`/api/batches/${id}/reset`, { reason }).then(r => r.data)

export const getPublicBatch = (qr_token: string) =>
  api.get(`/api/public/batch/${qr_token}`).then(r => r.data)

// ── Alerts ──────────────────────────────────────────────────────────────────

export const getAlerts = (params?: { limit?: number; unacked_only?: boolean }) =>
  api.get('/api/alerts', { params }).then(r => r.data)

export const ackAlert = (id: number) =>
  api.post(`/api/alerts/${id}/ack`).then(r => r.data)

// ── Audit ───────────────────────────────────────────────────────────────────

export const getAuditLog = (page = 1, per_page = 50) =>
  api.get('/api/audit', { params: { page, per_page } }).then(r => r.data)

export const verifyAuditChain = () =>
  api.get('/api/audit/verify').then(r => r.data)

export const getSecurityEvents = (limit = 100) =>
  api.get('/api/security/events', { params: { limit } }).then(r => r.data)

// ── ML ───────────────────────────────────────────────────────────────────────

export const getMlForecast = (fridgeId: number) =>
  api.get(`/api/ml/forecast/${fridgeId}`).then(r => r.data)

export const getMlHealth = (fridgeId: number) =>
  api.get(`/api/ml/health/${fridgeId}`).then(r => r.data)

export const getMlRelocation = (fridgeId: number) =>
  api.get(`/api/ml/relocation/${fridgeId}`).then(r => r.data)

export const confirmRelocation = (suggestionId: number) =>
  api.post(`/api/ml/relocation/${suggestionId}/confirm`).then(r => r.data)

// ── Users ────────────────────────────────────────────────────────────────────

export const getUsers = () => api.get('/api/users').then(r => r.data)

export const createUser = (body: { username: string; password: string; role: string }) =>
  api.post('/api/users', body).then(r => r.data)

export const updateUser = (id: number, body: Partial<{ role: string; active: boolean; password: string }>) =>
  api.patch(`/api/users/${id}`, body).then(r => r.data)

// ── Devices ──────────────────────────────────────────────────────────────────

export const getDevices = () => api.get('/api/devices').then(r => r.data)

// ── Admin controls ────────────────────────────────────────────────────────────

export const setTimeScale = (time_scale: number) =>
  api.patch('/api/admin/time-scale', { time_scale }).then(r => r.data)

export const simFault = (device_id: string, params: Record<string, unknown>) =>
  api.post(`/api/admin/sim/${device_id}`, params).then(r => r.data)
