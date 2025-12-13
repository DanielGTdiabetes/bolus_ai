import React, { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import Home from './pages/Home'
import Login from './pages/Login'
import SettingsPage from './pages/Settings'
import Calculate from './pages/Calculate'
import Changes from './pages/Changes'
import { useAuth } from './hooks/useAuth'

const tabs = [
  { id: 'home', label: 'Inicio' },
  { id: 'calculate', label: 'Calcular' },
  { id: 'settings', label: 'Ajustes' },
  { id: 'changes', label: 'Cambios' }
]

export default function App() {
  const { user, logout } = useAuth()
  const [tab, setTab] = useState('home')
  const [theme, setTheme] = useState('dark')

  const currentPage = useMemo(() => {
    if (!user) return <Login />
    switch (tab) {
      case 'calculate':
        return <Calculate />
      case 'settings':
        return <SettingsPage />
      case 'changes':
        return <Changes />
      default:
        return <Home />
    }
  }, [tab, user])

  return (
    <div className={`${theme} min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-slate-100`}>
      <div className="max-w-6xl mx-auto px-4 pb-24 md:pb-8">
        <header className="flex items-center justify-between py-6">
          <div>
            <p className="text-lg font-semibold text-primary">Bolus AI</p>
            <p className="text-xs opacity-60">Soporte de decisión seguro</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="px-3 py-2 rounded-full glass-card text-sm"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? 'Light' : 'Dark'}
            </button>
            {user && (
              <button className="px-3 py-2 rounded-full glass-card text-sm" onClick={logout}>
                Salir
              </button>
            )}
          </div>
        </header>
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
          {currentPage}
        </motion.div>
      </div>

      {user && (
        <nav className="fixed bottom-0 inset-x-0 md:static md:mt-8 bg-slate-900/70 backdrop-blur-lg border-t border-slate-800 md:border md:rounded-2xl md:max-w-6xl md:mx-auto">
          <div className="flex md:justify-center">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex-1 md:flex-none md:px-6 py-3 text-sm font-semibold ${tab === t.id ? 'text-primary' : 'text-slate-400'}`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </nav>
      )}
    </div>
  )
}
