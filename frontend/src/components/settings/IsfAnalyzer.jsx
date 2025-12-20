import React, { useState } from 'react';
import { Button } from '../ui/Atoms';
import { fetchIsfAnalysis } from '../../lib/api';

const COLORS = {
    ok: '#22c55e', // green
    strong_drop: '#ef4444', // red
    weak_drop: '#f59e0b', // amber
    insufficient_data: '#94a3b8' // slate
};

const LABELS = {
    ok: 'Correcto',
    strong_drop: 'Excesivo (Baja mucho)',
    weak_drop: 'Insuficiente (Se queda corto)',
    insufficient_data: 'Faltan datos'
};

export function IsfAnalyzer() {
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [days, setDays] = useState(14);
    const [showEvents, setShowEvents] = useState(false);

    const runAnalysis = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await fetchIsfAnalysis(days);
            setResult(data);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return (
            <div style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                <p>Analizando historial de glucosa...</p>
                <p style={{ fontSize: '0.8rem' }}>Buscando correcciones limpias en los últimos {days} días.</p>
            </div>
        );
    }

    if (error) {
        return (
            <div style={{ padding: '1rem', background: '#fee2e2', color: '#b91c1c', borderRadius: '8px', marginBottom: '1rem' }}>
                <p style={{ fontWeight: 'bold', margin: '0 0 0.5rem 0' }}>Error en análisis:</p>
                <p style={{ margin: 0, fontSize: '0.9rem' }}>{error}</p>
                <Button onClick={runAnalysis} variant="secondary" style={{ marginTop: '1rem' }}>Reintentar</Button>
            </div>
        );
    }

    if (!result) {
        return (
            <div style={{ background: '#f8fafc', padding: '1rem', borderRadius: '12px', border: '1px solid #e2e8f0', marginTop: '1rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#1e293b' }}>Análisis ISF Inteligente</h3>
                    <span style={{ fontSize: '0.7rem', background: '#dbeafe', color: '#1d4ed8', padding: '2px 8px', borderRadius: '99px', fontWeight: 'bold' }}>BETA</span>
                </div>
                <p style={{ fontSize: '0.9rem', color: '#475569', marginBottom: '1rem', lineHeight: '1.4' }}>
                    Detecta si tu factor de sensibilidad (ISF) es demasiado fuerte o débil analizando cómo reacciona tu glucosa tras correcciones "limpias".
                </p>

                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1rem', fontSize: '0.9rem' }}>
                    <label style={{ fontWeight: 500, color: '#334155' }}>Analizar últimos:</label>
                    <select
                        value={days}
                        onChange={e => setDays(Number(e.target.value))}
                        style={{ padding: '0.4rem', borderRadius: '6px', border: '1px solid #cbd5e1', background: 'white' }}
                    >
                        <option value={7}>7 días</option>
                        <option value={14}>14 días</option>
                        <option value={30}>30 días (Lento)</option>
                    </select>
                </div>

                <Button onClick={runAnalysis} style={{ width: '100%', justifyContent: 'center' }}>
                    🔍 Ejecutar Análisis
                </Button>
            </div>
        );
    }

    return (
        <div className="stack" style={{ gap: '1rem', animation: 'fadeIn 0.5s ease' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Resultados ({days} días)</h3>
                <Button variant="ghost" onClick={() => setResult(null)} style={{ fontSize: '0.8rem', padding: '0.4rem' }}>Cerrar</Button>
            </div>

            <div style={{ display: 'grid', gap: '1rem' }}>
                {result.buckets.map(bucket => (
                    <BucketCard key={bucket.bucket} stat={bucket} />
                ))}
            </div>

            <div style={{ marginTop: '0.5rem' }}>
                <Button
                    variant="secondary"
                    style={{ width: '100%', fontSize: '0.9rem' }}
                    onClick={() => setShowEvents(!showEvents)}
                >
                    {showEvents ? 'Ocultar Detalles' : `Ver ${result.clean_events.length} Correcciones Limpias`}
                </Button>
            </div>

            {showEvents && (
                <div style={{ background: '#f8fafc', padding: '0.8rem', borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '0.8rem', maxHeight: '300px', overflowY: 'auto' }}>
                    {result.clean_events.length === 0 ? (
                        <p style={{ textAlign: 'center', color: '#94a3b8' }}>No se encontraron eventos limpios.</p>
                    ) : result.clean_events.map(ev => (
                        <div key={ev.id} style={{ borderBottom: '1px solid #e2e8f0', padding: '0.5rem 0', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 500 }}>
                                <span>{new Date(ev.timestamp).toLocaleString()}</span>
                                <span style={{
                                    color: (ev.bucket === 'madrugada' || ev.bucket === 'night') ? '#4f46e5' : '#0ea5e9',
                                    textTransform: 'capitalize'
                                }}>
                                    {ev.bucket}
                                </span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', color: '#475569' }}>
                                <span>{ev.correction_units}U → Δ{ev.bg_delta} mg/dL</span>
                                <span style={{ fontWeight: 'bold' }}>ISF Obs: {ev.isf_observed}</span>
                            </div>
                            <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>
                                Inicio: {ev.bg_start} → Fin: {ev.bg_end} (IOB al inicio: {ev.iob}U)
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function BucketCard({ stat }) {
    const isActionable = stat.status === 'strong_drop' || stat.status === 'weak_drop';
    const color = COLORS[stat.status] || COLORS.insufficient_data;
    const label = LABELS[stat.status] || stat.status;

    return (
        <div style={{
            background: 'white',
            borderRadius: '12px',
            border: '1px solid #f1f5f9',
            boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            position: 'relative',
            overflow: 'hidden',
            padding: '1rem'
        }}>
            <div style={{
                position: 'absolute', left: 0, top: 0, bottom: 0, width: '4px', background: color
            }}></div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem', paddingLeft: '0.5rem' }}>
                <div>
                    <h4 style={{ margin: 0, fontWeight: 700, color: '#1e293b' }}>{stat.label}</h4>
                    <p style={{ margin: 0, fontSize: '0.8rem', color: '#64748b' }}>{stat.events_count} eventos limpios</p>
                </div>
                <span
                    style={{
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        padding: '0.2rem 0.6rem',
                        borderRadius: '99px',
                        backgroundColor: `${color}15`,
                        color: color
                    }}
                >
                    {label}
                </span>
            </div>

            {stat.median_isf && (
                <div style={{ paddingLeft: '0.5rem', marginTop: '1rem', display: 'flex', alignItems: 'flex-end', gap: '1rem' }}>
                    <div>
                        <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px' }}>ISF Config</div>
                        <div style={{ fontSize: '1.2rem', fontWeight: 500, color: '#475569' }}>{stat.current_isf}</div>
                    </div>

                    <div style={{ paddingBottom: '0.4rem', color: '#cbd5e1' }}>→</div>

                    <div>
                        <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px' }}>ISF Real (Mediana)</div>
                        <div style={{ fontSize: '1.5rem', fontWeight: 800, color: color }}>{stat.median_isf}</div>
                    </div>

                    {stat.change_ratio !== 0 && (
                        <div style={{
                            paddingBottom: '0.5rem', fontSize: '0.8rem', fontWeight: 700,
                            color: stat.change_ratio > 0 ? '#ef4444' : '#f59e0b'
                        }}>
                            {stat.change_ratio > 0 ? '+' : ''}{Math.round(stat.change_ratio * 100)}%
                        </div>
                    )}
                </div>
            )}

            {isActionable && stat.suggested_isf && (
                <div style={{ marginTop: '1rem', paddingLeft: '0.5rem', paddingTop: '0.8rem', borderTop: '1px solid #f8fafc' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                        <span style={{ fontSize: '1.2rem' }}>💡</span>
                        <span style={{ fontWeight: 600, color: '#1e293b', fontSize: '0.9rem' }}>Sugerencia ({stat.confidence === 'high' ? 'Confianza Alta' : 'Confianza Media'})</span>
                    </div>
                    <p style={{ fontSize: '0.9rem', color: '#475569', margin: '0 0 0.8rem 0', lineHeight: '1.4' }}>
                        {stat.suggestion_type === 'increase'
                            ? `El ISF observado es mucho mayor (${stat.median_isf}). El actual corrige demasiado fuerte.`
                            : `El ISF observado es mucho menor (${stat.median_isf}). El actual se queda corto.`
                        }
                    </p>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f8fafc', padding: '0.6rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <span style={{ fontSize: '0.85rem', color: '#64748b' }}>Nuevo valor recomendado:</span>
                        <span style={{ fontSize: '1.1rem', fontWeight: 800, color: '#1e293b' }}>{stat.suggested_isf}</span>
                    </div>
                    <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <p style={{ margin: 0, fontSize: '0.75rem', color: '#94a3b8', fontStyle: 'italic', width: '100%' }}>
                            Ve arriba y ajusta el ISF manualmente a <b>{stat.suggested_isf}</b> si estás de acuerdo.
                        </p>
                    </div>
                </div>
            )}

            {!isActionable && stat.events_count > 0 && stat.status === 'ok' && (
                <div style={{ marginTop: '0.8rem', paddingLeft: '0.5rem', fontSize: '0.85rem', color: '#16a34a', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span>✨</span> Configuración correcta.
                </div>
            )}
        </div>
    );
}
