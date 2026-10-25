import { useEffect, useRef, useState, useCallback } from 'react'
import { getAccessToken } from '../api/client'
import type { LiveEvent } from '../types'

const WS_URL = (() => {
  const base = (import.meta.env.VITE_API_URL ?? window.location.origin)
  return base.replace(/^http/, 'ws') + '/api/ws/live'
})()

const RECONNECT_DELAY_MS = 3000
const PING_INTERVAL_MS   = 20_000

interface UseLiveFeedReturn {
  connected: boolean
  lastEvent: LiveEvent | null
  subscribe: (cb: (evt: LiveEvent) => void) => () => void
}

export function useLiveFeed(): UseLiveFeedReturn {
  const [connected, setConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState<LiveEvent | null>(null)
  const wsRef       = useRef<WebSocket | null>(null)
  const pingRef     = useRef<ReturnType<typeof setInterval> | null>(null)
  const retryRef    = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef  = useRef(true)
  const listenersRef = useRef<Set<(e: LiveEvent) => void>>(new Set())

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    const token = getAccessToken()
    const url = token ? `${WS_URL}?token=${token}` : WS_URL
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return }
      setConnected(true)
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, PING_INTERVAL_MS)
    }

    ws.onmessage = evt => {
      try {
        const data: LiveEvent = JSON.parse(evt.data)
        setLastEvent(data)
        listenersRef.current.forEach(cb => cb(data))
      } catch { /* ignore non-JSON pong */ }
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setConnected(false)
      if (pingRef.current) { clearInterval(pingRef.current); pingRef.current = null }
      retryRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
    }

    ws.onerror = () => ws.close()
  }, [])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      wsRef.current?.close()
      if (pingRef.current)  clearInterval(pingRef.current)
      if (retryRef.current) clearTimeout(retryRef.current)
    }
  }, [connect])

  const subscribe = useCallback((cb: (e: LiveEvent) => void) => {
    listenersRef.current.add(cb)
    return () => listenersRef.current.delete(cb)
  }, [])

  return { connected, lastEvent, subscribe }
}
