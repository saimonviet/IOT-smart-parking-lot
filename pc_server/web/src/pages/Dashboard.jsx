import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { AlertTriangle, CarFront, CircleParking, Clock, Info, Timer, Wallet } from 'lucide-react'
import { api, tokenUrl } from '../api'
import { fmtClock, money } from '../utils'
import LotMap from '../components/LotMap.jsx'
import SlotModal from '../components/SlotModal.jsx'
import { useLayout } from '../useLayout'

function Stat({ icon: Icon, label, value, tone, sub }) {
  return (
    <div className={`card stat tone-${tone}`}>
      <span className="stat-icon"><Icon size={20} /></span>
      <div>
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value}</div>
        {sub && <div className="stat-sub">{sub}</div>}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { state, events } = useOutletContext()
  const { layout } = useLayout()
  const [overview, setOverview] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    const load = () => api('/stats/overview').then(setOverview).catch(() => {})
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])

  if (!state || !layout) return <div className="muted">Đang tải dữ liệu…</div>
  const cam = state.devices.camera
  const selSlot = state.slots.find((s) => s.id === selected)
  const pct = Math.round(((state.occupied + state.reserved) / state.total) * 100)

  return (
    <>
      <div className="grid-stats">
        <Stat icon={CircleParking} label="Ô trống" value={`${state.free}/${state.total}`} tone="green" sub={state.free === 0 ? 'Bãi đã đầy' : `Lấp đầy ${pct}%`} />
        <Stat icon={CarFront} label="Đang có xe" value={state.occupied} tone="red" />
        <Stat icon={Timer} label="Đang giữ chỗ" value={state.reserved} tone="amber" sub="Xe đang chạy vào ô" />
        <Stat icon={Clock} label="Lượt vào hôm nay" value={overview?.entries_today ?? '…'} tone="blue" />
        <Stat icon={Wallet} label="Doanh thu hôm nay" value={overview ? money(overview.revenue_today) : '…'} tone="violet" />
      </div>

      <div className="grid-main">
        <section className="card">
          <div className="card-head">
            <h3>Sơ đồ bãi đỗ</h3>
            <div className="legend">
              <span><i className="lg lg-free" />Trống (đèn sáng)</span>
              <span><i className="lg lg-occupied" />Có xe (đèn tắt)</span>
              <span><i className="lg lg-reserved" />Giữ chỗ (nhấp nháy)</span>
            </div>
          </div>
          <LotMap layout={layout} slots={state.slots} onSelect={setSelected} />
          <div className="muted small center">Bấm vào một ô để xem chi tiết hoặc đặt tay trạng thái</div>
        </section>

        <div className="col">
          <section className="card">
            <div className="card-head">
              <h3>Camera + nhận diện</h3>
              <span className={`pill ${cam.online ? 'pill-ok' : 'pill-bad'}`}><i className="dot" />{cam.online ? `${cam.fps} fps` : 'Mất tín hiệu'}</span>
            </div>
            <div className="cam">
              <img src={tokenUrl('/stream')} alt="Camera bãi đỗ" />
              {!cam.online && <div className="cam-off">Chưa có tín hiệu camera</div>}
            </div>
            {state.devices.detector.error && <div className="notice"><AlertTriangle size={15} /> {state.devices.detector.error}</div>}
          </section>

          <section className="card events">
            <div className="card-head"><h3>Sự kiện gần đây</h3></div>
            <ul>
              {events.length === 0 && <li className="muted">Chưa có sự kiện</li>}
              {events.slice(0, 12).map((ev) => (
                <li key={ev.id} className={`ev ev-${ev.level}`}>
                  <span className="ev-ico">{ev.level === 'warn' || ev.level === 'error' ? <AlertTriangle size={14} /> : <Info size={14} />}</span>
                  <span className="ev-msg">{ev.message}</span>
                  <time>{fmtClock(ev.ts)}</time>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>

      {selSlot && <SlotModal slot={selSlot} onClose={() => setSelected(null)} />}
    </>
  )
}
