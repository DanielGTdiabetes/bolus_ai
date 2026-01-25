import React, { useEffect, useMemo, useState } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Button, Card } from '../components/ui/Atoms';
import {
    getLearningSummary,
    getLearningClusters,
    getLearningClusterDetail,
    getLearningEvents,
} from '../lib/api';

const FILTERS = [
    { id: 'standard', label: 'Estándar' },
    { id: 'dual', label: 'Dual (experimental)' },
    { id: 'excluded', label: 'Excluidos' },
];

export default function LearningPage() {
    const [summary, setSummary] = useState(null);
    const [clusters, setClusters] = useState([]);
    const [events, setEvents] = useState([]);
    const [filter, setFilter] = useState('standard');
    const [loading, setLoading] = useState(true);
    const [selectedCluster, setSelectedCluster] = useState(null);
    const [detail, setDetail] = useState(null);

    const filterLabel = useMemo(() => FILTERS.find((f) => f.id === filter)?.label, [filter]);

    const loadSummary = async () => {
        const res = await getLearningSummary();
        setSummary(res);
    };

    const loadClusters = async () => {
        const res = await getLearningClusters();
        setClusters(res || []);
    };

    const loadEvents = async () => {
        if (filter === 'dual') {
            setEvents(await getLearningEvents({ event_kind: 'MEAL_DUAL' }));
        } else if (filter === 'excluded') {
            setEvents(await getLearningEvents({ window_status: 'excluded' }));
        } else {
            setEvents([]);
        }
    };

    const loadDetail = async (clusterKey) => {
        const res = await getLearningClusterDetail(clusterKey);
        setDetail(res);
    };

    useEffect(() => {
        let active = true;
        const load = async () => {
            setLoading(true);
            try {
                await loadSummary();
                if (filter === 'standard') {
                    await loadClusters();
                } else {
                    await loadEvents();
                }
            } finally {
                if (active) setLoading(false);
            }
        };
        load();
        return () => {
            active = false;
        };
    }, [filter]);

    const handleSelectCluster = async (clusterKey) => {
        setSelectedCluster(clusterKey);
        await loadDetail(clusterKey);
    };

    return (
        <>
            <Header title="Aprendizaje" showBack={true} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <Card>
                    <div style={{ fontWeight: 700, marginBottom: '0.5rem' }}>
                        Aprendizaje ajusta timing del forecast/alertas. No cambia bolos ni ratios.
                    </div>
                    <div style={{ fontSize: '0.9rem', color: '#64748b' }}>
                        Se registran experiencias OK para ajustar duración, pico y cola de la curva de absorción.
                    </div>
                </Card>

                <Card>
                    <h3 style={{ marginTop: 0 }}>Progreso</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.8rem' }}>
                        <SummaryStat label="Eventos OK" value={summary?.ok_events ?? '-'} />
                        <SummaryStat label="Descartados" value={summary?.discarded_events ?? '-'} />
                        <SummaryStat label="Excluidos" value={summary?.excluded_events ?? '-'} />
                        <SummaryStat label="Clusters activos" value={summary?.clusters_active ?? '-'} />
                    </div>
                </Card>

                <Card>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        {FILTERS.map((f) => (
                            <button
                                key={f.id}
                                onClick={() => {
                                    setSelectedCluster(null);
                                    setDetail(null);
                                    setFilter(f.id);
                                }}
                                style={{
                                    padding: '0.5rem 0.8rem',
                                    borderRadius: '999px',
                                    border: '1px solid',
                                    borderColor: filter === f.id ? '#2563eb' : '#e2e8f0',
                                    background: filter === f.id ? '#eff6ff' : 'white',
                                    color: filter === f.id ? '#1d4ed8' : '#475569',
                                    fontWeight: 600,
                                    cursor: 'pointer',
                                }}
                            >
                                {f.label}
                            </button>
                        ))}
                    </div>
                </Card>

                {loading ? (
                    <div className="spinner">Cargando aprendizaje...</div>
                ) : filter === 'standard' ? (
                    <>
                        {clusters.length === 0 ? (
                            <Card>
                                <div style={{ color: '#64748b', textAlign: 'center', fontStyle: 'italic' }}>
                                    Aún no hay suficientes experiencias limpias para generar clusters.
                                </div>
                            </Card>
                        ) : (
                            <div className="stack" style={{ gap: '1rem' }}>
                                {clusters.map((cluster) => (
                                    <Card key={cluster.cluster_key} style={{ borderLeft: '4px solid #3b82f6' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
                                            <div>
                                                <div style={{ fontWeight: 700 }}>{cluster.carb_profile || 'auto'}</div>
                                                <div style={{ fontSize: '0.85rem', color: '#64748b' }}>
                                                    Carbs {cluster.centroid?.carbs_g?.toFixed(0)}g · Prot {cluster.centroid?.protein_g?.toFixed(0)}g ·
                                                    Grasa {cluster.centroid?.fat_g?.toFixed(0)}g
                                                </div>
                                            </div>
                                            <div style={{ textAlign: 'right' }}>
                                                <div style={{ fontSize: '0.85rem', color: '#475569' }}>OK: {cluster.n_ok}</div>
                                                <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{cluster.confidence}</div>
                                            </div>
                                        </div>
                                        <div style={{ marginTop: '0.6rem', fontSize: '0.85rem', color: '#475569' }}>
                                            Curva: {cluster.curve?.duration_min || '-'}m · Pico {cluster.curve?.peak_min || '-'}m · Cola {cluster.curve?.tail_min || '-'}m
                                        </div>
                                        <Button
                                            variant="ghost"
                                            onClick={() => handleSelectCluster(cluster.cluster_key)}
                                            style={{ marginTop: '0.8rem' }}
                                        >
                                            Ver detalle →
                                        </Button>
                                    </Card>
                                ))}
                            </div>
                        )}
                        {selectedCluster && detail?.cluster_key && (
                            <Card>
                                <div style={{ fontWeight: 700, marginBottom: '0.5rem' }}>Detalle del cluster</div>
                                <div style={{ fontSize: '0.9rem', color: '#475569' }}>
                                    Curva aprendida: {detail.curve?.duration_min}m · Pico {detail.curve?.peak_min}m · Cola {detail.curve?.tail_min}m
                                </div>
                                <div style={{ fontSize: '0.9rem', color: '#475569', marginTop: '0.5rem' }}>
                                    Eventos OK: {detail.n_ok} · Descartados: {detail.n_discarded} · Confianza: {detail.confidence}
                                </div>
                                <div style={{ marginTop: '0.8rem' }}>
                                    <Button variant="ghost" onClick={() => setSelectedCluster(null)}>
                                        Cerrar detalle
                                    </Button>
                                </div>
                            </Card>
                        )}
                    </>
                ) : (
                    <Card>
                        <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>{filterLabel}</div>
                        {events.length === 0 ? (
                            <div style={{ color: '#64748b', fontStyle: 'italic' }}>
                                Sin eventos para este filtro.
                            </div>
                        ) : (
                            <div className="stack" style={{ gap: '0.6rem' }}>
                                {events.map((event) => (
                                    <div
                                        key={event.id}
                                        style={{
                                            background: '#f8fafc',
                                            border: '1px solid #e2e8f0',
                                            borderRadius: '8px',
                                            padding: '0.7rem',
                                            fontSize: '0.85rem',
                                        }}
                                    >
                                        <div style={{ fontWeight: 600 }}>
                                            {event.meal_type || 'Evento'} · {event.carb_profile || 'auto'}
                                        </div>
                                        <div style={{ color: '#64748b' }}>
                                            {event.carbs_g?.toFixed(0)}g carbs · {event.event_kind} · {event.window_status}
                                        </div>
                                        {event.discard_reason && (
                                            <div style={{ color: '#ef4444', marginTop: '0.3rem' }}>{event.discard_reason}</div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </Card>
                )}
            </main>
            <BottomNav activeTab="menu" />
        </>
    );
}

function SummaryStat({ label, value }) {
    return (
        <div style={{ background: '#f8fafc', borderRadius: '10px', padding: '0.8rem' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', textTransform: 'uppercase' }}>{label}</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>{value}</div>
        </div>
    );
}
