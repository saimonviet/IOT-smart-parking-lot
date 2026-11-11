const KEY = 'parking_token'

export const getToken = () => localStorage.getItem(KEY) || ''
export const setToken = (t) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY))

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch('/api' + path, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
      Authorization: `Bearer ${getToken()}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401 && path !== '/auth/login') {
    setToken('')
    window.location.href = '/login'
    throw new Error('Phiên đăng nhập đã hết hạn')
  }
  if (!res.ok) {
    let msg = res.statusText
    try { msg = (await res.json()).detail || msg } catch { /* không phải JSON */ }
    throw new Error(msg)
  }
  return res.json()
}

export const tokenUrl = (path, params = {}) => {
  const q = new URLSearchParams({ ...params, token: getToken() })
  return `/api${path}?${q}`
}
