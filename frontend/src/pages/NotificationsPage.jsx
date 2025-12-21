import React, { useState, useEffect } from 'react';
import { Header } from '../components/layout/Header';
import { BottomNav } from '../components/layout/BottomNav';
import { Card, Button } from '../components/ui/Atoms';
import { navigate } from '../modules/core/router';

export default function NotificationsPage() {
    const [alerts, setAlerts] = useState([]);

    useEffect(() => {
        const list = [];

        // Check Needles
        const needles = parseInt(localStorage.getItem('supplies_needles') || '100');
        if (needles < 20) {
            list.push({
                type: 'danger',
                title: 'Stock de Agujas muy bajo',
                msg: `Solo quedan ${needles} agujas. Reponer urgentemente.`,
                action: () => navigate('#/supplies'),
                btn: 'Gestionar Stock'
            });
        } else if (needles < 50) {
            list.push({
                type: 'warning',
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
                title: 'Modo Enfermedad Activo',
                msg: 'Tus ratios están aumentados un 20%. Recuerda desactivarlo cuando mejores.',
                action: () => navigate('#/profile'),
                btn: 'Configurar'
            });
        }

        // Check Forecast Warning
        const forecastWarn = localStorage.getItem('forecast_warning') === 'true';
        // Check if user dismissed it temporarily (optional logic, for now just show if active)
        if (forecastWarn) {
            list.push({
                id: 'forecast-alert',
                type: 'warning',
                title: 'Tendencia Riesgosa Detectada',
                msg: 'El modelo de predicción indica un posible riesgo de hipo/hiperglucemia en las próximas horas.',
                action: () => navigate('#/forecast'),
                btn: 'Ver Análisis',
                dismissable: true
            });
        }

        setAlerts(list);
    }, []);

    const dismissAlert = (id) => {
        if (id === 'forecast-alert') {
            // Logic to mute alert for some time? Or just clear for this session?
            // User requested "dismiss once read".
            // We can set a flag 'forecast_warning_dismissed_until' or just toggle warning off if that makes sense.
            // But 'forecast_warning' stored by HomePage updates on every fetch. 
            // So we need a side-flag.

            // Simple approach: Store timestamp of dismissal
            localStorage.setItem('forecast_warning_dismissed_at', Date.now().toString());
            // Remove from local state
            setAlerts(prev => prev.filter(a => a.id !== id));
            // Force header update
            window.dispatchEvent(new Event('forecast-update'));
        }
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
                                        onClick={() => dismissAlert(alert.id)}
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
