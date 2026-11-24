import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { BrainCircuit, Camera, Cpu, DoorOpen, HardDrive, Lock, LockOpen } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../App.jsx'
import ModelPicker from '../components/ModelPicker.jsx'
import PlateCamCard from '../components/PlateCamCard.jsx'
import PlateAiCard from '../components/PlateAiCard.jsx'

const BARRIER = { closed: 'Đóng', open: 'Mở', opening: 'Đang mở', closing: 'Đang đóng', partial: 'Giữa chừng' }

function Row({ k, v }) {
  return <div className="row"><span className="muted">{k}</span><b>{v ?? '—'}</b></div>
}

function Online({ ok, on = 'Online', off = 'Offline' }) {
  return <span className={`pill ${ok ? 'pill-ok' : 'pill-bad'}`}><i className="dot" />{ok ? on : off}</span>
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
          <h2>Thiết bị & AI</h2>
          <p className="muted">Tình trạng phần cứng, điều khiển rào chắn và hai mô hình AI của hệ thống.</p>
        </div>
      </div>
      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'}>{msg.text}</div>}

      {/* ------------------------------------------------ PHẦN CỨNG */}
      <h3 className="section-title"><HardDrive size={18} /> Thiết bị phần cứng</h3>
      <div className="grid-hw">
        <section className="card">
          <div className="card-head"><h3><Cpu size={18} /> Raspberry Pi</h3><Online ok={pi.online} /></div>
          <Row k="Địa chỉ IP" v={pi.ip} />
          <Row k="Thiết bị" v={pi.info?.device} />
          <Row k="Cảm biến cổng vào" v={t.dist_in_cm != null ? `${t.dist_in_cm} cm` : null} />
          <Row k="Cảm biến cổng ra" v={t.dist_out_cm != null ? `${t.dist_out_cm} cm` : null} />
          <Row k="Nhiệt độ CPU" v={t.cpu_temp != null ? `${t.cpu_temp}°C` : null} />
        </section>

        <section className="card">
          <div className="card-head"><h3><Camera size={18} /> Camera bãi đỗ</h3><Online ok={camera.online} on="Có tín hiệu" off="Mất tín hiệu" /></div>
          <Row k="Nguồn" v={camera.source} />
          <Row k="Tốc độ khung hình" v={camera.online ? `${camera.fps} fps` : null} />
          <p className="muted small">Ảnh từ camera này được đưa vào AI nhận diện ô trống.</p>
          {camera.error && <div className="notice">{camera.error}</div>}
        </section>

        <section className="card">
          <div className="card-head"><h3><DoorOpen size={18} /> Rào chắn</h3>
            <span className="muted small">{pi.info?.barrier === 'servo' ? 'Servo' : pi.info?.barrier === 'stepper' ? 'Động cơ bước' : ''}</span></div>
          <div className="ctl">
            {[['in', 'vào', t.barrier_in], ['out', 'ra', t.barrier_out]].map(([g, name, st]) => (
              <div key={g} className="ctl-row">
                <span>Rào {name}: <b>{BARRIER[st] ?? st ?? '—'}</b></span>
                <div className="btn-row">
                  <button className="btn" disabled={!isAdmin || !pi.online} onClick={() => run(`Mở rào ${name}`, '/devices/barrier', { gate: g, action: 'open' })}><LockOpen size={15} /> Mở</button>
                  <button className="btn" disabled={!isAdmin || !pi.online} onClick={() => run(`Đóng rào ${name}`, '/devices/barrier', { gate: g, action: 'close' })}><Lock size={15} /> Đóng</button>
                </div>
              </div>
            ))}
          </div>
          <p className="muted small">{isAdmin ? 'Dùng khi cần mở/đóng tay, ví dụ xe ưu tiên hoặc sự cố.' : 'Cần tài khoản quản lý.'}</p>
        </section>

        <PlateCamCard status={plate} isAdmin={isAdmin} />
      </div>

      {/* ------------------------------------------------ AI */}
      <h3 className="section-title"><BrainCircuit size={18} /> Nhận diện AI</h3>
      <div className="grid-ai">
        <ModelPicker detector={detector} cameraOnline={camera.online} isAdmin={isAdmin}
          onReference={() => run('Chụp ảnh nền', '/detector/reference')} />
        <PlateAiCard status={plate} isAdmin={isAdmin} />
      </div>
    </>
  )
}
