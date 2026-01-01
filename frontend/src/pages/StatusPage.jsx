import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { fetchHealth, fetchAutosens, getShadowLogs, getSuggestions, getAnalysisSummary } from '../lib/api';
import { navigate } from '../modules/core/router';

export default function StatusPage() {
    const [loading, setLoading] = useState(true);
    const [health, setHealth] = useState(null);
    const [autosens, setAutosens] = useState(null);
    const [logs, setLogs] = useState([]);
    const [suggestions, setSuggestions] = useState([]);
    const [analysis, setAnalysis] = useState(null);

    const refresh = async () => {
        setLoading(true);
        try {
            // Parallel fetches
            const [h, a, l, s, an] = await Promise.allSettled([
                fetchHealth(),
                fetchAutosens(),
                getShadowLogs(10), // Limit 10 for dashboard
                getSuggestions('pending'),
                getAnalysisSummary(14)
            ]);

            setHealth(h.status === 'fulfilled' ? h.value : { status: 'error', error: h.reason?.message });
            setAutosens(a.status === 'fulfilled' ? a.value : null);
            setLogs(l.status === 'fulfilled' ? l.value : []);
            setSuggestions(s.status === 'fulfilled' ? s.value : []);
            setAnalysis(an.status === 'fulfilled' ? an.value : null);

        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        refresh();
    }, []);

    const StatusDot = ({ status }) => (
        <span style={{
            display: 'inline-block',
            width: '10px', height: '10px',
            borderRadius: '50%',
            background: status === 'ok' ? '#10b981' : (status === 'warning' ? '#f59e0b' : '#ef4444'),
            marginRight: '8px'
        }}></span>
    );

    return (
        <>
            <Header title="Estado del Sistema" showBack={true} />
            <main className="page" style={{ paddingBottom: '80px' }}>

                {/* BACKEND HEALTH */}
                <Card title="Conectividad">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div>
                            <StatusDot status={health?.status === 'ok' ? 'ok' : 'error'} />
                            <span style={{ fontWeight: 600 }}>Backend API</span>
                        </div>
                        <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                            {health?.version ? `v${health.version}` : 'Desconectado'}
                        </div>
                    </div>
                </Card>

                {/* AUTOSENS CARD */}
                <Card title="Autosens (Sensibilidad)">
                    {autosens ? (
                        <div>
                            <div style={{ fontSize: '2rem', fontWeight: 800, color: '#3b82f6', marginBottom: '0.5rem' }}>
                                {autosens.ratio?.toFixed(2)}x
                            </div>
                            <div style={{ fontSize: '0.9rem', color: '#475569', marginBottom: '1rem' }}>
                                Factor de ajuste actual. <br />
                                <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
                                    (1.0 = Normal, &gt;1.0 = Resistente, &lt;1.0 = Sensible)
                                </span>
                            </div>
                            {autosens.reason && (
                                <div style={{ background: '#eff6ff', padding: '0.8rem', borderRadius: '8px', fontSize: '0.85rem', color: '#1e3a8a' }}>
                                    📝 {autosens.reason}
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="text-muted">Cargando o Inactivo...</div>
                    )}
                </Card>

                {/* PATTERNS & SUGGESTIONS */}
                <Card title="Inteligencia">
                    <div className="stack" style={{ gap: '1rem' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '0.5rem', borderBottom: '1px solid #f1f5f9' }}>
                            <div>
                                <div style={{ fontWeight: 600 }}>Patrones</div>
                                <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Análisis de 14 días</div>
                            </div>
                            <Button variant="ghost" onClick={() => navigate('#/patterns')}>
                                {analysis?.patterns_found?.length || 0} Detectados →
                            </Button>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                                <div style={{ fontWeight: 600 }}>Sugerencias</div>
                                <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Cambios propuestos</div>
                            </div>
                            <Button variant="ghost" onClick={() => navigate('#/suggestions')}>
                                {suggestions.length} Pendientes →
                            </Button>
                        </div>
                    </div>
                </Card>

                {/* SHADOW LABS / LEARNING */}
                <Card title="Aprendizaje (Shadow Labs)">
                    <div style={{ marginBottom: '1rem' }}>
                        <div style={{ fontSize: '0.9rem', color: '#64748b' }}>
                            Historial de aprendizaje y feedback reciente.
                        </div>
                    </div>

                    {logs.length === 0 ? (
                        <div className="text-muted text-center p-4" style={{ fontSize: '0.9rem' }}>
                            Sin datos recientes. Usa el sistema para generar aprendizaje.
                        </div>
                    ) : (
                        <div className="stack" style={{ gap: '0.8rem' }}>
                            {logs.map(log => (
                                <div key={log.id} style={{
                                    background: '#f8fafc',
                                    border: '1px solid #e2e8f0',
                                    borderRadius: '8px',
                                    padding: '0.8rem',
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center'
                                }}>
                                    <div>
                                        <div style={{ fontWeight: 700, fontSize: '0.9rem', color: '#334155' }}>
                                            {log.meal_name || 'Evento'}
                                        </div>
                                        <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                                            {new Date(log.created_at).toLocaleString()}
                                        </div>
                                        <div style={{ fontSize: '0.8rem', color: '#475569', marginTop: '4px' }}>
                                            {log.suggestion}
                                        </div>
                                    </div>
                                    <div style={{ textAlign: 'right' }}>
                                        {log.is_better || log.status === 'success' ? (
                                            <span style={{ color: '#10b981', fontWeight: 700 }}>✅ OK</span>
                                        ) : (
                                            <span style={{ color: '#f59e0b', fontWeight: 700 }}>⚠️</span>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                </Card>

                <div style={{ textAlign: 'center', marginTop: '1rem' }}>
                    <Button variant="ghost" onClick={refresh}>🔄 Actualizar Estado</Button>
                </div>

            </main>
            <BottomNav activeTab="home" />
        </>
    );
}
