import React, { useCallback, useEffect, useState } from 'react';
import { Button } from '../ui/Atoms';
import { actOnCompanionEpisode, getCompanionSnapshot, updateCompanionPreferences } from '../../lib/api';
import { navigate } from '../../modules/core/navigation';

const stateLabels = {
    stable: 'Todo tranquilo',
    watching: 'Te acompaño de cerca',
    needs_attention: 'Hay algo que revisar',
    unavailable: 'Seguimiento en pausa',
};

const severityStyle = {
    critical: { border: '#ef4444', background: '#fef2f2' },
    high: { border: '#f59e0b', background: '#fffbeb' },
    medium: { border: '#3b82f6', background: '#eff6ff' },
    info: { border: '#94a3b8', background: '#f8fafc' },
};

export function CompanionPanel({ showPreferences = false }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const load = useCallback(async () => {
        try {
            setData(await getCompanionSnapshot());
            setError('');
        } catch (err) {
            setError(err.message || 'No se pudo actualizar el compañero');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        load();
        const timer = setInterval(load, 5 * 60 * 1000);
        return () => clearInterval(timer);
    }, [load]);

    const act = async (episodeId, action, snoozeMinutes = 30) => {
        await actOnCompanionEpisode(episodeId, action, snoozeMinutes);
        await load();
        window.dispatchEvent(new Event('companion-update'));
    };

    const setPreference = async (changes) => {
        const preferences = await updateCompanionPreferences(changes);
        setData(previous => ({ ...previous, preferences }));
        if (changes.enabled !== false) await load();
    };

    if (loading) {
        return <section className="card" style={{ marginBottom: '1rem', color: '#64748b' }}>Preparando tu estado…</section>;
    }

    const snapshot = data?.snapshot || {};
    const episodes = data?.episodes || [];
    const preferences = data?.preferences || {};

    return (
        <section className="card" style={{ marginBottom: '1rem', border: '1px solid #c7d2fe', background: '#fff' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
                <div>
                    <div style={{ fontSize: '0.75rem', color: '#6366f1', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Tu compañero</div>
                    <h3 style={{ margin: '0.25rem 0', color: '#1e293b' }}>
                        {preferences.enabled === false ? 'Seguimiento pausado' : (stateLabels[snapshot.state] || 'Revisando tu estado')}
                    </h3>
                    {snapshot.current_bg != null && (
                        <div style={{ color: '#475569', fontSize: '0.88rem' }}>
                            {snapshot.current_bg} mg/dL
                            {snapshot.predicted_20m != null ? ` · estimación 20 min: ${snapshot.predicted_20m}` : ''}
                            {snapshot.iob_u != null ? ` · IOB ${snapshot.iob_u} U` : ''}
                            {snapshot.cob_g != null ? ` · COB ${snapshot.cob_g} g` : ''}
                        </div>
                    )}
                </div>
                <button onClick={load} aria-label="Actualizar compañero" style={{ border: 0, background: '#eef2ff', color: '#4338ca', borderRadius: '10px', padding: '0.5rem', cursor: 'pointer' }}>↻</button>
            </div>

            {error && <div style={{ marginTop: '0.75rem', color: '#b45309', fontSize: '0.85rem' }}>{error}</div>}
            {preferences.enabled !== false && episodes.length === 0 && !error && (
                <p style={{ margin: '0.8rem 0 0', color: '#64748b', fontSize: '0.9rem' }}>No hay ninguna situación pendiente. Solo te avisaré cuando haya algo útil que hacer.</p>
            )}

            <div style={{ display: 'grid', gap: '0.75rem', marginTop: episodes.length ? '0.9rem' : 0 }}>
                {episodes.map(episode => {
                    const style = severityStyle[episode.severity] || severityStyle.info;
                    const isSnoozed = episode.status === 'snoozed';
                    const isAcknowledged = episode.status === 'monitoring';
                    return (
                        <article key={episode.id} style={{ borderLeft: `4px solid ${style.border}`, background: style.background, borderRadius: '10px', padding: '0.85rem' }}>
                            <div style={{ fontWeight: 750, color: '#1e293b' }}>{episode.title}</div>
                            <div style={{ color: '#475569', fontSize: '0.88rem', lineHeight: 1.45, marginTop: '0.25rem' }}>{episode.message}</div>
                            {isSnoozed && <div style={{ color: '#6366f1', fontSize: '0.78rem', marginTop: '0.35rem' }}>Silenciado temporalmente</div>}
                            {isAcknowledged && <div style={{ color: '#0f766e', fontSize: '0.78rem', marginTop: '0.35rem' }}>Entendido · sigo vigilando</div>}
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.7rem' }}>
                                <Button size="sm" onClick={() => navigate(episode.route)}>
                                    {episode.action_label || episode.context?.action_label || 'Revisar'}
                                </Button>
                                {!isSnoozed && !isAcknowledged && <Button size="sm" variant="secondary" onClick={() => act(episode.id, 'acknowledge')}>Entendido</Button>}
                                {!isSnoozed && !isAcknowledged && <Button size="sm" variant="ghost" onClick={() => act(episode.id, 'snooze', 30)}>30 min</Button>}
                                <Button size="sm" variant="ghost" onClick={() => act(episode.id, 'dismiss')}>Descartar</Button>
                            </div>
                        </article>
                    );
                })}
            </div>

            {showPreferences && (
                <div style={{ marginTop: '1rem', paddingTop: '0.9rem', borderTop: '1px solid #e2e8f0' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
                        <label style={{ color: '#334155', fontWeight: 650 }}>Seguimiento proactivo</label>
                        <input type="checkbox" checked={preferences.enabled !== false} onChange={event => setPreference({ enabled: event.target.checked })} />
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.75rem' }}>
                        <label style={{ fontSize: '0.8rem', color: '#64748b' }}>
                            Intensidad
                            <select value={preferences.mode || 'balanced'} onChange={event => setPreference({ mode: event.target.value })} style={{ display: 'block', width: '100%', marginTop: '0.25rem', padding: '0.5rem', borderRadius: '8px', border: '1px solid #cbd5e1' }}>
                                <option value="quiet">Solo urgente</option>
                                <option value="balanced">Equilibrado</option>
                                <option value="active">Muy pendiente</option>
                            </select>
                        </label>
                        <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                            Horas de descanso
                            <div style={{ display: 'flex', gap: '0.35rem', marginTop: '0.25rem' }}>
                                <input type="time" value={preferences.quiet_hours_start || '23:00'} onChange={event => setPreference({ quiet_hours_start: event.target.value })} style={{ minWidth: 0, width: '50%' }} />
                                <input type="time" value={preferences.quiet_hours_end || '07:00'} onChange={event => setPreference({ quiet_hours_end: event.target.value })} style={{ minWidth: 0, width: '50%' }} />
                            </div>
                        </div>
                    </div>
                    <p style={{ margin: '0.7rem 0 0', color: '#64748b', fontSize: '0.78rem' }}>Las alertas críticas pueden interrumpir el descanso. El compañero nunca cambia dosis por sí solo.</p>
                </div>
            )}
        </section>
    );
}
