/**
 * Hàm dùng chung cho sơ đồ bãi: khung ô trên sơ đồ, ROI tạm, mũi tên cổng và các mẫu bãi có sẵn.
 * Sơ đồ ("map") và ảnh camera ("frame") là hai hệ tọa độ riêng — xem pc_server/app/layout.py.
 */

export const SNAP = 5
export const snap = (v) => Math.round(v / SNAP) * SNAP

export function roiBox(roi) {
  const xs = roi.map((p) => p[0])
  const ys = roi.map((p) => p[1])
  return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) }
}

/** Khung ô trên sơ đồ {x,y,w,h,rot}; layout cũ chưa có "map" thì lấy khung bao ROI. */
export const slotRect = (def) => ({ rot: 0, ...(def.map ?? roiBox(def.roi)) })
export const mapFrame = (l) => l.map ?? l.frame
export const center = (r) => [r.x + r.w / 2, r.y + r.h / 2]

/** 4 góc của khung (đã xoay quanh tâm). */
export function rectCorners(r) {
  const [cx, cy] = center(r)
  const a = ((r.rot || 0) * Math.PI) / 180
  const c = Math.cos(a)
  const s = Math.sin(a)
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([kx, ky]) => {
    const dx = (kx * r.w) / 2
    const dy = (ky * r.h) / 2
    return [cx + dx * c - dy * s, cy + dx * s + dy * c]
  })
}

/** ROI tạm cho ô mới: chiếu khung trên sơ đồ sang ảnh camera theo tỉ lệ (cần vẽ lại trên ảnh thật). */
export function placeholderRoi(layout, rect) {
  const m = mapFrame(layout)
  const sx = layout.frame.width / m.width
  const sy = layout.frame.height / m.height
  return rectCorners(rect).map(([x, y]) => [Math.round(x * sx), Math.round(y * sy)])
}

/** Bản nháp để chỉnh: sao chép sâu, tách "map" khỏi "frame" và gắn khung sơ đồ cho mọi ô. */
export function normalize(layout) {
  const l = structuredClone(layout)
  l.map = { ...mapFrame(l) }
  l.edges = l.edges ?? []
  l.decor = l.decor ?? {}
  l.slots = l.slots.map((s) => ({ ...s, map: slotRect(s) }))
  return l
}

export function nearestNode(layout, [x, y]) {
  let best = null
  for (const [name, [nx, ny]] of Object.entries(layout.nodes)) {
    const d = Math.hypot(nx - x, ny - y)
    if (!best || d < best.d) best = { name, d }
  }
  return best?.name ?? null
}

const neighbor = (layout, n) => layout.edges.find((e) => e.includes(n))?.find((x) => x !== n)

/** Mũi tên VÀO/RA vẽ theo hướng làn nối với nút cổng. */
export function gateArrows(layout) {
  const out = {}
  const unit = (a, b) => {
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
    return [(b[0] - a[0]) / d, (b[1] - a[1]) / d]
  }
  const e = layout.nodes[layout.entrance]
  const en = layout.nodes[neighbor(layout, layout.entrance)]
  if (e && en) {
    const [ux, uy] = unit(e, en)
    out.entrance_arrow = [[e[0] + ux * 6, e[1] + uy * 6], [e[0] + ux * 70, e[1] + uy * 70]].map((p) => p.map(Math.round))
  }
  const x = layout.nodes[layout.exit]
  const xn = layout.nodes[neighbor(layout, layout.exit)]
  if (x && xn) {
    const [ux, uy] = unit(xn, x)
    out.exit_arrow = [[x[0] - ux * 60, x[1] - uy * 60], [x[0] - ux * 6, x[1] - uy * 6]].map((p) => p.map(Math.round))
  }
  return out
}

/** Chuỗi nút nối tiếp nhau -> danh sách cạnh. */
const chain = (names) => names.slice(1).map((n, i) => [names[i], n])
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

// kích thước chuẩn trên sơ đồ (đơn vị = điểm ảnh sơ đồ)
const SW = 70   // bề ngang ô
const SL = 110  // chiều dài ô
const LANE = 90 // bề rộng làn
const GATE = 50 // khoảng trống ở đầu làn cho cổng

function singleRow({ n }) {
  const laneY = SL + LANE / 2
  const nodes = { E: [0, laneY], X: [GATE * 2 + n * SW, laneY] }
  const slots = []
  for (let i = 0; i < n; i++) {
    const x = GATE + i * SW
    nodes[`L${i + 1}`] = [x + SW / 2, laneY]
    slots.push({ label: `A${i + 1}`, node: `L${i + 1}`, map: { x, y: 0, w: SW, h: SL, rot: 0 } })
  }
  return {
    map: { width: GATE * 2 + n * SW, height: SL + LANE + 10 },
    nodes, entrance: 'E', exit: 'X',
    edges: chain(['E', ...slots.map((s) => s.node), 'X']),
    slots,
  }
}

function doubleRow({ n }) {
  const laneY = SL + LANE / 2
  const W = GATE * 2 + n * SW
  const nodes = { E: [0, laneY], X: [W, laneY] }
  const top = []
  const bottom = []
  for (let i = 0; i < n; i++) {
    const x = GATE + i * SW
    nodes[`L${i + 1}`] = [x + SW / 2, laneY]
    top.push({ label: `A${i + 1}`, node: `L${i + 1}`, map: { x, y: 0, w: SW, h: SL, rot: 0 } })
    bottom.push({ label: `B${i + 1}`, node: `L${i + 1}`, map: { x, y: SL + LANE, w: SW, h: SL, rot: 0 } })
  }
  return {
    map: { width: W, height: SL * 2 + LANE },
    nodes, entrance: 'E', exit: 'X',
    edges: chain(['E', ...top.map((s) => s.node), 'X']),
    slots: [...top, ...bottom],
  }
}

/** Nhiều làn dọc rẽ ra từ làn ngang phía trên, mỗi làn có ô hai bên (giống sơ đồ mặc định). */
function aisles({ k, m }) {
  const B = SL + LANE + SL
  const rx = k * B + LANE / 2
  const W = k * B + LANE + 30
  const H = LANE + m * SW + 10
  const nodes = { E: [W, LANE / 2], TR: [rx, LANE / 2], RB: [rx, H - SW / 2], X: [W, H - SW / 2] }
  const edges = [['E', 'TR'], ['TR', 'RB'], ['RB', 'X']]
  const slots = []
  for (let j = 0; j < k; j++) {
    const ax = j * B + SL + LANE / 2
    nodes[`T${j}`] = [ax, LANE / 2]
    edges.push([j === k - 1 ? 'TR' : `T${j + 1}`, `T${j}`])
    const col = []
    for (let i = 0; i < m; i++) {
      const name = `a${j}n${i}`
      nodes[name] = [ax, LANE + i * SW + SW / 2]
      col.push(name)
    }
    edges.push(...chain([`T${j}`, ...col]))
    for (const [side, x] of [[0, j * B], [1, ax + LANE / 2]]) {
      const letter = LETTERS[(2 * j + side) % 26]
      for (let i = 0; i < m; i++) {
        slots.push({ label: `${letter}${i + 1}`, node: col[i], map: { x, y: LANE + i * SW, w: SL, h: SW, rot: 0 } })
      }
    }
  }
  return { map: { width: W, height: H }, nodes, entrance: 'E', exit: 'X', edges, slots }
}

/** Một dãy ô đỗ xéo 30°, dễ lùi/tiến vào ô theo chiều xe chạy. */
function angled({ n }) {
  const STEP = 82
  const cy = SL / 2 + 12
  const laneY = SL + 30 + LANE / 2
  const W = GATE * 2 + n * STEP + 40
  const nodes = { E: [0, laneY], X: [W, laneY] }
  const slots = []
  for (let i = 0; i < n; i++) {
    const cx = GATE + 40 + i * STEP
    nodes[`L${i + 1}`] = [cx, laneY]
    slots.push({ label: `A${i + 1}`, node: `L${i + 1}`, map: { x: cx - SW / 2, y: cy - SL / 2, w: SW, h: SL, rot: 30 } })
  }
  return {
    map: { width: W, height: laneY + LANE / 2 + 10 },
    nodes, entrance: 'E', exit: 'X',
    edges: chain(['E', ...slots.map((s) => s.node), 'X']),
    slots,
  }
}

export const TEMPLATES = [
  { id: 'single', name: 'Một dãy', desc: 'Một làn thẳng, ô xếp một bên. Phù hợp lối đi hẹp, sát tường.',
    params: [{ key: 'n', label: 'Số ô', min: 1, max: 20, def: 8 }], build: singleRow },
  { id: 'double', name: 'Hai dãy đối diện', desc: 'Một làn ở giữa, ô hai bên. Bố cục phổ biến nhất.',
    params: [{ key: 'n', label: 'Số ô mỗi dãy', min: 1, max: 15, def: 5 }], build: doubleRow },
  { id: 'aisles', name: 'Nhiều làn dọc', desc: 'Làn ngang phía trên rẽ vào các làn dọc, mỗi làn có ô hai bên (giống sơ đồ mặc định).',
    params: [{ key: 'k', label: 'Số làn dọc', min: 1, max: 4, def: 2 }, { key: 'm', label: 'Số ô mỗi bên', min: 1, max: 8, def: 3 }], build: aisles },
  { id: 'angled', name: 'Đỗ xéo', desc: 'Một dãy ô xéo 30°, xe vào ô không cần đánh lái nhiều.',
    params: [{ key: 'n', label: 'Số ô', min: 1, max: 16, def: 8 }], build: angled },
]

/**
 * Dựng sơ đồ hoàn chỉnh từ mẫu, giữ khung ảnh camera của bản đang chỉnh. Mọi ô nhận ROI tạm và
 * cờ "roi_todo" — vị trí ô trên ảnh camera phải vẽ lại ở bước "Vùng camera".
 */
export function buildTemplate(tpl, params, current) {
  const l = { frame: { ...current.frame }, ...tpl.build(params) }
  l.slots = l.slots.map((s, i) => ({ id: i + 1, ...s, roi: placeholderRoi(l, s.map), roi_todo: true }))
  l.decor = gateArrows(l)
  return l
}
