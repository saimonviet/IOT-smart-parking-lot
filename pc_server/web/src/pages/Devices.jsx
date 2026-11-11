import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Camera, Cpu, Lightbulb, Lock, LockOpen, ScanSearch } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../App.jsx'
import ModelPicker from '../components/ModelPicker.jsx'
import PlateCamCard from '../components/PlateCamCard.jsx'

const BARRIER = { closed: 'Đóng', open: 'Mở', opening: 'Đang mở', closing: 'Đang đóng', partial: 'Giữa chừng' }

function Row({ k, v }) {
  return <div className="row"><span className="muted">{k}</span><b>{v ?? '—'}</b></div>
}

export default function Devices() {
  const { state } = useOutletContext()
  const { user } = useAuth()
  const [msg, setMsg] = useState(null)
  const isAdmin = user.role === 'admin'

  if (!state) return <div className="muted">Đang tải…</div>
  const { pi, camera, detector, plate } = state.devices
  const t = pi.telemetry || {}

  const run = async (label, path, body) => {
    try {
      await api(path, { method: 'POST', body })
      setMsg({ ok: true, text: `${label}: đã gửi` })
    } catch (e) {
      setMsg({ ok: false, text: `${label}: ${e.message}` })
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Thiết bị</h2>
          <p className="muted">Tình trạng Raspberry Pi, camera, bộ nhận diện và điều khiển thủ công.</p>
        </div>
      </div>
      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'}>{msg.text}</div>}

      <div className="grid-devices">
        <section className="card">
          <div className="card-head"><h3><Cpu size={18} /> Raspberry Pi</h3>
            <span className={`pill ${pi.online ? 'pill-ok' : 'pill-bad'}`}><i className="dot" />{pi.online ? 'Online' : 'Offline'}</span></div>
          <Row k="Địa chỉ IP" v={pi.ip} />
          <Row k="Thiết bị" v={pi.info?.device} />
          <Row k="Loại rào chắn" v={pi.info?.barrier === 'servo' ? 'Servo' : pi.info?.barrier === 'stepper' ? 'Động cơ bước' : null} />
          <Row k="Khoảng cách cổng vào" v={t.dist_in_cm != null ? `${t.dist_in_cm} cm` : null} />
          <Row k="Khoảng cách cổng ra" v={t.dist_out_cm != null ? `${t.dist_out_cm} cm` : null} />
          <Row k="Rào vào" v={BARRIER[t.barrier_in] ?? t.barrier_in} />
          <Row k="Rào ra" v={BARRIER[t.barrier_out] ?? t.barrier_out} />
          <Row k="Nhiệt độ CPU" v={t.cpu_temp != null ? `${t.cpu_temp}°C` : null} />
        </section>

        <section className="card">
          <div className="card-head"><h3><Camera size={18} /> Camera</h3>
            <span className={`pill ${camera.online ? 'pill-ok' : 'pill-bad'}`}><i className="dot" />{camera.online ? 'Có tín hiệu' : 'Mất tín hiệu'}</span></div>
          <Row k="Tốc độ khung hình" v={camera.online ? `${camera.fps} fps` : null} />
          <Row k="Nguồn" v={camera.source} />
          {camera.error && <div className="notice">{camera.error}</div>}
        </section>

        <section className="card">
          <div className="card-head"><h3><ScanSearch size={18} /> Nhận diện AI</h3></div>
          <Row k="Bộ nhận diện" v={{ classifier: 'Mô hình phân loại ô (tự huấn luyện)', yolo: 'YOLOv8 (COCO)', background: 'So sánh ảnh nền' }[detector.name] ?? 'Tắt'} />
          {detector.model && <Row k="Mô hình" v={detector.model} />}
          {detector.threshold != null && <Row k="Ngưỡng có xe" v={detector.threshold.toFixed(2)} />}
          <Row k="Tốc độ xử lý" v={`${detector.fps} fps`} />
          <Row k="Số vật thể phát hiện" v={detector.boxes} />
          <Row k="Ảnh nền bãi trống" v={detector.has_reference ? 'Đã có' : 'Chưa có'} />
          {detector.error && <div className="notice">{detector.error}</div>}
          <button className="btn" disabled={!isAdmin || !camera.online} onClick={() => run('Chụp ảnh nền', '/detector/reference')}>
            Chụp ảnh nền (khi bãi đang trống)
          </button>
        </section>

        <ModelPicker detector={detector} isAdmin={isAdmin} />

        <PlateCamCard status={plate} isAdmin={isAdmin} />

        <section className="card">
          <div className="card-head"><h3>Điều khiển thủ công</h3></div>
          {!isAdmin && <div className="muted small">Cần tài khoản quản lý.</div>}
          <div className="ctl">
            {[['in', 'vào'], ['out', 'ra']].map(([g, name]) => (
              <div key={g} className="ctl-row">
                <span>Rào {name}</span>
                <div className="btn-row">
                  <button className="btn" disabled={!isAdmin || !pi.online} onClick={() => run(`Mở rào ${name}`, '/devices/barrier', { gate: g, action: 'open' })}><LockOpen size={15} /> Mở</button>
                  <button className="btn" disabled={!isAdmin || !pi.online} onClick={() => run(`Đóng rào ${name}`, '/devices/barrier', { gate: g, action: 'close' })}><Lock size={15} /> Đóng</button>
                </div>
              </div>
            ))}
            <div className="ctl-row">
              <span>12 đèn LED</span>
              <button className="btn" disabled={!isAdmin || !pi.online} onClick={() => run('Chạy thử đèn', '/devices/led-test')}><Lightbulb size={15} /> Chạy đèn 1→12</button>
            </div>
          </div>
        </section>
      </div>
    </>
  )
}
