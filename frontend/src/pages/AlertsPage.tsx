import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, Check, Filter, AlertTriangle, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { getAlerts, ackAlert } from '../api/endpoints'
import { useAuth } from '../hooks/useAuth'
import { useLiveFeed } from '../hooks/useLiveFeed'
import { fmtDate } from '../lib/utils'
import type { Alert } from '../types'

const ALERT_COLORS: Record<string, string> = {
  BREACH:           'text-red-400 bg-red-950/50 border-red-800/40',
  DOOR_OPEN:        'text-amber-400 bg-amber-950/50 border-amber-800/40',
  DISCARD:          'text-red-600 bg-red-950/80 border-red-900/60',
  AT_RISK:          'text-amber-300 bg-amber-950/40 border-amber-800/30',
  POWER_FAIL:       'text-yellow-400 bg-yellow-950/40 border-yellow-800/30',
  DEVICE_OFFLINE:   'text-slate-400 bg-surface-700 border-surface-600',
  PREDICTED_BREACH: 'text-orange-400 bg-orange-950/40 border-orange-800/30',
  HEALTH_FAILING:   'text-rose-400 bg-rose-950/40 border-rose-800/30',
}

export function AlertsPage() {
  const { isPharm } = useAuth()
  const qc = useQueryClient()
  const { subscribe } = useLiveFeed()
  const [unackedOnly, setUnackedOnly] = useState(false)

  const { data: alerts = [], isLoading, refetch } = useQuery<Alert[]>({
    queryKey: ['alerts', unackedOnly],
    queryFn: () => getAlerts({ limit: 200, unacked_only: unackedOnly }),
    refetchInterval: 10_000,
  })

  const ackMut = useMutation({
    mutationFn: (id: number) => ackAlert(id),
    onSuccess: () => {
      toast.success('Alert acknowledged')
      qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })

  // Live alert: refetch on new alert event
  useEffect(() => subscribe(evt => {
    if (evt.type === 'alert') {
      qc.invalidateQueries({ queryKey: ['alerts'] })
    }
  }), [subscribe, qc])

  const unacked = alerts.filter(a => !a.acknowledged_by).length

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-white">Alerts</h1>
          {unacked > 0 && (
            <span className="badge-breach animate-pulse">{unacked} unacknowledged</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setUnackedOnly(v => !v)}
            className={`btn-ghost text-xs ${unackedOnly ? 'bg-surface-700 text-white border-surface-500' : ''}`}
          >
            <Filter size={13} />
            {unackedOnly ? 'Showing unacked' : 'All alerts'}
          </button>
          <button onClick={() => refetch()} className="btn-ghost py-1.5">
            <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1,2,3].map(i => <div key={i} className="skeleton h-16 rounded-xl" />)}
        </div>
      ) : alerts.length === 0 ? (
        <div className="card text-center py-14">
          <Bell size={36} className="text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400">No alerts{unackedOnly ? ' pending acknowledgement' : ''}.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {alerts.map((a: Alert) => {
            const cls = ALERT_COLORS[a.type] ?? 'text-slate-300 bg-surface-700 border-surface-600'
            return (
              <div key={a.id} className={`card border animate-in flex items-start gap-3 ${cls}`}>
                <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold uppercase tracking-wide">{a.type.replace(/_/g, ' ')}</span>
                    {a.device_id && <span className="text-[10px] text-slate-400 font-mono">{a.device_id}</span>}
                    {a.acknowledged_by && (
                      <span className="badge bg-emerald-900/30 text-emerald-400 border-emerald-800/30 text-[9px]">
                        <Check size={9} /> Acked
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-slate-200 mt-0.5">{a.message}</p>
                  <div className="flex gap-3 mt-1 text-[10px] text-slate-500">
                    <span>{fmtDate(a.created_at)}</span>
                    {a.sent_via && <span>via {a.sent_via}</span>}
                    {a.acknowledged_at && <span>acked {fmtDate(a.acknowledged_at)}</span>}
                  </div>
                </div>
                {isPharm && !a.acknowledged_by && (
                  <button
                    onClick={() => ackMut.mutate(a.id)}
                    disabled={ackMut.isPending}
                    className="btn-success text-xs py-1 flex-shrink-0"
                  >
                    <Check size={13} /> Acknowledge
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
