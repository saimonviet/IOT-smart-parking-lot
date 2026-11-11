import { useRef, useState } from 'react'
import { CircleDot, Copy, LogIn, LogOut, MousePointer2, Plus, Route, Trash2 } from 'lucide-react'
import { center, gateArrows, mapFrame, nearestNode, placeholderRoi, slotRect, snap } from '../layoutTools'

const TOOLS = [
  { id: 'select', label: 'Chọn / kéo', icon: MousePointer2 },
  { id: 'slot', label: 'Thêm ô', icon: Plus },
  { id: 'node', label: 'Thêm nút', icon: CircleDot },
  { id: 'edge', label: 'Nối / bỏ làn', icon: Route },
]

const HINT = {
  select: 'Kéo ô hoặc nút để di chuyển, kéo góc vuông nhỏ ở ô đang chọn để đổi kích thước. Bấm vào ô/nút để sửa thông số.',
  slot: 'Bấm vào sơ đồ để đặt ô mới — ô tự gắn vào nút đường đi gần nhất.',
  node: 'Bấm để đặt nút đường đi (điểm rẽ, hoặc điểm trên làn ngay trước ô).',
  edge: 'Bấm lần lượt hai nút để nối làn đường; bấm lại một cặp đã nối để xóa làn.',
}

const PAD = 24 // chừa lề quanh sơ đồ để thấy nút cổng nằm sát mép

function Num({ label, value, onChange, step = 5 }) {
  return (
    <label>{label}
      <input type="number" step={step} value={Math.round(value * 10) / 10}
        onChange={(e) => e.target.value !== '' && onChange(Number(e.target.value))} />
    </label>
  )
}

/** Ô nhập tên nút: chỉ đổi tên khi rời ô / Enter để không làm hỏng liên kết khi đang gõ dở. */
function RenameInput({ value, onCommit }) {
  const [v, setV] = useState(value)
  return (
    <label>Tên nút
      <input value={v} onChange={(e) => setV(e.target.value)} onBlur={() => onCommit(v.trim())}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
    </label>
  )
}

/** Trình chỉnh sơ đồ nhìn từ trên xuống: ô đỗ, nút đường đi, làn đường, cổng vào/ra. */
export default function MapEditor({ draft, edit }) {
  const svgRef = useRef(null)
  const drag = useRef(null)
  const [tool, setTool] = useState('select')
  const [sel, setSel] = useState(null) // { kind: 'slot' | 'node', id }
  const [edgeFrom, setEdgeFrom] = useState(null)
  const [msg, setMsg] = useState('')
  const { width, height } = mapFrame(draft)
  const { nodes } = draft

  // mọi thay đổi sơ đồ đều vẽ lại mũi tên cổng theo vị trí nút vào/ra
  const change = (fn) => edit((d) => { fn(d); Object.assign(d.decor, gateArrows(d)) })
  const findSlot = (d, id) => d.slots.find((s) => s.id === id)

  const toSvg = (e) => {
    const svg = svgRef.current
    const p = svg.createSVGPoint()
    p.x = e.clientX
    p.y = e.clientY
    const q = p.matrixTransform(svg.getScreenCTM().inverse())
    return [q.x, q.y]
  }

  const startDrag = (e, d) => {
    e.stopPropagation()
    svgRef.current.setPointerCapture(e.pointerId)
    drag.current = { ...d, start: toSvg(e) }
  }

  const pickTool = (id) => {
    setTool(id)
    setEdgeFrom(null)
    setMsg('')
  }

  const onSlotDown = (e, s) => {
    if (tool !== 'select') return
    setSel({ kind: 'slot', id: s.id })
    startDrag(e, { kind: 'slot', id: s.id, orig: slotRect(s) })
  }

  const onNodeDown = (e, name) => {
    if (tool === 'edge') {
      e.stopPropagation()
      if (!edgeFrom) return setEdgeFrom(name)
      if (edgeFrom !== name) {
        change((d) => {
          const i = d.edges.findIndex(([a, b]) => (a === edgeFrom && b === name) || (a === name && b === edgeFrom))
          if (i >= 0) d.edges.splice(i, 1)
          else d.edges.push([edgeFrom, name])
        })
      }
      return setEdgeFrom(null)
    }
    if (tool !== 'select') return
    setSel({ kind: 'node', id: name })
    startDrag(e, { kind: 'node', id: name, orig: [...nodes[name]] })
  }

  const onBgDown = (e) => {
    const [x, y] = toSvg(e).map(snap)
    if (tool === 'slot') {
      const id = Math.max(0, ...draft.slots.map((s) => s.id)) + 1
      const map = { x: x - 35, y: y - 55, w: 70, h: 110, rot: 0 }
      change((d) => {
        d.slots.push({ id, label: `S${id}`, node: nearestNode(d, [x, y]), map, roi: placeholderRoi(d, map), roi_todo: true })
      })
      setSel({ kind: 'slot', id })
    } else if (tool === 'node') {
      let k = 1
      while (nodes[`N${k}`]) k++
      change((d) => { d.nodes[`N${k}`] = [x, y] })
      setSel({ kind: 'node', id: `N${k}` })
    } else {
      setSel(null)
      setEdgeFrom(null)
    }
  }

  const onMove = (e) => {
    const g = drag.current
    if (!g) return
    const [x, y] = toSvg(e)
    const dx = x - g.start[0]
    const dy = y - g.start[1]
    if (g.kind === 'node') {
      change((d) => { d.nodes[g.id] = [snap(g.orig[0] + dx), snap(g.orig[1] + dy)] })
      return
    }
    change((d) => {
      const s = findSlot(d, g.id)
      if (g.kind === 'slot') {
        s.map = { ...g.orig, x: snap(g.orig.x + dx), y: snap(g.orig.y + dy) }
      } else {
        // kéo góc của ô đang xoay: đổi độ dời sang trục của ô
        const a = (g.orig.rot * Math.PI) / 180
        const lx = dx * Math.cos(a) + dy * Math.sin(a)
        const ly = -dx * Math.sin(a) + dy * Math.cos(a)
        s.map = { ...g.orig, w: Math.max(20, snap(g.orig.w + lx)), h: Math.max(20, snap(g.orig.h + ly)) }
      }
    })
  }

  const slot = sel?.kind === 'slot' ? draft.slots.find((s) => s.id === sel.id) : null
  const node = sel?.kind === 'node' && nodes[sel.id] ? sel.id : null

  const setSlot = (fn) => change((d) => fn(findSlot(d, slot.id)))

  const duplicate = () => {
    const id = Math.max(...draft.slots.map((s) => s.id)) + 1
    const labels = new Set(draft.slots.map((s) => s.label))
    let label = slot.label.replace(/(\d+)$/, (n) => String(Number(n) + 1))
    if (label === slot.label || labels.has(label)) label = `S${id}`
    const map = { ...slotRect(slot), x: slot.map.x + slot.map.w }
    change((d) => {
      d.slots.push({ id, label, node: nearestNode(d, center(map)), map, roi: placeholderRoi(d, map), roi_todo: true })
    })
    setSel({ kind: 'slot', id })
  }

  const renameNode = (to) => {
    if (to === node) return
    if (!/^[A-Za-z0-9_]{1,12}$/.test(to)) return setMsg('Tên nút chỉ gồm chữ, số, "_" (tối đa 12 ký tự)')
    if (nodes[to]) return setMsg(`Đã có nút tên ${to}`)
    const from = node
    change((d) => {
      d.nodes[to] = d.nodes[from]
      delete d.nodes[from]
      d.edges = d.edges.map((e) => e.map((n) => (n === from ? to : n)))
      d.slots.forEach((s) => { if (s.node === from) s.node = to })
      if (d.entrance === from) d.entrance = to
      if (d.exit === from) d.exit = to
    })
    setSel({ kind: 'node', id: to })
    setMsg('')
  }

  const deleteNode = () => {
    if (node === draft.entrance || node === draft.exit) return setMsg('Không xóa được nút cổng vào/ra — hãy chọn nút khác làm cổng trước')
    change((d) => {
      delete d.nodes[node]
      d.edges = d.edges.filter((e) => !e.includes(node))
      d.slots.forEach((s) => { if (s.node === node) s.node = nearestNode(d, center(s.map)) })
    })
    setSel(null)
  }

  const linked = slot ? nodes[slot.node] : null

  return (
    <div className="editor">
      <div className="editor-main">
        <div className="toolbar">
          {TOOLS.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`btn tool ${tool === id ? 'active' : ''}`} onClick={() => pickTool(id)}>
              <Icon size={15} /> {label}
            </button>
          ))}
        </div>
        <div className="muted small">{edgeFrom ? `Đã chọn nút ${edgeFrom} — bấm nút thứ hai để nối/bỏ làn.` : HINT[tool]}</div>

        <svg ref={svgRef} viewBox={`${-PAD} ${-PAD} ${width + PAD * 2} ${height + PAD * 2}`} className={`map-canvas tool-${tool}`}
          onPointerDown={onBgDown} onPointerMove={onMove} onPointerUp={() => { drag.current = null }}>
          <defs>
            <pattern id="ed-grid" width="20" height="20" patternUnits="userSpaceOnUse">
              <path d="M20 0H0V20" fill="none" stroke="#ffffff0d" strokeWidth="1" />
            </pattern>
          </defs>
          <rect x="0" y="0" width={width} height={height} rx="14" className="asphalt" />
          <rect x="0" y="0" width={width} height={height} rx="14" fill="url(#ed-grid)" />

          {draft.edges.map(([a, b]) => nodes[a] && nodes[b] && (
            <line key={`l${a}-${b}`} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} className="lane-road" />
          ))}
          {draft.edges.map(([a, b]) => nodes[a] && nodes[b] && (
            <line key={`d${a}-${b}`} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} className="lane-mark" />
          ))}
          {linked && <line x1={linked[0]} y1={linked[1]} x2={center(slot.map)[0]} y2={center(slot.map)[1]} className="ed-link" />}

          {draft.slots.map((s) => {
            const r = slotRect(s)
            const [cx, cy] = center(r)
            const on = slot?.id === s.id
            return (
              <g key={s.id} transform={r.rot ? `rotate(${r.rot} ${cx} ${cy})` : undefined}
                className={`ed-slot ${on ? 'sel' : ''}`} onPointerDown={(e) => onSlotDown(e, s)}>
                <rect x={r.x + 2} y={r.y + 2} width={r.w - 4} height={r.h - 4} rx="8" />
                <text x={cx} y={cy + 6} textAnchor="middle">{s.label}</text>
                {on && tool === 'select' && (
                  <rect x={r.x + r.w - 12} y={r.y + r.h - 12} width="14" height="14" rx="3" className="ed-handle"
                    onPointerDown={(e) => { setSel({ kind: 'slot', id: s.id }); startDrag(e, { kind: 'resize', id: s.id, orig: r }) }} />
                )}
              </g>
            )
          })}

          {Object.entries(nodes).map(([name, [x, y]]) => {
            const kind = name === draft.entrance ? 'in' : name === draft.exit ? 'out' : ''
            return (
              <g key={name} className={`ed-node ${kind} ${node === name || edgeFrom === name ? 'sel' : ''}`}
                onPointerDown={(e) => onNodeDown(e, name)}>
                <circle cx={x} cy={y} r={kind ? 11 : 8} />
                <text x={x} y={y - 15} textAnchor="middle">{kind === 'in' ? `${name} · VÀO` : kind === 'out' ? `${name} · RA` : name}</text>
              </g>
            )
          })}
        </svg>
      </div>

      <aside className="ed-panel card">
        {msg && <div className="notice">{msg}</div>}
        {slot && (
          <>
            <h3>Ô {slot.label}</h3>
            <label>Tên ô (hiện trên OLED)
              <input value={slot.label} maxLength={6} onChange={(e) => setSlot((s) => { s.label = e.target.value.toUpperCase() })} />
            </label>
            <label>Nút đường đi dẫn tới ô
              <div className="inline">
                <select value={slot.node ?? ''} onChange={(e) => setSlot((s) => { s.node = e.target.value })}>
                  {Object.keys(nodes).map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
                <button className="btn" onClick={() => setSlot((s) => { s.node = nearestNode(draft, center(s.map)) })}>Gần nhất</button>
              </div>
            </label>
            <div className="ed-grid2">
              <Num label="X" value={slot.map.x} onChange={(v) => setSlot((s) => { s.map.x = v })} />
              <Num label="Y" value={slot.map.y} onChange={(v) => setSlot((s) => { s.map.y = v })} />
              <Num label="Rộng" value={slot.map.w} onChange={(v) => setSlot((s) => { s.map.w = Math.max(10, v) })} />
              <Num label="Dài" value={slot.map.h} onChange={(v) => setSlot((s) => { s.map.h = Math.max(10, v) })} />
              <Num label="Xoay (độ)" value={slot.map.rot || 0} onChange={(v) => setSlot((s) => { s.map.rot = v })} />
            </div>
            <div className="muted small">
              {slot.roi_todo ? '⚠ Chưa vẽ vùng camera cho ô này.' : 'Đã có vùng camera.'} Di chuyển ô trên sơ đồ không đổi vùng camera.
            </div>
            <div className="btn-row">
              <button className="btn" onClick={duplicate}><Copy size={15} /> Nhân bản</button>
              <button className="btn btn-danger" onClick={() => { change((d) => { d.slots = d.slots.filter((s) => s.id !== slot.id) }); setSel(null) }}>
                <Trash2 size={15} /> Xóa ô
              </button>
            </div>
          </>
        )}

        {node && (
          <>
            <h3>Nút {node}</h3>
            <RenameInput key={node} value={node} onCommit={renameNode} />
            <div className="ed-grid2">
              <Num label="X" value={nodes[node][0]} onChange={(v) => change((d) => { d.nodes[node][0] = v })} />
              <Num label="Y" value={nodes[node][1]} onChange={(v) => change((d) => { d.nodes[node][1] = v })} />
            </div>
            <div className="muted small">
              {draft.edges.filter((e) => e.includes(node)).length} làn nối · {draft.slots.filter((s) => s.node === node).length} ô gắn vào nút này
            </div>
            <div className="btn-row">
              <button className="btn" disabled={draft.entrance === node} onClick={() => change((d) => { d.entrance = node })}><LogIn size={15} /> Làm cổng vào</button>
              <button className="btn" disabled={draft.exit === node} onClick={() => change((d) => { d.exit = node })}><LogOut size={15} /> Làm cổng ra</button>
              <button className="btn btn-danger" onClick={deleteNode}><Trash2 size={15} /> Xóa nút</button>
            </div>
          </>
        )}

        {!slot && !node && (
          <>
            <h3>Khung sơ đồ</h3>
            <div className="ed-grid2">
              <Num label="Rộng" step={10} value={width} onChange={(v) => edit((d) => { d.map.width = Math.max(100, v) })} />
              <Num label="Cao" step={10} value={height} onChange={(v) => edit((d) => { d.map.height = Math.max(100, v) })} />
            </div>
            <div className="muted small">
              {draft.slots.length} ô · {Object.keys(nodes).length} nút · {draft.edges.length} làn.
              Xe đi từ nút <b>VÀO</b> theo làn tới nút gắn với ô; hướng rẽ trên OLED tính từ hình dạng làn.
            </div>
            <div className="muted small">Mẹo: đặt mỗi ô một nút trên làn, ngay trước miệng ô, để chỉ dẫn rẽ chính xác.</div>
          </>
        )}
      </aside>
    </div>
  )
}
