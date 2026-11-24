import { useEffect, useState } from 'react'
import { ArrowRight, Boxes, BrainCircuit, Camera, Check, ImageMinus, ParkingSquare, RefreshCw } from 'lucide-react'
import { api } from '../api'

// Ba cách nhận diện ô trống, thứ tự hiển thị = thứ tự khuyên dùng
const KIND = {
  classifier: {
    label: 'Phân loại từng ô (AI tự huấn luyện)', short: 'Phân loại ô', icon: BrainCircuit,
    desc: 'Cắt ảnh từng ô theo vùng đã vẽ ở "Sơ đồ bãi", mạng CNN cho xác suất có xe. Chính xác nhất khi đã huấn luyện với ảnh của camera này.',
  },
  yolo: {
    label: 'YOLO phát hiện xe (AI có sẵn)', short: 'YOLO', icon: Boxes,
    desc: 'Tìm khung bao xe trong cả khung hình, ô có xe khi khung xe phủ đủ vùng ô. Hợp xe thật; xe mô hình nhìn từ trên xuống thường không nhận ra.',
  },
  background: {
    label: 'So sánh ảnh nền (không dùng AI)', short: 'Ảnh nền', icon: ImageMinus,
    desc: 'So từng ô với ảnh chụp lúc bãi trống. Nhanh, hợp xe mô hình, nhưng nhạy khi ánh sáng thay đổi.',
  },
}
const KIND_NAME = { ...Object.fromEntries(Object.entries(KIND).map(([k, v]) => [k, v.short])), none: 'Tắt' }

const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
const sameSel = (a, b) => a && b && a.kind === b.kind && (a.model ?? null) === (b.model ?? null)
const selName = (data, sel) => {
  if (!sel || sel.kind === 'none') return 'Tắt nhận diện'
  const m = data.models.find((x) => sameSel(x, sel))
  return m ? `${KIND_NAME[m.kind]} · ${m.name}` : KIND_NAME[sel.kind]
}

function Info({ m }) {
  const i = m.info
  if (m.kind === 'classifier') {
    return (
      <div className="model-info">
        <span>{i.arch ?? '—'}{m.size_mb ? ` · ${m.size_mb} MB` : ''}</span>
        <span>Dữ liệu: {i.dataset ?? '—'}{i.finetuned_on_custom ? ' + ảnh bãi riêng' : ''}</span>
        <span>F1 tập test: <b>{pct(i.test_metrics?.f1)}</b> · camera lạ: <b>{pct(i.unseen_camera_metrics?.f1)}</b></span>
        <span>Ngưỡng mặc định {i.threshold != null ? i.threshold.toFixed(2) : '0.50'}{i.created ? ` · tạo ${i.created}` : ''}</span>
      </div>
    )
  }
  if (m.kind === 'yolo') {
    return <div className="model-info"><span>{m.size_mb ? `${m.size_mb} MB` : 'Tự tải về ở lần dùng đầu'} · tập COCO (lớp ô tô, xe tải…)</span></div>
  }
  return <div className="model-info"><span>Cần chụp ảnh nền khi bãi đang trống.</span></div>
}

function Row({ k, v }) {
  return <div className="row"><span className="muted">{k}</span><b>{v ?? '—'}</b></div>
}

/** AI 1: nhận diện ô trống từ camera bãi đỗ — trạng thái + chọn mô hình + chỉnh ngưỡng. */
export default function ModelPicker({ detector, cameraOnline, isAdmin, onReference }) {
  const [data, setData] = useState(null)
  const [pick, setPick] = useState(null)
  const [thr, setThr] = useState(null) // null = dùng ngưỡng mặc định của mô hình
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const load = () => api('/detector/models').then((d) => {
    setData(d)
    setPick((p) => p ?? d.current)
    setThr((t) => t ?? d.current.threshold)
  }).catch((e) => setMsg({ ok: false, text: e.message }))

  useEffect(() => { load() }, [])

  const choose = (m) => {
    setPick({ kind: m.kind, model: m.model })
    setThr(sameSel(m, data.current) ? data.current.threshold : null)
    setMsg(null)
  }

  const apply = async (sel) => {
    setBusy(true)
    setMsg(null)
    try {
      await api('/detector', { method: 'PUT', body: sel })
      setMsg({ ok: true, text: sel.kind === 'none' ? 'Đã tắt nhận diện ô trống.' : 'Đã đổi mô hình, có hiệu lực ngay.' })
      const d = await api('/detector/models')
      setData(d)
      setPick(d.current)
      setThr(d.current.threshold)
    } catch (e) {
      setMsg({ ok: false, text: e.message })
    } finally {
      setBusy(false)
    }
  }

  const chosen = data?.models.find((m) => sameSel(m, pick))
  const isCurrent = data && sameSel(pick, data.current)
  const defThr = chosen?.kind === 'classifier' ? (chosen.info.threshold ?? 0.5) : null
  const effThr = thr ?? defThr
  const changed = data && pick && (!isCurrent || (pick.kind === 'classifier' && (thr ?? null) !== (data.current.threshold ?? null)))
  const probs = isCurrent && pick.kind === 'classifier' ? Object.entries(detector.probs ?? {}) : []

  return (
    <section className="card ai-card">
      <div className="card-head">
        <div>
          <h3><ParkingSquare size={18} /> AI nhận diện ô trống</h3>
          <div className="ai-flow">
            <span><Camera size={13} /> Camera bãi đỗ (Pi Camera)</span><ArrowRight size={13} />
            <span>Mô hình</span><ArrowRight size={13} />
            <span>Trống / có xe cho từng ô</span>
          </div>
        </div>
        <span className={`pill ${detector.name !== 'none' && !detector.error ? 'pill-ok' : 'pill-bad'}`}>
          <i className="dot" />{detector.name === 'none' ? 'Đang tắt' : detector.error ? 'Lỗi' : 'Đang chạy'}
        </span>
      </div>

      <div className="ai-status">
        <Row k="Đang dùng" v={data ? selName(data, data.current) : KIND_NAME[detector.name]} />
        {detector.threshold != null && <Row k="Ngưỡng có xe" v={detector.threshold.toFixed(2)} />}
        <Row k="Tốc độ xử lý" v={`${detector.fps} khung/giây`} />
        {detector.name === 'yolo' && <Row k="Số xe đang thấy" v={detector.boxes} />}
        {detector.name === 'background' && <Row k="Ảnh nền bãi trống" v={detector.has_reference ? 'Đã có' : 'Chưa có, cần chụp'} />}
      </div>
      {detector.error && <div className="notice">{detector.error}</div>}

      <div className="ai-pick-head">
        <b>Chọn mô hình</b>
        <button className="btn btn-ghost btn-sm" onClick={() => load()} title="Quét lại thư mục pc_server/models/"><RefreshCw size={14} /> Quét lại</button>
      </div>
      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'}>{msg.text}</div>}
      {!data ? <div className="muted small">Đang tải danh sách mô hình…</div> : (
        <div className="model-groups">
          {Object.entries(KIND).map(([kind, k]) => {
            const items = data.models.filter((m) => m.kind === kind)
            if (!items.length) return null
            const Icon = k.icon
            return (
              <div key={kind} className="model-group">
                <div className="model-group-head"><Icon size={16} /><b>{k.label}</b></div>
                <p className="muted small">{k.desc}</p>
                <div className="model-list">
                  {items.map((m) => {
                    const cur = sameSel(m, data.current)
                    const sel = sameSel(m, pick)
                    return (
                      <button key={`${m.kind}:${m.model}`} disabled={!isAdmin}
                        className={`model ${sel ? 'sel' : ''}`} onClick={() => choose(m)}>
                        <div className="model-head">
                          <i className={`radio ${sel ? 'on' : ''}`} />
                          <div>
                            <b>{m.name}</b>
                            {m.model && <div className="muted small">{m.model}</div>}
                          </div>
                          {cur && <span className="pill pill-ok"><Check size={12} />Đang dùng</span>}
                        </div>
                        <Info m={m} />
                      </button>
                    )
                  })}
                </div>
                {kind === 'background' && (
                  <div><button className="btn btn-sm" disabled={!isAdmin || !cameraOnline} onClick={onReference}>Chụp ảnh nền (khi bãi đang trống)</button></div>
                )}
              </div>
            )
          })}
          <p className="muted small">
            Thêm mô hình phân loại: chép cặp file <code>tên.pt</code> + <code>tên.json</code> (xuất từ model_training) vào
            <code> pc_server/models/</code> rồi bấm Quét lại. File .pt không kèm .json được coi là mô hình YOLO.
          </p>
        </div>
      )}

      {chosen?.kind === 'classifier' && (
        <div className="thr">
          <label>Ngưỡng có xe: <b>{effThr.toFixed(2)}</b>{thr == null && ' (mặc định của mô hình)'}
            <input type="range" min="0.01" max="0.99" step="0.01" value={effThr} disabled={!isAdmin}
              onChange={(e) => setThr(Number(e.target.value))} />
          </label>
          <div className="muted small">
            Ô có xe khi xác suất ≥ ngưỡng. Hạ ngưỡng nếu hay bỏ sót xe, nâng nếu ô trống hay bị báo có xe.
            {thr != null && <button className="link" onClick={() => setThr(null)}>Về mặc định</button>}
          </div>
          {probs.length > 0 && (
            <div className="probs">
              {probs.map(([label, p]) => (
                <span key={label} className={`prob ${p >= effThr ? 'on' : ''}`} title="Xác suất có xe hiện tại">
                  {label} <b>{p.toFixed(2)}</b>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {isAdmin && data && (
        <div className="apply-bar">
          <span className="muted small">
            {changed ? <>Đổi sang <b>{selName(data, pick)}</b>{pick.kind === 'classifier' && effThr != null ? `, ngưỡng ${effThr.toFixed(2)}` : ''}</> : 'Chọn một mô hình khác để đổi.'}
          </span>
          <div className="btn-row">
            <button className="btn" disabled={busy || data.current.kind === 'none'} onClick={() => apply({ kind: 'none' })}>Tắt nhận diện</button>
            <button className="btn btn-primary" disabled={busy || !changed}
              onClick={() => apply({ kind: pick.kind, model: pick.model ?? null, threshold: pick.kind === 'classifier' ? thr : null })}>
              {busy ? 'Đang tải mô hình…' : 'Áp dụng'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
