import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { runAnalysis, getAnalysisSummary } from '../lib/api';

export default function PatternsPage() {
    return (
        <>
            <Header title="Patrones" showBack={false} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <PatternsContent />
            </main>
            <BottomNav activeTab="patterns" />
        </>
    );
}

function PatternsContent() {
    const [days, setDays] = useState(30);
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [analyzing, setAnalyzing] = useState(false);
    const [status, setStatus] = useState(null);

    const load = async (d) => {
        setLoading(true);
        try {
            const res = await getAnalysisSummary(d);
            setData(res);
        } catch (e) {
            setStatus({ text: "Error cargando resumen: " + e.message, type: 'error' });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(days); }, [days]);

    const handleRecalc = async () => {
        setAnalyzing(true);
        setStatus({ text: "Calculando patrones... espera unos segundos.", type: 'info' });
        try {
            const res = await runAnalysis(days);
            setStatus({ text: `Análisis completado: ${res.boluses} bolos analizados.`, type: 'success' });
            await load(days);
        } catch (e) {
            setStatus({ text: "Error: " + e.message, type: 'error' });
        } finally {
            setAnalyzing(false);
        }
    };

    return (
        <Card>
            <h3 style={{ marginTop: 0 }}>Análisis Post-Bolo</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <select
                    value={days}
                    onChange={e => setDays(parseInt(e.target.value))}
                    style={{ padding: '0.5rem', borderRadius: '6px', fontSize: '1rem', border: '1px solid #cbd5e1' }}
                >
                    <option value="14">14 días</option>
                    <option value="30">30 días</option>
                    <option value="60">60 días</option>
                </select>
                <Button onClick={handleRecalc} disabled={analyzing} style={{ padding: '0.5rem 1rem', fontSize: '0.9rem' }}>
                    {analyzing ? 'Analizando...' : 'Recalcular'}
                </Button>
            </div>

            {status && (
                <div style={{
                    marginBottom: '1rem', padding: '0.5rem', borderRadius: '6px', fontSize: '0.9rem',
                    background: status.type === 'error' ? '#fee2e2' : (status.type === 'success' ? '#dcfce7' : '#f1f5f9'),
                    color: status.type === 'error' ? '#991b1b' : (status.type === 'success' ? '#166534' : '#64748b')
                }}>
                    {status.text}
                </div>
            )}

            {loading ? <div className="spinner">Cargando datos...</div> : (
                data ? <PatternResults data={data} /> : null
            )}

            {data && data.data_quality && (
                <div style={{ marginTop: '2rem', fontSize: '0.8rem', color: '#94a3b8', borderTop: '1px solid #e2e8f0', paddingTop: '1rem' }}>
                    Calidad de datos: {data.data_quality.iob_unavailable_events || 0} eventos con IOB no disponible (excluidos). Total eventos: {data.data_quality.total_events || 0}.
                </div>
            )}
        </Card>
    );
}

function PatternResults({ data }) {
    if (!data) return null;

    const meals = ["breakfast", "lunch", "dinner", "snack"];
    const mealLabels = { breakfast: "Desayuno", lunch: "Comida", dinner: "Cena", snack: "Snack" };

    return (
        <div className="fade-in">
            {/* Insights */}
            {data.insights && data.insights.length > 0 ? (
                <ul style={{ background: '#f0fdf4', padding: '1rem', borderRadius: '8px', border: '1px solid #bbf7d0', marginBottom: '1.5rem', listStylePosition: 'inside' }}>
                    {data.insights.map((i, idx) => (
                        <li key={idx} style={{ marginBottom: '0.5rem', color: '#166534' }}><strong>{i}</strong></li>
                    ))}
                </ul>
            ) : (
                <div style={{ padding: '1rem', color: '#64748b', textAlign: 'center' }}>
                    <div style={{ fontStyle: 'italic', marginBottom: '0.5rem' }}>No se detectaron patrones claros o faltan datos.</div>
                    <small>Se requieren al menos 5 eventos para cada comida. Sigue registrando tus bolos para obtener análisis.</small>
                </div>
            )}

            {/* Table */}
            <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                    <thead>
                        <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                            <th style={{ padding: '0.5rem', textAlign: 'left' }}>Comida</th>
                            <th style={{ padding: '0.5rem', textAlign: 'center' }}>2h</th>
                            <th style={{ padding: '0.5rem', textAlign: 'center' }}>3h</th>
                            <th style={{ padding: '0.5rem', textAlign: 'center' }}>5h</th>
                        </tr>
                    </thead>
                    <tbody>
                        {meals.map(m => {
                            const row = data.by_meal ? data.by_meal[m] : null;
                            if (!row) return null;

                            return (
                                <tr key={m} style={{ borderBottom: '1px solid #f1f5f9' }}>
                                    <td style={{ padding: '0.8rem 0.5rem', fontWeight: 600 }}>{mealLabels[m] || m}</td>
                                    {[2, 3, 5].map(h => {
                                        const w = row[`${h}h`];
                                        const total = w ? (w.short + w.ok + w.over) : 0;

                                        if (!w || total < 5) {
                                            return <td key={h} style={{ padding: '0.5rem', textAlign: 'center', color: '#cbd5e1', fontSize: '0.8rem' }}>(n={total})</td>;
                                        }

                                        return (
                                            <td key={h} style={{ padding: '0.5rem', textAlign: 'center', verticalAlign: 'top' }}>
                                                {w.short > 0 && <span className="chip" style={{ background: '#fef3c7', color: '#b45309', border: '1px solid #fcd34d', fontSize: '0.75rem', padding: '2px 4px', borderRadius: '4px', marginRight: '2px' }}>Altos:{w.short}</span>}
                                                {w.over > 0 && <span className="chip" style={{ background: '#fee2e2', color: '#b91c1c', border: '1px solid #fca5a5', fontSize: '0.75rem', padding: '2px 4px', borderRadius: '4px', marginRight: '2px' }}>Bajos:{w.over}</span>}
                                                {w.ok > 0 && <span className="chip" style={{ background: '#dcfce7', color: '#15803d', border: '1px solid #86efac', fontSize: '0.75rem', padding: '2px 4px', borderRadius: '4px' }}>OK:{w.ok}</span>}
                                            </td>
                                        );
                                    })}
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
