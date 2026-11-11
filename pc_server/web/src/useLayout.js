import { useEffect, useState } from 'react'
import { api } from './api'

let cache = null
const subs = new Set()

/** Tải lại sơ đồ (sau khi quản lý lưu sơ đồ mới) và báo cho mọi component đang dùng. */
export function reloadLayout() {
  return api('/layout').then((l) => {
    cache = l
    subs.forEach((fn) => fn(l))
    return l
  })
}

/** Sơ đồ bãi (tải một lần, tự cập nhật khi có sơ đồ mới) + hàm đổi id ô -> tên ô (A1, B2...). */
export function useLayout() {
  const [layout, setLayout] = useState(cache)
  useEffect(() => {
    subs.add(setLayout)
    if (!cache) reloadLayout().catch(() => {})
    return () => subs.delete(setLayout)
  }, [])
  const label = (id) => layout?.slots.find((s) => s.id === Number(id))?.label ?? String(id)
  return { layout, label }
}
