import { NavLink, Outlet } from 'react-router-dom'
import { BarChart3, Car, Cpu, History, LayoutDashboard, LayoutGrid, LogOut, ParkingSquare } from 'lucide-react'
import { useAuth } from '../App.jsx'
import { useLive } from '../useLive.js'

const NAV = [
  { to: '/', label: 'Tổng quan', icon: LayoutDashboard },
  { to: '/vehicles', label: 'Xe ra vào', icon: Car },
  { to: '/history', label: 'Lịch sử đỗ xe', icon: History },
  { to: '/analytics', label: 'Thống kê', icon: BarChart3 },
  { to: '/devices', label: 'Thiết bị', icon: Cpu },
  { to: '/layout-settings', label: 'Sơ đồ bãi', icon: LayoutGrid, admin: true },
]

function Pill({ ok, label }) {
  return (
    <span className={`pill ${ok ? 'pill-ok' : 'pill-bad'}`}>
      <i className="dot" /> {label}
    </span>
  )
}

export default function Layout() {
  const { user, logout } = useAuth()
  const live = useLive()
  const dev = live.state?.devices

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-icon"><ParkingSquare size={22} /></span>
          <div>
            <div className="brand-name">SmartPark</div>
            <div className="brand-sub">Bãi đỗ xe thông minh</div>
          </div>
        </div>
        <nav>
          {NAV.filter((n) => !n.admin || user.role === 'admin').map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')}>
              <Icon size={18} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="user">
            <div className="avatar">{user.username[0].toUpperCase()}</div>
            <div>
              <div className="user-name">{user.username}</div>
              <div className="user-role">{user.role === 'admin' ? 'Quản lý' : 'Xem'}</div>
            </div>
          </div>
          <button className="icon-btn" title="Đăng xuất" onClick={logout}><LogOut size={18} /></button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-title">{new Date().toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' })}</div>
          <div className="pills">
            <Pill ok={live.connected} label="Máy chủ" />
            <Pill ok={!!dev?.pi.online} label="Raspberry Pi" />
            <Pill ok={!!dev?.camera.online} label="Camera" />
            {dev?.plate?.enabled && <Pill ok={dev.plate.online && dev.plate.model_ready} label="Cam biển số" />}
          </div>
        </header>
        <div className="content">
          <Outlet context={live} />
        </div>
      </main>
    </div>
  )
}
