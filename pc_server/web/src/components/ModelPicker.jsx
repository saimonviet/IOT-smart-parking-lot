import { useEffect, useState } from 'react'
import { Boxes, BrainCircuit, Check, ImageMinus, RefreshCw } from 'lucide-react'
import { api } from '../api'

const KIND = {
  classifier: { label: 'Phân loại ô (tự huấn luyện)', icon: BrainCircuit },
  yolo: { label: 'YOLO phát hiện xe', icon: Boxes },
  background: { label: 'So sánh ảnh nền', icon: ImageMinus },
}

const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
const sameSel = (a, b) => a && b && a.kind === b.kind && (a.model ?? null) === (b.model ?? null)

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
    return (
      <div className="model-info">
        <span>{m.size_mb ? `${m.size_mb} MB` : 'Tự tải về ở lần dùng đầu'} · nhận diện xe theo khung, ô có xe khi khung phủ đủ ROI</span>
        <span>Hợp xe thật; xe mô hình / hộp đồ chơi thường không nhận ra</span>
      </div>
    )
  }
  return (
    <div className="model-info">
      <span>So từng ô với ảnh chụp lúc bãi trống. Nhanh, hợp xe mô hình; nhạy với thay đổi ánh sáng.</span>
      <span>Cần bấm "Chụp ảnh nền" khi bãi đang trống.</span>
    </div>
  )
}

/** Chọn bộ nhận diện / mô hình (quét pc_server/models/) và chỉnh ngưỡng của mô hình phân loại. */
export default function ModelPicker({ detector, isAdmin }) {
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

  if (!data) return <section className="card wide"><div className="muted">{msg?.text ?? 'Đang tải danh sách mô hình…'}</div></section>

  const chosen = data.models.find((m) => sameSel(m, pick))
  const isCurrent = sameSel(pick, data.current)
  const defThr = chosen?.kind === 'classifier' ? (chosen.info.threshold ?? 0.5) : null
  const effThr = thr ?? defThr
  const changed = !isCurrent || (pick.kind === 'classifier' && (thr ?? null) !== (data.current.threshold ?? null))
  const probs = isCurrent && pick.kind === 'classifier' ? Object.entries(detector.probs ?? {}) : []

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
      setMsg({ ok: true, text: sel.kind === 'none' ? 'Đã tắt nhận diện.' : 'Đã đổi bộ nhận diện.' })
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

  return (
    <section className="card wide">
      <div className="card-head">
        <h3><BrainCircuit size={18} /> Mô hình nhận diện</h3>
        <button className="btn" onClick={() => load()} title="Quét lại thư mục models/"><RefreshCw size={15} /> Quét lại</button>
      </div>
      <p className="muted small">
        Thêm mô hình phân loại: chép cặp file <code>tên.pt</code> + <code>tên.json</code> (xuất từ model_training/) vào
        <code> pc_server/models/</code> rồi bấm Quét lại. File .pt không kèm .json được coi là mô hình YOLO.
      </p>
      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'}>{msg.text}</div>}

      <div className="model-list">
        {data.models.map((m) => {
          const Icon = KIND[m.kind].icon
          const cur = sameSel(m, data.current)
          return (
            <button key={`${m.kind}:${m.model}`} disabled={!isAdmin}
              className={`model ${sameSel(m, pick) ? 'sel' : ''}`} onClick={() => choose(m)}>
              <div className="model-head">
                <Icon size={18} />
                <div>
                  <b>{m.name}</b>
                  <div className="muted small">{KIND[m.kind].label}{m.model ? ` · ${m.model}` : ''}</div>
                </div>
                {cur && <span className="pill pill-ok"><Check size={12} />Đang dùng</span>}
              </div>
              <Info m={m} />
            </button>
          )
        })}
      </div>

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

      {isAdmin && (
        <div className="btn-row">
          <button className="btn btn-primary" disabled={busy || !changed}
            onClick={() => apply({ kind: pick.kind, model: pick.model ?? null, threshold: pick.kind === 'classifier' ? thr : null })}>
            {busy ? 'Đang tải mô hình…' : 'Áp dụng'}
          </button>
          <button className="btn" disabled={busy || data.current.kind === 'none'} onClick={() => apply({ kind: 'none' })}>
            Tắt nhận diện
          </button>
        </div>
      )}
    </section>
  )
}
