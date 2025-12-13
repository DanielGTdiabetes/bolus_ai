import { useEffect, useState } from 'react'
import { api } from '../api/client'

let accessToken = null
let refreshToken = null

export function useAuth() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const stored = localStorage.getItem('bolus_auth')
    if (stored) {
      const parsed = JSON.parse(stored)
      accessToken = parsed.access
      refreshToken = parsed.refresh
      setUser(parsed.user)
    }
    setLoading(false)
  }, [])

  const login = async (username, password) => {
    const res = await api.post('/api/auth/login', new URLSearchParams({ username, password }))
    accessToken = res.data.access_token
    refreshToken = res.data.refresh_token
    setUser(res.data.user)
    localStorage.setItem('bolus_auth', JSON.stringify({ access: accessToken, refresh: refreshToken, user: res.data.user }))
  }

  const logout = async () => {
    try {
      if (accessToken) await api.post('/api/auth/logout', {}, { headers: { Authorization: `Bearer ${accessToken}` } })
    } catch (e) {
      // ignore
    }
    accessToken = null
    refreshToken = null
    localStorage.removeItem('bolus_auth')
    setUser(null)
  }

  return { user, login, logout, loading, getAccessToken: () => accessToken, getRefreshToken: () => refreshToken }
}

export function authHeaders() {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {}
}

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers = { ...config.headers, Authorization: `Bearer ${accessToken}` }
  }
  return config
})

api.interceptors.response.use(
  (resp) => resp,
  async (error) => {
    if (error.response?.status === 401 && refreshToken) {
      try {
        const res = await api.post('/api/auth/refresh', { refresh_token: refreshToken })
        accessToken = res.data.access_token
        localStorage.setItem('bolus_auth', JSON.stringify({ access: accessToken, refresh: refreshToken, user: JSON.parse(localStorage.getItem('bolus_auth')).user }))
        error.config.headers = { ...error.config.headers, Authorization: `Bearer ${accessToken}` }
        return api.request(error.config)
      } catch (err) {
        // failed refresh
      }
    }
    return Promise.reject(error)
  }
)
