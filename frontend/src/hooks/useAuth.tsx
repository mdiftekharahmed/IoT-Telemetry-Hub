import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { ccMe, ccLogin as apiLogin } from '../api/endpoints'
import { setTokens, clearTokens } from '../api/client'
import type { Role } from '../types'

interface AuthUser { id: number; username: string; role: Role; demo_time_scale: number }

interface AuthCtx {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isAdmin: boolean
  isPharm: boolean
}

const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]       = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    ccMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const login = async (username: string, password: string) => {
    const data = await apiLogin(username, password)
    setTokens(data.access_token, data.refresh_token)
    const me = await ccMe()
    setUser(me)
  }

  const logout = () => {
    clearTokens()
    setUser(null)
  }

  return (
    <Ctx.Provider value={{
      user, loading, login, logout,
      isAdmin: user?.role === 'admin',
      isPharm: user?.role === 'admin' || user?.role === 'pharmacist',
    }}>
      {children}
    </Ctx.Provider>
  )
}

export const useAuth = () => {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be inside AuthProvider')
  return ctx
}
