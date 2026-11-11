import { useState } from 'react'
import { X } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../App.jsx'
import { fmtTime, sinceText, STATUS_TEXT } from '../utils'

export default function SlotModal({ slot, onClose }) {
  const { user } = useAuth()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const isAdmin = user.role === 'admin'

  const set = async (mode) => {
    setBusy(true)
    setErr('')
    try {
      await api(`/slots/${slot.id}/override`, { method: 'POST', body: { mode } })
      onClose()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="icon-btn modal-x" onClick={onClose}><X size={18} /></button>
        <h3>Ô {slot.label ?? slot.id}</h3>
        <span className={`badge badge-${slot.status}`}>{STATUS_TEXT[slot.status]}</span>
        <dl className="kv">
          <dt>Trạng thái từ</dt><dd>{sinceText(slot.since)}</dd>
          {slot.entry_at && (<><dt>Giờ vào</dt><dd>{fmtTime(slot.entry_at)}</dd></>)}
          {slot.status === 'reserved' && (<><dt>Giữ chỗ còn</dt><dd>{slot.expires_in}s</dd></>)}
          <dt>Nguồn dữ liệu</dt>
          <dd>{slot.override === null || slot.override === undefined ? 'Camera / AI' : 'Quản lý đặt tay'}</dd>
        </dl>
        {isAdmin ? (
          <>
            <div className="muted small">Đặt tay (dùng khi test hoặc camera lỗi)</div>
            <div className="btn-row">
              <button className="btn" disabled={busy} onClick={() => set('occupied')}>Đặt có xe</button>
              <button className="btn" disabled={busy} onClick={() => set('free')}>Đặt trống</button>
              <button className="btn btn-ghost" disabled={busy} onClick={() => set('auto')}>Theo camera</button>
            </div>
          </>
        ) : <div className="muted small">Tài khoản chỉ xem, không thể chỉnh sửa.</div>}
        {err && <div className="form-error">{err}</div>}
      </div>
    </div>
  )
}
