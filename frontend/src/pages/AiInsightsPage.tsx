import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  BrainCircuit, TrendingUp, Activity, Truck, CheckCircle2, RefreshCw,
  PowerOff, Thermometer
} from 'lucide-react'
import { toast } from 'sonner'
import {
  AreaChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, Legend
} from 'recharts'
import {
  getFridges, getMlForecast, getMlForecastAll, getMlHealth,
  getMlRelocation, confirmRelocation
} from '../api/endpoints'
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

  const { data: allForecasts = [] } = useQuery({
    queryKey: ['ml-forecast-all'],
    queryFn: getMlForecastAll,
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
        temp_normal: p.temp_normal ?? p.temp ?? p.predicted_temp,
        temp_off: p.temp_off ?? (p.type === 'history' || p.type === 'current' ? (p.temp ?? p.predicted_temp) : undefined),
        type: p.type ?? 'forecast',
        breach_pct: (p.breach_prob ?? 0) * 100,
      }))
    }
    const cur = forecast.current_temp ?? 4.0
    const predNormal = forecast.predicted_temp_30m ?? cur
    const predOff = forecast.predicted_temp_30m_off ?? (cur + 5.0)
    const stepN = (predNormal - cur) / 6
    const stepO = (predOff - cur) / 6
    return [
      { label: '-10m', temp_normal: Number((cur - stepN * 2).toFixed(2)), temp_off: Number((cur - stepN * 2).toFixed(2)), type: 'history' },
      { label: '-5m',  temp_normal: Number((cur - stepN).toFixed(2)),     temp_off: Number((cur - stepN).toFixed(2)),     type: 'history' },
      { label: 'Now',   temp_normal: Number(cur.toFixed(2)),               temp_off: Number(cur.toFixed(2)),               type: 'current' },
      { label: '+5m',  temp_normal: Number((cur + stepN).toFixed(2)),     temp_off: Number((cur + stepO).toFixed(2)),     type: 'forecast' },
      { label: '+10m', temp_normal: Number((cur + stepN * 2).toFixed(2)), temp_off: Number((cur + stepO * 2).toFixed(2)), type: 'forecast' },
      { label: '+15m', temp_normal: Number((cur + stepN * 3).toFixed(2)), temp_off: Number((cur + stepO * 3).toFixed(2)), type: 'forecast' },
      { label: '+20m', temp_normal: Number((cur + stepN * 4).toFixed(2)), temp_off: Number((cur + stepO * 4).toFixed(2)), type: 'forecast' },
      { label: '+25m', temp_normal: Number((cur + stepN * 5).toFixed(2)), temp_off: Number((cur + stepO * 5).toFixed(2)), type: 'forecast' },
      { label: '+30m', temp_normal: Number(predNormal.toFixed(2)),        temp_off: Number(predOff.toFixed(2)),        type: 'forecast' },
    ]
  })()

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <BrainCircuit size={22} className="text-brand-400" />
            AI Predictive Insights & Dual Forecast
          </h1>
          <p className="text-xs text-slate-400">
            Parallel temperature trajectories: Normal Operation vs. Compressor-Off Emergency Warming
          </p>
        </div>
        <button onClick={() => refetchForecast()} className="btn-ghost text-xs py-1.5 self-start sm:self-auto">
          <RefreshCw size={13} className={forecastLoading ? 'animate-spin' : ''} /> Refresh Projections
        </button>
      </div>

      {/* Fridge selector */}
      <div className="flex gap-2 flex-wrap items-center">
        <span className="text-xs font-semibold text-slate-400 mr-1 flex items-center gap-1">
          <Thermometer size={13} /> Select Storage Unit:
        </span>
        {fridges.map((f: Fridge) => (
          <button
            key={f.id}
            onClick={() => setSelectedId(f.id)}
            className={`btn text-xs py-1 px-3 ${fridgeId === f.id ? 'btn-primary' : 'btn-ghost'}`}
          >
            {f.name}
          </button>
        ))}
      </div>

      {/* Dual Scenario KPI Cards */}
      {forecast?.available && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Card 1: Current Sensor Reading */}
          <div className="card-sm">
            <p className="text-xs text-slate-400">Current Chamber Reading</p>
            <p className="text-xl font-bold text-white mt-1">
              {fmtTemp(forecast.current_temp)}
            </p>
            <span className="text-[10px] text-slate-500">Live chamber sensor</span>
          </div>

          {/* Card 2: Scenario 1 - Normal Operation */}
          <div className="card-sm border-l-2 border-l-cyan-400">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-cyan-300">Scenario 1: Normal</p>
              <span className="text-[10px] text-slate-500">+30m</span>
            </div>
            <p className="text-xl font-bold text-white mt-1">
              {fmtTemp(forecast.predicted_temp_30m)}
            </p>
            <span className={`text-[10px] font-medium ${forecast.breach_predicted ? 'text-red-400' : 'text-emerald-400'}`}>
              {forecast.breach_predicted ? '⚠️ Breach Predicted' : '✓ Safe Operational Band'}
            </span>
          </div>

          {/* Card 3: Scenario 2 - Compressor Off */}
          <div className="card-sm border-l-2 border-l-red-500">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-red-400 flex items-center gap-1">
                <PowerOff size={11} /> Scenario 2: Off
              </p>
              <span className="text-[10px] text-slate-500">+30m</span>
            </div>
            <p className="text-xl font-bold text-red-300 mt-1">
              {fmtTemp(forecast.predicted_temp_30m_off)}
            </p>
            <span className="text-[10px] font-medium text-amber-400">
              {forecast.breach_in_minutes_off != null
                ? `Breach in ~${forecast.breach_in_minutes_off}m without cooling`
                : 'Safe within 30m'}
            </span>
          </div>

          {/* Card 4: Model Engine */}
          <div className="card-sm">
            <p className="text-xs text-slate-400">Dual Predictive Engines</p>
            <p className="text-xs font-bold text-slate-200 mt-1">LightGBM & Thermal Physics</p>
            <span className="text-[10px] text-slate-500">
              Thermostat cycle + Newtonian drift
            </span>
          </div>
        </div>
      )}

      {/* Dual Trajectory Chart */}
      <div className="card">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-3">
          <div>
            <p className="text-sm font-semibold text-white flex items-center gap-2">
              <TrendingUp size={15} className="text-brand-400" />
              30-Minute Dual-Scenario Temperature Projection
            </p>
            <p className="text-xs text-slate-400 mt-0.5">
              Blue = Normal thermostat operation | Red Dashed = Emergency warming trajectory if compressor fails/turns off
            </p>
          </div>
          {forecast?.breach_in_minutes_off != null && (
            <span className="badge-breach text-xs px-2.5 py-1">
              Compressor Off: 8°C Breach in ~{forecast.breach_in_minutes_off}m
            </span>
          )}
        </div>

        {forecastLoading ? (
          <div className="skeleton h-56 rounded-lg" />
        ) : !forecast?.available ? (
          <div className="flex flex-col items-center justify-center h-48 text-slate-500 gap-2">
            <BrainCircuit size={28} />
            <p className="text-sm">{forecast?.reason ?? 'Insufficient telemetry data for AI projection'}</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={chartData} margin={{ top: 10, right: 15, bottom: 5, left: -10 }}>
              <defs>
                <linearGradient id="normalGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#38bdf8" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(71,85,105,0.25)" />
              <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} />
              <YAxis domain={[0, 14]} tick={{ fill: '#94a3b8', fontSize: 11 }} tickLine={false} tickFormatter={v => `${v}°C`} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                labelStyle={{ color: '#f8fafc', fontSize: 12, fontWeight: 'bold' }}
                formatter={(val: number, name: string) => {
                  if (name === 'temp_normal') return [fmtTemp(val), 'Normal Operation (ON)']
                  if (name === 'temp_off') return [fmtTemp(val), 'Compressor OFF (Warming)']
                  return [val, name]
                }}
              />
              <Legend
                verticalAlign="top"
                align="right"
                wrapperStyle={{ paddingBottom: 10, fontSize: 11 }}
                formatter={(val: string) => {
                  if (val === 'temp_normal') return <span style={{ color: '#38bdf8' }}>Normal Operation</span>
                  if (val === 'temp_off') return <span style={{ color: '#ef4444' }}>Compressor Turned Off</span>
                  return val
                }}
              />
              <ReferenceLine y={2} stroke="#38bdf8" strokeDasharray="4 2" label={{ value: 'Lower Safe (2°C)', fill: '#38bdf8', fontSize: 10 }} />
              <ReferenceLine y={8} stroke="#ef4444" strokeDasharray="4 2" label={{ value: 'Upper Breach (8°C)', fill: '#ef4444', fontSize: 10 }} />

              {/* Normal Operation curve */}
              <Area
                type="monotone"
                dataKey="temp_normal"
                stroke="#38bdf8"
                fill="url(#normalGrad)"
                strokeWidth={2.5}
                dot={{ r: 3, fill: '#38bdf8' }}
              />

              {/* Compressor OFF emergency curve */}
              <Line
                type="monotone"
                dataKey="temp_off"
                stroke="#ef4444"
                strokeWidth={2.2}
                strokeDasharray="5 3"
                dot={{ r: 3, fill: '#ef4444' }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Multi-Fridge Comparative Overview Table */}
      {allForecasts.length > 0 && (
        <div className="card space-y-3">
          <p className="text-sm font-semibold text-white flex items-center gap-2">
            <Thermometer size={15} className="text-cyan-400" />
            Fleet Dual-Scenario Forecast Comparison (All Storage Units)
          </p>
          <div className="table-wrapper">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Fridge Unit</th>
                  <th>Device</th>
                  <th>Current Temp</th>
                  <th>Normal (+30m)</th>
                  <th>Compressor Off (+30m)</th>
                  <th>Off Breach ETA</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {allForecasts.map((f: any) => (
                  <tr key={f.fridge_id} className={fridgeId === f.fridge_id ? 'bg-surface-700/30' : ''}>
                    <td className="font-semibold text-white">{f.fridge_name}</td>
                    <td className="font-mono text-xs text-brand-300">{f.device_id ?? '—'}</td>
                    <td className="font-mono text-xs text-white">{f.current_temp != null ? fmtTemp(f.current_temp) : '—'}</td>
                    <td className="font-mono text-xs text-cyan-300 font-bold">
                      {f.predicted_temp_30m != null ? fmtTemp(f.predicted_temp_30m) : '—'}
                    </td>
                    <td className="font-mono text-xs text-red-300 font-bold">
                      {f.predicted_temp_30m_off != null ? fmtTemp(f.predicted_temp_30m_off) : '—'}
                    </td>
                    <td>
                      {f.breach_in_minutes_off != null ? (
                        <span className="badge-breach text-[10px]">~{f.breach_in_minutes_off}m</span>
                      ) : (
                        <span className="badge-safe text-[10px]">Safe</span>
                      )}
                    </td>
                    <td>
                      <button
                        onClick={() => setSelectedId(f.fridge_id)}
                        className="btn-ghost text-xs py-0.5 px-2"
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Lower Row: Health & Relocations */}
      <div className="grid lg:grid-cols-2 gap-5">
        {/* Compressor health */}
        <div className="card">
          <p className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
            <Activity size={15} className="text-emerald-400" />
            Compressor Mechanical Health (Isolation Forest Anomaly Detection)
          </p>
          {healthLoading ? (
            <div className="skeleton h-20 rounded-lg" />
          ) : !health?.available ? (
            <div className="flex flex-col items-center justify-center h-20 text-slate-500 gap-1 text-sm">
              <p>{health?.reason ?? 'No telemetry available for health assessment'}</p>
            </div>
          ) : (
            <div className="space-y-3">
              <HealthGauge score={health.score} trend={health.trend} />
              <div className="grid grid-cols-2 gap-3 text-center">
                <div className="p-2 bg-surface-900 rounded-lg border border-surface-700/50">
                  <p className="text-lg font-bold text-white">{health.mean_cooling_rate} °C/min</p>
                  <p className="text-[10px] text-slate-400">Mean Cooling Rate</p>
                </div>
                <div className="p-2 bg-surface-900 rounded-lg border border-surface-700/50">
                  <p className="text-lg font-bold text-white">{health.cycles_analyzed}</p>
                  <p className="text-[10px] text-slate-400">Cycles Profiled</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Relocation suggestions */}
        <div className="card">
          <p className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
            <Truck size={15} className="text-purple-400" />
            AI Autonomous Relocation Plan
          </p>
          {relocLoading ? (
            <div className="space-y-2"><div className="skeleton h-16 rounded" /><div className="skeleton h-16 rounded" /></div>
          ) : relocation.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-28 text-slate-500 gap-1.5">
              <CheckCircle2 size={24} className="text-emerald-400" />
              <p className="text-xs text-slate-300 font-medium">Chamber conditions stable</p>
              <p className="text-[11px] text-slate-500">No batch evacuations necessary at this time</p>
            </div>
          ) : (
            <div className="space-y-3">
              {relocation.map((s: any) => (
                <div key={s.id} className="p-3 rounded-lg bg-surface-700/40 border border-purple-800/40 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-purple-300">
                      Evacuate {s.plan.length} batch(es)
                    </span>
                    <span className="text-[10px] text-slate-500">{fmtDate(s.created_at)}</span>
                  </div>
                  <div className="space-y-1">
                    {s.plan.map((item: any, i: number) => (
                      <div key={i} className="text-xs text-slate-300 flex items-center justify-between bg-surface-800/60 px-2 py-1 rounded">
                        <span><strong>{item.batch_code || item.vaccine_name}</strong> → Target Fridge #{item.to_fridge_id}</span>
                        <span className="text-[10px] text-amber-400">{item.reason}</span>
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={() => confirmMut.mutate(s.id)}
                    disabled={confirmMut.isPending}
                    className="btn-primary text-xs w-full py-1.5 mt-2"
                  >
                    {confirmMut.isPending ? 'Executing Move…' : '✓ 1-Click Execute Relocation'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
