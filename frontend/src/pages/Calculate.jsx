import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { api } from '../api/client'
import { authHeaders } from '../hooks/useAuth'

export default function Calculate() {
  const [carbs, setCarbs] = useState(50)
  const [highFat, setHighFat] = useState(false)
  const [exerciseType, setExerciseType] = useState('none')
  const [exerciseTiming, setExerciseTiming] = useState('within90')
  const [bg, setBg] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    api.get('/glucose/current', { headers: authHeaders() }).then((res) => setBg(res.data.glucose))
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    const res = await api.post(
      '/bolus/recommend',
      {
        carbs: Number(carbs),
        high_fat: highFat,
        exercise_type: exerciseType,
        exercise_timing: exerciseTiming,
        glucose: Number(bg)
      },
      { headers: authHeaders() }
    )
    setResult(res.data)
  }

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <form onSubmit={submit} className="glass-card p-6 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm text-slate-300">Carbs (g)</label>
          <input value={carbs} onChange={(e) => setCarbs(e.target.value)} className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2" />
          <label className="text-sm text-slate-300">Glucosa</label>
          <input value={bg} onChange={(e) => setBg(e.target.value)} className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2" />
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={highFat} onChange={(e) => setHighFat(e.target.checked)} /> Comida alta en grasa</label>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-xs uppercase text-slate-400">Ejercicio</p>
            <select value={exerciseType} onChange={(e) => setExerciseType(e.target.value)} className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2">
              <option value="none">Ninguno</option>
              <option value="walking">Caminata</option>
              <option value="cardio">Cardio</option>
              <option value="running">Running</option>
              <option value="gym">Gimnasio</option>
              <option value="other">Otro</option>
            </select>
          </div>
          <div>
            <p className="text-xs uppercase text-slate-400">Timing</p>
            <select value={exerciseTiming} onChange={(e) => setExerciseTiming(e.target.value)} className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2">
              <option value="within90">Dentro de 90'</option>
              <option value="after90">Después de 90'</option>
            </select>
          </div>
        </div>
        <button className="w-full py-3 rounded-xl bg-gradient-to-r from-primary to-secondary text-slate-900 font-semibold">Calcular</button>
      </form>
      <motion.div className="glass-card p-6">
        {!result && <p className="text-slate-400">Resultados aparecerán aquí</p>}
        {result && (
          <div className="space-y-2">
            <p className="text-3xl font-bold">{result.upfront} U upfront</p>
            <p className="text-xl">{result.later} U luego</p>
            <p className="text-sm text-slate-400">Retraso: {result.delay_min} min</p>
            <ul className="list-disc ml-4 text-sm text-slate-300">
              {result.explanation.map((item, idx) => (
                <li key={idx}>{item}</li>
              ))}
            </ul>
          </div>
        )}
      </motion.div>
    </div>
  )
}
