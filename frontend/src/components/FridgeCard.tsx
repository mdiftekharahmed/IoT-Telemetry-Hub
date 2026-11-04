import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  DoorOpen, DoorClosed, Zap, ZapOff,
  Package, ChevronRight, Wifi, WifiOff,
} from 'lucide-react'
import {
  ComposedChart, Area, Line,
  ReferenceLine, ReferenceArea,
  YAxis, ResponsiveContainer,
} from 'recharts'
import { TempGauge } from './TempGauge'
import { BudgetBar }  from './BudgetBar'
import { StatusBadge } from './StatusBadge'
import type { FridgeSummary } from '../types'
import { fmtDuration, fmtRelative, stateBg } from '../lib/utils'

// ─── Prop types ──────────────────────────────────────────────────────────────

interface SparkReading {
  ts: string
  temp_c: number
}

interface SparkForecast {
  ts: string
  temp_c: number
}

interface Props {
  summary: FridgeSummary
  /** Last ~12–60 readings (up to 1 h) for the mini sparkline */
  recentReadings?: SparkReading[]
  /** Optional 30-min forecast overlay */
  forecastPoints?: SparkForecast[]
  /** Number of readings buffered offline (badge shown when > 0) */
  offlineBufferCount?: number
}

// ─── Constants ────────────────────────────────────────────────────────────────

const NOMINAL_RUNTIME_HOURS = 4
const SAFE_LOW  = 2   // °C
const SAFE_HIGH = 8   // °C

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Format estimated battery runtime, e.g. "~2.5h" */
function fmtBatteryRuntime(battery_pct: number): string {
  const hours = battery_pct * (NOMINAL_RUNTIME_HOURS / 100)
  return `~${hours.toFixed(1)}h`
}

// ─── Mini Sparkline ───────────────────────────────────────────────────────────

interface SparklineProps {
  recentReadings: SparkReading[]
  forecastPoints: SparkForecast[]
}

interface ChartPoint {
  ts: string
  temp?: number
  forecast?: number
}

function MiniSparkline({ recentReadings, forecastPoints }: SparklineProps) {
  const historyData: ChartPoint[] = recentReadings.map(r => ({
    ts:   r.ts,
    temp: r.temp_c,
  }))

  const forecastData: ChartPoint[] = forecastPoints.map(p => ({
    ts:       p.ts,
    forecast: p.temp_c,
  }))

  const chartData: ChartPoint[] = [...historyData, ...forecastData]

  // Y-axis domain with breathing room
  const allTemps = [
    ...recentReadings.map(r => r.temp_c),
    ...forecastPoints.map(p => p.temp_c),
  ]
  const minTemp = allTemps.length ? Math.min(...allTemps, SAFE_LOW  - 1) : SAFE_LOW  - 2
  const maxTemp = allTemps.length ? Math.max(...allTemps, SAFE_HIGH + 1) : SAFE_HIGH + 2
  const yDomain: [number, number] = [Math.floor(minTemp - 0.5), Math.ceil(maxTemp + 0.5)]

  if (chartData.length === 0) {
    return (
      <div className="h-[60px] flex items-center justify-center">
        <span className="text-[9px] text-slate-600">No readings yet</span>
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={60}>
      <ComposedChart data={chartData} margin={{ top: 4, right: 2, left: 0, bottom: 0 }}>
        {/* Safe band shading (2–8 °C) */}
        <ReferenceArea
          y1={SAFE_LOW}
          y2={SAFE_HIGH}
          fill="#16a34a"
          fillOpacity={0.10}
          ifOverflow="hidden"
        />

        <YAxis domain={yDomain} hide allowDataOverflow />

        {/* Safe-range boundary dashed red lines */}
        <ReferenceLine
          y={SAFE_LOW}
          stroke="#ef4444"
          strokeDasharray="3 2"
          strokeWidth={1}
          ifOverflow="visible"
        />
        <ReferenceLine
          y={SAFE_HIGH}
          stroke="#ef4444"
          strokeDasharray="3 2"
          strokeWidth={1}
          ifOverflow="visible"
        />

        {/* Historical temperature area */}
        <Area
          type="monotone"
          dataKey="temp"
          stroke="#38bdf8"
          strokeWidth={1.5}
          fill="#38bdf8"
          fillOpacity={0.12}
          dot={false}
          isAnimationActive={false}
          connectNulls={false}
        />

        {/* Forecast overlay – dashed amber line */}
        {forecastPoints.length > 0 && (
          <Line
            type="monotone"
            dataKey="forecast"
            stroke="#f59e0b"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  )
}

// ─── FridgeCard ───────────────────────────────────────────────────────────────

export function FridgeCard({
  summary,
  recentReadings     = [],
  forecastPoints     = [],
  offlineBufferCount = 0,
}: Props) {
  const { fridge, batches, online, demo_time_scale } = summary
  const nav   = useNavigate()
  const r     = fridge.latest
  const state = r?.state ?? 'SAFE'

  // Live door timer
  const [doorSec, setDoorSec] = useState(r?.door_open_s ?? 0)
  useEffect(() => {
    if (!r?.door_open) { setDoorSec(r?.door_open_s ?? 0); return }
    const t = setInterval(() => setDoorSec(s => s + 1), 1000)
    return () => clearInterval(t)
  }, [r?.door_open, r?.door_open_s])

  const bgClass        = stateBg(state)
  const atRiskBatches  = batches.filter(b => b.status === 'AT_RISK').length
  const discardBatches = batches.filter(b => b.status === 'DISCARD').length

  // Battery runtime – only shown when on battery power with a known %
  const showBatteryRuntime = r?.mains_present === false && r?.battery_pct != null
  const batteryRuntime     = showBatteryRuntime ? fmtBatteryRuntime(r!.battery_pct!) : null

  return (
    <div
      className={`card border ${bgClass} cursor-pointer hover:scale-[1.005] transition-all duration-200 animate-in w-full h-full flex flex-col justify-between`}
      onClick={() => nav(`/app/fridges/${fridge.id}`)}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className={`pulse-dot ${online ? 'pulse-dot-online animate-pulse-slow' : 'pulse-dot-offline'}`} />
            <h3 className="font-semibold text-white text-sm">{fridge.name}</h3>
            {demo_time_scale > 1 && (
              <span className="badge bg-purple-900/50 text-purple-300 border-purple-700/50 text-[9px]">
                {demo_time_scale}x
              </span>
            )}
          </div>
          {fridge.location && (
            <p className="text-[10px] text-slate-500 ml-4">{fridge.location}</p>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {/* Offline buffer badge */}
          {offlineBufferCount > 0 && (
            <span
              className="badge bg-amber-900/50 text-amber-300 border-amber-700/50 text-[9px]"
              title={`${offlineBufferCount} reading(s) buffered offline`}
            >
              ↑{offlineBufferCount}
            </span>
          )}
          <StatusBadge status={state} size="sm" />
          <ChevronRight size={14} className="text-slate-500" />
        </div>
      </div>

      {/* Temp + metrics */}
      <div className="flex items-center gap-4 mb-3">
        <TempGauge temp={r?.temp_c ?? 4} size="sm" />

        <div className="flex-1 grid grid-cols-2 gap-x-4 gap-y-2">
          {/* Compressor */}
          <div className="flex items-center gap-1.5">
            <Zap size={12} className={r?.compressor_on ? 'text-amber-400' : 'text-slate-500'} />
            <span className="text-xs text-slate-400">
              {r?.compressor_on ? 'Compressor ON' : 'Compressor OFF'}
            </span>
          </div>

          {/* Door */}
          <div className="flex items-center gap-1.5">
            {r?.door_open
              ? <DoorOpen  size={12} className="text-red-400" />
              : <DoorClosed size={12} className="text-slate-500" />
            }
            <span className={`text-xs ${r?.door_open ? 'text-red-400' : 'text-slate-400'}`}>
              {r?.door_open ? `Open ${fmtDuration(doorSec)}` : 'Door closed'}
            </span>
          </div>

          {/* Power + battery runtime badge */}
          <div className="flex items-center gap-1.5">
            {r?.mains_present
              ? <Zap size={12} className="text-emerald-400" />
              : <ZapOff size={12} className="text-amber-400" />
            }
            <span className="text-xs text-slate-400">
              {r?.mains_present ? 'Mains' : 'Battery'}
              {r?.battery_pct != null && ` ${r.battery_pct.toFixed(0)}%`}
            </span>
            {batteryRuntime && (
              <span
                className="badge bg-amber-900/50 text-amber-300 border-amber-700/50 text-[9px] ml-0.5"
                title="Estimated battery runtime"
              >
                {batteryRuntime}
              </span>
            )}
          </div>

          {/* Batches */}
          <div className="flex items-center gap-1.5">
            <Package size={12} className="text-slate-500" />
            <span className="text-xs text-slate-400">
              {batches.length} batch{batches.length !== 1 ? 'es' : ''}
              {atRiskBatches > 0  && <span className="text-amber-400 ml-1">·{atRiskBatches} at risk</span>}
              {discardBatches > 0 && <span className="text-red-400 ml-1">·{discardBatches} discard</span>}
            </span>
          </div>
        </div>
      </div>

      {/* Mini sparkline chart */}
      <div className="border-t border-surface-700/60 pt-1.5 mb-2">
        <MiniSparkline
          recentReadings={recentReadings}
          forecastPoints={forecastPoints}
        />
      </div>

      {/* Budget bars (worst 2 batches) */}
      {batches.length > 0 && (
        <div className="space-y-1.5 pt-2 border-t border-surface-700/60">
          {batches
            .sort((a, b) => a.remaining_pct - b.remaining_pct)
            .slice(0, 2)
            .map(b => (
              <BudgetBar
                key={b.id}
                remaining_pct={b.remaining_pct}
                exposure_min={b.exposure_weighted_min}
                label={b.code}
                showNumbers={false}
              />
            ))}
        </div>
      )}

      {/* Last seen */}
      <div className="flex items-center gap-1 mt-2">
        {online ? <Wifi size={10} className="text-emerald-500" /> : <WifiOff size={10} className="text-slate-500" />}
        <span className="text-[9px] text-slate-500">
          {r ? `Updated ${fmtRelative(r.ingested_at)}` : 'No data yet'}
        </span>
      </div>
    </div>
  )
}
