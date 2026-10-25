import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BrainCircuit, TrendingUp, Activity, Truck, CheckCircle2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer,
} from 'recharts'
import { getFridges, getMlForecast, getMlHealth, getMlRelocation, confirmRelocation } from '../api/endpoints'
import { fmtTemp, fmtDate } from '../lib/utils'
import type { Fridge } from '../types'

function HealthGauge({ score, trend }: { score: number; trend: string }) {
  const color = score >= 70 ? '#22c55e' : score >= 40 ? '#f59e0b' : '#ef4444'
  const trendColor = trend === 'good' ? 'text-emerald-400' : trend === 'watch' ? 'text-amber-400' : 'text-red-400'
  return (
    <div className="flex items-center gap-4 p-3 rounded-lg bg-surface-700/40">
      <div className="relative w-16 h-16">
        <svg viewBox="0 0 64 64" className="w-full h-full -rotate-90">
          <circle cx="32" cy="32" r="26" fill="none" stroke="rgba(71,85,105,0.4)" strokeWidth="6" strokeDasharray="122 163" strokeLinecap="round" />
          <circle cx="32" cy="32" r="26" fill="none" stroke={color} strokeWidth="6"
            strokeDasharray={`${122 * score / 100} 163`} strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 4px ${color}88)` }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-bold" style={{ color }}>{score}</span>
        </div>
      </div>
      <div>
        <p className={`text-sm font-semibold capitalize ${trendColor}`}>{trend}</p>
        <p className="text-xs text-slate-400">Compressor health</p>
      </div>
    </div>
  )
}

export function AiInsightsPage() {
  const qc = useQueryClient()
  const { data: fridges = [] } = useQuery<Fridge[]>({
    queryKey: ['fridges'],
    queryFn: getFridges,
  })

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const fridgeId = selectedId ?? fridges[0]?.id ?? null

  const { data: forecast, isLoading: forecastLoading, refetch: refetchForecast } = useQuery({
    queryKey: ['ml-forecast', fridgeId],
    queryFn: () => getMlForecast(fridgeId!),
    enabled: fridgeId != null,
    refetchInterval: 60_000,
  })

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['ml-health', fridgeId],
    queryFn: () => getMlHealth(fridgeId!),
    enabled: fridgeId != null,
    refetchInterval: 120_000,
  })

  const { data: relocation = [], isLoading: relocLoading } = useQuery({
    queryKey: ['ml-relocation', fridgeId],
    queryFn: () => getMlRelocation(fridgeId!),
    enabled: fridgeId != null,
    refetchInterval: 60_000,
  })

  const confirmMut = useMutation({
    mutationFn: (id: number) => confirmRelocation(id),
    onSuccess: (data: { moves: number }) => {
      toast.success(`Relocation confirmed — ${data.moves} batches moved`)
      qc.invalidateQueries({ queryKey: ['ml-relocation'] })
      qc.invalidateQueries({ queryKey: ['batches'] })
    },
    onError: () => toast.error('Confirmation failed'),
  })

  const chartData = (() => {
    if (!forecast?.available) return []
    const pts = (forecast as { forecast?: unknown[]; series?: unknown[] }).forecast ??
                (forecast as { forecast?: unknown[]; series?: unknown[] }).series
    if (Array.isArray(pts) && pts.length > 0) {
      return pts.map((p: any) => ({
        label: p.label ?? (p.ts ? fmtDate(p.ts) : ''),
        temp: p.temp ?? p.predicted_temp,
        type: p.type ?? 'forecast',
        breach_pct: (p.breach_prob ?? 0) * 100,
      }))
    }
    const cur = forecast.current_temp ?? 4.0
    const pred = forecast.predicted_temp_30m ?? cur
    const step = (pred - cur) / 6
    return [
      { label: '-10m', temp: Number((cur - step * 2).toFixed(2)), type: 'history', breach_pct: 0 },
      { label: '-5m', temp: Number((cur - step).toFixed(2)), type: 'history', breach_pct: 0 },
      { label: 'Now', temp: Number(cur.toFixed(2)), type: 'current', breach_pct: 0 },
      { label: '+5m', temp: Number((cur + step).toFixed(2)), type: 'forecast', breach_pct: 0 },
      { label: '+10m', temp: Number((cur + step * 2).toFixed(2)), type: 'forecast', breach_pct: 0 },
      { label: '+15m', temp: Number((cur + step * 3).toFixed(2)), type: 'forecast', breach_pct: 0 },
      { label: '+20m', temp: Number((cur + step * 4).toFixed(2)), type: 'forecast', breach_pct: 0 },
      { label: '+25m', temp: Number((cur + step * 5).toFixed(2)), type: 'forecast', breach_pct: 0 },
      { label: '+30m', temp: Number(pred.toFixed(2)), type: 'forecast', breach_pct: (pred > 8 || pred < 2) ? 100 : 0 },
    ]
  })()

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <BrainCircuit size={22} className="text-brand-400" />
            AI Insights
          </h1>
          <p className="text-sm text-slate-400">ML-powered forecast, health scoring & relocation</p>
        </div>
        <button onClick={() => refetchForecast()} className="btn-ghost py-1.5">
          <RefreshCw size={13} className={forecastLoading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {/* Fridge selector */}
      <div className="flex gap-2 flex-wrap">
        {fridges.map((f: Fridge) => (
          <button
            key={f.id}
            onClick={() => setSelectedId(f.id)}
            className={`btn text-xs py-1.5 ${fridgeId === f.id ? 'btn-primary' : 'btn-ghost'}`}
          >
            {f.name}
          </button>
        ))}
      </div>

      {/* Forecast KPI cards */}
      {forecast?.available && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="card-sm">
            <p className="text-xs text-slate-400">Current Temperature</p>
            <p className="text-xl font-bold text-white mt-1">
              {fmtTemp(forecast.current_temp)}
            </p>
            <span className="text-[10px] text-slate-500">Live chamber sensor</span>
          </div>
          <div className="card-sm">
            <p className="text-xs text-slate-400">30-Min AI Forecast</p>
            <p className="text-xl font-bold text-brand-300 mt-1">
              {fmtTemp(forecast.predicted_temp_30m)}
            </p>
            <span className={`text-[10px] font-medium ${forecast.predicted_temp_30m > forecast.current_temp ? 'text-amber-400' : 'text-cyan-400'}`}>
              {forecast.predicted_temp_30m > forecast.current_temp ? '▲ Warming trend' : '▼ Cooling trend'}
            </span>
          </div>
          <div className="card-sm">
            <p className="text-xs text-slate-400">30-Min Safety Status</p>
            <p className={`text-sm font-bold mt-1.5 ${forecast.breach_predicted ? 'text-red-400' : 'text-emerald-400'}`}>
              {forecast.breach_predicted ? 'Breach Risk Projected' : 'Safe (2°C – 8°C)'}
            </p>
            <span className="text-[10px] text-slate-500">
              {forecast.breach_in_minutes != null ? `Breach in ~${forecast.breach_in_minutes}m` : 'Normal operational range'}
            </span>
          </div>
          <div className="card-sm">
            <p className="text-xs text-slate-400">Model Engine</p>
            <p className="text-sm font-bold text-slate-200 mt-1.5">LightGBM Regressor</p>
            <span className="text-[10px] text-slate-500">12 thermodynamic features</span>
          </div>
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-5">
        {/* Forecast chart */}
        <div className="card lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-white flex items-center gap-2">
              <TrendingUp size={15} className="text-brand-400" />
              30-Minute Temperature Forecast Trajectory
            </p>
            {forecast?.breach_in_minutes != null && (
              <span className="badge-breach animate-pulse text-xs">
                Breach predicted in {forecast.breach_in_minutes}m
              </span>
            )}
          </div>

          {forecastLoading ? (
            <div className="skeleton h-48 rounded-lg" />
          ) : !forecast?.available ? (
            <div className="flex flex-col items-center justify-center h-40 text-slate-500 gap-2">
              <BrainCircuit size={28} />
              <p className="text-sm">{forecast?.reason ?? 'Insufficient data for forecast'}</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={chartData} margin={{ top: 10, right: 10, bottom: 5, left: -10 }}>
                <defs>
                  <linearGradient id="fgGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#38bdf8" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0}   />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(71,85,105,0.25)" />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
                <YAxis yAxisId="temp" domain={[0, 12]} tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} tickFormatter={v => `${v}°C`} />
                <YAxis yAxisId="prob" orientation="right" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} tickFormatter={v => `${v}%`} domain={[0, 100]} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  labelStyle={{ color: '#f8fafc', fontSize: 12, fontWeight: 'bold' }}
                  formatter={(val: number, name: string) =>
                    name === 'temp' ? [fmtTemp(val), 'Trajectory °C'] : [`${val.toFixed(1)}%`, 'Breach Risk']
                  }
                />
                <ReferenceLine yAxisId="temp" y={2} stroke="#38bdf8" strokeDasharray="4 2" label={{ value: 'Lower Safe (2°C)', fill: '#38bdf8', fontSize: 10 }} />
                <ReferenceLine yAxisId="temp" y={8} stroke="#f59e0b" strokeDasharray="4 2" label={{ value: 'Upper Safe (8°C)', fill: '#f59e0b', fontSize: 10 }} />
                <Area yAxisId="temp" type="monotone" dataKey="temp" stroke="#38bdf8" fill="url(#fgGrad)" strokeWidth={2.5} dot={{ r: 3, fill: '#38bdf8' }} />
                <Area yAxisId="prob" type="monotone" dataKey="breach_pct" stroke="#ef444460" fill="none" strokeWidth={1} strokeDasharray="4 2" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Compressor health */}
        <div className="card">
          <p className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
            <Activity size={15} className="text-emerald-400" />
            Compressor Health
          </p>
          {healthLoading ? (
            <div className="skeleton h-20 rounded-lg" />
          ) : !health?.available ? (
            <div className="flex flex-col items-center justify-center h-20 text-slate-500 gap-1 text-sm">
              <p>{health?.reason ?? 'No data'}</p>
            </div>
          ) : (
            <div className="space-y-3">
              <HealthGauge score={health.score} trend={health.trend} />
              <div className="grid grid-cols-2 gap-3 text-center">
                <div>
                  <p className="text-lg font-bold text-white">{health.mean_cooling_rate} °C/min</p>
                  <p className="text-[10px] text-slate-400">Avg cooling rate</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-white">{health.cycles_analyzed}</p>
                  <p className="text-[10px] text-slate-400">Cycles analyzed</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Relocation suggestions */}
        <div className="card">
          <p className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
            <Truck size={15} className="text-purple-400" />
            Relocation Suggestions
          </p>
          {relocLoading ? (
            <div className="space-y-2"><div className="skeleton h-16 rounded" /><div className="skeleton h-16 rounded" /></div>
          ) : relocation.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-24 text-slate-500 gap-1">
              <CheckCircle2 size={24} className="text-emerald-600" />
              <p className="text-sm">No relocation needed</p>
            </div>
          ) : (
            <div className="space-y-3">
              {relocation.map((s: { id: number; plan: { from_fridge: string; to_fridge: string; reason: string }[]; created_at: string }) => (
                <div key={s.id} className="p-3 rounded-lg bg-purple-950/30 border border-purple-800/40">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div className="space-y-1">
                      {s.plan.map((move, i) => (
                        <p key={i} className="text-xs text-slate-200">
                          Move batch from <strong>{move.from_fridge}</strong> → <strong>{move.to_fridge}</strong>
                          <span className="text-slate-400 ml-1">({move.reason})</span>
                        </p>
                      ))}
                    </div>
                    <button
                      onClick={() => confirmMut.mutate(s.id)}
                      disabled={confirmMut.isPending}
                      className="btn-success text-xs flex-shrink-0"
                    >
                      <CheckCircle2 size={12} /> Confirm
                    </button>
                  </div>
                  <p className="text-[10px] text-slate-500">{fmtDate(s.created_at)}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
