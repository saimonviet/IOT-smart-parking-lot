import { useEffect, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { money } from '../utils'
import { useLayout } from '../useLayout'

const AXIS = { stroke: '#64748b', fontSize: 12, tickLine: false, axisLine: false }
const TIP = { contentStyle: { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, color: '#e2e8f0' }, cursor: { fill: 'rgba(148,163,184,.08)' } }

function Kpi({ label, value }) {
  return <div className="card kpi"><div className="stat-label">{label}</div><div className="kpi-value">{value}</div></div>
}

export default function Analytics() {
  const [d, setD] = useState(null)
  const { label } = useLayout()
  useEffect(() => { api('/stats/overview').then(setD) }, [])
  if (!d) return <div className="muted">Đang tải thống kê…</div>

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Thống kê</h2>
          <p className="muted">Tổng hợp từ lịch sử đỗ xe 7 ngày gần nhất.</p>
        </div>
      </div>
      <div className="grid-kpi">
        <Kpi label="Lượt vào hôm nay" value={d.entries_today} />
        <Kpi label="Doanh thu hôm nay" value={money(d.revenue_today)} />
        <Kpi label="Thời gian đỗ trung bình" value={`${d.avg_duration_min} phút`} />
        <Kpi label="Giờ cao điểm (24h qua)" value={d.peak_hour ?? '—'} />
      </div>

      <div className="grid-charts">
        <section className="card">
          <div className="card-head"><h3>Lượt xe vào theo giờ (24 giờ qua)</h3></div>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={d.hourly} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="gA" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#14b8a6" stopOpacity={0.55} />
                  <stop offset="100%" stopColor="#14b8a6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" {...AXIS} interval={2} />
              <YAxis {...AXIS} allowDecimals={false} />
              <Tooltip {...TIP} formatter={(v) => [v, 'Lượt vào']} />
              <Area type="monotone" dataKey="entries" stroke="#14b8a6" strokeWidth={2.5} fill="url(#gA)" />
            </AreaChart>
          </ResponsiveContainer>
        </section>

        <section className="card">
          <div className="card-head"><h3>Doanh thu theo ngày</h3></div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={d.daily} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" {...AXIS} />
              <YAxis {...AXIS} tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : v)} />
              <Tooltip {...TIP} formatter={(v) => [money(v), 'Doanh thu']} />
              <Bar dataKey="revenue" fill="#6366f1" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </section>

        <section className="card wide">
          <div className="card-head"><h3>Mức sử dụng từng ô (7 ngày)</h3></div>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={d.slot_usage.map((s) => ({ ...s, label: `Ô ${label(s.slot)}` }))} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="label" {...AXIS} />
              <YAxis {...AXIS} allowDecimals={false} />
              <Tooltip {...TIP} formatter={(v) => [v, 'Lượt đỗ']} />
              <Bar dataKey="count" fill="#f59e0b" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </section>
      </div>
    </>
  )
}
