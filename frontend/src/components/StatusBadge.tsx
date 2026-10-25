import { ShieldCheck, ShieldX, AlertTriangle, Skull } from 'lucide-react'
import type { BatchStatus, FridgeState } from '../types'

type Status = FridgeState | BatchStatus | string

interface Props {
  status: Status
  size?: 'sm' | 'md' | 'lg'
  showIcon?: boolean
}

const cfg: Record<string, { label: string; cls: string; icon: typeof ShieldCheck }> = {
  SAFE:     { label: 'SAFE',     cls: 'badge-safe',    icon: ShieldCheck  },
  OK:       { label: 'OK',       cls: 'badge-safe',    icon: ShieldCheck  },
  WARNING:  { label: 'WARNING',  cls: 'badge-warning', icon: AlertTriangle },
  AT_RISK:  { label: 'AT RISK',  cls: 'badge-warning', icon: AlertTriangle },
  BREACH:   { label: 'BREACH',   cls: 'badge-breach',  icon: ShieldX      },
  DISCARD:  { label: 'DISCARD',  cls: 'badge-discard', icon: Skull        },
}

export function StatusBadge({ status, size = 'md', showIcon = true }: Props) {
  const c = cfg[status] ?? { label: status, cls: 'badge-blue', icon: ShieldCheck }
  const Icon = c.icon
  const iconSize = size === 'sm' ? 10 : size === 'lg' ? 16 : 12

  return (
    <span className={`${c.cls} ${size === 'lg' ? 'text-sm px-3 py-1.5' : size === 'sm' ? 'text-[10px] px-2 py-0.5' : ''}`}>
      {showIcon && <Icon size={iconSize} />}
      {c.label}
    </span>
  )
}
