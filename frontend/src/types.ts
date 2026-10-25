// Shared TypeScript types mirroring backend responses

export type FridgeState = 'SAFE' | 'WARNING' | 'BREACH' | 'DISCARD'
export type BatchStatus  = 'OK' | 'AT_RISK' | 'DISCARD'
export type Role         = 'admin' | 'pharmacist' | 'inspector'
export type PowerSource  = 'MAINS' | 'BATTERY'

export interface Reading {
  id: number
  device_id: string
  seq: number
  ts: string
  temp_c: number
  door_open: boolean
  door_open_s: number
  compressor_on: boolean
  lockout_s: number
  power_source: PowerSource
  mains_present: boolean
  battery_pct: number | null
  battery_v: number | null
  state: FridgeState
  red_latched: boolean
  sim_mode: boolean
  ingested_at: string
}

export interface Batch {
  id: number
  code: string
  vaccine_name: string
  qty: number
  expiry_date: string | null
  fridge_id: number | null
  exposure_weighted_min: number
  remaining_pct: number
  status: BatchStatus
  discard_latched: boolean
  qr_token: string
  created_at: string
}

export interface Fridge {
  id: number
  name: string
  capacity_slots: number
  location: string | null
  device_id: string | null
  latest: Reading | null
}

export interface FridgeSummary {
  fridge: Fridge & { latest: Reading | null }
  batches: Batch[]
  online: boolean
  demo_time_scale: number
}

export interface Alert {
  id: number
  type: string
  device_id: string | null
  batch_id: number | null
  message: string
  sent_via: string
  created_at: string
  acknowledged_by: number | null
  acknowledged_at: string | null
}

export interface AuditEntry {
  idx: number
  ts: string
  actor: string
  action: string
  payload: Record<string, unknown>
  hash: string
  prev_hash: string
}

export interface SecurityEvent {
  id: number
  device_id: string | null
  kind: string
  raw_excerpt: string
  created_at: string
}

export interface ForecastPoint {
  ts: string
  predicted_temp: number
  breach_prob?: number
}

export interface ForecastResult {
  available: boolean
  reason?: string
  forecast?: ForecastPoint[]
  breach_in_minutes?: number
}

export interface HealthResult {
  available: boolean
  reason?: string
  score?: number
  trend?: 'good' | 'watch' | 'failing'
  mean_cooling_rate?: number
  cycles_analyzed?: number
}

export interface RelocationSuggestion {
  id: number
  plan: { batch_id: number; from_fridge: string; to_fridge: string; reason: string }[]
  created_at: string
}

export interface User {
  id: number
  username: string
  role: Role
  active: boolean
  created_at: string
}

export interface Device {
  device_id: string
  name: string
  enabled: boolean
  last_seen: string | null
  last_seq: number | null
}

export interface LiveEvent {
  type: 'reading' | 'alert' | 'batch_status'
  fridge_id?: number
  device_id?: string
  data: Record<string, unknown>
}
