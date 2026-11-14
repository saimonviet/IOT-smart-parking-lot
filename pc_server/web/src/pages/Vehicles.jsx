import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Car, ChevronLeft, ChevronRight, LogIn, LogOut, Pencil, ScanLine, Search, X } from 'lucide-react'
import { api, tokenUrl } from '../api'
import { useAuth } from '../App.jsx'
import { useLayout } from '../useLayout'
import { READ_RESULT, fmtDuration, fmtPlate, fmtTime, money } from '../utils'

const SIZE = 15
const GATE = { in: 'Cổng vào', out: 'Cổng ra' }
const img = (path) => (path ? tokenUrl(`/plates/img/${path}`) : null)

function Thumb({ path, onOpen }) {
  if (!path) return <span className="muted small">—</span>
  return <img className="plate-thumb" src={img(path)} alt="ảnh biển số" onClick={() => onOpen(path)} />
}

/** Ô nhập biển số tay (bảo vệ xử lý khi camera không đọc được). */
function ManualGate({ isAdmin, preset, onDone }) {
  const [gate, setGate] = useState('in')
  const [plate, setPlate] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (preset) { setGate(preset.gate); setPlate(preset.plate || '') }
  }, [preset])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await api(gate === 'in' ? '/visits/manual-entry' : '/visits/manual-exit', { method: 'POST', body: { plate } })
      setMsg({ ok: true, text: gate === 'in' ? `Đã cho vào, chỉ định ô ${r.slot}` : `Đã cho ra, phí ${money(r.fee)}` + (r.pi ? '' : ' (Pi offline — mở rào tay)') })
      setPlate('')
      onDone()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <div className="card-head"><h3><ScanLine size={18} /> Xử lý tay tại cổng</h3></div>
      <p className="muted small" style={{ margin: '0 0 12px' }}>
        Khi camera không đọc được biển, bảo vệ kiểm tra xe rồi nhập biển số. Hệ thống ghi lượt, tính phí và mở rào.
      </p>
      <form className="manual" onSubmit={submit}>
        <div className="seg">
          {['in', 'out'].map((g) => (
            <button type="button" key={g} className={gate === g ? 'on' : ''} onClick={() => setGate(g)}>
              {g === 'in' ? <LogIn size={15} /> : <LogOut size={15} />} {GATE[g]}
            </button>
          ))}
        </div>
        <input value={plate} onChange={(e) => setPlate(e.target.value.toUpperCase())} placeholder="vd. 51G-123.45 hoặc 59-X1 234.56" disabled={!isAdmin} />
        <button className="btn btn-primary" disabled={!isAdmin || busy || !plate.trim()}>
          {gate === 'in' ? 'Cho vào' : 'Cho ra'}
        </button>
      </form>
      {!isAdmin && <div className="muted small">Cần tài khoản quản lý.</div>}
      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'} style={{ marginTop: 12 }}>{msg.text}</div>}
    </section>
  )
}

export default function Vehicles() {
  const { plateTick, state } = useOutletContext()
  const { user } = useAuth()
  const isAdmin = user.role === 'admin'
  const { label } = useLayout()
  const [filters, setFilters] = useState({ status: '', q: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [reads, setReads] = useState([])
  const [preset, setPreset] = useState(null)
  const [viewer, setViewer] = useState(null)
  const [reload, setReload] = useState(0)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    const q = new URLSearchParams({ page, size: SIZE, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) })
    api('/visits?' + q).then((d) => alive && setData(d)).catch((e) => setErr(e.message))
    api('/plate-reads?limit=8').then((d) => alive && setReads(d)).catch(() => {})
    return () => { alive = false }
  }, [page, filters, plateTick, reload])

  const set = (k) => (e) => { setPage(1); setFilters({ ...filters, [k]: e.target.value }) }
  const pages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1
  const plateStatus = state?.devices?.plate

  const act = async (fn) => {
    setErr(null)
    try { await fn(); setReload((n) => n + 1) } catch (e) { setErr(e.message) }
  }
  const edit = (v) => {
    const p = window.prompt(`Sửa biển số lượt #${v.id}`, fmtPlate(v.plate))
    if (p && p.trim()) act(() => api(`/visits/${v.id}`, { method: 'PUT', body: { plate: p } }))
  }
  const checkout = (v) => {
    if (window.confirm(`Kết thúc lượt xe ${fmtPlate(v.plate)} và tính phí?`)) act(() => api(`/visits/${v.id}/checkout`, { method: 'POST' }))
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Xe ra vào</h2>
          <p className="muted">Mỗi xe được đọc biển số ở cổng vào và cổng ra. Phí tính từ lúc qua cổng vào đến lúc qua cổng ra.</p>
        </div>
      </div>

      {plateStatus && !plateStatus.enabled && (
        <div className="notice">Chưa cấu hình camera biển số: vào trang Thiết bị, nhập địa chỉ ESP32-CAM.</div>
      )}
      {plateStatus?.enabled && !plateStatus.model_ready && (
        <div className="notice">{plateStatus.model_error || 'Chưa nạp được mô hình biển số'}</div>
      )}
      {err && <div className="notice">{err}</div>}

      <div className="grid-plates">
        <section className="card">
          <div className="card-head"><h3><Car size={18} /> Lần đọc gần nhất</h3>
            <span className="muted small">Xe trong bãi: <b>{data?.inside ?? '…'}</b></span></div>
          <ul className="reads">
            {reads.map((r) => {
              const [text, cls] = READ_RESULT[r.result] ?? [r.result, '']
              const denied = r.result !== 'allowed'
              return (
                <li key={r.id} className={denied ? 'read-bad' : ''}>
                  <Thumb path={r.image} onOpen={setViewer} />
                  <div className="read-main">
                    <div><span className={`gate-tag ${r.gate}`}>{GATE[r.gate]}</span> <span className="muted small">{fmtTime(r.ts)}</span></div>
                    {r.plate
                      ? <span className="plate">{fmtPlate(r.plate)}</span>
                      : <span className="muted">{r.guess ? `Đoán: ${fmtPlate(r.guess)}` : 'Không thấy biển'}</span>}
                    {r.reason && <div className="muted small">{r.reason}</div>}
                  </div>
                  <div className="read-side">
                    <span className={`badge ${cls}`}>{text}</span>
                    {r.conf != null && <span className="muted small">{Math.round(r.conf * 100)}%</span>}
                    {(r.total_ms ?? r.read_ms) != null && (
                      <span className="muted small" title={`Đọc biển ${r.read_ms ?? '?'} ms · cả lượt ${r.total_ms ?? '?'} ms`}>
                        {((r.total_ms ?? r.read_ms) / 1000).toFixed(1)} s
                      </span>
                    )}
                    {denied && isAdmin && r.result !== 'denied_full' && (
                      <button className="link" onClick={() => setPreset({ gate: r.gate, plate: fmtPlate(r.plate || r.guess || ''), t: Date.now() })}>Xử lý tay</button>
                    )}
                  </div>
                </li>
              )
            })}
            {reads.length === 0 && <li className="empty">Chưa có lần đọc nào</li>}
          </ul>
        </section>
        <ManualGate isAdmin={isAdmin} preset={preset} onDone={() => setReload((n) => n + 1)} />
      </div>

      <div className="card filters">
        <label>Biển số
          <span className="input-wrap"><Search size={15} /><input value={filters.q} onChange={set('q')} placeholder="51G123" /></span>
        </label>
        <label>Trạng thái
          <select value={filters.status} onChange={set('status')}>
            <option value="">Tất cả</option>
            <option value="inside">Đang trong bãi</option>
            <option value="done">Đã ra</option>
          </select>
        </label>
        <label>Từ ngày<input type="date" value={filters.date_from} onChange={set('date_from')} /></label>
        <label>Đến ngày<input type="date" value={filters.date_to} onChange={set('date_to')} /></label>
        <div className="filter-sum">
          <div><span className="muted small">Số lượt</span><b>{data?.total ?? '…'}</b></div>
          <div><span className="muted small">Đã thu</span><b>{data ? money(data.revenue) : '…'}</b></div>
        </div>
      </div>

      <div className="card table-card">
        <table>
          <thead>
            <tr><th>#</th><th>Biển số</th><th>Ảnh vào</th><th>Giờ vào</th><th>Ô</th><th>Ảnh ra</th><th>Giờ ra</th><th>Thời gian</th><th>Phí</th><th></th></tr>
          </thead>
          <tbody>
            {data?.items.map((v) => (
              <tr key={v.id}>
                <td className="muted">{v.id}</td>
                <td>
                  <span className="plate">{v.display}</span>
                  {v.entry_mode === 'manual' && <div className="muted small">nhập tay</div>}
                  {v.note && <div className="muted small">{v.note}</div>}
                </td>
                <td><Thumb path={v.entry_img} onOpen={setViewer} /></td>
                <td>{fmtTime(v.entry_at)}</td>
                <td>{v.slot_id ? <span className="slot-chip">{label(v.slot_id)}</span> : <span className="muted">—</span>}</td>
                <td><Thumb path={v.exit_img} onOpen={setViewer} /></td>
                <td>{v.exit_at ? fmtTime(v.exit_at) : <span className="badge badge-occupied">Trong bãi</span>}</td>
                <td>{fmtDuration(v.duration_s)}</td>
                <td>{v.fee != null ? money(v.fee) : '—'}{v.exit_mode === 'manual' && <div className="muted small">xác nhận tay</div>}</td>
                <td className="actions">
                  {isAdmin && <button className="icon-btn" title="Sửa biển số" onClick={() => edit(v)}><Pencil size={15} /></button>}
                  {isAdmin && v.status === 'inside' && <button className="icon-btn" title="Kết thúc lượt (tính phí)" onClick={() => checkout(v)}><LogOut size={15} /></button>}
                </td>
              </tr>
            ))}
            {data && data.items.length === 0 && <tr><td colSpan="10" className="empty">Chưa có lượt xe nào</td></tr>}
          </tbody>
        </table>
        <div className="pager">
          <span className="muted small">Trang {page}/{pages}</span>
          <button className="icon-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={18} /></button>
          <button className="icon-btn" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight size={18} /></button>
        </div>
      </div>

      {viewer && (
        <div className="modal-back" onClick={() => setViewer(null)}>
          <div className="viewer" onClick={(e) => e.stopPropagation()}>
            <button className="icon-btn modal-x" onClick={() => setViewer(null)}><X size={18} /></button>
            <img src={img(viewer)} alt="ảnh bằng chứng" />
          </div>
        </div>
      )}
    </>
  )
}
