import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import { authHeaders, useAuth } from '../hooks/useAuth'

const Section = ({ title, children }) => (
  <div className="glass-card p-4 space-y-3">
    <div className="flex items-center justify-between">
      <h3 className="text-lg font-semibold">{title}</h3>
    </div>
    {children}
  </div>
)

export default function SettingsPage() {
  const { user } = useAuth()
  const [settings, setSettings] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    api.get('/settings', { headers: authHeaders() }).then((res) => setSettings(res.data.settings))
  }, [])

  const updateField = (path, value) => {
    setSettings((prev) => {
      const clone = structuredClone(prev)
      let ref = clone
      const keys = path.split('.')
      keys.slice(0, -1).forEach((k) => (ref = ref[k]))
      ref[keys[keys.length - 1]] = value
      return clone
    })
  }

  const save = async () => {
    await api.put('/settings', settings, { headers: authHeaders() })
    setMessage('Guardado')
  }

  if (!settings) return <p>Cargando...</p>
  const readOnly = user?.role !== 'admin'

  return (
    <div className="space-y-3">
      <Section title="Objetivos y unidades">
        <div className="grid grid-cols-3 gap-2 text-sm">
          {['low','mid','high'].map((k) => (
            <input key={k} type="number" value={settings.targets[k]} onChange={(e) => updateField(`targets.${k}`, Number(e.target.value))} readOnly={readOnly} className="bg-slate-900 rounded-xl px-3 py-2" />
          ))}
        </div>
      </Section>
      <Section title="CF/CR por comida">
        <div className="grid grid-cols-3 gap-2 text-sm">
          {['breakfast','lunch','dinner'].map((meal) => (
            <div key={meal} className="space-y-1">
              <p className="text-xs uppercase text-slate-400">{meal}</p>
              <input value={settings.cf[meal]} onChange={(e) => updateField(`cf.${meal}`, Number(e.target.value))} readOnly={readOnly} className="w-full bg-slate-900 rounded-xl px-3 py-2" />
              <input value={settings.cr[meal]} onChange={(e) => updateField(`cr.${meal}`, Number(e.target.value))} readOnly={readOnly} className="w-full bg-slate-900 rounded-xl px-3 py-2" />
            </div>
          ))}
        </div>
      </Section>
      <Section title="IOB y límites">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <input value={settings.iob.dia_hours} onChange={(e) => updateField('iob.dia_hours', Number(e.target.value))} readOnly={readOnly} className="bg-slate-900 rounded-xl px-3 py-2" />
          <select value={settings.iob.curve} onChange={(e) => updateField('iob.curve', e.target.value)} disabled={readOnly} className="bg-slate-900 rounded-xl px-3 py-2">
            <option value="walsh">Walsh</option>
            <option value="bilinear">Bilinear</option>
          </select>
          <input value={settings.max_bolus_u} onChange={(e) => updateField('max_bolus_u', Number(e.target.value))} readOnly={readOnly} className="bg-slate-900 rounded-xl px-3 py-2" />
          <input value={settings.max_correction_u} onChange={(e) => updateField('max_correction_u', Number(e.target.value))} readOnly={readOnly} className="bg-slate-900 rounded-xl px-3 py-2" />
        </div>
      </Section>
      <Section title="Aprendizaje">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <select value={settings.learning.mode} onChange={(e) => updateField('learning.mode', e.target.value)} disabled={readOnly} className="bg-slate-900 rounded-xl px-3 py-2">
            <option value="B">Modo B</option>
          </select>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={settings.learning.cr_on} onChange={(e) => updateField('learning.cr_on', e.target.checked)} disabled={readOnly} /> CR ON</label>
          <input value={settings.learning.step_pct} onChange={(e) => updateField('learning.step_pct', Number(e.target.value))} readOnly={readOnly} className="bg-slate-900 rounded-xl px-3 py-2" />
          <input value={settings.learning.weekly_cap_pct} onChange={(e) => updateField('learning.weekly_cap_pct', Number(e.target.value))} readOnly={readOnly} className="bg-slate-900 rounded-xl px-3 py-2" />
        </div>
      </Section>
      <Section title="Ratios adaptativos">
        <p className="text-sm text-slate-400">Configura grasa y ejercicio</p>
      </Section>
      {readOnly ? <p className="text-sm text-slate-400">Vista solo lectura</p> : <button onClick={save} className="px-4 py-2 bg-primary text-slate-900 rounded-xl">Guardar</button>}
      {message && <p className="text-sm text-primary">{message}</p>}
    </div>
  )
}
