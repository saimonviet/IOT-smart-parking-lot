import { useEffect, useState } from 'react'
import { RefreshCw, ScanLine, Video } from 'lucide-react'
import { api, tokenUrl } from '../api'
import { fmtPlate } from '../utils'

const GATES = [['in', 'Cổng vào', '#38bdf8'], ['out', 'Cổng ra', '#f87171']]

/** Cấu hình ESP32-CAM đọc biển số: địa chỉ, khóa, vùng ảnh của từng làn (camera xoay bằng servo: cả khung hình; camera cố định: mỗi làn một nửa). */
export default function PlateCamCard({ status, isAdmin }) {
  const [cfg, setCfg] = useState(null)
  const [snap, setSnap] = useState(0)
  const [msg, setMsg] = useState(null)
  const [test, setTest] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { api('/plate-cam').then((d) => setCfg(d.config)).catch(() => {}) }, [])
  if (!cfg) return null

  const setRoi = (g, i) => (e) => {
    const roi = { ...cfg.roi, [g]: cfg.roi[g].map((v, j) => (j === i ? Number(e.target.value) : v)) }
    setCfg({ ...cfg, roi })
  }
  const run = async (fn, ok) => {
    setBusy(true); setMsg(null)
    try { const r = await fn(); if (ok) setMsg({ ok: true, text: ok(r) }) } catch (e) { setMsg({ ok: false, text: e.message }) } finally { setBusy(false) }
  }
  const save = () => run(() => api('/plate-cam', { method: 'PUT', body: cfg }), () => { setSnap(Date.now()); return 'Đã lưu cấu hình camera biển số' })
  const doTest = (g) => run(async () => { const r = await api('/plate-cam/test', { method: 'POST', body: { gate: g } }); setTest(r); return r })
  const reload = () => run(() => api('/plate-cam/reload-model', { method: 'POST' }), () => 'Đã nạp lại mô hình biển số')

  return (
    <section className="card wide-plate">
      <div className="card-head"><h3><ScanLine size={18} /> Camera biển số (ESP32-CAM)</h3>
        <span className={`pill ${status?.online ? 'pill-ok' : 'pill-bad'}`}><i className="dot" />{status?.enabled ? (status.online ? 'Có tín hiệu' : 'Chưa có ảnh') : 'Tắt'}</span></div>
      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'}>{msg.text}</div>}
      <div className="platecam">
        <div className="platecam-form">
          <label>Địa chỉ ESP32-CAM
            <input value={cfg.url} onChange={(e) => setCfg({ ...cfg, url: e.target.value })} placeholder="http://192.168.1.50" disabled={!isAdmin} />
          </label>
          <label>Khóa truy cập (CAM_KEY trong firmware)
            <input value={cfg.key} onChange={(e) => setCfg({ ...cfg, key: e.target.value })} placeholder="để trống nếu không đặt" disabled={!isAdmin} />
          </label>
          <label>Đèn flash khi chụp biển (0 = tắt, 255 = sáng nhất)
            <div className="flash-row">
              <input type="range" min="0" max="255" step="5" value={cfg.flash ?? 0}
                onChange={(e) => setCfg({ ...cfg, flash: Number(e.target.value) })} disabled={!isAdmin} />
              <b>{cfg.flash ?? 0}</b>
            </div>
          </label>
          {GATES.map(([g, name, color]) => (
            <div key={g} className="roi-row">
              <span style={{ color }}>Vùng {name.toLowerCase()}</span>
              {['x1', 'y1', 'x2', 'y2'].map((k, i) => (
                <label key={k} className="small">{k}
                  <input type="number" min="0" max="1" step="0.05" value={cfg.roi[g][i]} onChange={setRoi(g, i)} disabled={!isAdmin} />
                </label>
              ))}
            </div>
          ))}
          <p className="muted small">Vùng tính theo tỉ lệ khung hình (0–1). Đặt mỗi vùng bao trọn chỗ xe dừng ở cổng tương ứng.</p>
          <div className="btn-row">
            <button className="btn btn-primary" disabled={!isAdmin || busy} onClick={save}>Lưu</button>
            <button className="btn" disabled={busy} onClick={() => setSnap(Date.now())}><RefreshCw size={15} /> Chụp xem</button>
            {GATES.map(([g, name]) => (
              <button key={g} className="btn" disabled={!isAdmin || busy || !status?.enabled} onClick={() => doTest(g)}>Đọc thử {name.toLowerCase()}</button>
            ))}
            <button className="btn" disabled={!isAdmin || busy} onClick={reload}>Nạp lại mô hình</button>
          </div>
          <div className="row"><span className="muted">Mô hình</span><b>{status?.model_ready ? 'Sẵn sàng' : (status?.model_error || 'Chưa nạp')}</b></div>
          <div className="row"><span className="muted">Bắt buộc đọc được biển</span><b>{status?.required ? 'Có' : 'Không'}</b></div>
          {status?.error && <div className="notice">{status.error}</div>}
          {test && (
            <div className={test.plate ? 'notice notice-ok' : 'notice'}>
              {test.plate ? `Đọc được: ${fmtPlate(test.plate)} (${Math.round(test.conf * 100)}%)` : `Không đọc được — ${test.reason}`}
              {test.timing && (
                <div className="small">
                  Mất {(test.timing.read_ms / 1000).toFixed(2)} s: {test.timing.frames} ảnh, chụp {test.timing.capture_ms} ms,
                  nhận diện {test.timing.detect_ms} ms{test.timing.flash ? ', có flash' : ''}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="platecam-view">
          {snap
            ? <img src={tokenUrl('/plate-cam/snapshot.jpg', { t: snap })} alt="ESP32-CAM" onError={() => setMsg({ ok: false, text: 'Không lấy được ảnh từ ESP32-CAM' })} />
            : <div className="cam-off"><Video size={28} /><span className="muted small">Bấm “Chụp xem” để xem ảnh và vùng cổng</span></div>}
          {test?.image && <img src={tokenUrl(`/plates/img/${test.image}`)} alt="kết quả đọc thử" />}
        </div>
      </div>
    </section>
  )
}
