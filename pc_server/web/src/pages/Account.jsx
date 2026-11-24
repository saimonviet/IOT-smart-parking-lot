import { useCallback, useEffect, useState } from 'react'
import { KeyRound, Loader2, Lock, LockOpen, Trash2, UserPlus } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../App.jsx'
import { fmtTime } from '../utils'

export const ROLE_TEXT = { admin: 'Quản lý', viewer: 'Nhân viên' }
const MIN = 8

function ChangePassword() {
  const { user, login } = useAuth()
  const [f, setF] = useState({ old: '', next: '', again: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    if (f.next.length < MIN) return setMsg({ err: `Mật khẩu mới phải có ít nhất ${MIN} ký tự` })
    if (f.next !== f.again) return setMsg({ err: 'Nhập lại mật khẩu mới không khớp' })
    setBusy(true)
    setMsg(null)
    try {
      const res = await api('/auth/change-password', { method: 'POST', body: { old_password: f.old, new_password: f.next } })
      login(res.token, res.user)
      setF({ old: '', next: '', again: '' })
      setMsg({ ok: 'Đã đổi mật khẩu. Các thiết bị khác đang đăng nhập tài khoản này đã bị đăng xuất.' })
    } catch (err) {
      setMsg({ err: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card account-form" onSubmit={submit}>
      <div className="card-head"><h3><KeyRound size={18} /> Đổi mật khẩu</h3></div>
      {user.must_change && (
        <div className="notice">Bạn đang dùng mật khẩu mặc định hoặc mật khẩu do quản lý cấp. Hãy đổi mật khẩu mới.</div>
      )}
      <label>Mật khẩu hiện tại<input type="password" value={f.old} onChange={set('old')} autoComplete="current-password" required /></label>
      <label>Mật khẩu mới (ít nhất {MIN} ký tự)<input type="password" value={f.next} onChange={set('next')} autoComplete="new-password" required /></label>
      <label>Nhập lại mật khẩu mới<input type="password" value={f.again} onChange={set('again')} autoComplete="new-password" required /></label>
      {msg?.err && <div className="form-error">{msg.err}</div>}
      {msg?.ok && <div className="notice notice-ok">{msg.ok}</div>}
      <div><button className="btn btn-primary" disabled={busy}>{busy && <Loader2 size={16} className="spin" />} Đổi mật khẩu</button></div>
    </form>
  )
}

function NewUser({ onDone }) {
  const [f, setF] = useState({ username: '', password: '', role: 'viewer' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await api('/users', { method: 'POST', body: f })
      setF({ username: '', password: '', role: 'viewer' })
      onDone(`Đã tạo tài khoản '${f.username}'. Người dùng sẽ được nhắc đổi mật khẩu sau khi đăng nhập.`)
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card account-form" onSubmit={submit}>
      <div className="card-head"><h3><UserPlus size={18} /> Tạo tài khoản</h3></div>
      <label>Tên đăng nhập<input value={f.username} onChange={set('username')} placeholder="vd. nv_ca1" autoComplete="off" required /></label>
      <label>Mật khẩu ban đầu (ít nhất {MIN} ký tự)<input type="text" value={f.password} onChange={set('password')} autoComplete="off" required /></label>
      <label>Vai trò
        <select value={f.role} onChange={set('role')}>
          <option value="viewer">Nhân viên: chỉ xem</option>
          <option value="admin">Quản lý: toàn quyền</option>
        </select>
      </label>
      {err && <div className="form-error">{err}</div>}
      <div><button className="btn btn-primary" disabled={busy}>{busy && <Loader2 size={16} className="spin" />} Tạo tài khoản</button></div>
    </form>
  )
}

function UserList({ users, me, reload, onMsg }) {
  const [busy, setBusy] = useState(0)

  const act = async (u, fn, ok) => {
    setBusy(u.id)
    try {
      await fn()
      onMsg({ ok })
      await reload()
    } catch (e) {
      onMsg({ err: e.message })
    } finally {
      setBusy(0)
    }
  }

  const setRole = (u, role) => act(u, () => api(`/users/${u.id}`, { method: 'PATCH', body: { role } }),
    `Đã đổi '${u.username}' thành ${ROLE_TEXT[role].toLowerCase()}`)
  const toggle = (u) => act(u, () => api(`/users/${u.id}`, { method: 'PATCH', body: { active: !u.active } }),
    `Đã ${u.active ? 'khóa' : 'mở khóa'} '${u.username}'`)
  const reset = (u) => {
    const pw = window.prompt(`Mật khẩu mới cho '${u.username}' (ít nhất ${MIN} ký tự).\nNgười dùng sẽ bị đăng xuất và phải đổi lại sau khi đăng nhập.`)
    if (pw === null) return
    act(u, () => api(`/users/${u.id}/reset-password`, { method: 'POST', body: { password: pw } }),
      `Đã đặt lại mật khẩu cho '${u.username}'`)
  }
  const remove = (u) => {
    if (!window.confirm(`Xóa tài khoản '${u.username}'? Thao tác không hoàn tác được (có thể chọn Khóa thay vì xóa).`)) return
    act(u, () => api(`/users/${u.id}`, { method: 'DELETE' }), `Đã xóa '${u.username}'`)
  }

  return (
    <div className="card table-card">
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Tên đăng nhập</th><th>Vai trò</th><th>Trạng thái</th><th>Ngày tạo</th><th /></tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const self = u.id === me.id
              const dis = self || busy === u.id
              return (
                <tr key={u.id}>
                  <td><b>{u.username}</b>{self && <span className="muted small"> (bạn)</span>}</td>
                  <td>
                    <select value={u.role} disabled={dis} onChange={(e) => setRole(u, e.target.value)}>
                      <option value="viewer">{ROLE_TEXT.viewer}</option>
                      <option value="admin">{ROLE_TEXT.admin}</option>
                    </select>
                  </td>
                  <td>
                    {u.active ? <span className="badge badge-free">Hoạt động</span> : <span className="badge badge-occupied">Đã khóa</span>}
                    {u.active && u.must_change && <span className="badge badge-reserved" title="Chưa đổi mật khẩu được cấp">Chưa đổi MK</span>}
                  </td>
                  <td className="muted">{fmtTime(u.created_at)}</td>
                  <td>
                    <div className="btn-row nowrap">
                      <button className="icon-btn" title="Đặt lại mật khẩu" disabled={dis} onClick={() => reset(u)}><KeyRound size={16} /></button>
                      <button className="icon-btn" title={u.active ? 'Khóa tài khoản' : 'Mở khóa'} disabled={dis} onClick={() => toggle(u)}>
                        {u.active ? <Lock size={16} /> : <LockOpen size={16} />}
                      </button>
                      <button className="icon-btn btn-danger" title="Xóa tài khoản" disabled={dis} onClick={() => remove(u)}><Trash2 size={16} /></button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function Account() {
  const { user } = useAuth()
  const isAdmin = user.role === 'admin'
  const [users, setUsers] = useState([])
  const [msg, setMsg] = useState(null)

  const reload = useCallback(() => api('/users').then(setUsers).catch((e) => setMsg({ err: e.message })), [])
  useEffect(() => { if (isAdmin) reload() }, [isAdmin, reload])

  return (
    <>
      <div className="page-head">
        <div>
          <h2>Tài khoản</h2>
          <p className="muted">
            Đăng nhập với <b>{user.username}</b> ({ROLE_TEXT[user.role] ?? user.role}).
            {isAdmin ? ' Quản lý cấp tài khoản cho nhân viên trực bãi. Nhân viên chỉ xem, không mở rào, sửa biển số hay đổi cấu hình được.' : ''}
          </p>
        </div>
      </div>

      <div className={isAdmin ? 'grid-account' : 'account-single'}>
        <ChangePassword />
        {isAdmin && <NewUser onDone={(ok) => { setMsg({ ok }); reload() }} />}
      </div>

      {isAdmin && (
        <>
          <h3 className="section-title">Danh sách tài khoản</h3>
          {msg?.err && <div className="form-error">{msg.err}</div>}
          {msg?.ok && <div className="notice notice-ok">{msg.ok}</div>}
          <UserList users={users} me={user} reload={reload} onMsg={setMsg} />
        </>
      )}
    </>
  )
}
