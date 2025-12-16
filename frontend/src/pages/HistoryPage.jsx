import React, { useEffect, useState } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { fetchTreatments, getLocalNsConfig } from '../lib/api';

export default function HistoryPage() {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [treatments, setTreatments] = useState([]);
    const [stats, setStats] = useState({ insulin: 0, carbs: 0 });

    useEffect(() => {
        let mounted = true;

        const load = async () => {
            try {
                // Relaxed config check, relying on backend fallback
                const config = getLocalNsConfig() || {};
                const data = await fetchTreatments({ ...config, count: 50 });

                if (!mounted) return;

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
                setLoading(false);
            } catch (e) {
                if (mounted) {
                    setError(e.message);
                    setLoading(false);
                }
            }
        };
        load();

        return () => { mounted = false; };
    }, []);

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

                <h4 style={{ marginBottom: '1rem', color: 'var(--text-muted)' }}>Últimas Transacciones</h4>

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

                        return (
                            <div className="activity-item" key={t._id || idx}>
                                <div className="act-icon" style={isBolus ? {} : { background: '#fff7ed', color: '#f97316' }}>{icon}</div>
                                <div className="act-details">
                                    <div className="act-val">{val}</div>
                                    <div className="act-sub">{t.notes || t.enteredBy || 'Entrada'}</div>
                                </div>
                                <div className="act-time">{timeStr}</div>
                            </div>
                        );
                    })}
                </div>
            </main>
            <BottomNav activeTab="history" />
        </>
    );
}
