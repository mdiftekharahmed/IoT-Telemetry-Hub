import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  DoorOpen, DoorClosed, Zap, ZapOff,
  Package, ChevronRight, Wifi, WifiOff,
} from 'lucide-react'
import { TempGauge } from './TempGauge'
import { BudgetBar }  from './BudgetBar'
import { StatusBadge } from './StatusBadge'
import type { FridgeSummary } from '../types'
import { fmtDuration, fmtRelative, stateBg } from '../lib/utils'

interface Props {
  summary: FridgeSummary
}

export function FridgeCard({ summary }: Props) {
  const { fridge, batches, online, demo_time_scale } = summary
  const nav = useNavigate()
  const r   = fridge.latest
  const state = r?.state ?? 'SAFE'

  // Live door timer
  const [doorSec, setDoorSec] = useState(r?.door_open_s ?? 0)
  useEffect(() => {
    if (!r?.door_open) { setDoorSec(r?.door_open_s ?? 0); return }
    const t = setInterval(() => setDoorSec(s => s + 1), 1000)
    return () => clearInterval(t)
  }, [r?.door_open, r?.door_open_s])

  const bgClass    = stateBg(state)
  const atRiskBatches  = batches.filter(b => b.status === 'AT_RISK').length
  const discardBatches = batches.filter(b => b.status === 'DISCARD').length

  return (
    <div
      className={`card border ${bgClass} cursor-pointer hover:scale-[1.01] transition-all duration-200 animate-in`}
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

          {/* Power */}
          <div className="flex items-center gap-1.5">
            {r?.mains_present
              ? <Zap size={12} className="text-emerald-400" />
              : <ZapOff size={12} className="text-amber-400" />
            }
            <span className="text-xs text-slate-400">
              {r?.mains_present ? 'Mains' : 'Battery'}
              {r?.battery_pct != null && ` ${r.battery_pct.toFixed(0)}%`}
            </span>
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
