import { useEffect, useState } from 'react'
import { ArrowRight, Camera, ScanLine, ScanText, Scan } from 'lucide-react'
import { api, tokenUrl } from '../api'
import { fmtPlate } from '../utils'

const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
const GATES = [['in', 'cổng vào'], ['out', 'cổng ra']]

function Row({ k, v }) {
  return <div className="row"><span className="muted">{k}</span><b>{v ?? '—'}</b></div>
}

/** AI 2: đọc biển số từ ảnh ESP32-CAM = YOLO tìm biển + CRNN đọc ký tự. */
export default function PlateAiCard({ status, isAdmin }) {
  const [info, setInfo] = useState(null)
  const [msg, setMsg] = useState(null)
  const [test, setTest] = useState(null)
  const [busy, setBusy] = useState(false)
  const [thr, setThr] = useState(null)       // giá trị đang kéo trên thanh trượt
  const [saved, setSaved] = useState(null)   // giá trị server đang dùng
  const [defs, setDefs] = useState(null)     // mặc định (biến môi trường)

  const load = () => api('/plate-cam').then((d) => {
    setInfo(d.model)
    setSaved(d.thresholds)
    setThr((t) => t ?? d.thresholds)
    setDefs(d.default_thresholds)
  }).catch(() => {})
  useEffect(() => { load() }, [])

  const run = async (fn, ok) => {
    setBusy(true); setMsg(null)
    try { const r = await fn(); if (ok) setMsg({ ok: true, text: ok(r) }) } catch (e) { setMsg({ ok: false, text: e.message }) } finally { setBusy(false) }
  }
  const doTest = (g) => run(async () => setTest(await api('/plate-cam/test', { method: 'POST', body: { gate: g } })))
  const saveThr = () => run(async () => {
    const r = await api('/plate-ai', { method: 'PUT', body: thr })
    setSaved(r.thresholds); setThr(r.thresholds)
  }, () => 'Đã lưu ngưỡng, áp dụng từ lượt đọc tiếp theo')
  const thrChanged = thr && saved && (thr.det_conf !== saved.det_conf || thr.min_conf !== saved.min_conf)
  const isDefault = thr && defs && thr.det_conf === defs.det_conf && thr.min_conf === defs.min_conf
  const reload = () => run(async () => { await api('/plate-cam/reload-model', { method: 'POST' }); await load() }, () => 'Đã nạp lại mô hình biển số')

  const ready = status?.model_ready
  const d = info?.det_metrics ?? {}
  const o = info?.ocr_metrics ?? {}
  const e = info?.e2e_metrics ?? {}

  return (
    <section className="card ai-card">
      <div className="card-head">
        <div>
          <h3><ScanLine size={18} /> AI nhận diện biển số</h3>
          <div className="ai-flow">
            <span><Camera size={13} /> ESP32-CAM ở cổng</span><ArrowRight size={13} />
            <span>Tìm biển</span><ArrowRight size={13} />
            <span>Đọc ký tự</span><ArrowRight size={13} />
            <span>Biển số xe</span>
          </div>
        </div>
        <span className={`pill ${ready ? 'pill-ok' : 'pill-bad'}`}><i className="dot" />{ready ? 'Sẵn sàng' : 'Chưa nạp'}</span>
      </div>
      {!ready && status?.model_error && <div className="notice">{status.model_error}</div>}
      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'}>{msg.text}</div>}

      <div className="stage-list">
        <div className="stage">
          <div className="stage-head"><Scan size={16} /><b>Bước 1: Tìm vị trí biển số</b></div>
          <div className="model-info">
            <span>YOLO ({info?.det_arch ?? '—'}) · file <code>{info?.det_file ?? 'plate_det.pt'}</code>{info && !info.det_exists && <b className="warn"> (chưa có file)</b>}</span>
            <span>Độ chính xác (mAP50): <b>{pct(d.mAP50)}</b> · tìm thấy biển: <b>{pct(d.recall)}</b></span>
            {d.cpu_ms_1024x768 != null && <span>~{Math.round(d.cpu_ms_1024x768)} ms/ảnh trên CPU</span>}
          </div>
        </div>
        <div className="stage">
          <div className="stage-head"><ScanText size={16} /><b>Bước 2: Đọc ký tự trên biển</b></div>
          <div className="model-info">
            <span>{info?.ocr_arch ?? 'CRNN + CTC'} · file <code>{info?.ocr_file ?? 'plate_ocr.pt'}</code>{info && !info.ocr_exists && <b className="warn"> (chưa có file)</b>}</span>
            <span>Đọc đúng cả biển: <b>{pct(o.test_accuracy)}</b> (biển 1 dòng {pct(o.acc_1row)}, 2 dòng {pct(o.acc_2row)})</span>
            {o.cpu_ms_per_plate != null && <span>~{Math.round(o.cpu_ms_per_plate)} ms/biển trên CPU</span>}
          </div>
        </div>
      </div>

      <div className="ai-status">
        <Row k="Đúng toàn bộ quy trình (ảnh → biển số)" v={pct(e.end_to_end_accuracy)} />
        <Row k="Dữ liệu huấn luyện" v={info?.datasets?.length ? info.datasets.join(', ') : null} />
        <Row k="Ngày huấn luyện" v={info?.created} />
        <Row k="Bắt buộc đọc được biển mới mở rào" v={status?.required ? 'Có' : 'Không'} />
      </div>
      {thr && (
        <div className="thr">
          <b>Ngưỡng nhận diện</b>
          <label>Bước 1: độ tin cậy tối thiểu để coi là biển số: <b>{thr.det_conf.toFixed(2)}</b>
            <input type="range" min="0.05" max="0.95" step="0.05" value={thr.det_conf} disabled={!isAdmin}
              onChange={(ev) => setThr({ ...thr, det_conf: Number(ev.target.value) })} />
          </label>
          <div className="muted small">Hạ xuống nếu hay báo "Không thấy biển số" (biển nhỏ, xa, tối). Nâng lên nếu khung nhận nhầm vật khác là biển.</div>
          <label>Bước 2: độ tin cậy tối thiểu để chấp nhận biển đọc được: <b>{thr.min_conf.toFixed(2)}</b>
            <input type="range" min="0.05" max="0.95" step="0.05" value={thr.min_conf} disabled={!isAdmin}
              onChange={(ev) => setThr({ ...thr, min_conf: Number(ev.target.value) })} />
          </label>
          <div className="muted small">
            Kết quả dưới ngưỡng bị coi là "đọc chưa chắc chắn": xe không được tự mở rào, nhân viên phải nhập tay.
            Nâng lên để tránh ghi sai biển (an toàn hơn cho cổng ra), hạ xuống để ít phải nhập tay hơn.
          </div>
          {isAdmin && (
            <div className="btn-row">
              <button className="btn btn-primary btn-sm" disabled={busy || !thrChanged} onClick={saveThr}>Lưu ngưỡng</button>
              {thrChanged && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setThr(saved)}>Hủy</button>}
              {!isDefault && defs && <button className="btn btn-ghost btn-sm" disabled={busy}
                onClick={() => setThr(defs)}>Về mặc định ({defs.det_conf.toFixed(2)} / {defs.min_conf.toFixed(2)})</button>}
            </div>
          )}
        </div>
      )}

      <p className="muted small">
        Mỗi lượt chụp vài ảnh, đọc từng ảnh rồi lấy kết quả nhiều phiếu nhất, chuẩn hóa theo định dạng biển Việt Nam.
        Mô hình mới: chép đè <code>plate_det.pt</code>, <code>plate_ocr.pt</code> + <code>plate_ocr.json</code> vào <code>pc_server/models/</code> rồi bấm Nạp lại.
      </p>

      <div className="btn-row">
        {GATES.map(([g, name]) => (
          <button key={g} className="btn" disabled={!isAdmin || busy || !status?.enabled} onClick={() => doTest(g)}>Đọc thử {name}</button>
        ))}
        <button className="btn" disabled={!isAdmin || busy} onClick={reload}>Nạp lại mô hình</button>
      </div>
      {!status?.enabled && <div className="muted small">Cần nhập địa chỉ ESP32-CAM ở phần Thiết bị để đọc thử.</div>}
      {test && (
        <div className={test.plate ? 'notice notice-ok test-result' : 'notice test-result'}>
          <div>
            {test.plate ? <>Đọc được: <span className="plate">{fmtPlate(test.plate)}</span> ({Math.round(test.conf * 100)}%)</> : `Không đọc được: ${test.reason}`}
            {saved && test.conf > 0 && <div className="small">Độ tin cậy {Math.round(test.conf * 100)}%, ngưỡng chấp nhận {Math.round(saved.min_conf * 100)}%</div>}
            {test.timing && (
              <div className="small">
                Mất {(test.timing.read_ms / 1000).toFixed(2)} s: {test.timing.frames} ảnh, chụp {test.timing.capture_ms} ms,
                nhận diện {test.timing.detect_ms} ms{test.timing.flash ? ', có flash' : ''}
                {test.timing.aim_ms ? `, xoay camera ${test.timing.aim_ms} ms` : ''}
              </div>
            )}
          </div>
          {test.image && <img src={tokenUrl(`/plates/img/${test.image}`)} alt="kết quả đọc thử" />}
        </div>
      )}
    </section>
  )
}
