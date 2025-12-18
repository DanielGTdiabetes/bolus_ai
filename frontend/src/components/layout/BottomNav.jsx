import React from 'react';
import { navigate } from '../../modules/core/router';

export function BottomNav({ activeTab = 'home' }) {
    const items = [
        { id: 'home', icon: '🏠', label: 'Inicio', hash: '#/' },
        { id: 'scan', icon: '📷', label: 'Escanear', hash: '#/scan' },
        { id: 'bolus', icon: '💉', label: 'Bolo', hash: '#/bolus' },
        { id: 'basal', icon: '📉', label: 'Basal', hash: '#/basal' },
        { id: 'menu', icon: '☰', label: 'Menú', hash: '#/menu' }
    ];

    return (
        <nav className="bottom-nav" style={{ overflowX: 'auto', justifyContent: 'flex-start', gap: '0.5rem', paddingLeft: '0.5rem', paddingRight: '0.5rem' }}>
            {items.map(item => (
                <button
                    key={item.id}
                    className={`nav-btn ${activeTab === item.id ? 'active' : ''}`}
                    onClick={() => navigate(item.hash)}
                    style={{ minWidth: '60px', width: 'auto', padding: '0.5rem 0.2rem' }}
                >
                    <span className="nav-icon">{item.icon}</span>
                    <span className="nav-lbl">{item.label}</span>
                </button>
            ))}
        </nav>
    );
}
