import React, { useState } from 'react';
import { useStore } from '../../hooks/useStore';
import { navigate } from '../../modules/core/router';
import { logout } from '../../lib/api';

export function Header({ title = "Bolus AI", showBack = false, notificationActive = false, onNotificationClick }) {
    const user = useStore(s => s.user);
    const dbMode = useStore(s => s.dbMode);
    const [menuOpen, setMenuOpen] = useState(false);
    const [hasSupplyWarning, setHasSupplyWarning] = useState(false);

    React.useEffect(() => {
        const check = () => {
            try {
                const n = parseInt(localStorage.getItem('supplies_needles') || '100');
                const s = parseInt(localStorage.getItem('supplies_sensors') || '10');
                if (n < 20 || s < 4) return true;

                // Also check Sick Mode?
                const sick = localStorage.getItem('sick_mode_enabled') === 'true';
                if (sick) return true;

                return false;
            } catch { return false; }
        };
        setHasSupplyWarning(check());
    }, []);

    const handleNotifClick = () => {
        if (onNotificationClick) {
            onNotificationClick();
        } else {
            // Default: Check where to go
            if (hasSupplyWarning) {
                // If sick mode or supplies, show notifications page or specific?
                // Let's go to supplies if that's the issue?
                // Actually, standard behavior: Go to Notifications Page.
                // We will create/ensure that page exists.
                navigate('#/notifications');
            } else {
                navigate('#/notifications');
            }
        }
    };

    if (!user) return null;

    return (
        <>
            {/* ... (keep existing dbMode alert if present, though not shown in strict partial replacement usually) */}
            {dbMode === 'memory' && (
                <div style={{
                    background: '#fff7ed', color: '#c2410c', fontSize: '0.8rem', padding: '0.4rem',
                    textAlign: 'center', fontWeight: 600, borderBottom: '1px solid #ffedd5'
                }}>
                    ⚠️ MODO MEMORIA: Datos volátiles
                </div>
            )}

            <header className="topbar">
                {showBack ? (
                    <div className="header-action" onClick={() => window.history.back()} style={{ cursor: 'pointer' }}>‹</div>
                ) : (
                    <div className="header-profile" style={{ position: 'relative' }}>
                        <button className="ghost" onClick={() => setMenuOpen(!menuOpen)}>👤</button>

                        {menuOpen && (
                            <>
                                <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 99 }} onClick={() => setMenuOpen(false)} />
                                <div style={{
                                    position: 'absolute', top: '40px', left: 0, background: 'white',
                                    border: '1px solid #e2e8f0', borderRadius: '12px',
                                    boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)', zIndex: 100, minWidth: '180px', overflow: 'hidden'
                                }}>
                                    <div style={{ padding: '10px', borderBottom: '1px solid #f1f5f9', background: '#f8fafc', fontSize: '0.8rem', fontWeight: 600, color: '#64748b' }}>
                                        {user.username || 'Usuario'}
                                    </div>
                                    <button onClick={() => navigate('#/profile')} style={{
                                        width: '100%', textAlign: 'left', background: 'none', border: 'none',
                                        padding: '12px 16px', cursor: 'pointer', fontSize: '0.9rem', color: '#334155', display: 'flex', gap: '8px'
                                    }}>
                                        <span>👤</span> Mi Perfil
                                    </button>
                                    <button onClick={() => logout()} style={{
                                        width: '100%', textAlign: 'left', background: 'none', border: 'none',
                                        padding: '12px 16px', cursor: 'pointer', fontSize: '0.9rem',
                                        borderTop: '1px solid #f1f5f9', color: '#ef4444', display: 'flex', gap: '8px'
                                    }}>
                                        <span>🚪</span> Cerrar Sesión
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                )}

                <div className="header-title-group">
                    <div className="header-title">{title}</div>
                    {!showBack && <div className="header-subtitle">Tu asistente de diabetes</div>}
                </div>

                <div className="header-action" style={{ position: 'relative' }}>
                    <button className="ghost" onClick={handleNotifClick}>🔔</button>
                    {(notificationActive || hasSupplyWarning) && (
                        <div style={{
                            position: 'absolute', top: '8px', right: '8px', width: '10px', height: '10px',
                            background: '#ef4444', borderRadius: '50%', border: '2px solid white'
                        }} />
                    )}
                </div>
            </header>
        </>
    );
}
