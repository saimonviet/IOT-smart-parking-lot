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
          <p>Giám sát bãi đỗ xe theo thời gian thực: nhận diện ô trống bằng AI, chỉ đường cho xe vào và quản lý lịch sử đỗ xe.</p>
          <ul>
            <li>Camera + AI nhận diện 12 ô đỗ</li>
            <li>Tự chỉ ô trống gần nhất cho xe vào</li>
            <li>Điều khiển rào chắn, đèn, màn hình OLED</li>
          </ul>
        </div>
      </div>
      <form className="login-card" onSubmit={submit}>
        <h2>Đăng nhập quản lý</h2>
        <p className="muted">Nhập tài khoản để truy cập hệ thống</p>
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
