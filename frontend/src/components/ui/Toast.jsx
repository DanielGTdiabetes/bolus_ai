import React, { useEffect, useState } from 'react';

/**
 * A simple global toast system.
 * Usage:
 * import { showToast } from '../components/ui/Toast';
 * ...
 * showToast("Mensaje de éxito", "success");
 */

let toastListeners = [];
let toastIdCounter = 0;

export function showToast(msg, type = 'success', duration = 3000) {
    const id = ++toastIdCounter;
    const event = { id, msg, type, duration };
    toastListeners.forEach(cb => cb(event));
}

export function ToastContainer() {
    const [toasts, setToasts] = useState([]);

    useEffect(() => {
        const handler = (event) => {
            setToasts(prev => [...prev, event]);
            // Auto remove
            setTimeout(() => {
                setToasts(prev => prev.filter(t => t.id !== event.id));
            }, event.duration);
        };
        toastListeners.push(handler);
        return () => {
            toastListeners = toastListeners.filter(cb => cb !== handler);
        };
    }, []);

    return (
        <div style={{
            position: 'fixed',
            bottom: '20px',
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 9999,
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
            pointerEvents: 'none' // Click through empty space
        }}>
            {toasts.map(toast => (
                <div key={toast.id} className="fade-in-up" style={{
                    background: toast.type === 'error' ? '#fecaca' : (toast.type === 'warning' ? '#fef3c7' : '#dcfce7'),
                    color: toast.type === 'error' ? '#991b1b' : (toast.type === 'warning' ? '#92400e' : '#166534'),
                    padding: '12px 24px',
                    borderRadius: '50px',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    pointerEvents: 'auto',
                    border: '1px solid rgba(0,0,0,0.05)'
                }}>
                    <span>{toast.type === 'error' ? '⚠️' : (toast.type === 'warning' ? '✋' : '✅')}</span>
                    {toast.msg}
                </div>
            ))}
        </div>
    );
}
