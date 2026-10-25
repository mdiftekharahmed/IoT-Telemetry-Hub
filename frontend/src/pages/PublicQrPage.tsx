import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Snowflake, ShieldCheck, ShieldX, AlertTriangle, Skull, Clock } from 'lucide-react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

interface PublicBatch {
  vaccine_name: string
  status: 'OK' | 'AT_RISK' | 'DISCARD'
  remaining_pct: number
  expiry_date: string | null
  last_checked: string
}

const STATUS_CFG = {
  OK: {
    icon: ShieldCheck,
    title: 'Safe to Use',
    desc: 'This vaccine batch is within acceptable cold-chain parameters.',
    bg: 'from-emerald-950 via-surface-900 to-surface-900',
    border: 'border-emerald-700/40',
    iconCls: 'text-emerald-400',
    barCls: 'bg-emerald-500',
    badge: 'bg-emerald-900/50 text-emerald-300 border-emerald-700/50',
  },
  AT_RISK: {
    icon: AlertTriangle,
    title: 'At Risk',
    desc: 'This batch has experienced heat exposure. Use with caution and consult a pharmacist.',
    bg: 'from-amber-950 via-surface-900 to-surface-900',
    border: 'border-amber-700/40',
    iconCls: 'text-amber-400',
    barCls: 'bg-amber-500',
    badge: 'bg-amber-900/50 text-amber-300 border-amber-700/50',
  },
  DISCARD: {
    icon: Skull,
    title: 'DISCARD — Do Not Use',
    desc: 'This batch has exceeded its cold-chain heat budget and must not be administered.',
    bg: 'from-red-950 via-surface-900 to-surface-900',
    border: 'border-red-800/60',
    iconCls: 'text-red-400',
    barCls: 'bg-red-700',
    badge: 'bg-red-950 text-red-300 border-red-900',
  },
}

export function PublicQrPage() {
  const { token } = useParams<{ token: string }>()

  const { data, isLoading, isError } = useQuery<PublicBatch>({
    queryKey: ['public-batch', token],
    queryFn: () => axios.get(`${API_BASE}/api/public/batch/${token}`).then(r => r.data),
    retry: 1,
  })

  if (isLoading) return (
    <div className="min-h-screen bg-surface-900 flex flex-col items-center justify-center gap-4">
      <div className="w-10 h-10 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-slate-400">Loading batch info…</p>
    </div>
  )

  if (isError || !data) return (
    <div className="min-h-screen bg-surface-900 flex flex-col items-center justify-center gap-4 p-6 text-center">
      <ShieldX size={48} className="text-red-500" />
      <h1 className="text-xl font-bold text-white">Batch Not Found</h1>
      <p className="text-slate-400 max-w-xs">This QR code is invalid or has expired. Contact your pharmacist.</p>
    </div>
  )

  const cfg = STATUS_CFG[data.status] ?? STATUS_CFG.OK
  const Icon = cfg.icon

  return (
    <div className={`min-h-screen bg-gradient-to-b ${cfg.bg} flex flex-col items-center justify-center p-5`}>
      <div className={`w-full max-w-sm border ${cfg.border} rounded-2xl overflow-hidden shadow-2xl`}>
        {/* Header */}
        <div className="p-5 border-b border-white/5">
          <div className="flex items-center gap-2 mb-4">
            <Snowflake size={18} className="text-brand-400" />
            <span className="text-xs text-slate-400 font-medium">ColdChain Verification</span>
          </div>
          <div className="flex items-center gap-3">
            <div className={`w-12 h-12 rounded-xl ${cfg.badge.replace('text-', 'bg-').split(' ')[0].replace('bg-', 'bg-')} flex items-center justify-center`}>
              <Icon size={26} className={cfg.iconCls} />
            </div>
            <div>
              <h1 className={`text-lg font-bold ${cfg.iconCls}`}>{cfg.title}</h1>
              <p className="text-xs text-slate-400">Cold Chain Status</p>
            </div>
          </div>
        </div>

        {/* Info */}
        <div className="p-5 space-y-4">
          <p className="text-sm text-slate-300">{cfg.desc}</p>

          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Vaccine</span>
              <span className="text-white font-medium">{data.vaccine_name}</span>
            </div>
            {data.expiry_date && (
              <div className="flex justify-between text-sm">
                <span className="text-slate-400">Expiry Date</span>
                <span className="text-white font-medium">{data.expiry_date}</span>
              </div>
            )}
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Status</span>
              <span className={`font-semibold ${cfg.iconCls}`}>{data.status}</span>
            </div>
          </div>

          {/* Budget bar */}
          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-slate-400">Heat Budget Remaining</span>
              <span className={`font-semibold ${cfg.iconCls}`}>{data.remaining_pct.toFixed(1)}%</span>
            </div>
            <div className="h-2.5 bg-surface-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${cfg.barCls}`}
                style={{ width: `${data.remaining_pct}%` }}
              />
            </div>
          </div>

          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 pt-2 border-t border-surface-700/40">
            <Clock size={10} />
            Verified: {new Date(data.last_checked).toLocaleString()}
          </div>
        </div>
      </div>

      <p className="text-slate-600 text-xs mt-5">Powered by ColdChain Monitor</p>
    </div>
  )
}
