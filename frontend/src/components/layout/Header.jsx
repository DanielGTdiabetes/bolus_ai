import React, { useState } from 'react';
import { useStore } from '../../hooks/useStore';
import { navigate } from '../../modules/core/navigation';
import { getCompanionActiveEpisodes, getNotificationsSummary } from '../../lib/api';

export function Header({ title = "Bolus AI", showBack = false, notificationActive = false, onNotificationClick }) {
    const user = useStore(s => s.user);
    const dbMode = useStore(s => s.dbMode);
    const [hasSupplyWarning, setHasSupplyWarning] = useState(false);
    const [hasBackendNotifications, setHasBackendNotifications] = useState(false);

    React.useEffect(() => {
        const check = () => {
            try {
                const n = parseInt(localStorage.getItem('supplies_needles') || '100');
                const s = parseInt(localStorage.getItem('supplies_sensors') || '10');
                if (n < 20 || s < 4) return true;

                // Also check Sick Mode?
                const sick = localStorage.getItem('sick_mode_enabled') === 'true';
                if (sick) return true;

                // Check Forecast Warning
                const forecastWarn = localStorage.getItem('forecast_warning') === 'true';
                if (forecastWarn) {
                    // Check if dismissed recently (e.g., within last 30 mins)
                    const dismissedAt = parseInt(localStorage.getItem('forecast_warning_dismissed_at') || '0');
                    // If dismissed less than 30 mins ago, don't show red dot
                    if (Date.now() - dismissedAt > 30 * 60 * 1000) {
                        return true;
                    }
                }

                return false;
            } catch { return false; }
        };

        const checkBackend = async () => {
            try {
                const [summary, companion] = await Promise.all([
                    getNotificationsSummary(),
                    getCompanionActiveEpisodes(),
                ]);
                const hasCompanionAlert = (companion?.episodes || []).some(item =>
                    !['snoozed', 'monitoring'].includes(item.status) && item.severity !== 'info'
                );
                setHasBackendNotifications(Boolean(summary?.has_unread || hasCompanionAlert));
            } catch {
                // Silent fail
            }
        };

        setHasSupplyWarning(check());
        checkBackend();

        // Listen for storage events to update immediately if forecast changes
        const handleStorage = () => setHasSupplyWarning(check());
        window.addEventListener('storage', handleStorage);
        // Custom event for same-window updates
        window.addEventListener('forecast-update', handleStorage);
        window.addEventListener('companion-update', checkBackend);

        // Interval for backend notifications (every 60s)
        const interval = setInterval(checkBackend, 60000);

        return () => {
            window.removeEventListener('storage', handleStorage);
            window.removeEventListener('forecast-update', handleStorage);
            window.removeEventListener('companion-update', checkBackend);
            clearInterval(interval);
        };
    }, []);

    const handleNotifClick = () => {
        if (onNotificationClick) {
            onNotificationClick();
        } else {
            // Default: Check where to go
            navigate('#/notifications');
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
                    <button className="header-action-button" onClick={() => window.history.back()} aria-label="Volver">‹</button>
                ) : (
                    <button className="brand-mark" onClick={() => navigate('#/')} aria-label="Ir al inicio">B</button>
                )}

                <div className="header-title-group">
                    <div className="header-title">{title}</div>
                    {!showBack && <div className="header-subtitle">Bolus AI · tu compañero</div>}
                </div>

                <div className="header-action" style={{ position: 'relative' }}>
                    <button className="ghost" onClick={handleNotifClick}>🔔</button>
                    {(notificationActive || hasSupplyWarning || hasBackendNotifications) && (
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
