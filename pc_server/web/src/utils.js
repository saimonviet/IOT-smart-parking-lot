export const money = (n) => (n ?? 0).toLocaleString('vi-VN') + 'đ'

export const fmtTime = (iso) =>
  iso ? new Date(iso).toLocaleString('vi-VN', { hour12: false, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—'

export const fmtClock = (iso) =>
  new Date(iso).toLocaleTimeString('vi-VN', { hour12: false })

export function fmtDuration(sec) {
  if (sec == null) return '—'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (h) return `${h} giờ ${m} phút`
  if (m) return `${m} phút`
  return `${sec} giây`
}

export function sinceText(ts) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
  return fmtDuration(s)
}

export const STATUS_TEXT = { free: 'Trống', occupied: 'Có xe', reserved: 'Giữ chỗ' }

/** Biển số chuẩn hóa -> dạng hiển thị: 51G12345 -> 51G-123.45, 59X123456 -> 59-X1 234.56 (giống app/plates.py) */
export function fmtPlate(p) {
  const m = /^(\d{2})([A-Z]{1,2}|[A-Z]\d)(\d{4,5})$/.exec(p || '')
  if (!m) return p || ''
  const [, prov, series, num] = m
  const n = num.length === 5 ? `${num.slice(0, 3)}.${num.slice(3)}` : num
  return /\d/.test(series[1] || '') ? `${prov}-${series} ${n}` : `${prov}${series}-${n}`
}

export const READ_RESULT = {
  allowed: ['Cho qua', 'badge-free'],
  denied_unread: ['Không đọc được', 'badge-occupied'],
  denied_duplicate: ['Trùng xe trong bãi', 'badge-occupied'],
  denied_nomatch: ['Không có lượt vào', 'badge-occupied'],
  denied_full: ['Bãi đầy', 'badge-reserved'],
}
