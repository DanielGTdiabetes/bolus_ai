import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button, Input } from '../components/ui/Atoms';
import { getCalcParams, saveCalcParams } from '../modules/core/store';
import {
    getSuggestions, generateSuggestions, getEvaluations,
    evaluateSuggestion, rejectSuggestion, acceptSuggestion
} from '../lib/api';

export default function SuggestionsPage() {
    const [tab, setTab] = useState('pending'); // pending | accepted

    return (
        <>
            <Header title="Sugerencias" showBack={false} />
            <main className="page" style={{ paddingBottom: '90px' }}>
                <div style={{ display: 'flex', marginBottom: '1.5rem', background: 'white', padding: '4px', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
                    <button
                        onClick={() => setTab('pending')}
                        style={{
                            flex: 1, border: 'none', background: tab === 'pending' ? 'var(--primary-soft)' : 'transparent',
                            padding: '0.6rem', borderRadius: '8px', fontWeight: 600,
                            color: tab === 'pending' ? 'var(--primary)' : 'var(--text-muted)', cursor: 'pointer'
                        }}
                    >
                        Pendientes
                    </button>
                    <button
                        onClick={() => setTab('accepted')}
                        style={{
                            flex: 1, border: 'none', background: tab === 'accepted' ? 'var(--primary-soft)' : 'transparent',
                            padding: '0.6rem', borderRadius: '8px', fontWeight: 600,
                            color: tab === 'accepted' ? 'var(--primary)' : 'var(--text-muted)', cursor: 'pointer'
                        }}
                    >
                        Aceptadas
                    </button>
                </div>

                {tab === 'pending' ? <PendingView /> : <AcceptedView />}

            </main>
            <BottomNav activeTab="suggestions" />
        </>
    );
}

function PendingView() {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [generating, setGenerating] = useState(false);
    const [error, setError] = useState(null);

    const load = async () => {
        setLoading(true);
        try {
            const res = await getSuggestions("pending");
            setItems(res || []);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const handleGenerate = async () => {
        setGenerating(true);
        try {
            const res = await generateSuggestions(30);
            alert(`Sugerencias generadas: ${res.created} nuevas.`);
            load();
        } catch (e) {
            alert(e.message);
        } finally {
            setGenerating(false);
        }
    };

    // Modal State
    const [modalOpen, setModalOpen] = useState(false);
    const [selectedItem, setSelectedItem] = useState(null);

    const openAcceptModal = (item) => {
        const settings = getCalcParams();
        if (!settings || !settings[item.meal_slot]) {
            alert("Error: Configuración no encontrada para " + item.meal_slot);
            return;
        }
        const currentVal = settings[item.meal_slot][item.parameter];
        setSelectedItem({ ...item, currentVal, newVal: currentVal });
        setModalOpen(true);
    };

    if (loading && !items.length) return <div className="spinner">Cargando sugerencias...</div>;

    return (
        <div className="fade-in">
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1rem' }}>
                <Button onClick={handleGenerate} disabled={generating} style={{ fontSize: '0.9rem', padding: '0.5rem 1rem' }}>
                    {generating ? 'Generando...' : '✨ Generar Nuevas'}
                </Button>
            </div>

            {error && <div className="error">{error}</div>}

            {items.length === 0 && !error && (
                <div style={{ textAlign: 'center', padding: '3rem', color: '#94a3b8', fontStyle: 'italic' }}>No hay sugerencias pendientes.</div>
            )}

            <div className="stack">
                {items.map(s => (
                    <SuggestionCard
                        key={s.id}
                        item={s}
                        onAccept={() => openAcceptModal(s)}
                        onReject={async () => {
                            const reason = prompt("¿Motivo del rechazo?");
                            if (reason !== null) {
                                await rejectSuggestion(s.id, reason || "Rechazado por usuario");
                                load();
                            }
                        }}
                    />
                ))}
            </div>

            {modalOpen && selectedItem && (
                <AcceptModal
                    item={selectedItem}
                    onClose={() => setModalOpen(false)}
                    onConfirm={async (finalVal) => {
                        // Logic to save settings & mark accepted
                        const settings = getCalcParams();
                        settings[selectedItem.meal_slot][selectedItem.parameter] = finalVal;
                        saveCalcParams(settings);

                        await acceptSuggestion(selectedItem.id, "Aceptado por usuario", {
                            meal_slot: selectedItem.meal_slot,
                            parameter: selectedItem.parameter,
                            old_value: selectedItem.currentVal,
                            new_value: finalVal
                        });

                        setModalOpen(false);
                        alert("Cambio aplicado.");
                        load();
                    }}
                />
            )}
        </div>
    );
}

function SuggestionCard({ item, onAccept, onReject }) {
    return (
        <Card style={{ borderLeft: '4px solid var(--primary)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                    <span className="chip" style={{ background: '#e0f2fe', color: '#0369a1', textTransform: 'capitalize', marginRight: '4px' }}>{item.meal_slot}</span>
                    <span className="chip" style={{ background: '#f1f5f9', color: '#475569', textTransform: 'uppercase' }}>{item.parameter}</span>
                </div>
                <small style={{ color: '#94a3b8' }}>{new Date(item.created_at).toLocaleDateString()}</small>
            </div>

            <p style={{ margin: '1rem 0', fontWeight: 600, lineHeight: 1.4 }}>{item.reason}</p>

            <div style={{ background: '#f8fafc', padding: '0.8rem', borderRadius: '6px', fontSize: '0.85rem', color: '#64748b', marginBottom: '1rem' }}>
                <strong>Evidencia:</strong> Ventana {item.evidence.window}. Ratio incidencia: {Math.round(item.evidence.ratio * 100)}%. (Base {item.evidence.days} días)
            </div>

            <div style={{ display: 'flex', gap: '0.5rem' }}>
                <Button variant="ghost" onClick={onReject} style={{ color: '#b91c1c', border: '1px solid #fecaca', flex: 1 }}>Rechazar</Button>
                <Button onClick={onAccept} style={{ flex: 1 }}>Revisar</Button>
            </div>
        </Card>
    );
}

function AcceptModal({ item, onClose, onConfirm }) {
    const [val, setVal] = useState(item.currentVal);
    const [saving, setSaving] = useState(false);

    const handleSave = async () => {
        setSaving(true);
        try {
            await onConfirm(parseFloat(val));
        } catch (e) {
            alert("Error: " + e.message);
            setSaving(false);
        }
    };

    return (
        <div style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 999,
            display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}>
            <div style={{ background: 'white', padding: '1.5rem', borderRadius: '12px', width: '90%', maxWidth: '400px', boxShadow: '0 10px 25px rgba(0,0,0,0.2)' }}>
                <h3 style={{ marginTop: 0, color: 'var(--primary)' }}>Aceptar Cambio</h3>
                <p style={{ fontSize: '0.9rem', color: '#64748b', marginBottom: '1rem' }}>
                    Estás revisando el {item.parameter.toUpperCase()} para {item.meal_slot}.
                </p>

                <div style={{ marginBottom: '1rem' }}>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#64748b' }}>Valor Actual</label>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>{item.currentVal}</div>
                </div>

                <div style={{ marginBottom: '1.5rem' }}>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#64748b' }}>Nuevo Valor</label>
                    <Input
                        type="number" step="0.1"
                        value={val} onChange={e => setVal(e.target.value)}
                        style={{ width: '100%', fontSize: '1.2rem', fontWeight: 700 }}
                    />
                </div>

                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <Button variant="ghost" onClick={onClose} style={{ flex: 1 }}>Cancelar</Button>
                    <Button onClick={handleSave} disabled={saving} style={{ flex: 1 }}>
                        {saving ? 'Guardando...' : 'Guardar'}
                    </Button>
                </div>
            </div>
        </div>
    );
}

function AcceptedView() {
    const [items, setItems] = useState([]);
    const [evaluations, setEvaluations] = useState([]);
    const [loading, setLoading] = useState(true);

    const load = async () => {
        setLoading(true);
        try {
            const [acc, evs] = await Promise.all([
                getSuggestions("accepted"),
                getEvaluations()
            ]);
            setItems(acc);
            setEvaluations(evs);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const evalMap = {};
    evaluations.forEach(e => evalMap[e.suggestion_id] = e);

    const handleEval = async (id) => {
        try {
            const res = await evaluateSuggestion(id, 7);
            alert(`Evaluación completada: ${res.summary}`);
            load();
        } catch (e) { alert(e.message); }
    };

    if (loading) return <div className="spinner">Cargando historial...</div>;
    if (!items.length) return <div style={{ textAlign: 'center', padding: '3rem', color: '#94a3b8', fontStyle: 'italic' }}>No hay historial de cambios aceptados.</div>;

    return (
        <div className="stack fade-in">
            {items.map(s => {
                const ev = evalMap[s.id];
                const resolvedDate = new Date(s.resolved_at);
                const diffDays = Math.ceil(Math.abs(new Date() - resolvedDate) / (1000 * 60 * 60 * 24));

                return (
                    <Card key={s.id} style={{ borderLeft: '4px solid #cbd5e1' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <div>
                                <span className="chip" style={{ background: '#f1f5f9', color: '#475569', textTransform: 'capitalize', marginRight: '4px' }}>{s.meal_slot}</span>
                                <span className="chip" style={{ background: '#f1f5f9', color: '#475569', textTransform: 'uppercase' }}>{s.parameter}</span>
                            </div>
                            <small style={{ color: '#94a3b8' }}>{resolvedDate.toLocaleDateString()}</small>
                        </div>
                        <p style={{ fontSize: '0.9rem', color: '#334155', margin: '0.5rem 0' }}>{s.resolution_note || "Sin nota"}</p>

                        {ev ? (
                            <div style={{
                                marginTop: '1rem', background: '#f8fafc', padding: '0.8rem', borderRadius: '8px',
                                borderLeft: `4px solid ${ev.result === 'improved' ? 'var(--success)' : (ev.result === 'worse' ? 'var(--danger)' : '#cbd5e1')}`
                            }}>
                                <div style={{ fontWeight: 700, fontSize: '0.9rem', color: ev.result === 'improved' ? 'var(--success)' : (ev.result === 'worse' ? 'var(--danger)' : '#64748b') }}>
                                    {ev.result === 'improved' ? '✅' : (ev.result === 'worse' ? '⚠️' : '➖')} Impacto: {ev.result.toUpperCase()}
                                </div>
                                <p style={{ fontSize: '0.85rem', margin: '0.5rem 0 0', color: '#475569' }}>{ev.summary}</p>
                            </div>
                        ) : (
                            <div style={{ marginTop: '1rem' }}>
                                {diffDays < 7 ? (
                                    <div style={{ background: '#fff7ed', padding: '0.8rem', borderRadius: '8px', border: '1px dashed #fdba74', fontSize: '0.85rem', color: '#c2410c' }}>
                                        📉 Faltan datos para evaluar. <small>({diffDays}/7 días)</small>
                                    </div>
                                ) : (
                                    <Button variant="secondary" onClick={() => handleEval(s.id)} style={{ fontSize: '0.85rem', color: 'var(--primary)', borderColor: 'var(--primary)' }}>
                                        📊 Evaluar Impacto (7 días)
                                    </Button>
                                )}
                            </div>
                        )}
                    </Card>
                );
            })}
        </div>
    );
}
