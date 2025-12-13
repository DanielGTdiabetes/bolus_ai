import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import { authHeaders } from '../hooks/useAuth'

export default function Changes() {
  const [changes, setChanges] = useState([])

  useEffect(() => {
    api.get('/changes', { headers: authHeaders() }).then((res) => setChanges(res.data))
  }, [])

  const undo = async (id) => {
    try {
      await api.post(`/changes/${id}/undo`, {}, { headers: authHeaders() })
    } catch (err) {
      alert('Aún no implementado')
    }
  }

  return (
    <div className="space-y-3">
      {changes.map((c) => (
        <div key={c.id} className="glass-card p-4 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold">{c.message}</p>
            <p className="text-xs text-slate-400">{c.user}</p>
          </div>
          <button onClick={() => undo(c.id)} className="px-3 py-2 rounded-xl bg-secondary text-white text-sm">Deshacer</button>
        </div>
      ))}
      {changes.length === 0 && <p className="text-slate-400">Sin cambios aún</p>}
    </div>
  )
}
