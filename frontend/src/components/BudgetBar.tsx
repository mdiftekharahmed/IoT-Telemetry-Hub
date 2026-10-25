import { budgetBarColor, fmtPct } from '../lib/utils'

interface Props {
  remaining_pct: number
  exposure_min: number
  label?: string
  showNumbers?: boolean
}

const BUDGET_MINUTES = 60

export function BudgetBar({ remaining_pct, exposure_min, label, showNumbers = true }: Props) {
  const pct   = Math.max(0, Math.min(100, remaining_pct))
  const color = budgetBarColor(pct)

  return (
    <div className="space-y-1">
      {(label || showNumbers) && (
        <div className="flex items-center justify-between text-xs">
          {label && <span className="text-slate-400">{label}</span>}
          {showNumbers && (
            <span className={pct < 20 ? 'text-red-400 font-semibold' : 'text-slate-300'}>
              {fmtPct(pct)} remaining
            </span>
          )}
        </div>
      )}
      <div className="budget-bar-track">
        <div
          className={`budget-bar-fill ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showNumbers && (
        <div className="text-[10px] text-slate-500">
          {exposure_min.toFixed(1)} / {BUDGET_MINUTES} weighted min used
        </div>
      )}
    </div>
  )
}
