import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity, Download, Filter, ChevronLeft, ChevronRight,
  Clock, CheckCircle2, AlertTriangle, RefreshCw
} from 'lucide-react'
import { getReadings, getDevices } from '../api/endpoints'
import { fmtDate, fmtTemp, clsx } from '../lib/utils'
import type { Device, Reading, ReadingsResponse } from '../types'

const PAGE_SIZE = 50

export function TelemetryPage() {
  const [deviceId, setDeviceId] = useState<string>('')
  const [fromTs, setFromTs]     = useState<string>('')
  const [toTs, setToTs]         = useState<string>('')
  const [page, setPage]         = useState<number>(0)

  const { data: devices = [] } = useQuery<Device[]>({
    queryKey: ['devices'],
    queryFn: getDevices,
  })

  const { data, isLoading, isFetching, refetch } = useQuery<ReadingsResponse>({
    queryKey: ['readings', deviceId, fromTs, toTs, page],
    queryFn: () => getReadings({
      device_id: deviceId || undefined,
      from_ts: fromTs || undefined,
      to_ts: toTs || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
  })

  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)
  const items = data?.items ?? []

  // Quick timeline presets
  const setPreset = (hours: number | null) => {
    if (hours === null) {
      setFromTs('')
      setToTs('')
    } else {
      const now = new Date()
      const past = new Date(now.getTime() - hours * 60 * 60 * 1000)
      setFromTs(past.toISOString())
      setToTs(now.toISOString())
    }
    setPage(0)
  }

  const handleExportCsv = () => {
    const params = new URLSearchParams()
    if (deviceId) params.append('device_id', deviceId)
    if (fromTs) params.append('from_ts', fromTs)
    if (toTs) params.append('to_ts', toTs)
    params.append('limit', '50000')

    const token = localStorage.getItem('token')
    const url = `/api/readings/export?${params.toString()}`

    // Trigger download via fetch with bearer token
    fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(res => {
        if (!res.ok) throw new Error('Export failed')
        return res.blob()
      })
      .then(blob => {
        const downloadUrl = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = downloadUrl
        a.download = `telemetry_export_${deviceId || 'all'}_${Date.now()}.csv`
        document.body.appendChild(a)
        a.click()
        a.remove()
        window.URL.revokeObjectURL(downloadUrl)
      })
      .catch(err => alert(`CSV export error: ${err.message}`))
  }

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Activity size={20} className="text-brand-400" />
            Telemetry Explorer
          </h1>
          <p className="text-xs text-slate-400">
            Audit and inspect raw cryptographic sensor transmissions across all devices
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => refetch()} className="btn-ghost text-xs py-1.5">
            <RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} /> Refresh
          </button>
          <button onClick={handleExportCsv} className="btn-primary text-xs py-1.5 flex items-center gap-1.5">
            <Download size={13} /> Export Filtered CSV
          </button>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="card space-y-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
          <Filter size={14} className="text-brand-400" />
          Transmission Filters
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Device selector */}
          <div>
            <label className="label">Device Identifier</label>
            <select
              className="input text-xs"
              value={deviceId}
              onChange={e => { setDeviceId(e.target.value); setPage(0) }}
            >
              <option value="">All Registered Devices</option>
              {devices.map((d: Device) => (
                <option key={d.device_id} value={d.device_id}>
                  {d.device_id} ({d.name})
                </option>
              ))}
            </select>
          </div>

          {/* From timestamp */}
          <div>
            <label className="label">From Date / Time</label>
            <input
              type="datetime-local"
              className="input text-xs"
              value={fromTs ? fromTs.slice(0, 16) : ''}
              onChange={e => {
                setFromTs(e.target.value ? new Date(e.target.value).toISOString() : '')
                setPage(0)
              }}
            />
          </div>

          {/* To timestamp */}
          <div>
            <label className="label">To Date / Time</label>
            <input
              type="datetime-local"
              className="input text-xs"
              value={toTs ? toTs.slice(0, 16) : ''}
              onChange={e => {
                setToTs(e.target.value ? new Date(e.target.value).toISOString() : '')
                setPage(0)
              }}
            />
          </div>

          {/* Quick presets */}
          <div>
            <label className="label">Timeline Quick Presets</label>
            <div className="flex gap-1">
              <button onClick={() => setPreset(1)} className="btn-ghost text-[10px] py-1 px-2 flex-1">1h</button>
              <button onClick={() => setPreset(6)} className="btn-ghost text-[10px] py-1 px-2 flex-1">6h</button>
              <button onClick={() => setPreset(24)} className="btn-ghost text-[10px] py-1 px-2 flex-1">24h</button>
              <button onClick={() => setPreset(null)} className="btn-ghost text-[10px] py-1 px-2 flex-1">All</button>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-surface-700/50">
          <span>Found <strong className="text-white">{total.toLocaleString()}</strong> readings</span>
          {totalPages > 1 && (
            <span>Page <strong className="text-white">{page + 1}</strong> of <strong className="text-white">{totalPages}</strong></span>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="table-wrapper">
        <table className="tbl">
          <thead>
            <tr>
              <th>Timestamp (UTC)</th>
              <th>Device</th>
              <th>Seq</th>
              <th>Temp</th>
              <th>Compressor</th>
              <th>Door State</th>
              <th>Power</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={8} className="text-center py-10 text-slate-500">
                  <div className="flex flex-col items-center gap-2">
                    <div className="w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
                    <span>Loading telemetry records…</span>
                  </div>
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-10 text-slate-500">
                  No telemetry transmissions match the selected filters.
                </td>
              </tr>
            ) : (
              items.map((r: Reading) => (
                <tr key={`${r.device_id}-${r.seq}`}>
                  <td className="text-xs text-slate-300 font-mono flex items-center gap-1.5 whitespace-nowrap">
                    <Clock size={11} className="text-slate-500" />
                    {fmtDate(r.ts)}
                  </td>
                  <td className="font-mono text-xs text-brand-300 font-semibold">{r.device_id}</td>
                  <td className="font-mono text-xs text-slate-400">{r.seq}</td>
                  <td className="font-mono text-xs font-bold text-white">
                    <span className={clsx(
                      'px-1.5 py-0.5 rounded text-[11px]',
                      r.temp_c < 2 || r.temp_c > 8 ? 'bg-red-950 text-red-300 border border-red-800' : 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                    )}>
                      {fmtTemp(r.temp_c)}
                    </span>
                  </td>
                  <td>
                    {r.compressor_on ? (
                      <span className="badge-safe text-[10px] flex items-center gap-1 w-fit">
                        <CheckCircle2 size={10} /> ON
                      </span>
                    ) : (
                      <span className="badge text-[10px] bg-surface-700 text-slate-400 border-surface-600 w-fit">
                        OFF {r.lockout_s > 0 ? `(${r.lockout_s}s)` : ''}
                      </span>
                    )}
                  </td>
                  <td>
                    {r.door_open ? (
                      <span className="badge-warn text-[10px] flex items-center gap-1 w-fit">
                        <AlertTriangle size={10} /> OPEN ({r.door_open_s}s)
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">Closed</span>
                    )}
                  </td>
                  <td>
                    <span className="text-xs text-slate-300">
                      {r.mains_present ? 'Mains' : `Battery (${r.battery_pct?.toFixed(0) ?? '?'}%)`}
                    </span>
                  </td>
                  <td>
                    <span className={clsx(
                      'text-[10px]',
                      r.state === 'SAFE' && 'badge-safe',
                      r.state === 'WARNING' && 'badge-warn',
                      r.state === 'BREACH' && 'badge-breach',
                      r.state === 'DISCARD' && 'badge text-red-200 bg-red-900/60 border-red-700'
                    )}>
                      {r.state}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination controls */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            className="btn-ghost text-xs py-1 px-3 flex items-center gap-1"
          >
            <ChevronLeft size={14} /> Previous
          </button>
          <span className="text-xs text-slate-400">
            Page {page + 1} of {totalPages}
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="btn-ghost text-xs py-1 px-3 flex items-center gap-1"
          >
            Next <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  )
}
