import { useEffect, useState } from 'react'
import { RefreshCw, ScanLine, Video } from 'lucide-react'
import { api, tokenUrl } from '../api'

const GATES = [['in', 'Cổng vào', '#38bdf8'], ['out', 'Cổng ra', '#f87171']]

/** Thiết bị ESP32-CAM ở cổng: địa chỉ, khóa, flash, động cơ xoay, vùng ảnh từng làn. Phần AI đọc biển nằm ở PlateAiCard. */
export default function PlateCamCard({ status, isAdmin }) {
  const [cfg, setCfg] = useState(null)
  const [snap, setSnap] = useState(0)
  const [msg, setMsg] = useState(null)
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
  const save = () => run(() => api('/plate-cam', { method: 'PUT', body: cfg }), () => { setSnap(Date.now()); return 'Đã lưu cấu hình ESP32-CAM' })
  const aim = (g, name) => run(() => api('/plate-cam/aim', { method: 'POST', body: { gate: g } }),
    (r) => { setSnap(Date.now()); return r.moved ? `Đã xoay camera về ${name.toLowerCase()} (${(r.ms / 1000).toFixed(1)} s)` : `Camera đã nhìn ${name.toLowerCase()} sẵn` })

  return (
    <section className="card wide-plate">
      <div className="card-head"><h3><ScanLine size={18} /> Camera biển số ở cổng (ESP32-CAM)</h3>
        <span className={`pill ${status?.online ? 'pill-ok' : 'pill-bad'}`}><i className="dot" />{status?.enabled ? (status.online ? 'Có tín hiệu' : 'Chưa có ảnh') : 'Tắt'}</span></div>
      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'}>{msg.text}</div>}
      {status?.error && <div className="notice">{status.error}</div>}
      <div className="platecam">
        <div className="platecam-form">
          <label>Địa chỉ ESP32-CAM
            <input value={cfg.url} onChange={(e) => setCfg({ ...cfg, url: e.target.value })} placeholder="http://192.168.1.50" disabled={!isAdmin} />
          </label>
          <label>Khóa truy cập (CAM_KEY trong firmware)
            <input value={cfg.key} onChange={(e) => setCfg({ ...cfg, key: e.target.value })} placeholder="để trống nếu không đặt" disabled={!isAdmin} />
          </label>
          <label className="check-row">
            <input type="checkbox" checked={!!cfg.aim} onChange={(e) => setCfg({ ...cfg, aim: e.target.checked })} disabled={!isAdmin} />
            Camera xoay bằng động cơ bước (xoay về cổng có xe rồi mới chụp; xe ra được ưu tiên)
          </label>
          <label>Đèn flash khi chụp (0 = tắt, 255 = sáng nhất)
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
            {cfg.aim && GATES.map(([g, name]) => (
              <button key={g} className="btn" disabled={!isAdmin || busy || !status?.enabled} onClick={() => aim(g, name)}>
                Xoay về {name.toLowerCase()}
              </button>
            ))}
          </div>
        </div>
        <div className="platecam-view">
          {snap
            ? <img src={tokenUrl('/plate-cam/snapshot.jpg', { t: snap })} alt="ESP32-CAM" onError={() => setMsg({ ok: false, text: 'Không lấy được ảnh từ ESP32-CAM' })} />
            : <div className="cam-off"><Video size={28} /><span className="muted small">Bấm “Chụp xem” để xem ảnh và vùng cổng</span></div>}
        </div>
      </div>
    </section>
  )
}
