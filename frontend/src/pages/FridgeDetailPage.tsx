import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, Zap, DoorOpen, DoorClosed, Battery, ZapOff, Package,
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
  ResponsiveContainer,
} from 'recharts'
import { getFridgeLive, getFridgeReadings, getBatches, getMlForecast, getMlHealth } from '../api/endpoints'
import { TempGauge } from '../components/TempGauge'
import { BudgetBar }  from '../components/BudgetBar'
import { StatusBadge } from '../components/StatusBadge'
import { fmtTemp, fmtDate, fmtDuration, fmtRelative, tempBarColor } from '../lib/utils'
import type { Batch } from '../types'

export function FridgeDetailPage() {
  const { id } = useParams<{ id: string }>()
  const fridgeId = Number(id)
  const nav = useNavigate()

  const { data: live, isLoading }   = useQuery({
    queryKey: ['fridge-live', fridgeId],
    queryFn: () => getFridgeLive(fridgeId),
    refetchInterval: 5_000,
  })

  const { data: readings = [] } = useQuery({
    queryKey: ['fridge-readings', fridgeId],
    queryFn: () => getFridgeReadings(fridgeId, { limit: 200 }),
    refetchInterval: 30_000,
  })

  const { data: allBatches = [] } = useQuery<Batch[]>({
    queryKey: ['batches'],
    queryFn: getBatches,
  })

  const { data: forecast } = useQuery({
    queryKey: ['ml-forecast', fridgeId],
    queryFn: () => getMlForecast(fridgeId),
    refetchInterval: 60_000,
  })

  const { data: health } = useQuery({
    queryKey: ['ml-health', fridgeId],
    queryFn: () => getMlHealth(fridgeId),
    refetchInterval: 120_000,
  })

  const batches = allBatches.filter((b: Batch) => b.fridge_id === fridgeId)
  const r = live?.latest

  // Build chart data
  const chartData = [...readings].reverse().map((rd: { ts: string; temp_c: number; compressor_on: boolean; door_open: boolean }) => ({
    ts:    new Date(rd.ts).getTime(),
    label: fmtDate(rd.ts),
    temp:  rd.temp_c,
    comp:  rd.compressor_on ? rd.temp_c : null,
    door:  rd.door_open ? 1 : 0,
  }))

  // Append forecast
  const forecastData = forecast?.available
    ? (forecast.forecast ?? []).map((p: { ts: string; predicted_temp: number }) => ({
        ts: new Date(p.ts).getTime(), label: fmtDate(p.ts),
        temp: null, forecast: p.predicted_temp,
      }))
    : []

  const combinedChart = [...chartData, ...forecastData]

  if (isLoading) return (
    <div className="p-6 space-y-4 animate-in">
      <div className="skeleton h-6 w-48" />
      <div className="skeleton h-64 rounded-xl" />
    </div>
  )

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => nav(-1)} className="btn-ghost py-1.5 px-2">
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-lg font-bold text-white">{live?.name ?? `Fridge #${fridgeId}`}</h1>
          {live?.location && <p className="text-xs text-slate-400">{live.location}</p>}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {live?.online
            ? <span className="badge-online"><span className="pulse-dot-online animate-pulse" />Online</span>
            : <span className="badge-offline"><span className="pulse-dot-offline" />Offline</span>
          }
          {r && <StatusBadge status={r.state} />}
        </div>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="card flex flex-col items-center gap-2">
          <TempGauge temp={r?.temp_c ?? 4} size="md" />
        </div>

        <div className="card space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Compressor</p>
          <div className="flex items-center gap-2">
            <Zap size={18} className={r?.compressor_on ? 'text-amber-400' : 'text-slate-500'} />
            <span className="text-sm font-medium text-white">
              {r?.compressor_on ? 'Running' : 'Idle'}
            </span>
          </div>
          {r?.lockout_s != null && r.lockout_s > 0 && (
            <p className="text-xs text-amber-400">Lockout: {fmtDuration(r.lockout_s)}</p>
          )}
        </div>

        <div className="card space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Door</p>
          <div className="flex items-center gap-2">
            {r?.door_open
              ? <DoorOpen  size={18} className="text-red-400" />
              : <DoorClosed size={18} className="text-emerald-400" />
            }
            <span className="text-sm font-medium text-white">
              {r?.door_open ? `Open ${fmtDuration(r.door_open_s)}` : 'Closed'}
            </span>
          </div>
        </div>

        <div className="card space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Power</p>
          <div className="flex items-center gap-2">
            {r?.mains_present
              ? <Zap size={18} className="text-emerald-400" />
              : <ZapOff size={18} className="text-amber-400" />
            }
            <span className="text-sm font-medium text-white">
              {r?.mains_present ? 'Mains' : 'Battery'}
            </span>
          </div>
          {r?.battery_pct != null && (
            <div>
              <div className="flex items-center gap-1.5 text-xs text-slate-400">
                <Battery size={12} />{r.battery_pct.toFixed(0)}%
              </div>
              <div className="budget-bar-track mt-1">
                <div
                  className={`budget-bar-fill ${r.battery_pct > 50 ? 'bg-emerald-500' : r.battery_pct > 20 ? 'bg-amber-500' : 'bg-red-500'}`}
                  style={{ width: `${r.battery_pct}%` }}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ML Health Score */}
      {health?.available && (
        <div className="card flex items-center gap-6">
          <div className="text-center min-w-[80px]">
            <p className="text-3xl font-bold" style={{
              color: health.score >= 70 ? '#22c55e' : health.score >= 40 ? '#f59e0b' : '#ef4444'
            }}>
              {health.score}
            </p>
            <p className="text-xs text-slate-400 mt-0.5">Health Score</p>
          </div>
          <div>
            <p className="text-sm font-semibold text-white capitalize">{health.trend}</p>
            <p className="text-xs text-slate-400">Cooling rate: {health.mean_cooling_rate} °C/min</p>
            <p className="text-xs text-slate-500">{health.cycles_analyzed} cycles analyzed</p>
          </div>
        </div>
      )}

      {/* Temperature chart + forecast */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm font-semibold text-white">Temperature History & Forecast</p>
          {forecast?.breach_in_minutes != null && (
            <span className="badge-breach animate-pulse">
              Predicted breach in {forecast.breach_in_minutes}m
            </span>
          )}
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={combinedChart} margin={{ top: 5, right: 5, bottom: 5, left: -10 }}>
            <defs>
              <linearGradient id="tempGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}   />
              </linearGradient>
              <linearGradient id="forecastGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#f59e0b" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#f59e0b" stopOpacity={0}    />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(71,85,105,0.3)" />
            <XAxis dataKey="label" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} minTickGap={60} />
            <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} domain={['auto', 'auto']} tickFormatter={v => `${v}°`} />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
              labelStyle={{ color: '#94a3b8', fontSize: 11 }}
              formatter={(val: number, name: string) => [`${fmtTemp(val)}`, name === 'temp' ? 'Actual' : 'Forecast']}
            />
            <ReferenceLine y={8}  stroke="#f59e0b" strokeDasharray="4 2" label={{ value: '8°C', fill: '#f59e0b', fontSize: 10 }} />
            <ReferenceLine y={12} stroke="#ef4444" strokeDasharray="4 2" label={{ value: '12°C', fill: '#ef4444', fontSize: 10 }} />
            <Area type="monotone" dataKey="temp"     stroke="#3b82f6" fill="url(#tempGrad)"     strokeWidth={2} dot={false} connectNulls={false} />
            <Area type="monotone" dataKey="forecast" stroke="#f59e0b" fill="url(#forecastGrad)" strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Batches in this fridge */}
      <div className="card">
        <div className="flex items-center gap-2 mb-4">
          <Package size={16} className="text-slate-400" />
          <p className="text-sm font-semibold text-white">Vaccine Batches</p>
          <span className="badge-blue">{batches.length}</span>
        </div>
        {batches.length === 0 ? (
          <p className="text-slate-500 text-sm text-center py-4">No batches in this fridge.</p>
        ) : (
          <div className="space-y-3">
            {batches.map((b: Batch) => (
              <div key={b.id} className="p-3 rounded-lg bg-surface-700/50 border border-surface-600/40 space-y-2">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm font-medium text-white">{b.code}</span>
                    <span className="text-xs text-slate-400 ml-2">{b.vaccine_name}</span>
                  </div>
                  <StatusBadge status={b.status} size="sm" />
                </div>
                <BudgetBar remaining_pct={b.remaining_pct} exposure_min={b.exposure_weighted_min} />
                <div className="flex gap-3 text-[10px] text-slate-500">
                  <span>Qty: {b.qty}</span>
                  {b.expiry_date && <span>Expires: {b.expiry_date}</span>}
                  <span>Created: {fmtRelative(b.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent readings table */}
      <div className="card">
        <p className="text-sm font-semibold text-white mb-3">Recent Readings</p>
        <div className="table-wrapper">
          <table className="tbl">
            <thead>
              <tr>
                <th>Time</th><th>Temp</th><th>State</th>
                <th>Compressor</th><th>Door</th><th>Power</th>
              </tr>
            </thead>
            <tbody>
              {readings.slice(0, 20).map((rd: { seq: number; ts: string; temp_c: number; state: string; compressor_on: boolean; door_open: boolean; mains_present: boolean }) => (
                <tr key={rd.seq}>
                  <td className="text-xs font-mono text-slate-400">{fmtDate(rd.ts)}</td>
                  <td style={{ color: tempBarColor(rd.temp_c) }} className="font-mono font-medium">
                    {fmtTemp(rd.temp_c)}
                  </td>
                  <td><StatusBadge status={rd.state} size="sm" /></td>
                  <td className="text-xs">{rd.compressor_on ? '🔵 ON' : '⚫ OFF'}</td>
                  <td className="text-xs">{rd.door_open ? '🔴 Open' : '🟢 Closed'}</td>
                  <td className="text-xs">{rd.mains_present ? 'Mains' : '🔋 Battery'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
