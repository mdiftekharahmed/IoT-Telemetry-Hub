import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Thermometer, Package, AlertTriangle, Refrigerator } from 'lucide-react'
import { getDashboard, getReport } from '../api/endpoints'
import { FridgeCard } from '../components/FridgeCard'
import { useLiveFeed } from '../hooks/useLiveFeed'
import type { FridgeSummary } from '../types'

function StatCard({ icon: Icon, label, value, sub, color = 'text-white' }: {
  icon: typeof Thermometer; label: string; value: string | number
  sub?: string; color?: string
}) {
  return (
    <div className="card flex items-center gap-4">
      <div className="w-10 h-10 rounded-xl bg-surface-700 flex items-center justify-center flex-shrink-0">
        <Icon size={20} className={color} />
      </div>
      <div>
        <p className={`text-xl font-bold ${color}`}>{value}</p>
        <p className="text-xs text-slate-400">{label}</p>
        {sub && <p className="text-[10px] text-slate-500">{sub}</p>}
      </div>
    </div>
  )
}

export function DashboardPage() {
  const qc     = useQueryClient()
  const { subscribe } = useLiveFeed()

  const { data: summaries = [], isLoading, refetch } = useQuery<FridgeSummary[]>({
    queryKey: ['dashboard'],
    queryFn: getDashboard,
    refetchInterval: 15_000,
  })

  const { data: report } = useQuery({
    queryKey: ['report'],
    queryFn: getReport,
    refetchInterval: 30_000,
  })

  // Refresh on any live reading
  useEffect(() => subscribe(evt => {
    if (evt.type === 'reading') {
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    }
  }), [subscribe, qc])

  const totalBatches  = summaries.reduce((s, f) => s + f.batches.length, 0)
  const atRisk        = summaries.reduce((s, f) => s + f.batches.filter(b => b.status === 'AT_RISK').length, 0)
  const discard       = summaries.reduce((s, f) => s + f.batches.filter(b => b.status === 'DISCARD').length, 0)
  const demoScale     = summaries[0]?.demo_time_scale ?? 1

  return (
    <div className="p-4 lg:p-6 space-y-6 animate-in">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Live Dashboard</h1>
          <p className="text-sm text-slate-400">Real-time cold-chain status</p>
        </div>
        <div className="flex items-center gap-2">
          {demoScale > 1 && (
            <span className="badge bg-purple-900/50 text-purple-300 border-purple-700/50 text-xs">
              Demo {demoScale}×
            </span>
          )}
          <button onClick={() => refetch()} className="btn-ghost py-1.5">
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard icon={Refrigerator} label="Fridges"       value={summaries.length}  color="text-brand-400" />
        <StatCard icon={Package}      label="Batches"        value={totalBatches}      color="text-cyan-400" />
        <StatCard
          icon={AlertTriangle} label="At Risk" value={atRisk}
          color={atRisk > 0 ? 'text-amber-400' : 'text-slate-500'}
        />
        <StatCard
          icon={AlertTriangle} label="Discard" value={discard}
          color={discard > 0 ? 'text-red-400' : 'text-slate-500'}
        />
      </div>

      {/* Fridge grid */}
      {(() => {
        const gridColsClass =
          summaries.length === 1 ? 'grid-cols-1' :
          summaries.length === 2 ? 'grid-cols-1 md:grid-cols-2' :
          summaries.length === 3 ? 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3' :
          summaries.length === 4 ? 'grid-cols-1 md:grid-cols-2 lg:grid-cols-4' :
          'grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4'

        return isLoading ? (
          <div className={`grid gap-4 w-full ${gridColsClass}`}>
            {[1, 2].map(i => (
              <div key={i} className="card h-64 w-full">
                <div className="skeleton h-4 w-32 mb-3" />
                <div className="skeleton h-24 mb-3" />
                <div className="skeleton h-2 mb-1.5" />
                <div className="skeleton h-2 w-3/4" />
              </div>
            ))}
          </div>
        ) : summaries.length === 0 ? (
          <div className="card text-center py-16">
            <Refrigerator size={40} className="text-slate-600 mx-auto mb-3" />
            <p className="text-slate-400">No fridges registered yet.</p>
            <p className="text-slate-500 text-sm mt-1">Go to Admin to add a fridge and assign a device.</p>
          </div>
        ) : (
          <div className={`grid gap-4 w-full ${gridColsClass}`}>
            {summaries.map(s => (
              <FridgeCard key={s.fridge.id} summary={s} />
            ))}
          </div>
        )
      })()}

      {/* Global stats footer */}
      {report && (
        <div className="card border-surface-700/40">
          <p className="text-xs text-slate-500 mb-2 font-medium uppercase tracking-wider">System Summary</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
            {[
              { label: 'Total Readings', val: report.total_readings?.toLocaleString() },
              { label: 'Security Events', val: report.security_events },
              { label: 'Audit Entries',   val: report.audit_entries },
              { label: 'Active Devices',  val: report.fridges },
            ].map(({ label, val }) => (
              <div key={label}>
                <p className="text-base font-bold text-white">{val ?? '—'}</p>
                <p className="text-[10px] text-slate-500">{label}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
