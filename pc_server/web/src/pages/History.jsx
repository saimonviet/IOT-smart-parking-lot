import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Download } from 'lucide-react'
import { api, tokenUrl } from '../api'
import { fmtDuration, fmtPlate, fmtTime, money } from '../utils'
import { useLayout } from '../useLayout'

const SIZE = 15

export default function History() {
  const [filters, setFilters] = useState({ slot: '', status: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const { layout, label } = useLayout()

  const params = () => Object.fromEntries(Object.entries(filters).filter(([, v]) => v))

  useEffect(() => {
    let alive = true
    setLoading(true)
    const q = new URLSearchParams({ page, size: SIZE, ...params() })
    api('/history?' + q).then((d) => alive && setData(d)).finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [page, filters])

  const set = (k) => (e) => { setPage(1); setFilters({ ...filters, [k]: e.target.value }) }
  const pages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Lịch sử đỗ xe</h2>
          <p className="muted">Mỗi dòng là một lượt đỗ, được ghi tự động khi camera thấy xe vào/ra ô.</p>
        </div>
        <a className="btn" href={tokenUrl('/history/export.csv', params())}><Download size={16} /> Xuất CSV</a>
      </div>

      <div className="card filters">
        <label>Ô đỗ
          <select value={filters.slot} onChange={set('slot')}>
            <option value="">Tất cả</option>
            {layout?.slots.map((s) => <option key={s.id} value={s.id}>Ô {s.label ?? s.id}</option>)}
          </select>
        </label>
        <label>Trạng thái
          <select value={filters.status} onChange={set('status')}>
            <option value="">Tất cả</option>
            <option value="active">Đang đỗ</option>
            <option value="done">Đã rời</option>
          </select>
        </label>
        <label>Từ ngày<input type="date" value={filters.date_from} onChange={set('date_from')} /></label>
        <label>Đến ngày<input type="date" value={filters.date_to} onChange={set('date_to')} /></label>
        <div className="filter-sum">
          <div><span className="muted small">Số lượt</span><b>{data?.total ?? '…'}</b></div>
          <div><span className="muted small">Doanh thu</span><b>{data ? money(data.revenue) : '…'}</b></div>
        </div>
      </div>

      <div className={`card table-card ${loading ? 'loading' : ''}`}>
        <table>
          <thead>
            <tr><th>#</th><th>Ô</th><th>Biển số</th><th>Giờ vào</th><th>Giờ ra</th><th>Thời gian đỗ</th><th>Phí</th><th>Nguồn</th></tr>
          </thead>
          <tbody>
            {data?.items.map((r) => (
              <tr key={r.id}>
                <td className="muted">{r.id}</td>
                <td><span className="slot-chip">{label(r.slot_id)}</span></td>
                <td>{r.plate ? <span className="plate">{fmtPlate(r.plate)}</span> : <span className="muted">—</span>}</td>
                <td>{fmtTime(r.entry_at)}</td>
                <td>{r.exit_at ? fmtTime(r.exit_at) : <span className="badge badge-occupied">Đang đỗ</span>}</td>
                <td>{fmtDuration(r.duration_s)}</td>
                <td>{r.fee != null ? money(r.fee) : '—'}</td>
                <td className="muted">{r.source === 'manual' ? 'Đặt tay' : 'Camera'}</td>
              </tr>
            ))}
            {data && data.items.length === 0 && <tr><td colSpan="8" className="empty">Không có dữ liệu phù hợp</td></tr>}
          </tbody>
        </table>
        <div className="pager">
          <span className="muted small">Trang {page}/{pages}</span>
          <button className="icon-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={18} /></button>
          <button className="icon-btn" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight size={18} /></button>
        </div>
      </div>
    </>
  )
}
