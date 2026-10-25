import { useState, useEffect } from 'react'
import { Outlet, Navigate } from 'react-router-dom'
import { Menu, Bell } from 'lucide-react'
import { Sidebar } from './Sidebar'
import { useAuth } from '../hooks/useAuth'
import { useLiveFeed } from '../hooks/useLiveFeed'
import { getAlerts } from '../api/endpoints'

export function Layout() {
  const { user, loading } = useAuth()
  const [sidebarOpen, setSidebarOpen]       = useState(false)
  const [unackedCount, setUnackedCount]     = useState(0)
  const { connected, subscribe }            = useLiveFeed()

  // Fetch unacked alert count on mount + on live events
  useEffect(() => {
    const load = () => getAlerts({ unacked_only: true, limit: 10 })
      .then((data: unknown[]) => setUnackedCount(data.length))
      .catch(() => {})
    load()
    const unsub = subscribe(evt => {
      if (evt.type === 'alert') setUnackedCount(n => n + 1)
    })
    return unsub
  }, [subscribe])

  if (loading) return (
    <div className="min-h-screen bg-surface-900 flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-400 text-sm">Loading…</p>
      </div>
    </div>
  )

  if (!user) return <Navigate to="/app/login" replace />

  return (
    <div className="flex h-screen overflow-hidden bg-surface-900">
      {/* Desktop sidebar */}
      <div className="hidden lg:flex w-[var(--sidebar-w)] flex-shrink-0">
        <div className="w-full">
          <Sidebar />
        </div>
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-40 flex">
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setSidebarOpen(false)} />
          <div className="relative w-72 bg-surface-900 z-50 flex flex-col h-full">
            <Sidebar onClose={() => setSidebarOpen(false)} />
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile header */}
        <header className="lg:hidden flex items-center justify-between px-4 py-3 bg-surface-800 border-b border-surface-700 flex-shrink-0">
          <button onClick={() => setSidebarOpen(true)} className="btn-icon text-slate-400">
            <Menu size={20} />
          </button>
          <span className="text-sm font-semibold text-white">ColdChain</span>
          <div className="relative">
            <Bell size={20} className="text-slate-400" />
            {unackedCount > 0 && (
              <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white text-[9px] rounded-full flex items-center justify-center font-bold">
                {unackedCount > 9 ? '9+' : unackedCount}
              </span>
            )}
          </div>
        </header>

        {/* Disconnected banner */}
        {!connected && (
          <div className="bg-amber-900/60 border-b border-amber-800/60 px-4 py-1.5 text-center text-amber-300 text-xs flex-shrink-0">
            Live feed disconnected — reconnecting…
          </div>
        )}

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
