import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, LayoutTemplate, Map as MapIcon, RotateCcw, Save, ScanLine } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../App.jsx'
import LotMap from '../components/LotMap.jsx'
import MapEditor from '../components/MapEditor.jsx'
import RoiEditor from '../components/RoiEditor.jsx'
import { TEMPLATES, buildTemplate, normalize } from '../layoutTools'
import { reloadLayout } from '../useLayout'

const TABS = [
  { id: 'templates', label: '1. Mẫu có sẵn', icon: LayoutTemplate },
  { id: 'map', label: '2. Sơ đồ', icon: MapIcon },
  { id: 'roi', label: '3. Vùng camera', icon: ScanLine },
]

function TemplateCard({ tpl, current, onUse }) {
  const [p, setP] = useState(() => Object.fromEntries(tpl.params.map((x) => [x.key, x.def])))
  const preview = useMemo(() => buildTemplate(tpl, p, current), [tpl, p, current])
  const set = (x) => (e) => {
    const v = Math.round(Number(e.target.value))
    if (v >= x.min && v <= x.max) setP((old) => ({ ...old, [x.key]: v }))
  }
  return (
    <section className="card tpl">
      <div className="card-head">
        <h3>{tpl.name}</h3>
        <span className="muted small">{preview.slots.length} ô</span>
      </div>
      <div className="tpl-preview"><LotMap layout={preview} slots={[]} /></div>
      <p className="muted small">{tpl.desc}</p>
      <div className="btn-row tpl-params">
        {tpl.params.map((x) => (
          <label key={x.key}>{x.label}
            <input type="number" min={x.min} max={x.max} value={p[x.key]} onChange={set(x)} />
          </label>
        ))}
        <button className="btn btn-primary" onClick={() => onUse(preview)}>Dùng mẫu này</button>
      </div>
    </section>
  )
}

/** Cài đặt sơ đồ bãi (quản lý): chọn mẫu -> chỉnh sơ đồ -> vẽ vùng camera -> lưu & áp dụng ngay. */
export default function LayoutSettings() {
  const { user } = useAuth()
  const [orig, setOrig] = useState(null)
  const [draft, setDraft] = useState(null)
  const [tab, setTab] = useState('map')
  const [check, setCheck] = useState(null)
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  const isAdmin = user.role === 'admin'

  useEffect(() => {
    reloadLayout().then((l) => {
      const n = normalize(l)
      setOrig(n)
      setDraft(n)
    }).catch((e) => setMsg({ ok: false, text: e.message }))
  }, [])

  const edit = useCallback((fn) => setDraft((d) => {
    const n = structuredClone(d)
    fn(n)
    return n
  }), [])

  const dirty = useMemo(() => draft && JSON.stringify(draft) !== JSON.stringify(orig), [draft, orig])

  // kiểm tra trên server mỗi khi bản nháp ngừng thay đổi một lúc
  useEffect(() => {
    if (!draft || !isAdmin) return
    const t = setTimeout(() => api('/layout/validate', { method: 'POST', body: draft }).then(setCheck).catch(() => {}), 400)
    return () => clearTimeout(t)
  }, [draft, isAdmin])

  useEffect(() => {
    if (!dirty) return
    const warn = (e) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  if (!isAdmin) return <div className="notice">Cần tài khoản quản lý để chỉnh sơ đồ bãi.</div>
  if (!draft) return <div className="muted">{msg?.text ?? 'Đang tải sơ đồ…'}</div>

  const applyTemplate = (l) => {
    if (!window.confirm('Thay toàn bộ bản nháp bằng mẫu này? Vùng camera của các ô sẽ phải vẽ lại.')) return
    setDraft(l)
    setTab('map')
    setMsg(null)
  }

  const save = async () => {
    const text = `Áp dụng sơ đồ mới (${draft.slots.length} ô) ngay bây giờ?\n\n` +
      'Bộ nhận diện sẽ khởi động lại; xe đang đỗ ở ô bị xóa sẽ được kết thúc phiên đỗ.' +
      (check?.warnings.length ? `\n\nCảnh báo:\n- ${check.warnings.join('\n- ')}` : '')
    if (!window.confirm(text)) return
    setSaving(true)
    try {
      const res = await api('/layout', { method: 'PUT', body: draft })
      const n = normalize(res.layout)
      setOrig(n)
      setDraft(n)
      setMsg({ ok: true, text: 'Đã lưu và áp dụng sơ đồ mới. Bản trước được giữ ở config/layout.prev.json.' })
      reloadLayout().catch(() => {})
    } catch (e) {
      setMsg({ ok: false, text: e.message })
    } finally {
      setSaving(false)
    }
  }

  const errors = check?.errors ?? []
  const warnings = check?.warnings ?? []

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Sơ đồ bãi đỗ</h2>
          <p className="muted">Chọn mẫu hoặc tự chỉnh sơ đồ, vẽ vùng từng ô trên ảnh camera, rồi lưu để áp dụng ngay.</p>
        </div>
        <div className="btn-row">
          <button className="btn" disabled={!dirty || saving} onClick={() => { setDraft(orig); setMsg(null) }}>
            <RotateCcw size={15} /> Hoàn tác
          </button>
          <button className="btn btn-primary" disabled={!dirty || saving || errors.length > 0} onClick={save}>
            <Save size={15} /> {saving ? 'Đang áp dụng…' : 'Lưu & áp dụng'}
          </button>
        </div>
      </div>

      {msg && <div className={msg.ok ? 'notice notice-ok' : 'notice'}>{msg.text}</div>}
      {errors.length > 0 && (
        <div className="check check-bad">
          <b><AlertTriangle size={15} /> Chưa lưu được — {errors.length} lỗi:</b>
          <ul>{errors.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="check check-warn">
          <b><AlertTriangle size={15} /> Cảnh báo:</b>
          <ul>{warnings.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      )}
      {check && !errors.length && !warnings.length && dirty && (
        <div className="notice notice-ok"><CheckCircle2 size={15} /> Sơ đồ hợp lệ, có thể lưu.</div>
      )}

      <div className="tabs">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            <Icon size={16} /> {label}
          </button>
        ))}
        {dirty && <span className="pill pill-warn"><i className="dot" />Có thay đổi chưa lưu</span>}
      </div>

      {tab === 'templates' && (
        <div className="grid-tpl">
          {TEMPLATES.map((t) => <TemplateCard key={t.id} tpl={t} current={draft} onUse={applyTemplate} />)}
        </div>
      )}
      {tab === 'map' && <MapEditor draft={draft} edit={edit} />}
      {tab === 'roi' && <RoiEditor draft={draft} edit={edit} />}
    </>
  )
}
