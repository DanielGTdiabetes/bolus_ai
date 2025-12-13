import React, { useState } from 'react'
import { motion } from 'framer-motion'
import { useAuth } from '../hooks/useAuth'

export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    try {
      await login(username, password)
      setError('')
    } catch (err) {
      setError('Credenciales inválidas')
    }
  }

  return (
    <div className="flex items-center justify-center py-20">
      <motion.form onSubmit={submit} className="glass-card p-8 w-full max-w-md space-y-4">
        <div>
          <h1 className="text-2xl font-bold">Accede</h1>
          <p className="text-sm text-slate-400">Usuario y contraseña para continuar</p>
        </div>
        <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Usuario" className="w-full px-4 py-3 rounded-xl bg-slate-900 border border-slate-800" />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Contraseña" className="w-full px-4 py-3 rounded-xl bg-slate-900 border border-slate-800" />
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <button className="w-full py-3 rounded-xl bg-gradient-to-r from-primary to-secondary text-slate-900 font-semibold">Entrar</button>
        <label className="text-xs flex items-center gap-2 text-slate-400"><input type="checkbox" defaultChecked className="accent-primary" /> Remember me</label>
      </motion.form>
    </div>
  )
}
