import React from 'react';
import { navigate } from '../../modules/core/navigation';

export function BottomNav({ activeTab = 'home' }) {
    const items = [
        { id: 'home', icon: '⌂', label: 'Inicio', hash: '#/', aliases: ['home'] },
        { id: 'companion', icon: '♥', label: 'Compañero', hash: '#/notifications', aliases: ['companion', 'notifications', 'forecast', 'basal', 'suggestions'] },
        { id: 'scan', icon: '◎', label: 'Escanear', hash: '#/scan', aliases: ['scan', 'scale'] },
        { id: 'bolus', icon: '+', label: 'Bolo', hash: '#/bolus', aliases: ['bolus'] },
        { id: 'menu', icon: '☰', label: 'Más', hash: '#/menu', aliases: ['menu', 'history', 'settings', 'learning', 'supplies'] }
    ];

    return (
        <nav className="bottom-nav" aria-label="Navegación principal">
            {items.map(item => (
                <button
                    key={item.id}
                    className={`nav-btn ${item.aliases.includes(activeTab) ? 'active' : ''}`}
                    onClick={() => navigate(item.hash)}
                    aria-current={item.aliases.includes(activeTab) ? 'page' : undefined}
                >
                    <span className="nav-icon">{item.icon}</span>
                    <span className="nav-lbl">{item.label}</span>
                </button>
            ))}
        </nav>
    );
}
