import { useMemo } from 'react'
import { center, mapFrame, slotRect } from '../layoutTools'

const COLORS = { free: '#22c55e', occupied: '#ef4444', reserved: '#f59e0b' }

const pts = (arr) => arr.map((p) => p.join(',')).join(' ')

/** Nhãn VÀO/RA đặt cạnh giữa mũi tên, lệch sang bên trái theo chiều mũi tên. */
function gateLabel([[x1, y1], [x2, y2]]) {
  const d = Math.hypot(x2 - x1, y2 - y1) || 1
  return [(x1 + x2) / 2 + ((y2 - y1) / d) * 16, (y1 + y2) / 2 - ((x2 - x1) / d) * 16 + 5]
}

/** Sơ đồ bãi xe nhìn từ trên xuống (SVG), vẽ hoàn toàn từ layout.json: làn đường, ô, trụ cổng, mũi tên vào/ra. */
export default function LotMap({ layout, slots, onSelect }) {
  const byId = useMemo(() => Object.fromEntries(slots.map((s) => [s.id, s])), [slots])
  const { width, height } = mapFrame(layout)
  const { nodes, edges = [], decor = {} } = layout
  const routes = slots.filter((s) => s.status === 'reserved' && s.route)

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="lotmap" role="img" aria-label="Sơ đồ bãi đỗ xe">
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        {['in', 'out'].map((k) => (
          <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="5" refY="5" markerWidth="3.2" markerHeight="3.2" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill={k === 'in' ? '#38bdf8' : '#f87171'} />
          </marker>
        ))}
      </defs>
      <rect x="0" y="0" width={width} height={height} rx="14" className="asphalt" />

      {/* làn đường */}
      {edges.map(([a, b]) => (
        <line key={`l${a}${b}`} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} className="lane-road" />
      ))}
      {edges.map(([a, b]) => (
        <line key={`d${a}${b}`} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} className="lane-mark" />
      ))}

      {/* đường dẫn tới ô đang giữ chỗ */}
      {routes.map((s) => {
        const slot = layout.slots.find((x) => x.id === s.id)
        const p = s.route.map((n) => nodes[n])
        p.push(center(slotRect(slot)))
        return <polyline key={'r' + s.id} points={pts(p)} className="route" />
      })}

      {layout.slots.map((def) => {
        const s = byId[def.id]
        const st = s?.status ?? 'free'
        const b = slotRect(def)
        const [cx, cy] = center(b)
        const c = COLORS[st]
        const name = def.label ?? def.id
        const inset = Math.min(b.w, b.h) * 0.14
        return (
          <g key={def.id} className={`slot slot-${st}`} onClick={() => onSelect?.(def.id)}
            transform={b.rot ? `rotate(${b.rot} ${cx} ${cy})` : undefined}>
            <rect x={b.x + 2} y={b.y + 2} width={b.w - 4} height={b.h - 4} rx="8" className="slot-bg" style={{ stroke: c, fill: c + '1f' }} />
            {st === 'occupied' && (
              <g>
                <rect x={b.x + inset} y={b.y + inset} width={b.w - 2 * inset} height={b.h - 2 * inset} rx="14" fill="#ef4444" opacity=".92" />
                <rect x={b.x + inset * 1.8} y={b.y + b.h * 0.36} width={b.w - 3.6 * inset} height={b.h * 0.28} rx="6" fill="#0b1220" opacity=".55" />
              </g>
            )}
            {st === 'reserved' && (
              <text x={b.x + b.w / 2} y={b.y + b.h / 2 + 18} textAnchor="middle" className="slot-reserved-text">GIỮ CHỖ</text>
            )}
            <text x={b.x + b.w / 2} y={b.y + b.h / 2 + 6} textAnchor="middle" className="slot-num">{name}</text>
            {/* "đèn LED" của ô: sáng khi trống, nhấp nháy khi giữ chỗ */}
            <circle cx={b.x + b.w - 14} cy={b.y + 14} r="6" fill={st === 'occupied' ? '#334155' : c}
              filter={st === 'occupied' ? undefined : 'url(#glow)'} className={st === 'reserved' ? 'led-blink' : ''} />
          </g>
        )
      })}

      {decor.pillar && <polygon points={pts(decor.pillar)} className="pillar"><title>Trụ cổng: rào + cảm biến</title></polygon>}
      {decor.entrance_arrow && (
        <g>
          <line x1={decor.entrance_arrow[0][0]} y1={decor.entrance_arrow[0][1]} x2={decor.entrance_arrow[1][0]} y2={decor.entrance_arrow[1][1]}
            stroke="#38bdf8" strokeWidth="7" strokeLinecap="round" markerEnd="url(#arrow-in)" />
          <text x={gateLabel(decor.entrance_arrow)[0]} y={gateLabel(decor.entrance_arrow)[1]} textAnchor="middle" className="gate-text in">VÀO</text>
        </g>
      )}
      {decor.exit_arrow && (
        <g>
          <line x1={decor.exit_arrow[0][0]} y1={decor.exit_arrow[0][1]} x2={decor.exit_arrow[1][0]} y2={decor.exit_arrow[1][1]}
            stroke="#f87171" strokeWidth="7" strokeLinecap="round" markerEnd="url(#arrow-out)" />
          <text x={gateLabel(decor.exit_arrow)[0]} y={gateLabel(decor.exit_arrow)[1]} textAnchor="middle" className="gate-text out">RA</text>
        </g>
      )}
    </svg>
  )
}
