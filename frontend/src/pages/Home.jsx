import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '../api/client'
import { authHeaders } from '../hooks/useAuth'

export default function Home() {
  const [glucose, setGlucose] = useState(null)

  useEffect(() => {
    api.get('/glucose/current', { headers: authHeaders() }).then((res) => setGlucose(res.data))
  }, [])

  return (
    <div className="grid md:grid-cols-3 gap-4">
      <motion.div whileHover={{ y: -4 }} className="glass-card p-6 col-span-2">
        <p className="text-sm text-slate-400">Glucosa actual</p>
        <p className="text-5xl font-bold mt-2">{glucose ? glucose.glucose : '--'}<span className="text-lg ml-2">mg/dL</span></p>
        <p className="text-sm opacity-70">Trend: {glucose?.trend || '...'}</p>
      </motion.div>
      <motion.div whileHover={{ y: -4 }} className="glass-card p-6">
        <p className="text-sm text-slate-400">IOB</p>
        <p className="text-4xl font-semibold">1.2 U</p>
        <p className="text-xs opacity-70">Estimado</p>
      </motion.div>
      <motion.div whileHover={{ y: -4 }} className="glass-card p-6 md:col-span-3">
        <p className="text-sm text-slate-400">Último cálculo</p>
        <div className="flex flex-wrap gap-4 mt-3">
          <div className="px-4 py-3 rounded-xl bg-primary/10 text-primary font-semibold">3.5 U upfront</div>
          <div className="px-4 py-3 rounded-xl bg-secondary/10 text-secondary font-semibold">1.2 U later</div>
        </div>
      </motion.div>
    </div>
  )
}
