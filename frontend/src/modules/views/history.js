import { navigate, ensureAuthenticated } from '../core/router.js';
import { renderHeader, renderBottomNav } from '../components/layout.js';
import { fetchTreatments, getLocalNsConfig } from '../../lib/api.js';

export async function renderHistory() {
    const app = document.getElementById("app");
    app.innerHTML = `
      ${renderHeader("Historial", true)}
      <main class="page">
        <!-- Stats Row -->
        <div class="metrics-grid">
            <div class="metric-tile" style="background:#eff6ff; text-align:center; padding:1.5rem 0.5rem">
                <div style="font-size:1.5rem; font-weight:800; color:#2563eb" id="hist-daily-insulin">--</div>
                <div style="font-size:0.7rem; color:#93c5fd; font-weight:700">INSULINA HOY</div>
            </div>
            <div class="metric-tile" style="background:#fff7ed; text-align:center; padding:1.5rem 0.5rem">
                <div style="font-size:1.5rem; font-weight:800; color:#f97316" id="hist-daily-carbs">--</div>
                <div style="font-size:0.7rem; color:#fdba74; font-weight:700">CARBOS HOY</div>
            </div>
        </div>

        <h4 style="margin-bottom:1rem; color:var(--text-muted)">Últimas Transacciones</h4>
        
        <div class="activity-list" id="full-history-list">
             <div class="spinner">Cargando...</div>
        </div>
      </main>
      ${renderBottomNav('history')}
  `;

    // Fetch Logic
    try {
        const config = getLocalNsConfig();
        if (!config || !config.url) throw new Error("Configura Nightscout para ver el historial.");

        // We fetch last 50 treatments
        const treatments = await fetchTreatments({ ...config, count: 50 });

        const listContainer = document.getElementById('full-history-list');
        listContainer.innerHTML = "";

        let todayInsulin = 0;
        let todayCarbs = 0;
        const today = new Date().toDateString();

        const validItems = treatments.filter(t => {
            const u = parseFloat(t.insulin);
            const c = parseFloat(t.carbs);
            return (u > 0 || c > 0);
        });

        if (validItems.length === 0) {
            listContainer.innerHTML = "<div class='hint' style='text-align:center; padding:2rem;'>No hay historial disponible</div>";
        }

        validItems.forEach(t => {
            const date = new Date(t.created_at || t.timestamp || t.date);
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            const u = parseFloat(t.insulin);
            const c = parseFloat(t.carbs);

            if (date.toDateString() === today) {
                if (u > 0) todayInsulin += u;
                if (c > 0) todayCarbs += c;
            }

            const isBolus = u > 0;
            const isCarb = c > 0;

            const el = document.createElement('div');
            el.className = "activity-item";
            const icon = isBolus ? "💉" : "🍪";
            const typeLbl = t.enteredBy ? t.enteredBy : "Entrada";

            let mainVal = "";
            if (isBolus) mainVal += `${u} U `;
            if (isCarb) mainVal += `${c} g`;

            el.innerHTML = `
            <div class="act-icon" style="${isBolus ? '' : 'background:#fff7ed; color:#f97316'}">${icon}</div>
            <div class="act-details">
                <div class="act-val">${mainVal}</div>
                <div class="act-sub">${t.notes || typeLbl}</div>
            </div>
            <div class="act-time">${timeStr}</div>
         `;
            listContainer.appendChild(el);
        });

        document.getElementById('hist-daily-insulin').textContent = todayInsulin.toFixed(1);
        document.getElementById('hist-daily-carbs').textContent = Math.round(todayCarbs);

    } catch (e) {
        if (document.getElementById('full-history-list'))
            document.getElementById('full-history-list').innerHTML = `<div class="error-msg">${e.message}</div>`;
    }
}
