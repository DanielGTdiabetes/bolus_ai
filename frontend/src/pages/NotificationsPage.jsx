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

        setAlerts(list);
    }, []);

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
                            padding: '1rem'
                        }}>
                            <div style={{ fontWeight: 700, marginBottom: '0.5rem', color: '#1e293b' }}>
                                {alert.type === 'danger' && '⚠️ '}
                                {alert.type === 'warning' && '⚠️ '}
                                {alert.type === 'info' && 'ℹ️ '}
                                {alert.title}
                            </div>
                            <p style={{ fontSize: '0.9rem', color: '#475569', marginBottom: '1rem' }}>{alert.msg}</p>
                            <Button onClick={alert.action} size="sm" style={{ width: '100%', background: '#f1f5f9', color: '#334155', border: '1px solid #cbd5e1' }}>
                                {alert.btn}
                            </Button>
                        </div>
                    ))}
                </div>
            </main>
            <BottomNav />
        </>
    );
}
