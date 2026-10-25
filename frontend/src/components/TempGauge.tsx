import { Thermometer } from 'lucide-react'
import { tempBarColor, fmtTemp } from '../lib/utils'

interface Props {
  temp: number
  size?: 'sm' | 'md' | 'lg'
  animated?: boolean
}

export function TempGauge({ temp, size = 'md', animated = true }: Props) {
  const color = tempBarColor(temp)

  // Map temp to arc: -5°C = 0%, 20°C = 100%
  const clampedPct = Math.max(0, Math.min(100, ((temp + 5) / 25) * 100))

  const sizes = {
    sm: { outer: 72, strokeW: 5, iconSize: 12, fontSize: 'text-sm', labelSize: 'text-[9px]' },
    md: { outer: 96, strokeW: 6, iconSize: 16, fontSize: 'text-lg', labelSize: 'text-[10px]' },
    lg: { outer: 128, strokeW: 8, iconSize: 20, fontSize: 'text-2xl', labelSize: 'text-xs' },
  }

  const { outer, strokeW, iconSize, fontSize, labelSize } = sizes[size]
  const r      = (outer - strokeW * 2) / 2
  const cx     = outer / 2
  const cy     = outer / 2
  const circum = 2 * Math.PI * r
  const dashArr = circum * 0.75
  const dashOff = dashArr * (1 - clampedPct / 100)

  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative" style={{ width: outer, height: outer }}>
        <svg
          width={outer}
          height={outer}
          viewBox={`0 0 ${outer} ${outer}`}
          className={animated ? 'transition-all duration-1000' : ''}
          style={{ transform: 'rotate(135deg)' }}
        >
          {/* Track */}
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke="rgba(71,85,105,0.4)"
            strokeWidth={strokeW}
            strokeDasharray={`${dashArr} ${circum}`}
            strokeLinecap="round"
          />
          {/* Fill */}
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke={color}
            strokeWidth={strokeW}
            strokeDasharray={`${dashArr - dashOff} ${circum}`}
            strokeLinecap="round"
            style={{
              filter: `drop-shadow(0 0 4px ${color}88)`,
              transition: animated ? 'stroke-dasharray 1s ease, stroke 0.5s ease' : undefined,
            }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <Thermometer size={iconSize} style={{ color }} />
          <span className={`${fontSize} font-bold`} style={{ color }}>
            {fmtTemp(temp)}
          </span>
        </div>
      </div>
      <span className={`${labelSize} text-slate-400`}>Temperature</span>
    </div>
  )
}
