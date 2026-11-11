import { useEffect, useRef, useState } from 'react'
import { Camera, PenLine, Square, Wand2 } from 'lucide-react'
import { tokenUrl } from '../api'

const centroid = (roi) => [roi.reduce((a, p) => a + p[0], 0) / roi.length, roi.reduce((a, p) => a + p[1], 0) / roi.length]
const pts = (arr) => arr.map((p) => p.join(',')).join(' ')

/**
 * Vẽ vùng (ROI) của từng ô trên ảnh camera thật — đây là vùng bộ nhận diện cắt ra để phân loại trống/có xe.
 * Tọa độ theo khung "frame" của layout; server tự co giãn theo độ phân giải camera thực tế.
 */
export default function RoiEditor({ draft, edit }) {
  const svgRef = useRef(null)
  const drag = useRef(null)
  const [selId, setSelId] = useState(draft.slots[0]?.id)
  const [drawing, setDrawing] = useState(null) // các điểm đã bấm khi đang vẽ lại, null = không vẽ
  const [shot, setShot] = useState(Date.now())
  const [img, setImg] = useState({ ok: null, w: 0, h: 0 })
  const { width: fw, height: fh } = draft.frame
  const k = fw / 640 // giữ kích thước chữ / điểm nắm ổn định với mọi độ phân giải khung
  const sel = draft.slots.find((s) => s.id === selId)
  const todo = draft.slots.filter((s) => s.roi_todo)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && setDrawing(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const toFrame = (e) => {
    const svg = svgRef.current
    const p = svg.createSVGPoint()
    p.x = e.clientX
    p.y = e.clientY
    const q = p.matrixTransform(svg.getScreenCTM().inverse())
    return [Math.round(Math.min(fw, Math.max(0, q.x))), Math.round(Math.min(fh, Math.max(0, q.y)))]
  }

  const setRoi = (id, roi) => edit((d) => {
    const s = d.slots.find((x) => x.id === id)
    s.roi = roi
    delete s.roi_todo
  })

  const startDraw = (id) => {
    setSelId(id)
    setDrawing([])
  }

  const onDown = (e) => {
    if (drawing) {
      const next = [...drawing, toFrame(e)]
      if (next.length < 4) return setDrawing(next)
      setRoi(selId, next)
      // giống tools/roi_calibrate.py: vẽ xong tự chuyển sang ô kế tiếp còn chưa vẽ
      const rest = draft.slots.filter((s) => s.roi_todo && s.id !== selId)
      if (rest.length) startDraw(rest[0].id)
      else setDrawing(null)
      return
    }
    drag.current = null
  }

  const startDrag = (e, d) => {
    e.stopPropagation()
    svgRef.current.setPointerCapture(e.pointerId)
    drag.current = { ...d, start: toFrame(e) }
  }

  const onMove = (e) => {
    const g = drag.current
    if (!g) return
    const [x, y] = toFrame(e)
    if (g.kind === 'pt') {
      setRoi(g.id, g.orig.map((p, i) => (i === g.i ? [x, y] : p)))
    } else {
      const dx = x - g.start[0]
      const dy = y - g.start[1]
      setRoi(g.id, g.orig.map(([px, py]) => [px + dx, py + dy]))
    }
  }

  // ảnh camera khác tỉ lệ khung đang dùng -> đề nghị đổi khung (ROI được co giãn theo)
  const mismatch = img.ok && Math.abs(img.w / img.h - fw / fh) > 0.02
  const fitFrame = () => edit((d) => {
    const sx = img.w / d.frame.width
    const sy = img.h / d.frame.height
    d.slots.forEach((s) => { s.roi = s.roi.map(([x, y]) => [Math.round(x * sx), Math.round(y * sy)]) })
    d.frame = { width: img.w, height: img.h }
  })

  return (
    <div className="editor">
      <div className="editor-main">
        <div className="toolbar">
          <button className="btn" onClick={() => setShot(Date.now())}><Camera size={15} /> Chụp ảnh mới</button>
          {drawing
            ? <button className="btn tool active" onClick={() => setDrawing(null)}><Square size={15} /> Dừng vẽ (Esc)</button>
            : <button className="btn" disabled={!sel} onClick={() => startDraw(selId)}><PenLine size={15} /> Vẽ lại ô {sel?.label}</button>}
          {!drawing && todo.length > 0 && (
            <button className="btn btn-primary" onClick={() => startDraw(todo[0].id)}><Wand2 size={15} /> Vẽ {todo.length} ô chưa có vùng</button>
          )}
        </div>
        <div className="muted small">
          {drawing
            ? `Ô ${sel?.label}: bấm 4 góc ô trên ảnh (${drawing.length}/4), theo chiều bất kỳ.`
            : 'Chọn ô rồi kéo các góc để chỉnh, kéo phần giữa để dời cả vùng. Vẽ ROI ôm sát vạch kẻ ô, không lấn sang ô bên cạnh.'}
        </div>
        {mismatch && (
          <div className="notice">
            Ảnh camera {img.w}×{img.h} khác tỉ lệ khung đang dùng {fw}×{fh} — vùng vẽ sẽ bị lệch.
            <button className="btn" onClick={fitFrame}>Đổi khung theo camera</button>
          </div>
        )}

        <div className="roi-stage" style={{ aspectRatio: `${fw} / ${fh}` }}>
          <img src={tokenUrl('/camera/raw.jpg', { t: shot })} alt="Ảnh camera bãi đỗ" draggable={false}
            onLoad={(e) => setImg({ ok: true, w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            onError={() => setImg({ ok: false, w: 0, h: 0 })} />
          {img.ok === false && <div className="roi-noimg">Chưa có ảnh camera — vẫn chỉnh được vùng, nhưng nên kết nối camera để vẽ chính xác.</div>}
          <svg ref={svgRef} viewBox={`0 0 ${fw} ${fh}`} className={drawing ? 'drawing' : ''}
            onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => { drag.current = null }}>
            {draft.slots.map((s) => {
              const on = s.id === selId
              const [cx, cy] = centroid(s.roi)
              if (on && drawing) return null
              return (
                <g key={s.id} className={`roi ${on ? 'sel' : ''} ${s.roi_todo ? 'todo' : ''}`}>
                  <polygon points={pts(s.roi)} strokeWidth={2 * k}
                    onPointerDown={(e) => {
                      if (drawing) return // đang vẽ: để lần bấm rơi xuống svg thành một góc mới
                      setSelId(s.id)
                      startDrag(e, { kind: 'poly', id: s.id, orig: s.roi })
                    }} />
                  <text x={cx} y={cy + 6 * k} textAnchor="middle" fontSize={18 * k}>{s.label}</text>
                  {on && s.roi.map(([x, y], i) => (
                    <circle key={i} cx={x} cy={y} r={7 * k} className="roi-handle"
                      onPointerDown={(e) => startDrag(e, { kind: 'pt', id: s.id, i, orig: s.roi })} />
                  ))}
                </g>
              )
            })}
            {drawing && (
              <g className="roi drawing-poly">
                <polyline points={pts(drawing)} strokeWidth={2 * k} />
                {drawing.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={6 * k} />)}
              </g>
            )}
          </svg>
        </div>
      </div>

      <aside className="ed-panel card">
        <h3>Các ô ({draft.slots.length})</h3>
        <div className="muted small">
          {todo.length ? `⚠ ${todo.length} ô chưa vẽ vùng camera.` : '✓ Tất cả ô đã có vùng camera.'}
        </div>
        <div className="roi-list">
          {draft.slots.map((s) => (
            <button key={s.id} className={`roi-chip ${s.id === selId ? 'sel' : ''} ${s.roi_todo ? 'todo' : ''}`}
              onClick={() => { setSelId(s.id); if (drawing) setDrawing([]) }}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="muted small">
          Khung tọa độ: {fw}×{fh}. Bộ nhận diện cắt khung bao của vùng rồi phân loại trống/có xe, nên vùng chỉ cần ôm đúng ô —
          số ô và hình dạng bãi không ảnh hưởng tới mô hình.
        </div>
      </aside>
    </div>
  )
}
