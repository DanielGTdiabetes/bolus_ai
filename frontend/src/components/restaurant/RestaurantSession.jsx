import React, { useEffect, useMemo, useState } from 'react';
import { Card, Button } from '../ui/Atoms';
import {
  analyzeMenuImage,
  analyzePlateImage,
  calculateRestaurantAdjustment,
  addPlateToSession,
  finalizeRestaurantSession
} from '../../lib/restaurantApi';
import { saveTreatment, getCurrentGlucose, getLocalNsConfig } from '../../lib/api';
import { formatTrend } from '../../modules/core/utils';
import { RESTAURANT_CORRECTION_CARBS } from '../../lib/featureFlags';
const SESSION_KEY = 'restaurant_session_v1';
const SESSION_TTL_MS = 6 * 60 * 60 * 1000; // 6h

const defaultSession = () => ({
  sessionId: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
  createdAt: new Date().toISOString(),
  expectedCarbs: null,
  expectedConfidence: null,
  expectedItems: [],
  menuWarnings: [],
  reasoning_short: '',
  plates: [],
  actualCarbsTotal: 0,
  actualFatTotal: 0,
  actualProteinTotal: 0,
  deltaCarbs: null,
  suggestedAction: null,
  finalizedAt: null,
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

function persistSession(session, totals) {
  if (!session) return;
  localStorage.setItem(SESSION_KEY, JSON.stringify({ ...session, ...totals }));
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

export function RestaurantSession() {
  const [session, setSession] = useState(() => loadSession() || defaultSession());
  const [menuLoading, setMenuLoading] = useState(false);
  const [plateLoading, setPlateLoading] = useState(false);
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState('');
  const [statusMessage, setStatusMessage] = useState('');

  // Live Monitor
  const [bgData, setBgData] = useState(null);

  const actualCarbsTotal = useMemo(
    () => session.plates.reduce((sum, plate) => sum + (plate.carbs || 0), 0),
    [session.plates]
  );
  const actualFatTotal = useMemo(
    () => session.plates.reduce((sum, plate) => sum + (plate.fat || 0), 0),
    [session.plates]
  );
  const actualProteinTotal = useMemo(
    () => session.plates.reduce((sum, plate) => sum + (plate.protein || 0), 0),
    [session.plates]
  );

  const aggregateConfidence = useMemo(() => {
    const confidences = [];
    if (session.expectedConfidence) confidences.push(session.expectedConfidence);
    session.plates.forEach((p) => {
      if (p.confidence) confidences.push(p.confidence);
    });
    if (confidences.length === 0) return null;
    return Math.min(...confidences);
  }, [session.expectedConfidence, session.plates]);

  useEffect(() => {
    persistSession(session, { actualCarbsTotal, actualFatTotal, actualProteinTotal });
  }, [session, actualCarbsTotal, actualFatTotal, actualProteinTotal]);

  // Poll Glucose
  useEffect(() => {
    if (!session.expectedCarbs) return;
    const fetchBg = async () => {
      try {
        const config = getLocalNsConfig();
        const data = await getCurrentGlucose(config);
        setBgData(data);
      } catch (e) {
        console.warn("Monitor BG error:", e);
      }
    };
    fetchBg();
    const timer = setInterval(fetchBg, 60000);
    return () => clearInterval(timer);
  }, [session.expectedCarbs]);

  const resetSession = () => {
    const fresh = defaultSession();
    setSession(fresh);
    setError('');
    setStatusMessage('');
    setBgData(null);
  };

  const handleMenuCapture = async (file) => {
    setError('');
    setStatusMessage('');
    setMenuLoading(true);
    try {
      const result = await analyzeMenuImage(file);
      const freshSession = defaultSession();
      setSession({
        ...freshSession,
        expectedCarbs: result.expectedCarbs ?? null,
        expectedConfidence: result.confidence ?? null,
        expectedItems: result.items || [],
        reasoning_short: result.reasoning_short || '',
        menuWarnings: result.warnings || [],
      });
      setStatusMessage('Carta analizada. Estimación lista.');
    } catch (err) {
      setError(err.message);
    } finally {
      setMenuLoading(false);
    }
  };

  const handleAddPlateCapture = async (file) => {
    setError('');
    setStatusMessage('');
    if (!session.expectedCarbs) {
      setError('Primero estima los carbohidratos de la carta.');
      return;
    }
    setPlateLoading(true);
    try {
      const result = await analyzePlateImage(file);
      const plate = {
        id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`,
        carbs: result.carbs ?? 0,
        fat: result.fat ?? 0,
        protein: result.protein ?? 0,
        confidence: result.confidence ?? null,
        warnings: result.warnings || [],
        reasoning_short: result.reasoning_short || '',
        capturedAt: new Date().toISOString(),
      };

      // Update Backend Persistence
      try {
        if (session.sessionId) {
          await addPlateToSession(session.sessionId, {
            carbs: plate.carbs,
            fat: plate.fat,
            protein: plate.protein,
            confidence: plate.confidence,
            warnings: plate.warnings,
            reasoning_short: plate.reasoning_short,
            name: "Plato escaneado"
          });
        }
      } catch (err) {
        console.warn("Fallo persistencia backend (addPlate):", err);
        // Non-blocking, continue local
      }

      setSession((prev) => ({
        ...prev,
        plates: [...prev.plates, plate],
        deltaCarbs: null,
        suggestedAction: null,
        finalizedAt: null,
        menuWarnings: Array.from(new Set([...(prev.menuWarnings || []), ...(result.warnings || [])])),
      }));
      setStatusMessage('Plato añadido a la sesión.');
    } catch (err) {
      setError(err.message);
    } finally {
      setPlateLoading(false);
    }
  };

  const handleFinishSession = async () => {
    setError('');
    setStatusMessage('');
    if (!session.expectedCarbs) {
      setError('Necesitas estimar la carta primero.');
      return;
    }
    setClosing(true);
    try {
      const adjustment = await calculateRestaurantAdjustment({
        expectedCarbs: session.expectedCarbs,
        actualCarbs: actualCarbsTotal,
        confidence: aggregateConfidence,
      });

      // Update Backend Persistence
      try {
        if (session.sessionId) {
          await finalizeRestaurantSession(session.sessionId, {
            outcomeScore: adjustment.deltaCarbs > 10 ? 1 : (adjustment.deltaCarbs < -10 ? -1 : 0) // Simple heuristic
          });
        }
      } catch (err) {
        console.warn("Fallo persistencia backend (finalize):", err);
      }

      setSession((prev) => ({
        ...prev,
        actualCarbsTotal,
        deltaCarbs: adjustment.deltaCarbs,
        suggestedAction: adjustment.suggestedAction,
        finalizedAt: new Date().toISOString(),
        menuWarnings: Array.from(
          new Set([...(prev.menuWarnings || []), ...(adjustment.warnings || [])])
        ),
      }));
      setStatusMessage('Resumen listo. Revisa y confirma antes de aplicar.');
    } catch (err) {
      setError(err.message || 'No se pudo calcular el ajuste.');
    } finally {
      setClosing(false);
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
      notes: `Sesión restaurante delta=${session.deltaCarbs}g (${action.type})`,
      enteredBy: 'BolusAI',
    };

    if (action.type === 'ADD_INSULIN') {
      payload.insulin = action.units;
    } else if (action.type === 'EAT_CARBS') {
      payload.carbs = action.carbsGrams || RESTAURANT_CORRECTION_CARBS;
    }

    try {
      await saveTreatment(payload);
      setStatusMessage('Acción aplicada y registrada.');
    } catch (err) {
      setError(err.message || 'No se pudo registrar la acción');
    }
  };

  const handleSendToBolus = () => {
    if (!session.expectedCarbs) return;
    state.tempCarbs = session.expectedCarbs;
    state.tempReason = 'restaurant_menu';
    navigate('#/bolus');
  };

  const sessionStateLabel = session.expectedCarbs ? 'Sesión activa' : 'Sin sesión';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {error && (
        <div
          style={{
            background: '#fef2f2',
            color: '#991b1b',
            padding: '0.75rem',
            borderRadius: '8px',
          }}
        >
          {error}
        </div>
      )}
      {statusMessage && (
        <div
          style={{
            background: '#ecfeff',
            color: '#155e75',
            padding: '0.75rem',
            borderRadius: '8px',
          }}
        >
          {statusMessage}
        </div>
      )}

      <div style={{ color: '#475569', fontWeight: 600 }}>Estado: {sessionStateLabel}</div>

      <Card>
        <h2 style={{ marginTop: 0 }}>Carta</h2>
        <p style={{ color: '#475569' }}>
          Escanea la carta o menú para estimar carbohidratos de forma conservadora.
        </p>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <CameraCapture
            buttonLabel={menuLoading ? 'Analizando...' : 'Escanear carta'}
            onCapture={handleMenuCapture}
            disabled={menuLoading}
            variant="primary"
          />
          <Button
            type="button"
            style={{ background: '#e2e8f0', color: '#0f172a' }}
            onClick={resetSession}
          >
            Reiniciar
          </Button>
        </div>

        {session.expectedCarbs && (
          <div
            style={{
              marginTop: '1rem',
              padding: '0.75rem',
              background: '#f8fafc',
              borderRadius: '8px',
              border: '1px solid #e2e8f0',
            }}
          >
            <InfoRow label="Carbohidratos esperados" value={`${session.expectedCarbs} g`} />
            {session.expectedConfidence && (
              <InfoRow label="Confianza" value={`${Math.round(session.expectedConfidence * 100)}%`} />
            )}
            {session.expectedItems?.length > 0 && (
              <div style={{ marginTop: '0.5rem' }}>
                <strong style={{ color: '#0f172a' }}>Platos detectados:</strong>
                <ul style={{ marginTop: '0.25rem', paddingLeft: '1.1rem', color: '#475569' }}>
                  {session.expectedItems.map((item, idx) => (
                    <li key={idx}>{item.name} ({item.carbs_g ?? '?'}g)</li>
                  ))}
                </ul>
              </div>
            )}
            {session.reasoning_short && (
              <p style={{ color: '#475569', marginTop: '0.5rem' }}>{session.reasoning_short}</p>
            )}
            <WarningList warnings={session.menuWarnings} />
            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
              <Button type="button" onClick={handleSendToBolus}>
                Calcular bolo inicial
              </Button>
            </div>
          </div>
        )}
      </Card>

      {session.expectedCarbs && (
        <Card>
          <h2 style={{ marginTop: 0 }}>Sesión activa</h2>
          <p style={{ color: '#475569' }}>
            Añade fotos de cada plato. Sumaremos los carbohidratos detectados y te daremos un ajuste seguro al terminar.
          </p>

          <div style={{ display: 'grid', gap: '0.5rem', marginTop: '0.5rem' }}>
            {bgData && (
              <div style={{
                background: '#f1f5f9', padding: '0.5rem', borderRadius: '6px', textAlign: 'center',
                border: '1px solid #e2e8f0', marginBottom: '0.5rem'
              }}>
                <div style={{ fontSize: '0.9rem', color: '#64748b' }}>Glucosa Actual</div>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#0f172a' }}>
                  {bgData.bg_mgdl} <span style={{ fontSize: '1rem' }}>{formatTrend(bgData.trend)}</span>
                </div>
              </div>
            )}

            <InfoRow label="Total planificado" value={`${session.expectedCarbs} g`} />
            <InfoRow label="Total actual (HC)" value={`${actualCarbsTotal} g`} />
            <InfoRow label="Total G/P" value={`${actualFatTotal}g / ${actualProteinTotal}g`} />
            <InfoRow
              label="Delta"
              value={`${(actualCarbsTotal - (session.expectedCarbs || 0)).toFixed(1)} g`}
            />
          </div>

          <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <CameraCapture
              buttonLabel={plateLoading ? 'Analizando...' : 'Añadir plato'}
              onCapture={handleAddPlateCapture}
              disabled={plateLoading}
              variant="primary"
            />
            <Button type="button" onClick={handleFinishSession} disabled={closing}>
              {closing ? 'Calculando...' : 'Terminar'}
            </Button>
          </div>

          <div style={{ marginTop: '1rem', borderTop: '1px solid #e2e8f0', paddingTop: '0.75rem' }}>
            <strong style={{ color: '#0f172a' }}>Platos</strong>
            {session.plates.length === 0 && (
              <p style={{ color: '#94a3b8' }}>Aún no hay fotos de platos.</p>
            )}
            {session.plates.map((plate) => (
              <div
                key={plate.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '0.5rem 0',
                  borderBottom: '1px solid #e2e8f0',
                }}
              >
                <div>
                  <div style={{ fontWeight: 700 }}>
                    {plate.carbs ?? '?'}g <span style={{ fontSize: '0.8em', color: '#666' }}>({plate.fat | 0}g G, {plate.protein | 0}g P)</span>
                  </div>
                  <div style={{ color: '#475569', fontSize: '0.85rem' }}>
                    {new Date(plate.capturedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                  {plate.reasoning_short && (
                    <div style={{ color: '#64748b', fontSize: '0.85rem', marginTop: '0.25rem' }}>
                      {plate.reasoning_short}
                    </div>
                  )}
                  <WarningList warnings={plate.warnings} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {session.expectedCarbs && (
        <Card>
          <h2 style={{ marginTop: 0 }}>Cierre</h2>
          <p style={{ color: '#475569' }}>
            Al terminar la comida, revisa el balance y aplica el ajuste si procede.
          </p>
          <div style={{ display: 'grid', gap: '0.35rem', marginTop: '0.5rem' }}>
            <InfoRow label="Planificado" value={`${session.expectedCarbs ?? 0} g`} />
            <InfoRow label="Consumido" value={`${actualCarbsTotal} g`} />
            <InfoRow label="Delta" value={`${session.deltaCarbs ?? (actualCarbsTotal - (session.expectedCarbs || 0)).toFixed(1)} g`} />
          </div>

          {session.suggestedAction && (
            <div
              style={{
                marginTop: '0.75rem',
                padding: '0.75rem',
                background: '#f8fafc',
                borderRadius: '8px',
                border: '1px solid #e2e8f0',
              }}
            >
              <div style={{ fontWeight: 700, color: '#0f172a' }}>
                Acción sugerida: {session.suggestedAction.type}
              </div>
              {session.suggestedAction.type === 'ADD_INSULIN' && (
                <div style={{ color: '#334155', marginTop: '0.25rem' }}>
                  Micro-bolo recomendado: {session.suggestedAction.units} U
                </div>
              )}
              {session.suggestedAction.type === 'EAT_CARBS' && (
                <div style={{ color: '#334155', marginTop: '0.25rem' }}>
                  Toma {session.suggestedAction.carbsGrams || RESTAURANT_CORRECTION_CARBS} g de HC.
                </div>
              )}
              <WarningList warnings={session.menuWarnings} />
              <Button
                type="button"
                onClick={handleApplyAction}
                disabled={session.suggestedAction.type === 'NO_ACTION'}
                style={{ marginTop: '0.5rem' }}
              >
                Aplicar ajuste
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

