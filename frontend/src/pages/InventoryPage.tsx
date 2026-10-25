import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Package, QrCode, Truck, RefreshCw, X } from 'lucide-react'
import { toast } from 'sonner'
import QRCode from 'qrcode'
import { getBatches, getFridges, createBatch, moveBatch, resetBatchDiscard } from '../api/endpoints'
import { StatusBadge } from '../components/StatusBadge'
import { BudgetBar }   from '../components/BudgetBar'
import { useAuth }      from '../hooks/useAuth'
import type { Batch, Fridge } from '../types'

async function showQr(batch: Batch) {
  const url = `${window.location.origin}/check/${batch.qr_token}`
  const dataUrl = await QRCode.toDataURL(url, { width: 300, margin: 2, color: { dark: '#e2e8f0', light: '#0f172a' } })
  const win = window.open('', '_blank', 'width=400,height=450')
  if (!win) return
  win.document.write(`
    <html><head><title>QR — ${batch.code}</title>
    <style>body{background:#0f172a;color:#e2e8f0;font-family:Inter,sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;margin:0;gap:12px}
    h2{margin:0;font-size:16px}p{margin:0;font-size:12px;color:#94a3b8}img{border-radius:8px}
    button{background:#3b82f6;color:white;border:none;border-radius:6px;padding:8px 16px;cursor:pointer;font-size:13px}
    </style></head><body>
    <img src="${dataUrl}" />
    <h2>${batch.code} — ${batch.vaccine_name}</h2>
    <p>${url}</p>
    <button onclick="window.print()">Print</button>
    </body></html>
  `)
}

interface AddBatchForm { code: string; vaccine_name: string; qty: string; expiry_date: string; fridge_id: string }
const EMPTY: AddBatchForm = { code: '', vaccine_name: '', qty: '', expiry_date: '', fridge_id: '' }

export function InventoryPage() {
  const { isPharm, isAdmin } = useAuth()
  const qc = useQueryClient()
  const [showAdd, setShowAdd]   = useState(false)
  const [form, setForm]         = useState<AddBatchForm>(EMPTY)
  const [moveModal, setMoveModal] = useState<{ batch: Batch; toFridgeId: string } | null>(null)

  const { data: batches = [], isLoading } = useQuery<Batch[]>({
    queryKey: ['batches'],
    queryFn: getBatches,
    refetchInterval: 15_000,
  })

  const { data: fridges = [] } = useQuery<Fridge[]>({
    queryKey: ['fridges'],
    queryFn: getFridges,
  })

  const addMut = useMutation({
    mutationFn: () => createBatch({
      code: form.code, vaccine_name: form.vaccine_name,
      qty: Number(form.qty),
      expiry_date: form.expiry_date || undefined,
      fridge_id: form.fridge_id ? Number(form.fridge_id) : undefined,
    }),
    onSuccess: () => {
      toast.success('Batch created')
      qc.invalidateQueries({ queryKey: ['batches'] })
      setShowAdd(false); setForm(EMPTY)
    },
    onError: () => toast.error('Failed to create batch'),
  })

  const moveMut = useMutation({
    mutationFn: ({ batchId, fridgeId }: { batchId: number; fridgeId: number }) =>
      moveBatch(batchId, fridgeId),
    onSuccess: () => {
      toast.success('Batch moved')
      qc.invalidateQueries({ queryKey: ['batches'] })
      setMoveModal(null)
    },
    onError: () => toast.error('Move failed'),
  })

  const resetMut = useMutation({
    mutationFn: ({ batchId, reason }: { batchId: number; reason: string }) =>
      resetBatchDiscard(batchId, reason),
    onSuccess: () => {
      toast.success('Discard latch cleared')
      qc.invalidateQueries({ queryKey: ['batches'] })
    },
    onError: () => toast.error('Reset failed'),
  })

  const byStatus = (s: string) => batches.filter((b: Batch) => b.status === s)

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Inventory</h1>
          <p className="text-sm text-slate-400">{batches.length} batches total</p>
        </div>
        {isPharm && (
          <button onClick={() => setShowAdd(true)} className="btn-primary">
            <Plus size={15} /> Add Batch
          </button>
        )}
      </div>

      {/* Summary pills */}
      <div className="flex gap-3 flex-wrap">
        {[['OK', byStatus('OK').length, 'badge-safe'],
          ['AT_RISK', byStatus('AT_RISK').length, 'badge-warning'],
          ['DISCARD', byStatus('DISCARD').length, 'badge-discard'],
        ].map(([s, n, cls]) => (
          <span key={s as string} className={cls as string}>
            {s as string} · {n as number}
          </span>
        ))}
      </div>

      {/* Batch table */}
      {isLoading ? (
        <div className="space-y-3">
          {[1,2,3].map(i => <div key={i} className="skeleton h-16 rounded-xl" />)}
        </div>
      ) : batches.length === 0 ? (
        <div className="card text-center py-12">
          <Package size={36} className="text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400">No batches yet.</p>
        </div>
      ) : (
        <div className="table-wrapper">
          <table className="tbl">
            <thead>
              <tr>
                <th>Code</th><th>Vaccine</th><th>Fridge</th><th>Status</th>
                <th>Budget</th><th>Qty</th><th>Expiry</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b: Batch) => {
                const fridge = fridges.find((f: Fridge) => f.id === b.fridge_id)
                return (
                  <tr key={b.id}>
                    <td className="font-mono text-xs font-semibold text-white">{b.code}</td>
                    <td className="text-xs">{b.vaccine_name}</td>
                    <td className="text-xs text-slate-400">{fridge?.name ?? '—'}</td>
                    <td><StatusBadge status={b.status} size="sm" /></td>
                    <td className="min-w-[120px]">
                      <BudgetBar
                        remaining_pct={b.remaining_pct}
                        exposure_min={b.exposure_weighted_min}
                        showNumbers={false}
                      />
                      <span className="text-[9px] text-slate-500">{b.remaining_pct.toFixed(1)}% left</span>
                    </td>
                    <td className="text-xs">{b.qty}</td>
                    <td className="text-xs font-mono">{b.expiry_date ?? '—'}</td>
                    <td>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => showQr(b)}
                          className="btn-icon text-slate-400 hover:text-brand-400 p-1"
                          title="Show QR"
                        >
                          <QrCode size={14} />
                        </button>
                        {isPharm && (
                          <button
                            onClick={() => setMoveModal({ batch: b, toFridgeId: '' })}
                            className="btn-icon text-slate-400 hover:text-cyan-400 p-1"
                            title="Move batch"
                          >
                            <Truck size={14} />
                          </button>
                        )}
                        {isAdmin && b.discard_latched && (
                          <button
                            onClick={() => resetMut.mutate({ batchId: b.id, reason: 'admin override' })}
                            className="btn-danger text-[10px] px-1.5 py-0.5"
                            title="Reset Discard latch"
                          >
                            <RefreshCw size={10} /> Reset
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Add Batch Modal */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="card w-full max-w-md mx-4 animate-in">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-white">Add Batch</h2>
              <button onClick={() => setShowAdd(false)} className="btn-icon text-slate-400"><X size={16}/></button>
            </div>
            <div className="space-y-3">
              {([
                ['code',         'Batch Code',   'text', 'e.g. BCH-001'],
                ['vaccine_name', 'Vaccine Name', 'text', 'e.g. Pfizer COVID-19'],
                ['qty',          'Quantity',     'number','e.g. 100'],
                ['expiry_date',  'Expiry Date',  'date',  ''],
              ] as [keyof AddBatchForm, string, string, string][]).map(([k, label, type, ph]) => (
                <div key={k}>
                  <label className="label">{label}</label>
                  <input
                    type={type}
                    className="input"
                    placeholder={ph}
                    value={form[k]}
                    onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))}
                  />
                </div>
              ))}
              <div>
                <label className="label">Assign to Fridge</label>
                <select
                  className="input"
                  value={form.fridge_id}
                  onChange={e => setForm(f => ({ ...f, fridge_id: e.target.value }))}
                >
                  <option value="">— unassigned —</option>
                  {fridges.map((f: Fridge) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              </div>
            </div>
            <div className="flex gap-2 justify-end mt-5">
              <button onClick={() => setShowAdd(false)} className="btn-ghost">Cancel</button>
              <button
                onClick={() => addMut.mutate()}
                className="btn-primary"
                disabled={addMut.isPending || !form.code || !form.vaccine_name || !form.qty}
              >
                {addMut.isPending ? 'Creating…' : 'Create Batch'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Move Modal */}
      {moveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="card w-full max-w-sm mx-4 animate-in">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-white">Move Batch</h2>
              <button onClick={() => setMoveModal(null)} className="btn-icon text-slate-400"><X size={16}/></button>
            </div>
            <p className="text-sm text-slate-300 mb-4">
              Moving <strong className="text-white">{moveModal.batch.code}</strong> to a new fridge.
            </p>
            <label className="label">Destination Fridge</label>
            <select
              className="input mb-5"
              value={moveModal.toFridgeId}
              onChange={e => setMoveModal(m => m ? { ...m, toFridgeId: e.target.value } : null)}
            >
              <option value="">Select fridge…</option>
              {fridges
                .filter((f: Fridge) => f.id !== moveModal.batch.fridge_id)
                .map((f: Fridge) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            <div className="flex gap-2 justify-end">
              <button onClick={() => setMoveModal(null)} className="btn-ghost">Cancel</button>
              <button
                onClick={() => moveMut.mutate({ batchId: moveModal.batch.id, fridgeId: Number(moveModal.toFridgeId) })}
                className="btn-primary"
                disabled={moveMut.isPending || !moveModal.toFridgeId}
              >
                {moveMut.isPending ? 'Moving…' : 'Move Batch'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
