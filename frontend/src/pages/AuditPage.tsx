import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Shield, CheckCircle2, XCircle, RefreshCw, Hash } from 'lucide-react'
import { toast } from 'sonner'
import { getAuditLog, verifyAuditChain, getSecurityEvents } from '../api/endpoints'
import { fmtDate } from '../lib/utils'
import type { AuditEntry, SecurityEvent } from '../types'

export function AuditPage() {
  const [page, setPage]   = useState(1)
  const [tab, setTab]     = useState<'audit' | 'security'>('audit')

  const { data: auditData, isLoading: auditLoading } = useQuery({
    queryKey: ['audit', page],
    queryFn: () => getAuditLog(page, 50),
    refetchInterval: 30_000,
  })

  const { data: secEvents = [], isLoading: secLoading } = useQuery<SecurityEvent[]>({
    queryKey: ['security-events'],
    queryFn: () => getSecurityEvents(200),
    refetchInterval: 30_000,
  })

  const verifyMut = useMutation({
    mutationFn: verifyAuditChain,
    onSuccess: (data: { valid: boolean; checked: number; first_broken_idx?: number }) => {
      if (data.valid) {
        toast.success(`Chain verified — ${data.checked} entries intact`)
      } else {
        toast.error(`Chain broken at entry #${data.first_broken_idx}!`)
      }
    },
    onError: () => toast.error('Verification failed'),
  })

  const SEV_COLORS: Record<string, string> = {
    BAD_SIG:       'text-red-400',
    STALE_TS:      'text-orange-400',
    REPLAY:        'text-amber-400',
    BAD_FIELD:     'text-yellow-400',
    UNKNOWN_DEVICE:'text-slate-400',
    NO_SECRET:     'text-purple-400',
  }

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Audit & Security</h1>
          <p className="text-sm text-slate-400">Hash-chained audit log & rejected message log</p>
        </div>
        <button
          onClick={() => verifyMut.mutate()}
          disabled={verifyMut.isPending}
          className="btn-ghost"
        >
          {verifyMut.isPending
            ? <RefreshCw size={14} className="animate-spin" />
            : <Shield size={14} />
          }
          Verify Chain
        </button>
      </div>

      {/* Verify result */}
      {verifyMut.data && (
        <div className={`card border animate-in flex items-center gap-3 ${
          verifyMut.data.valid
            ? 'bg-emerald-950/40 border-emerald-800/40 text-emerald-300'
            : 'bg-red-950/50 border-red-800/50 text-red-300'
        }`}>
          {verifyMut.data.valid
            ? <CheckCircle2 size={18} />
            : <XCircle size={18} />
          }
          <div>
            <p className="font-semibold text-sm">
              {verifyMut.data.valid ? 'Audit chain is intact' : 'Chain integrity VIOLATION'}
            </p>
            <p className="text-xs opacity-70">
              {verifyMut.data.valid
                ? `${verifyMut.data.checked} entries verified`
                : `First broken entry: #${verifyMut.data.first_broken_idx}`
              }
            </p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-surface-800 rounded-lg p-1 w-fit">
        {(['audit', 'security'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              tab === t ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            {t === 'audit' ? `Audit Log` : `Security Events`}
            {t === 'security' && secEvents.length > 0 && (
              <span className="ml-2 badge-breach text-[9px] px-1.5 py-0">{secEvents.length}</span>
            )}
          </button>
        ))}
      </div>

      {tab === 'audit' && (
        <>
          {auditLoading ? (
            <div className="space-y-2">
              {[1,2,3,4].map(i => <div key={i} className="skeleton h-12 rounded" />)}
            </div>
          ) : (
            <>
              <div className="table-wrapper">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>#</th><th>Time</th><th>Actor</th><th>Action</th>
                      <th>Payload</th><th>Hash</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(auditData?.entries ?? []).map((e: AuditEntry) => (
                      <tr key={e.idx}>
                        <td className="font-mono text-xs text-slate-500">{e.idx}</td>
                        <td className="text-xs font-mono text-slate-400">{fmtDate(e.ts)}</td>
                        <td className="text-xs font-semibold text-brand-300">{e.actor}</td>
                        <td>
                          <span className="badge-blue text-[10px]">{e.action}</span>
                        </td>
                        <td className="text-[10px] font-mono text-slate-400 max-w-[200px] truncate">
                          {JSON.stringify(e.payload)}
                        </td>
                        <td className="font-mono text-[10px] text-slate-500 flex items-center gap-1">
                          <Hash size={9} />{e.hash}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex items-center justify-between text-sm text-slate-400">
                <span>
                  {auditData?.total ?? 0} entries · page {page} of {Math.ceil((auditData?.total ?? 0) / 50)}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="btn-ghost py-1"
                  >← Prev</button>
                  <button
                    onClick={() => setPage(p => p + 1)}
                    disabled={!auditData || page >= Math.ceil(auditData.total / 50)}
                    className="btn-ghost py-1"
                  >Next →</button>
                </div>
              </div>
            </>
          )}
        </>
      )}

      {tab === 'security' && (
        <>
          {secLoading ? (
            <div className="space-y-2">
              {[1,2,3].map(i => <div key={i} className="skeleton h-12 rounded" />)}
            </div>
          ) : secEvents.length === 0 ? (
            <div className="card text-center py-12">
              <Shield size={32} className="text-emerald-600 mx-auto mb-2" />
              <p className="text-slate-400">No security rejections recorded.</p>
            </div>
          ) : (
            <div className="table-wrapper">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Time</th><th>Device</th><th>Kind</th><th>Excerpt</th>
                  </tr>
                </thead>
                <tbody>
                  {secEvents.map((e: SecurityEvent) => (
                    <tr key={e.id}>
                      <td className="text-xs font-mono text-slate-400">{fmtDate(e.created_at)}</td>
                      <td className="font-mono text-xs text-slate-300">{e.device_id ?? '—'}</td>
                      <td>
                        <span className={`text-xs font-semibold ${SEV_COLORS[e.kind] ?? 'text-slate-300'}`}>
                          {e.kind}
                        </span>
                      </td>
                      <td className="text-[10px] font-mono text-slate-500 max-w-[300px] truncate">
                        {e.raw_excerpt}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
