import type { BatchStatus, FridgeState } from '../types'

// ── Formatting helpers ───────────────────────────────────────────────────────

export function fmtTemp(c: number) {
  return `${c.toFixed(1)}°C`
}

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function fmtDuration(seconds: number) {
  if (seconds < 60)  return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

export function fmtPct(pct: number) {
  return `${pct.toFixed(1)}%`
}

export function fmtRelative(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60)   return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// ── State styling ────────────────────────────────────────────────────────────

export function stateColor(state: FridgeState | BatchStatus | string): string {
  switch (state) {
    case 'SAFE': case 'OK':        return 'text-emerald-400'
    case 'WARNING': case 'AT_RISK': return 'text-amber-400'
    case 'BREACH':                  return 'text-red-400'
    case 'DISCARD':                 return 'text-red-600'
    default:                        return 'text-slate-400'
  }
}

export function stateBg(state: FridgeState | BatchStatus | string): string {
  switch (state) {
    case 'SAFE': case 'OK':         return 'bg-emerald-950 border-emerald-800/60'
    case 'WARNING': case 'AT_RISK': return 'bg-amber-950 border-amber-800/60'
    case 'BREACH':                  return 'bg-red-950 border-red-800/60'
    case 'DISCARD':                 return 'bg-red-950/80 border-red-900'
    default:                        return 'bg-surface-800 border-surface-700'
  }
}

export function budgetBarColor(pct: number): string {
  if (pct > 40) return 'bg-emerald-500'
  if (pct > 20) return 'bg-amber-500'
  if (pct > 0)  return 'bg-red-500'
  return 'bg-red-800'
}

export function tempBarColor(temp: number): string {
  if (temp <= 8)  return '#22c55e'
  if (temp <= 12) return '#f59e0b'
  return '#ef4444'
}

// ── Misc ─────────────────────────────────────────────────────────────────────

export function clsx(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ')
}
