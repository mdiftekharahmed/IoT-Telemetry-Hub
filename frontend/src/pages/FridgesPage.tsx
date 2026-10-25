import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Refrigerator, ChevronRight, MapPin, Cpu } from 'lucide-react'
import { getFridges } from '../api/endpoints'
import { StatusBadge } from '../components/StatusBadge'
import { TempGauge }   from '../components/TempGauge'
import type { Fridge } from '../types'

export function FridgesPage() {
  const nav = useNavigate()
  const { data: fridges = [], isLoading } = useQuery<(Fridge & { batches?: unknown[] })[]>({
    queryKey: ['fridges'],
    queryFn: getFridges,
    refetchInterval: 15_000,
  })

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      <div>
        <h1 className="text-xl font-bold text-white">Fridges</h1>
        <p className="text-sm text-slate-400">{fridges.length} registered fridges</p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1,2,3].map(i => <div key={i} className="skeleton h-24 rounded-xl" />)}
        </div>
      ) : fridges.length === 0 ? (
        <div className="card text-center py-12">
          <Refrigerator size={36} className="text-slate-600 mx-auto mb-2" />
          <p className="text-slate-400">No fridges registered. Go to Admin → Fridges to add one.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {fridges.map((f) => {
            const r     = f.latest
            const state = r?.state ?? 'SAFE'
            return (
              <div
                key={f.id}
                onClick={() => nav(`/app/fridges/${f.id}`)}
                className="card flex items-center gap-4 cursor-pointer hover:bg-surface-700/80 transition-all duration-150"
              >
                <TempGauge temp={r?.temp_c ?? 4} size="sm" animated={false} />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-semibold text-white">{f.name}</span>
                    <StatusBadge status={state} size="sm" />
                  </div>
                  <div className="flex gap-4 text-xs text-slate-400">
                    {f.location && (
                      <span className="flex items-center gap-1">
                        <MapPin size={10} />{f.location}
                      </span>
                    )}
                    {f.device_id && (
                      <span className="flex items-center gap-1 font-mono">
                        <Cpu size={10} />{f.device_id}
                      </span>
                    )}
                    <span>{f.capacity_slots} slots</span>
                  </div>
                </div>

                <ChevronRight size={16} className="text-slate-500 flex-shrink-0" />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
