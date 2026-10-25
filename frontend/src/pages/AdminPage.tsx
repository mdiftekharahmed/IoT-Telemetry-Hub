import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Settings, Users, Refrigerator, Cpu, Sliders, Plus, X, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import {
  getUsers, createUser, updateUser,
  getFridges, createFridge,
  getDevices, setTimeScale, simFault,
} from '../api/endpoints'
import { useAuth } from '../hooks/useAuth'
import { fmtDate } from '../lib/utils'
import type { User, Fridge, Device } from '../types'

export function AdminPage() {
  const { isAdmin } = useAuth()
  const qc = useQueryClient()
  const [tab, setTab]          = useState<'users' | 'fridges' | 'devices' | 'sim'>('users')
  const [showUserForm, setShowUserForm] = useState(false)
  const [showFridgeForm, setShowFridgeForm] = useState(false)
  const [timeScaleVal, setTimeScaleVal]     = useState(1)
  const [simFaultParams, setSimFaultParams] = useState('')
  const [simDevice, setSimDevice]           = useState('')

  const { data: users   = [] } = useQuery<User[]>({ queryKey: ['users'],   queryFn: getUsers   })
  const { data: fridges = [] } = useQuery<Fridge[]>({ queryKey: ['fridges'], queryFn: getFridges })
  const { data: devices = [] } = useQuery<Device[]>({ queryKey: ['devices'], queryFn: getDevices })

  const [uForm, setUForm] = useState({ username: '', password: '', role: 'pharmacist' })
  const [fForm, setFForm] = useState({ name: '', capacity_slots: '10', location: '', device_id: '' })

  const createUserMut = useMutation({
    mutationFn: () => createUser({ username: uForm.username, password: uForm.password, role: uForm.role }),
    onSuccess: () => { toast.success('User created'); qc.invalidateQueries({ queryKey: ['users'] }); setShowUserForm(false); setUForm({ username: '', password: '', role: 'pharmacist' }) },
    onError:   () => toast.error('Failed to create user'),
  })

  const toggleUserMut = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) => updateUser(id, { active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const createFridgeMut = useMutation({
    mutationFn: () => createFridge({
      name: fForm.name,
      capacity_slots: Number(fForm.capacity_slots),
      location: fForm.location || undefined,
      device_id: fForm.device_id || undefined,
    }),
    onSuccess: () => { toast.success('Fridge created'); qc.invalidateQueries({ queryKey: ['fridges'] }); setShowFridgeForm(false) },
    onError:   () => toast.error('Failed to create fridge'),
  })

  const timeScaleMut = useMutation({
    mutationFn: (ts: number) => setTimeScale(ts),
    onSuccess: (data: { demo_time_scale: number }) => toast.success(`Time scale set to ${data.demo_time_scale}×`),
    onError:   () => toast.error('Failed to set time scale'),
  })

  const simFaultMut = useMutation({
    mutationFn: () => simFault(simDevice, JSON.parse(simFaultParams || '{}')),
    onSuccess: () => toast.success('Fault injected'),
    onError:   () => toast.error('Failed to inject fault — check device ID and JSON'),
  })

  if (!isAdmin) return (
    <div className="p-6 flex flex-col items-center justify-center min-h-64 gap-2 text-slate-500">
      <Settings size={32} />
      <p>Admin access required.</p>
    </div>
  )

  const TABS = [
    { key: 'users',   icon: Users,       label: 'Users'   },
    { key: 'fridges', icon: Refrigerator, label: 'Fridges' },
    { key: 'devices', icon: Cpu,          label: 'Devices' },
    { key: 'sim',     icon: Sliders,      label: 'Simulation' },
  ] as const

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <Settings size={20} className="text-brand-400" />
        Admin Panel
      </h1>

      {/* Tabs */}
      <div className="flex gap-1 bg-surface-800 rounded-lg p-1 w-fit overflow-x-auto">
        {TABS.map(({ key, icon: Icon, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors ${
              tab === key ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Icon size={14} />{label}
          </button>
        ))}
      </div>

      {/* ── Users ── */}
      {tab === 'users' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-sm text-slate-400">{users.length} users</p>
            <button onClick={() => setShowUserForm(true)} className="btn-primary text-xs">
              <Plus size={13} /> Add User
            </button>
          </div>
          <div className="table-wrapper">
            <table className="tbl">
              <thead><tr><th>Username</th><th>Role</th><th>Status</th><th>Created</th><th></th></tr></thead>
              <tbody>
                {users.map((u: User) => (
                  <tr key={u.id}>
                    <td className="font-medium text-white">{u.username}</td>
                    <td><span className="badge-blue text-[10px]">{u.role}</span></td>
                    <td>
                      {u.active
                        ? <span className="badge-safe text-[10px]">Active</span>
                        : <span className="badge text-[10px] bg-surface-700 text-slate-400 border-surface-600">Disabled</span>
                      }
                    </td>
                    <td className="text-xs text-slate-500">{fmtDate(u.created_at)}</td>
                    <td>
                      <button
                        onClick={() => toggleUserMut.mutate({ id: u.id, active: !u.active })}
                        className={`text-xs ${u.active ? 'btn-danger' : 'btn-success'} py-0.5 px-2`}
                      >
                        {u.active ? 'Disable' : 'Enable'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {showUserForm && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
              <div className="card w-full max-w-sm mx-4 animate-in">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-semibold text-white">Create User</h2>
                  <button onClick={() => setShowUserForm(false)} className="btn-icon text-slate-400"><X size={15}/></button>
                </div>
                <div className="space-y-3">
                  {([['username','Username','text'],['password','Password','password']] as [keyof typeof uForm,string,string][]).map(([k,label,type]) => (
                    <div key={k}>
                      <label className="label">{label}</label>
                      <input type={type} className="input" value={uForm[k]} onChange={e => setUForm(f => ({...f,[k]:e.target.value}))} />
                    </div>
                  ))}
                  <div>
                    <label className="label">Role</label>
                    <select className="input" value={uForm.role} onChange={e => setUForm(f => ({...f,role:e.target.value}))}>
                      <option value="pharmacist">Pharmacist</option>
                      <option value="inspector">Inspector</option>
                      <option value="admin">Admin</option>
                    </select>
                  </div>
                </div>
                <div className="flex gap-2 justify-end mt-4">
                  <button onClick={() => setShowUserForm(false)} className="btn-ghost">Cancel</button>
                  <button onClick={() => createUserMut.mutate()} className="btn-primary" disabled={createUserMut.isPending || !uForm.username || !uForm.password}>
                    {createUserMut.isPending ? 'Creating…' : 'Create'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Fridges ── */}
      {tab === 'fridges' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-sm text-slate-400">{fridges.length} fridges</p>
            <button onClick={() => setShowFridgeForm(true)} className="btn-primary text-xs">
              <Plus size={13} /> Add Fridge
            </button>
          </div>
          <div className="table-wrapper">
            <table className="tbl">
              <thead><tr><th>Name</th><th>Location</th><th>Device</th><th>Capacity</th></tr></thead>
              <tbody>
                {fridges.map((f: Fridge) => (
                  <tr key={f.id}>
                    <td className="font-medium text-white">{f.name}</td>
                    <td className="text-xs text-slate-400">{f.location ?? '—'}</td>
                    <td className="font-mono text-xs text-brand-300">{f.device_id ?? '—'}</td>
                    <td className="text-xs">{f.capacity_slots} slots</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {showFridgeForm && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
              <div className="card w-full max-w-sm mx-4 animate-in">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-semibold text-white">Add Fridge</h2>
                  <button onClick={() => setShowFridgeForm(false)} className="btn-icon text-slate-400"><X size={15}/></button>
                </div>
                <div className="space-y-3">
                  {([['name','Fridge Name'],['location','Location (optional)'],['capacity_slots','Capacity Slots']] as [keyof typeof fForm, string][]).map(([k,label]) => (
                    <div key={k}>
                      <label className="label">{label}</label>
                      <input type={k==='capacity_slots'?'number':'text'} className="input" value={fForm[k]} onChange={e => setFForm(f => ({...f,[k]:e.target.value}))} />
                    </div>
                  ))}
                  <div>
                    <label className="label">Device ID (optional)</label>
                    <select className="input" value={fForm.device_id} onChange={e => setFForm(f => ({...f,device_id:e.target.value}))}>
                      <option value="">— none —</option>
                      {devices.map((d: Device) => <option key={d.device_id} value={d.device_id}>{d.device_id} ({d.name})</option>)}
                    </select>
                  </div>
                </div>
                <div className="flex gap-2 justify-end mt-4">
                  <button onClick={() => setShowFridgeForm(false)} className="btn-ghost">Cancel</button>
                  <button onClick={() => createFridgeMut.mutate()} className="btn-primary" disabled={createFridgeMut.isPending || !fForm.name}>
                    {createFridgeMut.isPending ? 'Creating…' : 'Create'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Devices ── */}
      {tab === 'devices' && (
        <div className="table-wrapper">
          <table className="tbl">
            <thead><tr><th>Device ID</th><th>Name</th><th>Status</th><th>Last Seen</th><th>Last Seq</th></tr></thead>
            <tbody>
              {devices.map((d: Device) => (
                <tr key={d.device_id}>
                  <td className="font-mono text-xs text-brand-300">{d.device_id}</td>
                  <td className="text-sm text-white">{d.name}</td>
                  <td>
                    {d.enabled
                      ? <span className="badge-safe text-[10px]">Enabled</span>
                      : <span className="badge text-[10px] bg-surface-700 text-slate-400 border-surface-600">Disabled</span>
                    }
                  </td>
                  <td className="text-xs text-slate-400">{d.last_seen ? fmtDate(d.last_seen) : '—'}</td>
                  <td className="font-mono text-xs text-slate-400">{d.last_seq ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Simulation ── */}
      {tab === 'sim' && (
        <div className="space-y-5">
          {/* Time scale */}
          <div className="card space-y-3">
            <p className="text-sm font-semibold text-white flex items-center gap-2">
              <Sliders size={14} className="text-purple-400" />
              Demo Time Scale
            </p>
            <p className="text-xs text-slate-400">Accelerates thermal simulation. 1× = real-time, 60× = 1 min simulates 1 hour.</p>
            <div className="flex items-center gap-4">
              <input
                type="range" min={1} max={1000} step={1}
                value={timeScaleVal}
                onChange={e => setTimeScaleVal(Number(e.target.value))}
                className="flex-1 accent-purple-500"
              />
              <span className="text-white font-mono w-16 text-right">{timeScaleVal}×</span>
            </div>
            <button
              onClick={() => timeScaleMut.mutate(timeScaleVal)}
              disabled={timeScaleMut.isPending}
              className="btn-warning"
            >
              <RefreshCw size={13} className={timeScaleMut.isPending ? 'animate-spin' : ''} />
              Apply
            </button>
          </div>

          {/* Fault inject */}
          <div className="card space-y-3">
            <p className="text-sm font-semibold text-white">Inject Simulation Fault</p>
            <p className="text-xs text-slate-400">Send a sim fault command to a device (admin only). Device must be registered.</p>
            <div>
              <label className="label">Device ID</label>
              <select className="input" value={simDevice} onChange={e => setSimDevice(e.target.value)}>
                <option value="">Select device…</option>
                {devices.map((d: Device) => <option key={d.device_id} value={d.device_id}>{d.device_id}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Fault Params (JSON)</label>
              <textarea
                className="input font-mono text-xs h-20 resize-none"
                placeholder={'{"fault": "compressor_weak", "k_cool": 0.005}'}
                value={simFaultParams}
                onChange={e => setSimFaultParams(e.target.value)}
              />
            </div>
            <button
              onClick={() => simFaultMut.mutate()}
              disabled={simFaultMut.isPending || !simDevice}
              className="btn-danger"
            >
              {simFaultMut.isPending ? 'Injecting…' : '⚡ Inject Fault'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
