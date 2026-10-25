import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Refrigerator, Package, Bell, Shield,
  BrainCircuit, Settings, LogOut, Snowflake, WifiOff, Wifi,
  ChevronRight,
} from 'lucide-react'
import { useAuth } from '../hooks/useAuth'
import { useLiveFeed } from '../hooks/useLiveFeed'
import { clsx } from '../lib/utils'

const NAV = [
  { to: '/app',          icon: LayoutDashboard, label: 'Dashboard',   exact: true },
  { to: '/app/fridges',  icon: Refrigerator,    label: 'Fridges'              },
  { to: '/app/inventory',icon: Package,          label: 'Inventory'            },
  { to: '/app/alerts',   icon: Bell,             label: 'Alerts'               },
  { to: '/app/ai',       icon: BrainCircuit,     label: 'AI Insights'          },
  { to: '/app/audit',    icon: Shield,           label: 'Audit & Security'     },
  { to: '/app/admin',    icon: Settings,         label: 'Admin',  adminOnly: true },
]

interface Props { onClose?: () => void }

export function Sidebar({ onClose }: Props) {
  const { user, logout, isAdmin } = useAuth()
  const { connected }             = useLiveFeed()
  const nav                       = useNavigate()

  const handleLogout = () => { logout(); nav('/app/login') }

  return (
    <aside className="flex flex-col h-full bg-surface-900 border-r border-surface-700/60">
      {/* Brand */}
      <div className="px-4 py-5 border-b border-surface-700/60">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-brand-500 to-cyan-500 flex items-center justify-center shadow-lg">
            <Snowflake size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white leading-none">ColdChain</h1>
            <p className="text-[9px] text-slate-500 mt-0.5">Monitor v0.2</p>
          </div>
        </div>
      </div>

      {/* Connection status */}
      <div className="px-4 py-2 border-b border-surface-700/40">
        <div className={clsx('flex items-center gap-1.5 text-[10px]', connected ? 'text-emerald-400' : 'text-amber-400')}>
          {connected ? <Wifi size={10} /> : <WifiOff size={10} />}
          {connected ? 'Live feed connected' : 'Reconnecting…'}
        </div>
      </div>

      {/* Nav links */}
      <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
        {NAV.filter(item => !item.adminOnly || isAdmin).map(({ to, icon: Icon, label, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            onClick={onClose}
            className={({ isActive }) =>
              clsx('nav-item', isActive && 'active')
            }
          >
            <Icon size={16} />
            <span className="flex-1">{label}</span>
            <ChevronRight size={12} className="opacity-30" />
          </NavLink>
        ))}
      </nav>

      {/* User profile */}
      <div className="px-3 py-3 border-t border-surface-700/60">
        <div className="flex items-center gap-3 px-2 py-2">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-brand-600 to-purple-600 flex items-center justify-center text-xs font-bold text-white">
            {user?.username[0].toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-white truncate">{user?.username}</p>
            <p className="text-[10px] text-slate-400 capitalize">{user?.role}</p>
          </div>
          <button onClick={handleLogout} className="btn-icon text-slate-400 hover:text-red-400 p-1">
            <LogOut size={14} />
          </button>
        </div>
      </div>
    </aside>
  )
}
