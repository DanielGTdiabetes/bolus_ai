import React, { useEffect, useState } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { fetchTreatments, getLocalNsConfig, updateTreatment } from '../lib/api';
import { Button, Input, Card } from '../components/ui/Atoms';

import { formatTrend, formatNotes } from '../modules/core/utils';
export default function HistoryPage() {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [treatments, setTreatments] = useState([]);
    const [stats, setStats] = useState({ insulin: 0, carbs: 0 });
    const [editingTx, setEditingTx] = useState(null);

    // Search State
    const [rangeMode, setRangeMode] = useState('7days'); // '7days' | 'custom'
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');

    const load = async () => {
        setLoading(true);
        try {
            const config = getLocalNsConfig() || {};
            const params = { ...config, count: 50 };

            if (rangeMode === '7days') {
                const d = new Date();
                d.setDate(d.getDate() - 7);
                params.from_date = d.toISOString();
                params.count = 500; // Load ample for week
            } else if (rangeMode === 'custom' && dateFrom) {
                params.from_date = new Date(dateFrom).toISOString();
                if (dateTo) params.to_date = new Date(dateTo).toISOString();
                params.count = 1000;
            }

            const data = await fetchTreatments(params);

            // Process Stats
            const today = new Date().toDateString();
            let iTotal = 0, cTotal = 0;

            const valid = data.filter(t => {
                const u = parseFloat(t.insulin) || 0;
                const c = parseFloat(t.carbs) || 0;
                const hasData = (u > 0 || c > 0);

                if (hasData) {
                    const d = new Date(t.created_at || t.timestamp || t.date);
                    if (d.toDateString() === today) {
                        if (u > 0) iTotal += u;
                        if (c > 0) cTotal += c;
                    }
                }
                return hasData;
            });

            setTreatments(valid);
            setStats({ insulin: iTotal, carbs: cTotal });
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
    }, [rangeMode]); // Auto-load when mode switches. Custom search triggered by Button.

    const handleSaveEdit = async (id, payload) => {
        try {
            await updateTreatment(id, payload);
            setEditingTx(null);
            load(); // Reload data
            alert("✅ Registro actualizado");
        } catch (e) {
            alert("Error: " + e.message);
        }
    };

    return (
        <>
            <Header title="Historial" showBack={true} />
            <main className="page fade-in" style={{ paddingBottom: '80px' }}>
                <div className="metrics-grid">
                    <div className="metric-tile" style={{ background: '#eff6ff', textAlign: 'center', padding: '1.5rem 0.5rem', borderRadius: '12px' }}>
                        <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#2563eb' }}>{loading ? '--' : stats.insulin.toFixed(1)}</div>
                        <div style={{ fontSize: '0.7rem', color: '#93c5fd', fontWeight: 700 }}>INSULINA HOY</div>
                    </div>
                    <div className="metric-tile" style={{ background: '#fff7ed', textAlign: 'center', padding: '1.5rem 0.5rem', borderRadius: '12px' }}>
                        <div style={{ fontSize: '1.5rem', fontWeight: 800, color: '#f97316' }}>{loading ? '--' : Math.round(stats.carbs)}</div>
                        <div style={{ fontSize: '0.7rem', color: '#fdba74', fontWeight: 700 }}>CARBOS HOY</div>
                    </div>
                </div>

                <div style={{ marginBottom: '1.5rem', background: '#fff', padding: '1rem', borderRadius: '12px', boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
                    <div style={{ display: 'flex', gap: '0.5rem', marginBottom: rangeMode === 'custom' ? '1rem' : 0 }}>
                        <Button
                            variant={rangeMode === '7days' ? 'primary' : 'secondary'}
                            onClick={() => setRangeMode('7days')}
                            style={{ flex: 1, fontSize: '0.9rem' }}
                        >
                            📅 Últimos 7 días
                        </Button>
                        <Button
                            variant={rangeMode === 'custom' ? 'primary' : 'secondary'}
                            onClick={() => setRangeMode('custom')}
                            style={{ flex: 1, fontSize: '0.9rem' }}
                        >
                            🔎 Buscar Fecha
                        </Button>
                    </div>

                    {rangeMode === 'custom' && (
                        <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '0.8rem' }}>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <div style={{ flex: 1 }}>
                                    <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b' }}>Desde</label>
                                    <Input
                                        type="date"
                                        value={dateFrom}
                                        onChange={e => setDateFrom(e.target.value)}
                                    />
                                </div>
                                <div style={{ flex: 1 }}>
                                    <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b' }}>Hasta</label>
                                    <Input
                                        type="date"
                                        value={dateTo}
                                        onChange={e => setDateTo(e.target.value)}
                                    />
                                </div>
                            </div>
                            <Button onClick={load} disabled={loading || !dateFrom}>
                                {loading ? 'Buscando...' : '🔍 Buscar'}
                            </Button>
                        </div>
                    )}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h4 style={{ margin: 0, color: 'var(--text-muted)' }}>Lista de Transacciones</h4>
                    <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                        {treatments.length} registradas
                    </span>
                </div>

                <div className="activity-list">
                    {loading && <div className="spinner">Cargando...</div>}
                    {error && <div className="error-msg" style={{ color: 'var(--danger)', padding: '1rem', background: '#fee2e2', borderRadius: '8px' }}>{error}</div>}

                    {!loading && !error && treatments.length === 0 && (
                        <div className='hint' style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>No hay historial disponible</div>
                    )}

                    {treatments.map((t, idx) => {
                        const u = parseFloat(t.insulin) || 0;
                        const c = parseFloat(t.carbs) || 0;
                        const isBolus = u > 0;
                        const icon = isBolus ? "💉" : "🍪";
                        const date = new Date(t.created_at || t.timestamp || t.date);
                        const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

                        let val = "";
                        if (u > 0) val += `${u} U `;
                        if (c > 0) val += `${c} g`;

                        let foodName = null;
                        if (t.notes) {
                            const match = t.notes.match(/Comida:\s*([^.]+)/);
                            if (match && match[1]) {
                                foodName = match[1].trim();
                            }
                        }

                        return (
                            <div className="activity-item" key={t._id || idx} style={{ alignItems: 'flex-start' }}>
                                <div className="act-icon" style={isBolus ? { marginTop: '4px' } : { background: '#fff7ed', color: '#f97316', marginTop: '4px' }}>{icon}</div>
                                <div className="act-details">
                                    <div className="act-val">{val}</div>
                                    {foodName && (
                                        <div style={{ fontWeight: 700, color: '#1e293b', fontSize: '0.9rem', marginBottom: '2px' }}>
                                            🍽️ {foodName}
                                        </div>
                                    )}
                                    <div className="act-sub" style={{ fontSize: '0.75rem', color: '#94a3b8', lineHeight: 1.2 }}>
                                        {formatNotes(t.notes) || t.enteredBy || 'Entrada'}
                                    </div>
                                </div>
                                <div className="act-time" style={{ marginTop: '4px' }}>{timeStr}</div>
                                {t._id && (
                                    <button
                                        onClick={() => setEditingTx(t)}
                                        style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: '0.5rem', opacity: 0.5, fontSize: '1.2rem' }}
                                    >
                                        ✏️
                                    </button>
                                )}
                            </div>
                        );
                    })}
                </div>

                {editingTx && (
                    <EditHistoryModal
                        treatment={editingTx}
                        onClose={() => setEditingTx(null)}
                        onSave={handleSaveEdit}
                    />
                )}
            </main>
            <BottomNav activeTab="history" />
        </>
    );
}

function EditHistoryModal({ treatment, onClose, onSave }) {
    // Helpers
    const getInitialDate = (t) => {
        const d = new Date(t.created_at || t.timestamp || t.date || Date.now());
        // Format YYYY-MM-DDTHH:mm for input
        const pad = n => n < 10 ? '0' + n : n;
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    };

    const [insulin, setInsulin] = useState(treatment.insulin || '');
    const [carbs, setCarbs] = useState(treatment.carbs || '');
    const [dateVal, setDateVal] = useState(getInitialDate(treatment));
    const [submitting, setSubmitting] = useState(false);

    const handleSubmit = async () => {
        if (!treatment._id) return;
        setSubmitting(true);

        // Prepare payload (Only fields we edit)
        // Keep it simple. User wants to fix errors.
        const payload = {
            insulin: parseFloat(insulin) || 0,
            carbs: parseFloat(carbs) || 0,
            created_at: new Date(dateVal).toISOString()
        };

        await onSave(treatment._id, payload);
        // onClose handled by parent logic if successful
        setSubmitting(false);
    };

    return (
        <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.5)', zIndex: 1000,
            display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem'
        }}>
            <Card style={{ width: '100%', maxWidth: '400px', padding: '1.5rem' }}>
                <h3 style={{ marginBottom: '1rem', fontWeight: 800 }}>Editar Registro</h3>

                <div style={{ marginBottom: '1rem' }}>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, color: '#64748b' }}>Insulina (U)</label>
                    <Input type="number" step="0.1" value={insulin} onChange={e => setInsulin(e.target.value)} />
                </div>

                <div style={{ marginBottom: '1rem' }}>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, color: '#64748b' }}>Carbohidratos (g)</label>
                    <Input type="number" step="1" value={carbs} onChange={e => setCarbs(e.target.value)} />
                </div>

                <div style={{ marginBottom: '1.5rem' }}>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 600, color: '#64748b' }}>Fecha y Hora</label>
                    <Input type="datetime-local" value={dateVal} onChange={e => setDateVal(e.target.value)} />
                </div>

                <div style={{ display: 'flex', gap: '1rem' }}>
                    <Button onClick={handleSubmit} disabled={submitting} style={{ flex: 1 }}>
                        {submitting ? 'Guardando...' : 'Guardar'}
                    </Button>
                    <Button onClick={onClose} variant="ghost" style={{ flex: 1 }}>
                        Cancelar
                    </Button>
                </div>
            </Card>
        </div>
    );
}
