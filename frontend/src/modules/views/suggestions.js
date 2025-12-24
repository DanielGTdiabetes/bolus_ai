import { getCalcParams, saveCalcParams } from '../core/store.js';
import { ensureAuthenticated } from '../core/router.js';
import { renderHeader, renderBottomNav } from '../components/layout.js';
import {
    getSuggestions,
    generateSuggestions,
    getEvaluations,
    evaluateSuggestion,
    rejectSuggestion,
    acceptSuggestion
} from '../../lib/api.js';

export async function renderSuggestions() {
    if (!ensureAuthenticated()) return;
    const app = document.getElementById("app");

    app.innerHTML = `
        ${renderHeader("Sugerencias", true)}
        <main class="page">
            <div style="display:flex; margin-bottom:1.5rem; background:white; padding:4px; border-radius:12px; border:1px solid #e2e8f0;">
                <button id="tab-pending" class="ws-tab active" style="flex:1; border:none; background:transparent; padding:0.6rem; border-radius:8px; font-weight:600; color:var(--text-muted); cursor:pointer;">Pendientes</button>
                <button id="tab-accepted" class="ws-tab" style="flex:1; border:none; background:transparent; padding:0.6rem; border-radius:8px; font-weight:600; color:var(--text-muted); cursor:pointer;">Aceptadas</button>
            </div>
            
            <div id="view-pending">
                <div style="display:flex; justify-content:flex-end; margin-bottom:1rem;">
                    <button id="btn-gen-sug" class="btn-primary" style="font-size:0.9rem; padding:0.5rem 1rem;">✨ Generar Nuevas</button>
                </div>
                <div id="sug-list" style="display:flex; flex-direction:column; gap:1rem;">
                    <div class="spinner">Cargando sugerencias...</div>
                </div>
            </div>
            
            <div id="view-accepted" class="hidden">
                 <div id="sug-history" style="display:flex; flex-direction:column; gap:1rem;">
                    <div class="spinner">Cargando historial...</div>
                 </div>
            </div>

        </main>
        ${renderBottomNav('suggestions')}
        
        <!-- Modal for Acceptance -->
        <dialog id="accept-modal" style="border:none; border-radius:12px; padding:0; width:90%; max-width:400px; box-shadow:0 10px 25px rgba(0,0,0,0.2);">
             <div style="padding:1.5rem;">
                 <h3 style="margin-top:0; color:var(--primary)">Aceptar Cambio</h3>
                 <p id="accept-modal-desc" style="font-size:0.9rem; color:#64748b; margin-bottom:1rem;"></p>
                 
                 <div style="margin-bottom:1rem;">
                    <label style="display:block; font-size:0.8rem; font-weight:600; color:#64748b">Valor Actual</label>
                    <div id="accept-current-val" style="font-size:1.1rem; font-weight:700;">--</div>
                 </div>
                 
                 <div style="margin-bottom:1.5rem;">
                    <label style="display:block; font-size:0.8rem; font-weight:600; color:#64748b">Nuevo Valor</label>
                    <input type="number" id="accept-new-val" step="0.1" style="width:100%; padding:0.8rem; border:1px solid #cbd5e1; border-radius:8px; font-size:1.2rem; font-weight:700;">
                 </div>
                 
                 <div style="display:flex; gap:0.5rem">
                    <button id="btn-modal-cancel" class="btn-ghost" style="flex:1">Cancelar</button>
                    <button id="btn-modal-confirm" class="btn-primary" style="flex:1">Guardar</button>
                 </div>
             </div>
        </dialog>
    `;

    // Tab Switching Logic
    const tabPending = document.getElementById('tab-pending');
    const tabAccepted = document.getElementById('tab-accepted');
    const viewPending = document.getElementById('view-pending');
    const viewAccepted = document.getElementById('view-accepted');

    function switchTab(target) {
        if (target === 'pending') {
            tabPending.classList.add('active'); tabPending.style.background = 'var(--primary-soft)'; tabPending.style.color = 'var(--primary)';
            tabAccepted.classList.remove('active'); tabAccepted.style.background = 'transparent'; tabAccepted.style.color = 'var(--text-muted)';
            viewPending.classList.remove('hidden');
            viewAccepted.classList.add('hidden');
            loadList();
        } else {
            tabAccepted.classList.add('active'); tabAccepted.style.background = 'var(--primary-soft)'; tabAccepted.style.color = 'var(--primary)';
            tabPending.classList.remove('active'); tabPending.style.background = 'transparent'; tabPending.style.color = 'var(--text-muted)';
            viewAccepted.classList.remove('hidden');
            viewPending.classList.add('hidden');
            loadHistory();
        }
    }

    tabPending.onclick = () => switchTab('pending');
    tabAccepted.onclick = () => switchTab('accepted');

    switchTab('pending');

    // --- PENDING LOGIC ---
    const btnGen = document.getElementById('btn-gen-sug');
    const list = document.getElementById('sug-list');

    async function loadList() {
        try {
            const items = await getSuggestions("pending");
            if (items.length === 0) {
                list.innerHTML = `<div style="text-align:center; padding:3rem; color:#94a3b8; font-style:italic;">No hay sugerencias pendientes.</div>`;
                return;
            }

            list.innerHTML = items.map(s => `
                <div class="card" style="border-left:4px solid var(--primary);">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                           <span class="chip" style="background:#e0f2fe; color:#0369a1; text-transform:capitalize;">${s.meal_slot}</span>
                           <span class="chip" style="background:#f1f5f9; color:#475569; text-transform:uppercase;">${s.parameter}</span>
                        </div>
                        <small style="color:#94a3b8">${new Date(s.created_at).toLocaleDateString()}</small>
                    </div>
                    
                    <p style="margin:1rem 0; font-weight:600; line-height:1.4;">${s.reason}</p>
                    
                    <div style="background:#f8fafc; padding:0.8rem; border-radius:6px; font-size:0.85rem; color:#64748b; margin-bottom:1rem;">
                        <strong>Evidencia:</strong> Ventana ${s.evidence.window}. Ratio incidencia: ${Math.round(s.evidence.ratio * 100)}%. (Base ${s.evidence.days} días)
                    </div>
                    
                    <div style="display:flex; gap:0.5rem;">
                         <button onclick="handleReject('${s.id}')" class="btn-ghost" style="color:#b91c1c; border:1px solid #fecaca; flex:1">Rechazar</button>
                         <button onclick="handleAccept('${s.id}', '${s.meal_slot}', '${s.parameter}')" class="btn-primary" style="flex:1">Revisar</button>
                    </div>
                </div>
            `).join('');

        } catch (e) {
            list.innerHTML = `<div class="error">Error: ${e.message}</div>`;
        }
    }

    btnGen.onclick = async () => {
        btnGen.disabled = true;
        btnGen.textContent = "Generando...";
        try {
            const res = await generateSuggestions(30);
            alert(`Sugerencias generadas: ${res.created} nuevas.`);
            loadList();
        } catch (e) {
            alert(e.message);
        } finally {
            btnGen.disabled = false;
            btnGen.textContent = "✨ Generar Nuevas";
        }
    };

    // --- ACCEPTED / HISTORY LOGIC ---
    const histList = document.getElementById('sug-history');

    async function loadHistory() {
        try {
            const [accepted, evaluations] = await Promise.all([
                getSuggestions("accepted"),
                getEvaluations()
            ]);

            const evalMap = {};
            evaluations.forEach(e => evalMap[e.suggestion_id] = e);

            if (accepted.length === 0) {
                histList.innerHTML = `<div style="text-align:center; padding:3rem; color:#94a3b8; font-style:italic;">No hay historial de cambios aceptados.</div>`;
                return;
            }

            histList.innerHTML = accepted.map(s => {
                const ev = evalMap[s.id];
                const resolvedDate = new Date(s.resolved_at);

                const now = new Date();
                const diffTime = Math.abs(now - resolvedDate);
                const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

                let impactHtml = "";

                if (ev) {
                    let color = "#64748b";
                    let icon = "➖";
                    if (ev.result === "improved") { color = "var(--success)"; icon = "✅"; }
                    if (ev.result === "worse") { color = "var(--danger)"; icon = "⚠️"; }
                    if (ev.result === "insufficient") { icon = "❓"; }

                    const scoreInfo = ev.evidence?.before?.score ?
                        `(${Math.round(ev.evidence.before.score * 100)}% ➜ ${Math.round(ev.evidence.after.score * 100)}%)` : "";

                    impactHtml = `
                     <div style="margin-top:1rem; background:#f8fafc; padding:0.8rem; border-radius:8px; border-left:4px solid ${color};">
                        <div style="font-weight:700; color:${color}; font-size:0.9rem;">${icon} Impacto: ${ev.result.toUpperCase()} ${scoreInfo}</div>
                        <p style="font-size:0.85rem; margin:0.5rem 0 0; color:#475569;">${ev.summary}</p>
                        <div style="margin-top:0.5rem; font-size:0.75rem; color:#94a3b8">Evaluado el: ${new Date(ev.evaluated_at || ev.created_at).toLocaleDateString()}</div>
                     </div>
                   `;
                } else {
                    if (diffDays < 7) {
                        impactHtml = `
                         <div style="margin-top:1rem; background:#fff7ed; padding:0.8rem; border-radius:8px; border:1px dashed #fdba74;">
                            <div style="font-size:0.85rem; color:#c2410c;">📉 Faltan datos para evaluar.</div>
                            <small style="color:#9a3412">Han pasado ${diffDays} días (mínimo 7).</small>
                         </div>
                       `;
                    } else {
                        impactHtml = `
                         <div style="margin-top:1rem;">
                            <button onclick="handleEvaluate('${s.id}')" class="btn-secondary" style="font-size:0.85rem; border-color:var(--primary); color:var(--primary);">
                               📊 Evaluar Impacto (7 días)
                            </button>
                         </div>
                       `;
                    }
                }

                return `
                <div class="card" style="border-left:4px solid #cbd5e1;">
                    <div style="display:flex; justify-content:space-between;">
                         <div>
                           <span class="chip" style="background:#f1f5f9; color:#475569; text-transform:capitalize;">${s.meal_slot}</span>
                           <span class="chip" style="background:#f1f5f9; color:#475569; text-transform:uppercase;">${s.parameter}</span>
                         </div>
                         <small style="color:#94a3b8">
                             ${resolvedDate.toLocaleDateString()}
                             <span onclick="handleDeleteHistory('${s.id}')" style="cursor:pointer; margin-left:8px; color:#cbd5e1;" title="Borrar del historial">🗑️</span>
                         </small>
                    </div>
                    <p style="font-size:0.9rem; color:#334155; margin:0.5rem 0;">${s.resolution_note || "Sin nota"}</p>
                    ${impactHtml}
                </div>
                `;
            }).join('');

        } catch (e) {
            histList.innerHTML = `<div class="error">Error: ${e.message}</div>`;
        }
    }

    // GLOBAL HANDLERS for inline onclicks. 
    // We need to expose them on window or bind them differently.
    // We'll expose them on window for now to match HTML string behavior.

    window.handleDeleteHistory = async (id) => {
        if (!confirm("¿Borrar esta sugerencia del historial?")) return;
        try {
            const token = localStorage.getItem('bolusai_token') || localStorage.getItem('token');
            // Ensure we use the correct relative API path or absolute if needed. 
            // Better to use the same hostname logic as the rest of the app.
            // If we are serving from frontend, we likely proxy to backend.
            const res = await fetch(`/api/suggestions/${id}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            if (res.ok) {
                document.getElementById('tab-accepted').click(); // Reload list
            } else {
                alert("No se pudo borrar. (Verifica si el backend soporta DELETE /api/suggestions/:id)");
            }
        } catch (e) {
            console.error(e);
            alert("Error de conexión");
        }
    };

    window.handleEvaluate = async (id) => {
        try {
            const btn = document.activeElement;
            if (btn) btn.textContent = "Evaluando...";

            const res = await evaluateSuggestion(id, 7);
            alert(`Evaluación completada: ${res.summary}`);
            loadHistory();
        } catch (e) {
            alert(e.message);
        }
    };

    window.handleReject = async (id) => {
        const reason = prompt("¿Motivo del rechazo? (Opcional)");
        if (reason === null) return;
        try {
            await rejectSuggestion(id, reason || "Rechazado por usuario");
            loadList();
        } catch (e) {
            alert(e.message);
        }
    };

    window.handleAccept = (id, slotRaw, paramRaw) => {
        const settings = getCalcParams();
        if (!settings) {
            alert("Error: No se encontró configuración local.");
            return;
        }

        const slotData = settings[slotRaw];
        if (!slotData) {
            alert(`Error: No existe configuración para ${slotRaw}`);
            return;
        }

        const currentVal = slotData[paramRaw];

        // Open Modal
        const modal = document.getElementById('accept-modal'); // Get fresh ref
        document.getElementById('accept-current-val').textContent = currentVal;
        document.getElementById('accept-new-val').value = currentVal;
        document.getElementById('accept-modal-desc').textContent = `Estás revisando el ${paramRaw.toUpperCase()} para ${slotRaw}.`;

        const btnSave = document.getElementById('btn-modal-confirm');
        const btnCancel = document.getElementById('btn-modal-cancel');

        // Remove old listeners involves cloning or managing listeners. 
        // Cloning is easiest way to wipe listeners.
        const newBtnSave = btnSave.cloneNode(true);
        btnSave.parentNode.replaceChild(newBtnSave, btnSave);
        const newBtnCancel = btnCancel.cloneNode(true);
        btnCancel.parentNode.replaceChild(newBtnCancel, btnCancel);

        newBtnCancel.onclick = () => modal.close();

        newBtnSave.onclick = async () => {
            const newVal = parseFloat(document.getElementById('accept-new-val').value);
            if (isNaN(newVal) || newVal <= 0) {
                alert("Valor inválido");
                return;
            }

            settings[slotRaw][paramRaw] = newVal;
            saveCalcParams(settings);

            try {
                newBtnSave.textContent = "Guardando...";
                await acceptSuggestion(id, "Aceptado por usuario", {
                    meal_slot: slotRaw,
                    parameter: paramRaw,
                    old_value: currentVal,
                    new_value: newVal
                });
                modal.close();
                alert("Cambio aplicado y sugerencia marcada como aceptada.");
                loadList();
            } catch (e) {
                alert("Error al guardar en backend: " + e.message);
                newBtnSave.textContent = "Guardar";
            }
        };

        modal.showModal();
    };
}
