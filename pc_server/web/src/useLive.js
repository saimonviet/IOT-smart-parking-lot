import { useEffect, useRef, useState } from 'react'
import { api, getToken } from './api'
import { reloadLayout } from './useLayout'

/** Nhận trạng thái bãi xe + sự kiện theo thời gian thực qua WebSocket (tự kết nối lại). */
export function useLive() {
  const [state, setState] = useState(null)
  const [events, setEvents] = useState([])
  const [plateTick, setPlateTick] = useState(0) // tăng mỗi lần đọc biển số -> trang Xe ra vào tải lại
  const [lastPlate, setLastPlate] = useState(null)
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)

  useEffect(() => {
    let closed = false
    let timer
    api('/events?limit=30').then(setEvents).catch(() => {})

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/ws/dashboard?token=${getToken()}`)
      wsRef.current = ws
      ws.onopen = () => setConnected(true)
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data)
        if (msg.type === 'state') setState(msg.data)
        else if (msg.type === 'event') setEvents((prev) => [{ id: Math.random(), ...msg.data }, ...prev].slice(0, 60))
        else if (msg.type === 'layout') reloadLayout().catch(() => {})
        else if (msg.type === 'plate') { setLastPlate(msg.data); setPlateTick((n) => n + 1) }
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) timer = setTimeout(connect, 2000)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      wsRef.current?.close()
    }
  }, [])

  return { state, events, connected, plateTick, lastPlate }
}
