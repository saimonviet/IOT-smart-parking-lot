import { useState } from 'react'
import { Loader2, Lock, ParkingSquare, User } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../App.jsx'

export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await api('/auth/login', { method: 'POST', body: { username, password } })
      login(res.token, res.user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-art">
        <div className="login-art-inner">
          <span className="brand-icon big"><ParkingSquare size={34} /></span>
          <h1>SmartPark</h1>
          <p>Hệ thống quản lý bãi đỗ xe dành cho quản lý và nhân viên vận hành.</p>
          <ul>
            <li>Theo dõi tình trạng bãi theo thời gian thực</li>
            <li>Quản lý xe ra vào theo biển số</li>
            <li>Tra cứu lịch sử, thống kê lượt xe và doanh thu</li>
            <li>Phân quyền tài khoản quản lý và nhân viên</li>
          </ul>
        </div>
      </div>
      <form className="login-card" onSubmit={submit}>
        <h2>Đăng nhập</h2>
        <p className="muted">Dùng tài khoản do quản lý cấp để truy cập hệ thống</p>
        <label>
          Tên đăng nhập
          <span className="input-wrap"><User size={16} /><input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required /></span>
        </label>
        <label>
          Mật khẩu
          <span className="input-wrap"><Lock size={16} /><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></span>
        </label>
        {error && <div className="form-error">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? <Loader2 size={16} className="spin" /> : null} Đăng nhập
        </button>
      </form>
    </div>
  )
}
