import { state } from '../core/store.js';
import { ensureAuthenticated } from '../core/router.js';
import { renderHeader, renderBottomNav } from '../components/layout.js';
import {
    getBasalAdvice,
    getBasalTimeline,
    getBasalEntries,
    createBasalEntry,
    createBasalCheckin,
    evaluateBasalChange,
    runNightScan,
    getLocalNsConfig
} from '../../lib/api.js';

export async function renderBasal() {
    if (!ensureAuthenticated()) return;
    const app = document.getElementById("app");

    app.innerHTML = `
    ${renderHeader("Basal Advisor", true)}
    <main class="page">
        <!-- 0. Manual Entry Block -->
        <section class="card" style="margin-bottom:1.5rem">
            <h3 style="margin:0 0 1rem 0">Registrar / Check-in</h3>
            
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:0.5rem; margin-bottom:1rem">
                <div>
                   <label style="font-size:0.75rem; font-weight:700; color:#64748b; margin-bottom:0.25rem; display:block">DOSIS (U)</label>
                   <input type="number" id="basal-u-input" step="0.5" placeholder="0.0" style="width:100%; padding:0.5rem; font-size:1.1rem; border:1px solid #cbd5e1; border-radius:6px">
                </div>
                <div>
                   <label style="font-size:0.75rem; font-weight:700; color:#64748b; margin-bottom:0.25rem; display:block">FECHA/HORA</label>
                   <input type="datetime-local" id="basal-dt-input" style="width:100%; padding:0.5rem; font-size:0.9rem; border:1px solid #cbd5e1; border-radius:6px">
                </div>
            </div>

            <div id="manual-bg-row" class="hidden" style="margin-bottom:1rem; padding:0.8rem; background:#f8fafc; border-radius:8px">
                 <label style="font-size:0.75rem; font-weight:700; color:#64748b; margin-bottom:0.25rem; display:block">GLUCOSA MANUAL (mg/dL)</label>
                 <div style="display:flex; gap:0.5rem">
                    <input type="number" id="manual-bg-input" placeholder="Check-in BG" style="flex:1; padding:0.5rem; border:1px solid #cbd5e1; border-radius:6px">
                     <button id="btn-save-manual" class="btn-primary" style="padding:0.5rem 1rem">Guardar</button>
                 </div>
            </div>

            <div style="display:flex; gap:0.5rem">
                <button id="btn-save-simple" class="btn-ghost" style="flex:1; border:1px solid #cbd5e1">Solo Guardar</button>
                <button id="btn-checkin-wake" class="btn-primary" style="flex:1.5">☀️ Al Levantarme</button>
            </div>
            <button id="btn-scan-last-night" class="btn-ghost" style="margin-top:0.8rem; width:100%; font-size:0.8rem; border:1px dashed #cbd5e1">🌙 Analizar Noche (00h-06h)</button>
            
            <div id="basal-action-msg" style="margin-top:0.5rem; font-size:0.85rem; color:#64748b; min-height:1.2em"></div>
        </section>

        <!-- 1. Advice Block -->
        <section class="card" style="margin-bottom:1.5rem; border-left:4px solid transparent" id="basal-advice-card">
            <h3 style="margin:0 0 0.5rem 0">Estado Basal</h3>
            <div id="basal-advice-content" style="font-size:0.9rem; color:#64748b">
                <div class="spinner">Analizando...</div>
            </div>
        </section>

        <!-- 2. Impact Evaluation Block -->
        <section class="card" style="margin-bottom:1.5rem">
             <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem">
                <h3 style="margin:0">Impacto Cambios</h3>
                <span style="font-size:0.7rem; background:#f1f5f9; padding:2px 6px; border-radius:4px">Memoria de efecto</span>
             </div>
             
             <div id="basal-eval-result" style="margin-bottom:1rem; display:none"></div>
             
             <div style="display:flex; gap:0.5rem">
                 <button id="btn-eval-7" class="btn-secondary" style="flex:1; font-size:0.85rem">📊 Evaluar (7 días)</button>
                 <button id="btn-eval-14" class="btn-ghost" style="flex:1; font-size:0.85rem">14 días</button>
             </div>
        </section>

        <!-- 3. Timeline Block -->
        <section>
            <h3 style="margin-bottom:1rem; color:#64748b">Timeline (14 días)</h3>
            <div class="card" style="padding:0; overflow:hidden">
                <div style="overflow-x:auto">
                    <table style="width:100%; text-align:left; border-collapse:collapse; font-size:0.85rem">
                        <thead style="background:#f8fafc; color:#64748b; font-size:0.75rem">
                            <tr>
                                <th style="padding:0.75rem">Fecha</th>
                                <th style="padding:0.75rem">Despertar</th>
                                <th style="padding:0.75rem">Noche</th>
                            </tr>
                        </thead>
                        <tbody id="basal-timeline-body">
                           <tr><td colspan="3" style="text-align:center; padding:1rem">Cargando...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

    </main>
    ${renderBottomNav('basal')}
  `;

    // --- LOGIC ---

    // 0. Bind Manual Controls
    const uInput = document.getElementById('basal-u-input');
    const dtInput = document.getElementById('basal-dt-input');
    // Set default datetime to now (local)
    const pad = (n) => n < 10 ? '0' + n : n;
    const nowFn = new Date();
    dtInput.value = `${nowFn.getFullYear()}-${pad(nowFn.getMonth() + 1)}-${pad(nowFn.getDate())}T${pad(nowFn.getHours())}:${pad(nowFn.getMinutes())}`;

    // Helper to save dose
    async function saveDoseOnly() {
        const uVal = parseFloat(uInput.value);
        const dtVal = dtInput.value;
        const msgEl = document.getElementById('basal-action-msg');

        if (isNaN(uVal) || uVal <= 0) {
            msgEl.textContent = "⚠️ Dosis requerida."; msgEl.style.color = "var(--danger)"; return false;
        }
        msgEl.textContent = "Guardando dosis...";
        const dateObj = new Date(dtVal);
        try {
            await createBasalEntry({
                dose_u: uVal,
                created_at: dateObj.toISOString(),
                effective_from: dateObj.toISOString().split('T')[0]
            });
            return true;
        } catch (e) {
            msgEl.textContent = "Error: " + e.message; msgEl.style.color = "var(--danger)"; return false;
        }
    }

    document.getElementById('btn-save-simple').onclick = async () => {
        const ok = await saveDoseOnly();
        if (ok) {
            document.getElementById('basal-action-msg').textContent = "✅ Dosis guardada.";
            document.getElementById('basal-action-msg').style.color = "var(--success)";
            setTimeout(() => renderBasal(), 1000); // Reload
        }
    };

    document.getElementById('btn-checkin-wake').onclick = async () => {
        // 1. Save dose
        const ok = await saveDoseOnly();
        if (!ok) return;

        const msgEl = document.getElementById('basal-action-msg');

        // 2. Check Nightscout
        const nsConfig = getLocalNsConfig();
        const dtVal = dtInput.value;
        const dateObj = new Date(dtVal);

        if (nsConfig && nsConfig.url) {
            msgEl.textContent = "Obteniendo glucosa...";
            try {
                await createBasalCheckin({
                    nightscout_url: nsConfig.url,
                    nightscout_token: nsConfig.token,
                    created_at: dateObj.toISOString()
                });
                msgEl.textContent = "✅ Guardado y analizado.";
                setTimeout(() => renderBasal(), 1000);
            } catch (e) {
                msgEl.textContent = "Error fetch NS: " + e.message;
                // Fallback manual?
            }
        } else {
            // Show manual
            document.getElementById('manual-bg-row').classList.remove('hidden');
            msgEl.textContent = "⚠️ Indica glucosa manual (Nightscout no config).";
            msgEl.style.color = "var(--warning)";
        }
    };

    document.getElementById('btn-save-manual').onclick = async () => {
        const bgVal = parseFloat(document.getElementById('manual-bg-input').value);
        const msgEl = document.getElementById('basal-action-msg');
        if (isNaN(bgVal)) { alert("Indica BG válida"); return; }

        const dtVal = dtInput.value;
        const dateObj = new Date(dtVal);

        try {
            msgEl.textContent = "Guardando check-in...";
            await createBasalCheckin({
                manual_bg: bgVal,
                manual_trend: "Manual",
                created_at: dateObj.toISOString()
            });
            msgEl.textContent = "✅ Check-in guardado.";
            setTimeout(() => renderBasal(), 1000);
        } catch (e) {
            msgEl.textContent = "Error: " + e.message;
        }
    };

    document.getElementById('btn-scan-last-night').onclick = async () => {
        const config = getLocalNsConfig();
        if (!config || !config.url) { alert("Configura Nightscout para analizar."); return; }

        const btn = document.getElementById('btn-scan-last-night');
        const original = btn.textContent;
        btn.textContent = "Analizando...";
        btn.disabled = true;

        try {
            // Default to today (which scans previous night 00-06)
            await runNightScan(config);
            renderBasal();
        } catch (e) {
            alert(e.message);
        } finally {
            btn.textContent = original;
            btn.disabled = false;
        }
    };

    // 1. Load Advice (3 days default)
    try {
        const advice = await getBasalAdvice(3);
        const card = document.getElementById('basal-advice-card');
        const content = document.getElementById('basal-advice-content');

        let color = "#64748b"; // default
        let icon = "ℹ️";

        if (advice.message.includes("OK")) {
            color = "var(--success)";
            icon = "✅";
        } else if (advice.message.includes("hipoglucemias")) {
            color = "var(--danger)";
            icon = "🚨";
        } else if (advice.message.includes("alza") || advice.message.includes("baja")) {
            color = "var(--warning)";
            icon = "⚠️";
        }

        card.style.borderLeftColor = color;

        content.innerHTML = `
        <div style="display:flex; gap:0.5rem; align-items:flex-start">
            <div style="font-size:1.2rem">${icon}</div>
            <div>
                <div style="font-weight:600; color:#334155; margin-bottom:0.2rem">${advice.message}</div>
                <div style="font-size:0.75rem; color:#94a3b8">
                   Confianza: <span style="text-transform:uppercase; font-weight:700">${advice.confidence === 'high' ? 'Alta' : (advice.confidence === 'medium' ? 'Media' : 'Baja (faltan datos)')}</span>
                </div>
            </div>
        </div>
    `;
    } catch (e) {
        const content = document.getElementById('basal-advice-content');
        if (content) content.innerHTML = `<div class="error">Error: ${e.message}</div>`;
    }

    // 2. Load Timeline
    try {
        const tl = await getBasalTimeline(14);
        const tbody = document.getElementById('basal-timeline-body');

        if (tl.items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; padding:1rem">No hay datos recientes.</td></tr>`;
        } else {
            tbody.innerHTML = tl.items.map(item => {
                const d = new Date(item.date);
                const dateStr = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' });

                let wakeHtml = "--";
                if (item.wake_bg !== null) {
                    wakeHtml = `<strong>${Math.round(item.wake_bg)}</strong>`;
                    if (item.wake_trend) wakeHtml += ` <small style="color:#94a3b8">${item.wake_trend}</small>`;
                }

                let nightHtml = `<span style="color:#cbd5e1">--</span>`;
                if (item.night_had_hypo === true) {
                    nightHtml = `<span style="color:var(--danger); font-weight:700">🌙 < 70</span>`;
                    if (item.night_events_below_70 > 1) nightHtml += ` (${item.night_events_below_70})`;
                } else if (item.night_had_hypo === false) {
                    nightHtml = `<span style="color:var(--success)">OK</span>`;
                } else {
                    nightHtml = `<button onclick="handleScanNight('${item.date}')" style="font-size:0.7rem; padding:2px 6px; border:1px solid #cbd5e1; background:transparent; border-radius:4px">🔍 Analizar</button>`;
                }

                return `
                <tr style="border-bottom:1px solid #f1f5f9">
                    <td style="padding:0.75rem; color:#334155">${dateStr}</td>
                    <td style="padding:0.75rem; color:#334155">${wakeHtml}</td>
                    <td style="padding:0.75rem">${nightHtml}</td>
                </tr>
             `;
            }).join('');
        }
    } catch (e) {
        const tbody = document.getElementById('basal-timeline-body');
        if (tbody) tbody.innerHTML = `<tr><td colspan="3" class="error">Error: ${e.message}</td></tr>`;
    }

    // 3. Eval Handlers Logic
    // Eval handlers require attaching events to dynamically created buttons
    // The original code used global or onclick handlers. We can keep it or use delegation.
    // Delegation is cleaner.
    // Actually, we defined onclicks inline. 
    // We need to attach listeners via ID after render.

    const handleEval = async (days) => {
        const resContainer = document.getElementById('basal-eval-result');
        const btn = document.getElementById(`btn-eval-${days}`);
        if (!btn) return;

        const originalText = btn.textContent;
        btn.textContent = "Evaluando...";
        btn.disabled = true;
        resContainer.style.display = 'none';

        try {
            const res = await evaluateBasalChange(days);

            let color = "#64748b";
            let icon = "ℹ️";
            if (res.result === 'improved') { color = "var(--success)"; icon = "✅"; }
            if (res.result === 'worse') { color = "var(--danger)"; icon = "📉"; }
            if (res.result === 'insufficient') { color = "#f59e0b"; icon = "❓"; }

            resContainer.innerHTML = `
             <div style="background:#f8fafc; padding:1rem; border-radius:8px; border-left:4px solid ${color}">
                <div style="font-weight:700; color:${color}">${icon} ${res.result.toUpperCase()}</div>
                <div style="margin-top:0.4rem; font-size:0.9rem; color:#334155">${res.summary}</div>
             </div>
          `;
            resContainer.style.display = 'block';

        } catch (e) {
            alert("Error: " + e.message);
        } finally {
            btn.textContent = originalText;
            btn.disabled = false;
        }
    };

    const btn7 = document.getElementById('btn-eval-7');
    if (btn7) btn7.onclick = () => handleEval(7);

    const btn14 = document.getElementById('btn-eval-14');
    if (btn14) btn14.onclick = () => handleEval(14);

    // Global handleScanNight is tricky if modules are isolated.
    // We attach it to window ONLY if we rely on inline onclick="handleScanNight..."
    // The render string above uses inline onclick.
    // So we must expose it.
    window.handleScanNight = async (dateStr) => {
        try {
            const config = getLocalNsConfig();
            if (!config || !config.url) {
                alert("Configura Nightscout primero.");
                return;
            }
            const btn = document.activeElement;
            if (btn) btn.textContent = "🔍...";

            await runNightScan(config, dateStr);
            renderBasal(); // Refresh logic calling itself
        } catch (e) {
            alert(e.message);
        }
    };
}
