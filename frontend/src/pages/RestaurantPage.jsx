import React, { useEffect, useMemo, useState } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { analyzeMenuImage, comparePlateImage } from '../lib/restaurantApi';
import { saveTreatment } from '../lib/api';
import { RESTAURANT_CORRECTION_CARBS } from '../lib/featureFlags';

const SESSION_KEY = 'restaurant_session_v1';
const SESSION_TTL_MS = 6 * 60 * 60 * 1000; // 6h

const defaultSession = () => ({
  sessionId: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
  createdAt: new Date().toISOString(),
  expectedCarbs: null,
  items: [],
  reasoning_short: '',
  warnings: [],
  preBolus: { applied: false, units: 0, percent: 75 },
  actualCarbs: null,
  deltaCarbs: null,
  suggestedAction: null,
});

function loadSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed.createdAt) return null;
    const age = Date.now() - new Date(parsed.createdAt).getTime();
    if (age > SESSION_TTL_MS) {
      localStorage.removeItem(SESSION_KEY);
      return null;
    }
    return parsed;
  } catch (e) {
    return null;
  }
}

function persistSession(session) {
  if (!session) return;
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

function deriveStep(session, currentStep) {
  if (!session || !session.expectedCarbs) return 'menu';
  if (session.actualCarbs !== null) return 'settlement';
  if (currentStep === 'plate') return 'plate';
  if (currentStep === 'settlement') return 'settlement';
  return 'waiting';
}

function WarningList({ warnings }) {
  if (!warnings || warnings.length === 0) return null;
  return (
    <ul style={{ marginTop: '0.5rem', color: '#b45309', paddingLeft: '1.2rem' }}>
      {warnings.map((w, idx) => (
        <li key={idx}>{w}</li>
      ))}
    </ul>
  );
}

function InfoRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.35rem', fontSize: '0.95rem' }}>
      <span style={{ color: '#475569', fontWeight: 600 }}>{label}</span>
      <span style={{ color: '#0f172a', fontWeight: 700 }}>{value}</span>
    </div>
  );
}

export default function RestaurantPage() {
  const [session, setSession] = useState(() => loadSession() || defaultSession());
  const [step, setStep] = useState(() => deriveStep(loadSession(), 'menu'));
  const [menuImage, setMenuImage] = useState(null);
  const [plateImage, setPlateImage] = useState(null);
  const [menuLoading, setMenuLoading] = useState(false);
  const [plateLoading, setPlateLoading] = useState(false);
  const [error, setError] = useState('');
  const [preBolusPlan, setPreBolusPlan] = useState({ totalUnits: '', percent: 75 });
  const [statusMessage, setStatusMessage] = useState('');
  const stepLabel = useMemo(() => ({
    menu: 'Carta',
    waiting: 'Espera',
    plate: 'Plato',
    settlement: 'Liquidación',
  }[step] || 'Carta'), [step]);

  useEffect(() => {
    setStep((prev) => deriveStep(session, prev));
    persistSession(session);
  }, [session]);

  const resetSession = () => {
    const fresh = defaultSession();
    setSession(fresh);
    setMenuImage(null);
    setPlateImage(null);
    setError('');
    setStatusMessage('');
    setStep('menu');
  };

  const handleMenuUpload = async (e) => {
    e.preventDefault();
    setError('');
    setStatusMessage('');
    if (!menuImage) {
      setError('Sube una foto de la carta para continuar.');
      return;
    }
    setMenuLoading(true);
    try {
      const result = await analyzeMenuImage(menuImage);
      const updated = {
        ...session,
        expectedCarbs: result.expectedCarbs ?? null,
        items: result.items || [],
        reasoning_short: result.reasoning_short || '',
        warnings: Array.from(new Set([...(session.warnings || []), ...(result.warnings || [])])),
        suggestedAction: null,
        actualCarbs: null,
        deltaCarbs: null,
      };
      setSession(updated);
      setStatusMessage('Carta analizada. Estimación lista.');
      setStep('waiting');
    } catch (err) {
      setError(err.message);
    } finally {
      setMenuLoading(false);
    }
  };

  const handlePreBolusApply = async () => {
    setError('');
    setStatusMessage('');
    if (!session.expectedCarbs) {
      setError('Primero estima los carbohidratos de la carta.');
      return;
    }
    const totalUnits = parseFloat(preBolusPlan.totalUnits);
    if (!totalUnits || Number.isNaN(totalUnits)) {
      setError('Introduce las unidades planificadas.');
      return;
    }
    const percent = Math.min(80, Math.max(70, preBolusPlan.percent || 75));
    const units = parseFloat((totalUnits * (percent / 100)).toFixed(2));

    try {
      await saveTreatment({
        insulin: units,
        carbs: 0,
        created_at: new Date().toISOString(),
        notes: `Restaurant pre-bolo ${percent}% (expected ${session.expectedCarbs}g)`,
        enteredBy: 'BolusAI',
      });
      setSession({
        ...session,
        preBolus: { applied: true, units, percent },
      });
      setStatusMessage('Pre-bolo aplicado y registrado.');
    } catch (err) {
      setError(err.message || 'No se pudo aplicar el pre-bolo');
    }
  };

  const handlePlateUpload = async (e) => {
    e.preventDefault();
    setError('');
    setStatusMessage('');
    if (!session.expectedCarbs) {
      setError('Primero necesitas la estimación de la carta.');
      return;
    }
    if (!plateImage) {
      setError('Sube una foto del plato real.');
      return;
    }
    setPlateLoading(true);
    try {
      const result = await comparePlateImage({ imageFile: plateImage, expectedCarbs: session.expectedCarbs });
      const updated = {
        ...session,
        actualCarbs: result.actualCarbs ?? null,
        deltaCarbs: result.deltaCarbs ?? null,
        suggestedAction: result.suggestedAction || null,
        warnings: Array.from(new Set([...(session.warnings || []), ...(result.warnings || [])])),
      };
      setSession(updated);
      setStatusMessage('Comparación lista. Revisa la sugerencia antes de aplicar.');
      setStep('settlement');
    } catch (err) {
      setError(err.message);
    } finally {
      setPlateLoading(false);
    }
  };

  const handleApplyAction = async () => {
    setError('');
    setStatusMessage('');
    const action = session.suggestedAction;
    if (!action || action.type === 'NO_ACTION') {
      setError('No hay acción sugerida.');
      return;
    }
    const confirmed = window.confirm('Confirma que deseas aplicar la acción sugerida.');
    if (!confirmed) return;

    const nowIso = new Date().toISOString();
    const payload = {
      insulin: 0,
      carbs: 0,
      created_at: nowIso,
      notes: `Restaurant action (${action.type}) delta=${session.deltaCarbs}g`,
      enteredBy: 'BolusAI',
    };

    if (action.type === 'ADD_INSULIN') {
      payload.insulin = action.units;
    } else if (action.type === 'EAT_CARBS') {
      payload.carbs = action.carbsGrams;
    }

    try {
      await saveTreatment(payload);
      setStatusMessage('Acción aplicada y registrada.');
    } catch (err) {
      setError(err.message || 'No se pudo registrar la acción');
    }
  };

  const estimatedPreBolusUnits = useMemo(() => {
    const totalUnits = parseFloat(preBolusPlan.totalUnits);
    if (!totalUnits || Number.isNaN(totalUnits)) return 0;
    return parseFloat((totalUnits * (preBolusPlan.percent / 100)).toFixed(2));
  }, [preBolusPlan]);

  return (
    <div className="page" style={{ background: '#f8fafc', minHeight: '100vh' }}>
      <Header title="Restaurante (Beta)" />
      <main style={{ padding: '1rem', paddingBottom: '5rem' }}>
        {error && (
          <div style={{ background: '#fef2f2', color: '#991b1b', padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem' }}>
            {error}
          </div>
        )}
        {statusMessage && (
          <div style={{ background: '#ecfeff', color: '#155e75', padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem' }}>
            {statusMessage}
          </div>
        )}

        <div style={{ marginBottom: '1rem', color: '#475569', fontWeight: 600 }}>
          Paso actual: {stepLabel}
        </div>

        <Card>
          <h2 style={{ marginTop: 0 }}>1) Carta</h2>
          <p style={{ color: '#475569' }}>Sube foto de la carta o menú. El sistema estimará carbohidratos de forma conservadora.</p>
          <form onSubmit={handleMenuUpload}>
            <input type="file" accept="image/*" onChange={(e) => setMenuImage(e.target.files?.[0] || null)} />
            <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
              <Button type="submit" disabled={menuLoading}>{menuLoading ? 'Analizando...' : 'Analizar carta'}</Button>
              <Button type="button" style={{ background: '#e2e8f0', color: '#0f172a' }} onClick={resetSession}>Reiniciar</Button>
            </div>
          </form>

          {session.expectedCarbs && (
            <div style={{ marginTop: '1rem', padding: '0.75rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <InfoRow label="Carbohidratos esperados" value={`${session.expectedCarbs} g`} />
              {session.items?.length > 0 && (
                <div style={{ marginTop: '0.5rem' }}>
                  <strong style={{ color: '#0f172a' }}>Platos detectados:</strong>
                  <ul style={{ marginTop: '0.25rem', paddingLeft: '1.1rem', color: '#475569' }}>
                    {session.items.map((item, idx) => (
                      <li key={idx}>{item.name} ({item.carbs_g ?? '?'}g)</li>
                    ))}
                  </ul>
                </div>
              )}
              {session.reasoning_short && <p style={{ color: '#475569', marginTop: '0.5rem' }}>{session.reasoning_short}</p>}
              <WarningList warnings={session.warnings} />
            </div>
          )}
        </Card>

        <Card>
          <h2 style={{ marginTop: 0 }}>2) Pre-bolo conservador</h2>
          <p style={{ color: '#475569' }}>Aplica solo si ya tienes la estimación de la carta. Usa 70-80% de tu bolo planificado.</p>
          <div style={{ display: 'grid', gap: '0.5rem', marginTop: '0.5rem' }}>
            <label style={{ color: '#334155' }}>
              Bolo planificado (U)
              <input
                type="number"
                min="0"
                step="0.1"
                value={preBolusPlan.totalUnits}
                onChange={(e) => setPreBolusPlan({ ...preBolusPlan, totalUnits: e.target.value })}
                style={{ width: '100%', padding: '0.4rem', marginTop: '0.25rem' }}
              />
            </label>
            <label style={{ color: '#334155' }}>
              Porcentaje (70-80%)
              <input
                type="number"
                min="70"
                max="80"
                step="1"
                value={preBolusPlan.percent}
                onChange={(e) => setPreBolusPlan({ ...preBolusPlan, percent: Number(e.target.value) })}
                style={{ width: '100%', padding: '0.4rem', marginTop: '0.25rem' }}
              />
            </label>
            <div style={{ color: '#0f172a', fontWeight: 700 }}>
              Pre-bolo sugerido: {estimatedPreBolusUnits} U
            </div>
            <Button type="button" onClick={handlePreBolusApply} disabled={!session.expectedCarbs}>
              Aplicar
            </Button>
            {session.preBolus?.applied && (
              <div style={{ color: '#16a34a', fontWeight: 600 }}>
                ✅ Pre-bolo registrado ({session.preBolus.units}U @ {session.preBolus.percent}%)
              </div>
            )}
          </div>
        </Card>

        <Card>
          <h2 style={{ marginTop: 0 }}>3) Espera y foto del plato</h2>
          <p style={{ color: '#475569' }}>Cuando llegue el plato, sube la foto para comparar con lo planificado.</p>
          <form onSubmit={handlePlateUpload}>
            <input type="file" accept="image/*" onChange={(e) => setPlateImage(e.target.files?.[0] || null)} />
            <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
              <Button type="submit" disabled={plateLoading || !session.expectedCarbs}>
                {plateLoading ? 'Comparando...' : 'Comparar plato'}
              </Button>
              <Button type="button" style={{ background: '#e2e8f0', color: '#0f172a' }} onClick={() => setStep('plate')}>Ir a paso Plato</Button>
            </div>
          </form>
        </Card>

        <Card>
          <h2 style={{ marginTop: 0 }}>4) Liquidación</h2>
          {session.actualCarbs === null ? (
            <p style={{ color: '#94a3b8' }}>Pendiente de foto del plato.</p>
          ) : (
            <div>
              <InfoRow label="Planificado" value={`${session.expectedCarbs} g`} />
              <InfoRow label="Detectado" value={`${session.actualCarbs} g`} />
              <InfoRow label="Delta" value={`${session.deltaCarbs} g`} />
              {session.suggestedAction && (
                <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                  <div style={{ fontWeight: 700, color: '#0f172a' }}>Acción sugerida: {session.suggestedAction.type}</div>
                  {session.suggestedAction.type === 'ADD_INSULIN' && (
                    <div style={{ color: '#334155', marginTop: '0.25rem' }}>Micro-bolo recomendado: {session.suggestedAction.units} U</div>
                  )}
                  {session.suggestedAction.type === 'EAT_CARBS' && (
                    <div style={{ color: '#334155', marginTop: '0.25rem' }}>Come {session.suggestedAction.carbsGrams || RESTAURANT_CORRECTION_CARBS} g de HC.</div>
                  )}
                  <WarningList warnings={session.warnings} />
                  <Button type="button" onClick={handleApplyAction} disabled={session.suggestedAction.type === 'NO_ACTION'} style={{ marginTop: '0.5rem' }}>
                    Aplicar acción
                  </Button>
                </div>
              )}
            </div>
          )}
        </Card>
      </main>
      <BottomNav />
    </div>
  );
}
