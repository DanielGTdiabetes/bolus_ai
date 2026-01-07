import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { navigate } from '../modules/core/router';

export default function NotificationsPage() {
    const [alerts, setAlerts] = useState([]);

    const priorityOrder = {
        critical: 0,
        high: 1,
        medium: 2,
        low: 3,
        info: 4
    };

    const priorityBadge = {
        critical: { label: 'Crítica', color: '#b91c1c', bg: '#fee2e2' },
        high: { label: 'Alta', color: '#b45309', bg: '#fef3c7' },
        medium: { label: 'Media', color: '#1d4ed8', bg: '#dbeafe' },
        low: { label: 'Baja', color: '#0f766e', bg: '#ccfbf1' },
        info: { label: 'Info', color: '#334155', bg: '#e2e8f0' },
    };

    useEffect(() => {
        async function load() {
            const list = [];

            // 1. Backend Notifications (Async)
            try {
                const { getNotificationsSummary, markNotificationsSeen } = await import('../lib/api');
                const summary = await getNotificationsSummary();

                if (summary && summary.items) {
                    // Mark as seen automatically? Or only on interaction?
                    // Usually opening the center marks "New" as seen (removes badge), but keeps actionable items in list.
                    // Some backend items may hide after being seen.
                    // For now, let's NOT auto-mark everything. Let the user dismiss or act.
                    // We only mark "unread" items as "read" to clear the badge count?
                    // We'll calculate IDs to mark seen if that's the desired behavior.
                    // Let's just map them for now.

                    summary.items
                        .sort((a, b) => (priorityOrder[a.priority] ?? 99) - (priorityOrder[b.priority] ?? 99))
                        .forEach(item => {
                            const priority = item.priority || 'info';
                            let uiType = 'info';
                            if (priority === 'critical') uiType = 'danger';
                            else if (priority === 'high') uiType = 'warning';
                            else if (priority === 'low') uiType = 'success';

                            let uiItem = {
                                id: item.type, // distinct key
                                type: uiType,
                                priority,
                                title: item.title,
                                msg: item.message,
                                action: () => navigate(item.route),
                                btn: 'Ver',
                                dismissable: true,
                                backendType: item.type // keep track for marking seen
                            };

                            if (item.type === 'suggestion_pending') {
                                uiItem.type = 'info';
                                uiItem.btn = 'Revisar';
                            } else if (item.type === 'basal_review_today') {
                                uiItem.type = 'warning';
                            } else if (item.type === 'post_prandial_warning') {
                                uiItem.type = 'danger'; // High importance
                                uiItem.btn = 'Corregir';
                            }

                            list.push(uiItem);
                        });
                }
            } catch (e) {
                console.warn("Error fetching notifications", e);
            }

            // 2. Local Checks (Sync)
            // Check Needles
            const needles = parseInt(localStorage.getItem('supplies_needles') || '100');
            if (needles < 20) {
                list.push({
                    type: 'danger',
                    priority: 'high',
                    title: 'Stock de Agujas muy bajo',
                    msg: `Solo quedan ${needles} agujas. Reponer urgentemente.`,
                    action: () => navigate('#/supplies'),
                    btn: 'Gestionar Stock'
                });
            } else if (needles < 50) {
                list.push({
                    type: 'warning',
                    priority: 'medium',
                    title: 'Stock de Agujas bajo',
                    msg: `Quedan ${needles} agujas. Considera comprar pronto.`,
                    action: () => navigate('#/supplies'),
                    btn: 'Ver Stock'
                });
            }

            // Check Sensors
            const sensors = parseInt(localStorage.getItem('supplies_sensors') || '10');
            if (sensors < 4) {
                list.push({
                    type: 'warning',
                    priority: 'medium',
                    title: 'Stock de Sensores bajo',
                    msg: `Quedan ${sensors} sensores.`,
                    action: () => navigate('#/supplies'),
                    btn: 'Ver Stock'
                });
            }

            // Check Sick Mode
            const sick = localStorage.getItem('sick_mode_enabled') === 'true';
            if (sick) {
                list.push({
                    type: 'info',
                    priority: 'low',
                    title: 'Modo Enfermedad Activo',
                    msg: 'Tus ratios están aumentados un 20%. Recuerda desactivarlo cuando mejores.',
                    action: () => navigate('#/profile'),
                    btn: 'Configurar'
                });
            }

            // Check Forecast Warning
            const forecastWarn = localStorage.getItem('forecast_warning') === 'true';
            if (forecastWarn) {
                list.push({
                    id: 'forecast-alert',
                    type: 'warning',
                    priority: 'high',
                    title: 'Tendencia Riesgosa Detectada',
                    msg: 'El modelo de predicción indica un posible riesgo de hipo/hiperglucemia en las próximas horas.',
                    action: () => navigate('#/forecast'),
                    btn: 'Ver Análisis',
                    dismissable: true
                });
            }

            list.sort((a, b) => (priorityOrder[a.priority || 'info'] ?? 99) - (priorityOrder[b.priority || 'info'] ?? 99));
            setAlerts(list);

            // Auto-clear badge count (optional)
            // import('../lib/api').then(({ markNotificationsSeen }) => markNotificationsSeen(['generic_read']));
        }

        load();
    }, []);

    const dismissAlert = async (id, backendType) => {
        if (backendType) {
            // Call backend to mark as seen (persists dismissal)
            try {
                const { markNotificationsSeen } = await import('../lib/api');
                await markNotificationsSeen([backendType]);
            } catch (e) { console.error(e); }
        }

        if (id === 'forecast-alert') {
            localStorage.setItem('forecast_warning_dismissed_at', Date.now().toString());
            window.dispatchEvent(new Event('forecast-update'));
        }

        setAlerts(prev => prev.filter(a => a.id !== id && a.backendType !== backendType));
    };

    return (
        <>
            <Header title="Notificaciones" showBack={true} />
            <main className="page" style={{ padding: '1rem' }}>
                <h3 style={{ marginBottom: '1rem', color: '#64748b' }}>Avisos y Alertas</h3>

                {alerts.length === 0 && (
                    <div className="card fade-in" style={{ textAlign: 'center', padding: '3rem', color: '#94a3b8' }}>
                        <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>✅</div>
                        <p>No tienes notificaciones pendientes.</p>
                    </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {alerts.map((alert, idx) => (
                        <div key={idx} className="card fade-in" style={{
                            borderLeft: `5px solid ${alert.type === 'danger' ? '#ef4444' : (alert.type === 'warning' ? '#f59e0b' : '#3b82f6')}`,
                            padding: '1rem',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.8rem'
                        }}>
                            <div>
                                <div style={{ fontWeight: 700, fontSize: '1rem', color: '#1e293b', marginBottom: '4px' }}>
                                    {alert.type === 'danger' && '🚨 '}
                                    {alert.type === 'warning' && '⚠️ '}
                                    {alert.type === 'info' && 'ℹ️ '}
                                    {alert.title}
                                    {alert.priority && (
                                        <span style={{
                                            marginLeft: '0.5rem',
                                            fontSize: '0.75rem',
                                            fontWeight: 700,
                                            padding: '2px 8px',
                                            borderRadius: '9999px',
                                            color: priorityBadge[alert.priority]?.color || '#334155',
                                            background: priorityBadge[alert.priority]?.bg || '#e2e8f0',
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.02em'
                                        }}>
                                            {priorityBadge[alert.priority]?.label || 'Info'}
                                        </span>
                                    )}
                                </div>
                                <p style={{ fontSize: '0.9rem', color: '#64748b', margin: 0, lineHeight: 1.4 }}>
                                    {alert.msg}
                                </p>
                            </div>

                            <div style={{ display: 'flex', gap: '0.8rem', marginTop: '0.2rem' }}>
                                {/* Primary Action Button */}
                                <Button
                                    onClick={alert.action}
                                    style={{
                                        flex: 1,
                                        background: alert.type === 'danger' ? '#fee2e2' : '#eff6ff',
                                        color: alert.type === 'danger' ? '#b91c1c' : '#1d4ed8',
                                        border: 'none',
                                        fontWeight: 600,
                                        display: 'flex',
                                        justifyContent: 'center',
                                        alignItems: 'center',
                                        gap: '6px'
                                    }}
                                >
                                    {alert.btn} <span>→</span>
                                </Button>

                                {/* Dismiss Button */}
                                {alert.dismissable && (
                                    <button
                                        onClick={() => dismissAlert(alert.id, alert.backendType)}
                                        style={{
                                            width: '42px',
                                            height: '42px',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            borderRadius: '12px',
                                            border: '1px solid #fecaca',
                                            background: '#fff',
                                            color: '#ef4444',
                                            fontSize: '1.2rem',
                                            cursor: 'pointer',
                                            transition: 'all 0.2s'
                                        }}
                                        aria-label="Ignorar"
                                    >
                                        ✕
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            </main>
            <BottomNav />
        </>
    );
}
