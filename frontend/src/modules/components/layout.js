import { state } from '../core/store.js';
import { navigate } from '../core/router.js';
import { logout } from '../../lib/api.js';

// Global Handler for Profile Menu (usually attached to window in main, but we can manage it here via inline onclicks if possible, or bind globally)
// The HTML string uses 'toggleProfileMenu()'. We need to expose it.
window.toggleProfileMenu = function () {
  const menu = document.getElementById('profile-menu');
  if (menu) {
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
  }
};

// Close menu when clicking outside
window.addEventListener('click', (e) => {
  const menu = document.getElementById('profile-menu');
  const btn = document.getElementById('profile-btn');
  if (menu && btn && !menu.contains(e.target) && !btn.contains(e.target)) {
    menu.style.display = 'none';
  }
});

export function renderHeader(title = "Bolus AI", showBack = false) {
  if (!state.user) return "";
  return `
      <header class="topbar">
        ${showBack
      ? `<div class="header-action" onclick="window.history.back()">‹</div>`
      : `<div class="header-profile" style="position:relative">
            <button id="profile-btn" class="ghost" onclick="toggleProfileMenu()">👤</button>
            <div id="profile-menu" style="display:none; position:absolute; top:40px; left:0; background:white; border:1px solid #e2e8f0; border-radius:12px; box-shadow:0 10px 15px -3px rgba(0,0,0,0.1); z-index:100; min-width:180px; overflow:hidden;">
                <div style="padding:10px; border-bottom:1px solid #f1f5f9; background:#f8fafc; font-size:0.8rem; font-weight:600; color:#64748b;">${state.user.username || 'Usuario'}</div>
                <button class="menu-item" onclick="navigate('#/change-password')" style="width:100%; text-align:left; background:none; border:none; padding:12px 16px; cursor:pointer; font-size:0.9rem; color:#334155; display:flex; align-items:center; gap:8px;">
                   <span>🔑</span> Cambiar Contraseña
                </button>
                <button class="menu-item" onclick="logout()" style="width:100%; text-align:left; background:none; border:none; padding:12px 16px; cursor:pointer; font-size:0.9rem; border-top:1px solid #f1f5f9; color:#ef4444; display:flex; align-items:center; gap:8px;">
                   <span>🚪</span> Cerrar Sesión
                </button>
            </div>
         </div>`}
        <div class="header-title-group">
          <div class="header-title">${title}</div>
          ${!showBack ? `<div class="header-subtitle">Tu asistente de diabetes</div>` : ''}
        </div>
        <div class="header-action has-dot">
          <button id="notifications-btn" class="ghost">🔔</button>
        </div>
      </header>
    `;
}

export function renderBottomNav(activeTab = 'home') {
  const items = [
    { id: 'home', icon: '🏠', label: 'Inicio', hash: '#/' },
    { id: 'scan', icon: '📷', label: 'Escanear', hash: '#/scan' },
    { id: 'bolus', icon: '💉', label: 'Bolo', hash: '#/bolus' },
    { id: 'basal', icon: '📉', label: 'Basal', hash: '#/basal' },
    { id: 'history', icon: '⏱️', label: 'Hist.', hash: '#/history' },
    { id: 'patterns', icon: '📊', label: 'Patrones', hash: '#/patterns' },
    { id: 'suggestions', icon: '💡', label: 'Suger.', hash: '#/suggestions' },
    { id: 'settings', icon: '⚙️', label: 'Ajustes', hash: '#/settings' }
  ];

  const html = items.map(item => {
    const isActive = activeTab === item.id;
    return `
      <button class="nav-btn ${isActive ? 'active' : ''}" onclick="navigate('${item.hash}')" style="min-width: 60px; width:auto; padding: 0.5rem 0.2rem;">
         <span class="nav-icon">${item.icon}</span>
         <span class="nav-lbl">${item.label}</span>
      </button>
    `;
  }).join('');

  return `
    <nav class="bottom-nav" style="overflow-x: auto; justify-content: flex-start; gap: 0.5rem; padding-left:0.5rem; padding-right:0.5rem;">
       ${html}
    </nav>
  `;
}
