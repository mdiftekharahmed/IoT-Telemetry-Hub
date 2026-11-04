import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Settings, Users, Refrigerator, Cpu, Sliders, Plus, X, RefreshCw,
  Lock, Copy, Check, Thermometer, ShieldCheck, Trash2, Zap, Info, Pencil
} from 'lucide-react'
import { toast } from 'sonner'
import {
  getUsers, createUser, updateUser,
  getFridges, createFridge,
  getDevices, createDevice,
  getThresholds, updateThresholds,
  getAdminParameters, addParameter, updateParameter, deleteParameter, clearParameterTelemetry,
  setTimeScale, simFault,
} from '../api/endpoints'
import { useAuth } from '../hooks/useAuth'
import { fmtDate } from '../lib/utils'
import type { User, Fridge, Device, SystemThresholds, AdminParameterItem } from '../types'


export function AdminPage() {
  const { user: currentUser, isAdmin } = useAuth()
  const qc = useQueryClient()
  const [tab, setTab] = useState<'users' | 'fridges' | 'devices' | 'thresholds' | 'parameters' | 'sim'>('thresholds')

  // Modals state
  const [showUserForm, setShowUserForm]       = useState(false)
  const [showFridgeForm, setShowFridgeForm]   = useState(false)
  const [showDeviceForm, setShowDeviceForm]   = useState(false)
  const [showParamForm, setShowParamForm]     = useState(false)
  const [createdSecret, setCreatedSecret]     = useState<{ devId: string; secret: string } | null>(null)
  const [copiedSecret, setCopiedSecret]       = useState(false)

  // Simulation state
  const [timeScaleVal, setTimeScaleVal]     = useState(1)
  const [simFaultParams, setSimFaultParams] = useState('')
  const [simDevice, setSimDevice]           = useState('')

  // Queries
  const { data: users   = [] } = useQuery<User[]>({ queryKey: ['users'],   queryFn: getUsers   })
  const { data: fridges = [] } = useQuery<Fridge[]>({ queryKey: ['fridges'], queryFn: getFridges })
  const { data: devices = [] } = useQuery<Device[]>({ queryKey: ['devices'], queryFn: getDevices })
  const { data: thresholds, isLoading: thresholdsLoading } = useQuery<SystemThresholds>({
    queryKey: ['thresholds'],
    queryFn: getThresholds,
  })
  const { data: parameters = [] } = useQuery<AdminParameterItem[]>({
    queryKey: ['admin-parameters'],
    queryFn: getAdminParameters,
  })

  // Forms
  const [uForm, setUForm] = useState({ username: '', password: '', role: 'pharmacist' })
  const [fForm, setFForm] = useState({ name: '', capacity_slots: '10', location: '', device_id: '' })
  const [dForm, setDForm] = useState({ device_id: '', name: '' })
  const [pForm, setPForm] = useState({ name: '', unit: '', enabled: true })
  const [editParam, setEditParam] = useState<AdminParameterItem | null>(null)
  const [editParamForm, setEditParamForm] = useState({ unit: '', enabled: true })

  // Thresholds form state
  const [thForm, setThForm] = useState<SystemThresholds | null>(null)

  useEffect(() => {
    if (thresholds && !thForm) {
      setThForm(thresholds)
    }
  }, [thresholds, thForm])

  // Mutations
  const createUserMut = useMutation({
    mutationFn: () => createUser({ username: uForm.username, password: uForm.password, role: uForm.role }),
    onSuccess: () => {
      toast.success('User created')
      qc.invalidateQueries({ queryKey: ['users'] })
      setShowUserForm(false)
      setUForm({ username: '', password: '', role: 'pharmacist' })
    },
    onError: () => toast.error('Failed to create user'),
  })

  const updateUserRoleMut = useMutation({
    mutationFn: ({ id, role }: { id: number; role: string }) => updateUser(id, { role }),
    onSuccess: () => {
      toast.success('User role updated — takes effect immediately')
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: () => toast.error('Failed to update role'),
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
    onSuccess: () => {
      toast.success('Fridge created')
      qc.invalidateQueries({ queryKey: ['fridges'] })
      setShowFridgeForm(false)
      setFForm({ name: '', capacity_slots: '10', location: '', device_id: '' })
    },
    onError: () => toast.error('Failed to create fridge'),
  })

  const createDeviceMut = useMutation({
    mutationFn: () => createDevice({ device_id: dForm.device_id, name: dForm.name }),
    onSuccess: (data: { device_id: string; mqtt_password?: string }) => {
      toast.success(`Device ${data.device_id} registered`)
      qc.invalidateQueries({ queryKey: ['devices'] })
      setShowDeviceForm(false)
      setCreatedSecret({ devId: data.device_id, secret: data.mqtt_password || '' })
      setDForm({ device_id: '', name: '' })
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to create device'),
  })

  const updateThresholdsMut = useMutation({
    mutationFn: (body: SystemThresholds) => updateThresholds(body as any),
    onSuccess: (data) => {
      toast.success('Thresholds saved and broadcast to devices via MQTT')
      qc.setQueryData(['thresholds'], data)
      setThForm(data)
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to update thresholds'),
  })

  const addParamMut = useMutation({
    mutationFn: () => addParameter(pForm),
    onSuccess: () => {
      toast.success(`Parameter ${pForm.name} added globally`)
      qc.invalidateQueries({ queryKey: ['admin-parameters'] })
      setShowParamForm(false)
      setPForm({ name: '', unit: '', enabled: true })
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to add parameter'),
  })

  const toggleParamMut = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) => updateParameter(name, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-parameters'] }),
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to update parameter'),
  })

  const deleteParamMut = useMutation({
    mutationFn: (name: string) => deleteParameter(name),
    onSuccess: () => {
      toast.success('Parameter deleted')
      qc.invalidateQueries({ queryKey: ['admin-parameters'] })
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to delete parameter'),
  })

  const editParamMut = useMutation({
    mutationFn: () => {
      if (!editParam) return Promise.resolve()
      return updateParameter(editParam.name, {
        unit: editParamForm.unit || undefined,
        enabled: editParamForm.enabled,
      })
    },
    onSuccess: () => {
      toast.success('Parameter updated')
      qc.invalidateQueries({ queryKey: ['admin-parameters'] })
      setEditParam(null)
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to update parameter'),
  })

  const clearParamTelemetryMut = useMutation({
    mutationFn: (name: string) => clearParameterTelemetry(name),
    onSuccess: (_: unknown, name: string) => {
      toast.success(`Telemetry cleared for "${name}"`)
      qc.invalidateQueries({ queryKey: ['admin-parameters'] })
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to clear telemetry'),
  })

    const timeScaleMut = useMutation({
    mutationFn: (ts: number) => setTimeScale(ts),
    onSuccess: (data: { demo_time_scale: number }) => toast.success(`Time scale set to ${data.demo_time_scale}×`),
    onError: () => toast.error('Failed to set time scale'),
  })

  const simFaultMut = useMutation({
    mutationFn: () => simFault(simDevice, JSON.parse(simFaultParams || '{}')),
    onSuccess: () => toast.success('Fault injected'),
    onError: () => toast.error('Failed to inject fault — check device ID and JSON'),
  })

  const copySecret = () => {
    if (createdSecret?.secret) {
      navigator.clipboard.writeText(createdSecret.secret)
      setCopiedSecret(true)
      setTimeout(() => setCopiedSecret(false), 2000)
    }
  }

  if (!isAdmin) return (
    <div className="p-6 flex flex-col items-center justify-center min-h-64 gap-2 text-slate-500">
      <Settings size={32} />
      <p>Admin access required.</p>
    </div>
  )

  const TABS = [
    { key: 'thresholds', icon: Thermometer,   label: 'Thresholds & Limits' },
    { key: 'users',      icon: Users,         label: 'Users & Roles'       },
    { key: 'fridges',    icon: Refrigerator,  label: 'Fridges'             },
    { key: 'devices',    icon: Cpu,           label: 'Devices & Secrets'   },
    { key: 'parameters', icon: ShieldCheck,   label: 'Data Parameters'     },
    { key: 'sim',        icon: Sliders,       label: 'Simulation & Scale'  },
  ] as const

  return (
    <div className="p-4 lg:p-6 space-y-5 animate-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Settings size={20} className="text-brand-400" />
            Admin Operations Panel
          </h1>
          <p className="text-xs text-slate-400">Configure global parameters, runtime thresholds, access roles & edge keys</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-surface-800 rounded-lg p-1 w-fit overflow-x-auto border border-surface-700/60">
        {TABS.map(({ key, icon: Icon, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors ${
              tab === key ? 'bg-brand-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Icon size={14} />{label}
          </button>
        ))}
      </div>

      {/* ── 1. Dynamic System Thresholds ── */}
      {tab === 'thresholds' && (
        <div className="space-y-4">
          <div className="card space-y-4">
            <div className="flex justify-between items-center border-b border-surface-700/60 pb-3">
              <div>
                <p className="text-sm font-semibold text-white flex items-center gap-2">
                  <Thermometer size={16} className="text-cyan-400" />
                  Dynamic Operational & Heat-Budget Thresholds
                </p>
                <p className="text-xs text-slate-400 mt-0.5">
                  Backed by <code className="text-brand-300">config/system_thresholds.json</code>. Changes apply immediately to budget calculations, alerts, and are pushed down to ESP32 nodes via MQTT.
                </p>
              </div>
              <button
                onClick={() => thForm && updateThresholdsMut.mutate(thForm)}
                disabled={updateThresholdsMut.isPending || !thForm}
                className="btn-primary text-xs"
              >
                <RefreshCw size={12} className={updateThresholdsMut.isPending ? 'animate-spin' : ''} />
                Save & Broadcast Downlink
              </button>
            </div>

            {thresholdsLoading || !thForm ? (
              <div className="skeleton h-48 rounded-lg" />
            ) : (
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4 pt-1">
                {/* Safe Range */}
                <div className="space-y-2 p-3 bg-surface-900/60 rounded-lg border border-surface-700/50">
                  <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5">
                    Safe Temperature Range
                  </span>
                  <div>
                    <label className="text-[11px] text-slate-400">Safe Lower Limit (°C)</label>
                    <input
                      type="number" step="0.1" className="input text-xs mt-1"
                      value={thForm.temp_safe_min}
                      onChange={e => setThForm({ ...thForm, temp_safe_min: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-slate-400">Safe Upper Limit (°C)</label>
                    <input
                      type="number" step="0.1" className="input text-xs mt-1"
                      value={thForm.temp_safe_max}
                      onChange={e => setThForm({ ...thForm, temp_safe_max: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                  <span className="text-[10px] text-slate-500 block">Readings outside this range trigger BREACH.</span>
                </div>

                {/* Compressor FSM */}
                <div className="space-y-2 p-3 bg-surface-900/60 rounded-lg border border-surface-700/50">
                  <span className="text-xs font-semibold text-cyan-400 flex items-center gap-1.5">
                    Compressor Thermostat Trigger
                  </span>
                  <div>
                    <label className="text-[11px] text-slate-400">Compressor ON Trigger (°C)</label>
                    <input
                      type="number" step="0.1" className="input text-xs mt-1"
                      value={thForm.compressor_on_temp}
                      onChange={e => setThForm({ ...thForm, compressor_on_temp: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-slate-400">Compressor OFF Target (°C)</label>
                    <input
                      type="number" step="0.1" className="input text-xs mt-1"
                      value={thForm.compressor_off_temp}
                      onChange={e => setThForm({ ...thForm, compressor_off_temp: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-slate-400">Lockout Minimum Off-Time (seconds)</label>
                    <input
                      type="number" className="input text-xs mt-1"
                      value={thForm.compressor_min_off_s}
                      onChange={e => setThForm({ ...thForm, compressor_min_off_s: parseInt(e.target.value) || 0 })}
                    />
                  </div>
                </div>

                {/* Heat-Budget Engine */}
                <div className="space-y-2 p-3 bg-surface-900/60 rounded-lg border border-surface-700/50">
                  <span className="text-xs font-semibold text-amber-400 flex items-center gap-1.5">
                    Heat-Exposure Budget Engine
                  </span>
                  <div>
                    <label className="text-[11px] text-slate-400">Exposure Starts Above (°C)</label>
                    <input
                      type="number" step="0.1" className="input text-xs mt-1"
                      value={thForm.budget_threshold_temp}
                      onChange={e => setThForm({ ...thForm, budget_threshold_temp: parseFloat(e.target.value) || 0 })}
                    />
                    <span className="text-[10px] text-slate-500">Weight = 1.0×</span>
                  </div>
                  <div>
                    <label className="text-[11px] text-slate-400">Double Rate Threshold (°C)</label>
                    <input
                      type="number" step="0.1" className="input text-xs mt-1"
                      value={thForm.budget_double_temp}
                      onChange={e => setThForm({ ...thForm, budget_double_temp: parseFloat(e.target.value) || 0 })}
                    />
                    <span className="text-[10px] text-slate-500">Weight = 2.0×</span>
                  </div>
                  <div>
                    <label className="text-[11px] text-slate-400">Total Budget (minutes)</label>
                    <input
                      type="number" className="input text-xs mt-1"
                      value={thForm.budget_total_minutes}
                      onChange={e => setThForm({ ...thForm, budget_total_minutes: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                </div>

                {/* Door & Alarms */}
                <div className="space-y-2 p-3 bg-surface-900/60 rounded-lg border border-surface-700/50">
                  <span className="text-xs font-semibold text-purple-400 flex items-center gap-1.5">
                    Door & Alert Durations
                  </span>
                  <div>
                    <label className="text-[11px] text-slate-400">Door Open Warning Delay (seconds)</label>
                    <input
                      type="number" className="input text-xs mt-1"
                      value={thForm.door_warning_s}
                      onChange={e => setThForm({ ...thForm, door_warning_s: parseInt(e.target.value) || 0 })}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-slate-400">Door Open Alarm & Buzzer Delay (seconds)</label>
                    <input
                      type="number" className="input text-xs mt-1"
                      value={thForm.door_alarm_s}
                      onChange={e => setThForm({ ...thForm, door_alarm_s: parseInt(e.target.value) || 0 })}
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-slate-400">At-Risk Budget Threshold (%)</label>
                    <input
                      type="number" className="input text-xs mt-1"
                      value={thForm.budget_at_risk_pct}
                      onChange={e => setThForm({ ...thForm, budget_at_risk_pct: parseFloat(e.target.value) || 0 })}
                    />
                  </div>
                </div>

                {/* Ambient Physics */}
                <div className="space-y-2 p-3 bg-surface-900/60 rounded-lg border border-surface-700/50">
                  <span className="text-xs font-semibold text-blue-400 flex items-center gap-1.5">
                    Ambient Room Temperature
                  </span>
                  <div>
                    <label className="text-[11px] text-slate-400">Nominal Clinic Ambient (°C)</label>
                    <input
                      type="number" step="0.5" className="input text-xs mt-1"
                      value={thForm.ambient_temp_c}
                      onChange={e => setThForm({ ...thForm, ambient_temp_c: parseFloat(e.target.value) || 0 })}
                    />
                    <span className="text-[10px] text-slate-500">Used for Newtonian emergency warming model when compressor is off.</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 2. Users & Roles (Immediate Enforcement) ── */}
      {tab === 'users' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-xs text-slate-400">{users.length} registered accounts</p>
            <button onClick={() => setShowUserForm(true)} className="btn-primary text-xs">
              <Plus size={13} /> Add User
            </button>
          </div>
          <div className="table-wrapper">
            <table className="tbl">
              <thead><tr><th>Username</th><th>Role (Immediate Effect)</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>
              <tbody>
                {users.map((u: User) => (
                  <tr key={u.id}>
                    <td className="font-medium text-white">{u.username}</td>
                    <td>
                      <select
                        className="bg-surface-800 text-xs text-white border border-surface-600 rounded px-2 py-1 focus:outline-none focus:border-brand-500"
                        value={u.role}
                        disabled={currentUser?.username === u.username}
                        onChange={e => updateUserRoleMut.mutate({ id: u.id, role: e.target.value })}
                      >
                        <option value="admin">Admin</option>
                        <option value="pharmacist">Pharmacist</option>
                        <option value="inspector">Inspector</option>
                      </select>
                    </td>
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
                        disabled={currentUser?.username === u.username}
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
                  <h2 className="font-semibold text-white">Create New User</h2>
                  <button onClick={() => setShowUserForm(false)} className="btn-icon text-slate-400"><X size={15}/></button>
                </div>
                <div className="space-y-3">
                  <div>
                    <label className="label">Username</label>
                    <input type="text" className="input" value={uForm.username} onChange={e => setUForm(f => ({...f, username: e.target.value}))} />
                  </div>
                  <div>
                    <label className="label">Password</label>
                    <input type="password" className="input" value={uForm.password} onChange={e => setUForm(f => ({...f, password: e.target.value}))} />
                  </div>
                  <div>
                    <label className="label">Role</label>
                    <select className="input" value={uForm.role} onChange={e => setUForm(f => ({...f, role: e.target.value}))}>
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

      {/* ── 3. Fridges ── */}
      {tab === 'fridges' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-xs text-slate-400">{fridges.length} fridges registered</p>
            <button onClick={() => setShowFridgeForm(true)} className="btn-primary text-xs">
              <Plus size={13} /> Add Fridge
            </button>
          </div>
          <div className="table-wrapper">
            <table className="tbl">
              <thead><tr><th>Name</th><th>Location</th><th>Assigned Device</th><th>Capacity</th></tr></thead>
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
                  <h2 className="font-semibold text-white">Add New Storage Fridge</h2>
                  <button onClick={() => setShowFridgeForm(false)} className="btn-icon text-slate-400"><X size={15}/></button>
                </div>
                <div className="space-y-3">
                  <div>
                    <label className="label">Fridge Name</label>
                    <input type="text" className="input" value={fForm.name} onChange={e => setFForm(f => ({...f, name: e.target.value}))} />
                  </div>
                  <div>
                    <label className="label">Location</label>
                    <input type="text" className="input" value={fForm.location} onChange={e => setFForm(f => ({...f, location: e.target.value}))} />
                  </div>
                  <div>
                    <label className="label">Capacity Slots</label>
                    <input type="number" className="input" value={fForm.capacity_slots} onChange={e => setFForm(f => ({...f, capacity_slots: e.target.value}))} />
                  </div>
                  <div>
                    <label className="label">Assign Device ID</label>
                    <select className="input" value={fForm.device_id} onChange={e => setFForm(f => ({...f, device_id: e.target.value}))}>
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

      {/* ── 4. Devices & Generated HMAC Secrets ── */}
      {tab === 'devices' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-xs text-slate-400">{devices.length} registered hardware nodes</p>
            <button onClick={() => setShowDeviceForm(true)} className="btn-primary text-xs">
              <Plus size={13} /> Add Device
            </button>
          </div>
          <div className="table-wrapper">
            <table className="tbl">
              <thead><tr><th>Device ID</th><th>Name</th><th>Status</th><th>Last Seen</th><th>Last Seq</th></tr></thead>
              <tbody>
                {devices.map((d: Device) => (
                  <tr key={d.device_id}>
                    <td className="font-mono text-xs text-brand-300 font-semibold">{d.device_id}</td>
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

          {/* Add Device Modal */}
          {showDeviceForm && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
              <div className="card w-full max-w-sm mx-4 animate-in">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-semibold text-white">Register Hardware Node</h2>
                  <button onClick={() => setShowDeviceForm(false)} className="btn-icon text-slate-400"><X size={15}/></button>
                </div>
                <div className="space-y-3">
                  <div>
                    <label className="label">Device ID (e.g. fridge-C)</label>
                    <input
                      type="text" className="input font-mono text-xs"
                      placeholder="fridge-C"
                      value={dForm.device_id}
                      onChange={e => setDForm(f => ({ ...f, device_id: e.target.value.trim() }))}
                    />
                    <span className="text-[10px] text-slate-500">Unique alphanumeric MQTT client identifier.</span>
                  </div>
                  <div>
                    <label className="label">Friendly Name</label>
                    <input
                      type="text" className="input text-xs"
                      placeholder="Fridge C (ICU Storage)"
                      value={dForm.name}
                      onChange={e => setDForm(f => ({ ...f, name: e.target.value }))}
                    />
                  </div>
                </div>
                <div className="flex gap-2 justify-end mt-4">
                  <button onClick={() => setShowDeviceForm(false)} className="btn-ghost">Cancel</button>
                  <button
                    onClick={() => createDeviceMut.mutate()}
                    className="btn-primary"
                    disabled={createDeviceMut.isPending || !dForm.device_id || !dForm.name}
                  >
                    {createDeviceMut.isPending ? 'Generating…' : 'Generate Secret & Register'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Secret Display Modal */}
          {createdSecret && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
              <div className="card w-full max-w-md mx-4 animate-in border border-brand-500/50">
                <h2 className="font-bold text-white text-base flex items-center gap-2">
                  <ShieldCheck size={18} className="text-emerald-400" />
                  Hardware Node Key Generated
                </h2>
                <p className="text-xs text-slate-300 mt-2">
                  Device <code className="text-brand-300 font-bold">{createdSecret.devId}</code> has been registered. Copy this 64-character HMAC-SHA256 secret key to flash into the firmware:
                </p>
                <div className="mt-3 p-3 bg-surface-900 rounded-lg border border-surface-700 flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-amber-300 break-all select-all">
                    {createdSecret.secret}
                  </span>
                  <button onClick={copySecret} className="btn-primary text-xs py-1 px-2.5 flex-shrink-0">
                    {copiedSecret ? <Check size={13} className="text-emerald-300" /> : <Copy size={13} />}
                    {copiedSecret ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <div className="mt-4 flex justify-end">
                  <button onClick={() => setCreatedSecret(null)} className="btn-primary text-xs">
                    Done
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── 5. Global Data Parameters ── */}
      {tab === 'parameters' && (
        <div className="space-y-4">
          {/* Header */}
          <div className="flex justify-between items-center flex-wrap gap-2">
            <div>
              <p className="text-xs text-slate-400">
                Global telemetry parameter catalogue — applies to all registered devices.
              </p>
              <span className="text-[10px] text-slate-500">
                <Lock size={9} className="inline mb-0.5 mr-0.5" /> System parameters are built-in and locked.
                Custom parameters can be added, toggled, or removed.
              </span>
            </div>
            <button onClick={() => setShowParamForm(true)} className="btn-primary text-xs flex items-center gap-1">
              <Plus size={13} /> Add Custom Parameter
            </button>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-3 text-[10px] text-slate-400">
            <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-full bg-blue-500/60"></span> System / Permanent (built-in, locked)</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-full bg-purple-500/60"></span> Custom (admin-defined, fully editable)</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500/60"></span> Node Power (ESP32 device supply, not fridge)</span>
          </div>

          {/* Table */}
          <div className="table-wrapper">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Parameter Key</th>
                  <th>Unit</th>
                  <th>Description</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(parameters as AdminParameterItem[]).map((p) => {
                  const isNodePower = p.name === 'device_power_status' || p.name === 'node_power' || p.name === 'node_mains_ok' || p.name === 'power_source' || p.name === 'mains_present'
                  return (
                    <tr key={p.name}>
                      {/* Key */}
                      <td>
                        <div className="flex items-center gap-1">
                          {isNodePower && <span title="ESP32 node power parameter"><Zap size={10} className="text-amber-400 flex-shrink-0" /></span>}
                          <span className="font-mono text-xs text-brand-200 font-semibold">{p.name}</span>
                        </div>
                      </td>

                      {/* Unit */}
                      <td>
                        <span className={`font-mono text-xs px-1.5 py-0.5 rounded ${
                          p.unit === 'bool' ? 'bg-blue-900/40 text-blue-300' :
                          p.unit === 'text' ? 'bg-slate-700 text-slate-300' :
                          'bg-emerald-900/40 text-emerald-300'
                        }`}>
                          {p.unit || '—'}
                        </span>
                      </td>

                      {/* Description */}
                      <td className="max-w-xs">
                        <div className="flex items-start gap-1">
                          <Info size={10} className="text-slate-500 mt-0.5 flex-shrink-0" />
                          <span className="text-[11px] text-slate-400 leading-tight">{p.description}</span>
                        </div>
                      </td>

                      {/* Type badge */}
                      <td>
                        {p.is_permanent ? (
                          <span className={`badge text-[10px] flex items-center gap-1 w-fit ${
                            isNodePower
                              ? 'bg-amber-900/40 text-amber-300 border-amber-700/60'
                              : 'bg-blue-900/40 text-blue-300 border-blue-700/60'
                          }`}>
                            <Lock size={9} />
                            {isNodePower ? 'Node Power' : 'System'}
                          </span>
                        ) : (
                          <span className="badge text-[10px] bg-purple-900/50 text-purple-300 border-purple-700/60 w-fit">
                            Custom
                          </span>
                        )}
                      </td>

                      {/* Status */}
                      <td>
                        {p.enabled
                          ? <span className="badge-safe text-[10px]">Active</span>
                          : <span className="badge text-[10px] bg-surface-700 text-slate-400 border-surface-600">Disabled</span>
                        }
                      </td>

                      {/* Actions */}
                      <td>
                        {p.is_permanent ? (
                          <div className="flex gap-1 items-center">
                            <button
                              onClick={() => { if (window.confirm(`Clear ALL stored telemetry for "${p.name}"? This cannot be undone.`)) clearParamTelemetryMut.mutate(p.name) }}
                              className="btn-icon text-amber-400 hover:text-amber-300"
                              title="Clear stored telemetry readings for this parameter"
                            >
                              <Zap size={12} />
                            </button>
                            <span className="text-[10px] text-slate-600 italic">locked</span>
                          </div>
                        ) : (
                          <div className="flex gap-1 items-center">
                            <button
                              onClick={() => {
                                setEditParam(p)
                                setEditParamForm({ unit: p.unit ?? '', enabled: p.enabled })
                              }}
                              className="btn-icon text-brand-300 hover:text-brand-200"
                              title="Edit parameter"
                            >
                              <Pencil size={12} />
                            </button>
                            <button
                              onClick={() => toggleParamMut.mutate({ name: p.name, enabled: !p.enabled })}
                              className={`text-[11px] py-0.5 px-2 rounded ${p.enabled ? 'btn-danger' : 'btn-success'}`}
                            >
                              {p.enabled ? 'Disable' : 'Enable'}
                            </button>
                            <button
                              onClick={() => { if (window.confirm(`Clear ALL stored telemetry for "${p.name}"?`)) clearParamTelemetryMut.mutate(p.name) }}
                              className="btn-icon text-amber-400 hover:text-amber-300"
                              title="Clear telemetry readings for this parameter"
                            >
                              <Zap size={12} />
                            </button>
                            <button
                              onClick={() => { if (window.confirm(`Delete parameter "${p.name}"? This also removes it from the allowed list.`)) deleteParamMut.mutate(p.name) }}
                              className="btn-icon text-red-400 hover:text-red-300"
                              title="Delete parameter"
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Add custom parameter modal */}
          {showParamForm && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
              <div className="card w-full max-w-sm mx-4 animate-in">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-semibold text-white">Add Custom Data Parameter</h2>
                  <button onClick={() => setShowParamForm(false)} className="btn-icon text-slate-400"><X size={15}/></button>
                </div>
                <div className="space-y-3">
                  <div>
                    <label className="label">Parameter Name</label>
                    <input
                      type="text" className="input font-mono text-xs"
                      placeholder="e.g. ambient_humidity"
                      value={pForm.name}
                      onChange={e => setPForm(f => ({ ...f, name: e.target.value.toLowerCase().trim() }))}
                    />
                    <span className="text-[10px] text-slate-500">Lowercase letters, numbers, underscores only.</span>
                  </div>
                  <div>
                    <label className="label">Unit (optional)</label>
                    <input
                      type="text" className="input text-xs"
                      placeholder="e.g. % or ppm or bool"
                      value={pForm.unit}
                      onChange={e => setPForm(f => ({ ...f, unit: e.target.value }))}
                    />
                  </div>
                </div>
                <div className="flex gap-2 justify-end mt-4">
                  <button onClick={() => setShowParamForm(false)} className="btn-ghost">Cancel</button>
                  <button
                    onClick={() => addParamMut.mutate()}
                    className="btn-primary"
                    disabled={addParamMut.isPending || !pForm.name}
                  >
                    {addParamMut.isPending ? 'Adding…' : 'Add to Allowed List'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}


          {/* Edit Parameter Modal */}
          {editParam && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
              <div className="card w-full max-w-sm mx-4 animate-in">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="font-semibold text-white">Edit Parameter: <code className="text-brand-300">{editParam.name}</code></h2>
                  <button onClick={() => setEditParam(null)} className="btn-icon text-slate-400"><X size={15}/></button>
                </div>
                <div className="space-y-3">
                  <div>
                    <label className="label">Unit</label>
                    <input
                      type="text" className="input text-xs"
                      placeholder="e.g. °C, %, ppm"
                      value={editParamForm.unit}
                      onChange={e => setEditParamForm(f => ({ ...f, unit: e.target.value }))}
                    />
                  </div>
                  <div className="flex items-center gap-2 pt-2">
                    <input
                      type="checkbox"
                      id="edit-enabled"
                      checked={editParamForm.enabled}
                      onChange={e => setEditParamForm(f => ({ ...f, enabled: e.target.checked }))}
                      className="rounded border-surface-600 bg-surface-900 text-brand-500"
                    />
                    <label htmlFor="edit-enabled" className="text-xs text-slate-300">Enabled for ingestion</label>
                  </div>
                </div>
                <div className="flex gap-2 justify-end mt-4">
                  <button onClick={() => setEditParam(null)} className="btn-ghost">Cancel</button>
                  <button
                    onClick={() => editParamMut.mutate()}
                    className="btn-primary"
                    disabled={editParamMut.isPending}
                  >
                    {editParamMut.isPending ? 'Saving…' : 'Save Changes'}
                  </button>
                </div>
              </div>
            </div>
          )}

      {/* ── 6. Simulation & Time Scale ── */}
      {tab === 'sim' && (
        <div className="space-y-5">
          <div className="card space-y-3">
            <p className="text-sm font-semibold text-white flex items-center gap-2">
              <Sliders size={14} className="text-purple-400" />
              Demo Time Scale Accelerator
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
              Apply Time Scale
            </button>
          </div>

          <div className="card space-y-3">
            <p className="text-sm font-semibold text-white">Inject Simulation Fault</p>
            <p className="text-xs text-slate-400">Send an authenticated sim fault command to an active edge node.</p>
            <div>
              <label className="label">Device ID</label>
              <select className="input text-xs" value={simDevice} onChange={e => setSimDevice(e.target.value)}>
                <option value="">Select device…</option>
                {devices.map((d: Device) => <option key={d.device_id} value={d.device_id}>{d.device_id} ({d.name})</option>)}
              </select>
            </div>
            <div>
              <label className="label">Fault Parameters (JSON)</label>
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
