import { state, getCalcParams, getDualPlan, getDualPlanTiming, getDefaultMealParams, syncSettings } from '../core/store.js';
import { formatTrend } from '../core/utils.js';
import { navigate } from '../core/router.js';
import { renderHeader, renderBottomNav } from '../components/layout.js';
import { getLocalNsConfig, getCurrentGlucose, fetchTreatments, getIOBData, recalcSecondBolus } from '../../lib/api.js';

// --- U2 PANEL LOGIC ---
const DUAL_PLAN_KEY = "bolusai_active_dual_plan";

function renderDualPanel() {
    const parent = document.querySelector("#u2-panel-container");
    if (!parent) return;

    if (state.activeDualTimer) {
        clearInterval(state.activeDualTimer);
        state.activeDualTimer = null;
    }

    const plan = getDualPlan();
    if (!plan) {
        parent.innerHTML = "";
        parent.hidden = true;
        return;
    }
    state.activeDualPlan = plan;

    const timing = getDualPlanTiming(plan);
    let timingHtml = "";
    let btnText = "🔁 Recalcular U2 ahora";
    let warningHtml = "";

    if (timing) {
        const { elapsed_min, remaining_min } = timing;

        timingHtml = `
    <div class="u2-timing">
            <span>Transcurrido: <strong>${elapsed_min} min</strong></span>
            <span>U2 en: <strong>${remaining_min} min</strong></span>
         </div>
    `;

        if (remaining_min === 0) {
            warningHtml = `<div class="warning success-border">✅ U2 lista para administrar</div>`;
            btnText = "🔁 Recalcular U2 ahora";
        } else if (remaining_min < 20) {
            warningHtml = `<div class="warning">⚠️ Muy cerca del momento de U2; recalcula justo antes de ponerla</div>`;
            btnText = `Recalcular U2 (en ${remaining_min} min)`;
        } else {
            btnText = `Recalcular U2 (en ${remaining_min} min)`;
        }
    } else {
        timingHtml = `<small>(sin contador)</small>`;
    }

    parent.hidden = false;
    parent.innerHTML = `
      <section class="card u2-card">
         <div class="card-header">
           <h3 style="margin:0; color:#1e40af;">⏱️ Bolo Dividido (U2)</h3>
           <button id="btn-clear-u2" class="ghost small">Ocultar</button>
         </div>
         <div class="stack">
            <div style="text-align:center;">
               <div class="u2-timer-big">${timing ? timing.remaining_min : '--'} min</div>
               <div style="font-size:0.9rem; color:#64748b;">para la segunda dosis</div>
            </div>

            <div style="display:flex; justify-content:space-around; background:#fff; padding:0.5rem; border-radius:8px;">
               <div class="text-center">
                  <div class="small text-muted">Planificado</div>
                  <strong style="font-size:1.2rem; color:#2563eb;">${plan.later_u_planned} U</strong>
               </div>
               <div class="text-center">
                   <div class="small text-muted">Transcurrido</div>
                   <strong>${timing ? timing.elapsed_min : '--'} min</strong>
               </div>
            </div>

            ${warningHtml}

            <div class="row" style="align-items:center;">
               <label style="flex:1;">Carbs extra (g)
                  <input type="number" id="u2-carbs" value="0" placeholder="0" />
               </label>
               <button id="btn-recalc-u2" class="primary" style="flex:1.5;">${btnText}</button>
            </div>
            
            <div id="u2-result" class="box" hidden style="background:#f0fdf4; border:1px solid #bbf7d0; padding:1rem; border-radius:8px; margin-top:0.5rem;">
               <div id="u2-details"></div>
               <div id="u2-recommendation" class="big-number" style="text-align:center; margin:0.5rem 0;"></div>
               <ul id="u2-warnings" class="warning-list"></ul>
               <button id="btn-accept-u2" class="secondary" hidden>✅ Aceptar U2</button>
            </div>
            <p class="error" id="u2-error" hidden></p>
         </div>
      </section>
    `;

    state.activeDualTimer = setInterval(() => {
        if (getDualPlan()) renderDualPanel();
    }, 15000);

    parent.querySelector("#btn-clear-u2").onclick = () => {
        if (confirm("¿Borrar plan activo?")) {
            localStorage.removeItem(DUAL_PLAN_KEY);
            state.activeDualPlan = null;
            if (state.activeDualTimer) clearInterval(state.activeDualTimer);
            renderDualPanel();
        }
    };

    const btnRecalc = parent.querySelector("#btn-recalc-u2");
    const errDisplay = parent.querySelector("#u2-error");
    const resDiv = parent.querySelector("#u2-result");
    const recDiv = parent.querySelector("#u2-recommendation");
    const detailsDiv = parent.querySelector("#u2-details");
    const warnList = parent.querySelector("#u2-warnings");

    btnRecalc.onclick = async () => {
        if (!plan) return;
        errDisplay.hidden = true;
        resDiv.hidden = true;
        btnRecalc.disabled = true;
        btnRecalc.textContent = "Calculando...";

        try {
            const nsConfig = getLocalNsConfig();
            if (!nsConfig || !nsConfig.url) {
                throw new Error("Configura Nightscout para recalcular U2");
            }

            const calcParams = getCalcParams();
            const slot = plan.slot || "lunch";
            const mealParams = calcParams ? (calcParams[slot] || getDefaultMealParams(calcParams)) : null;

            if (!mealParams) throw new Error("Faltan parámetros de cálculo (CR, ISF).");

            const extraCarbs = parseFloat(parent.querySelector("#u2-carbs").value) || 0;

            const payload = {
                later_u_planned: plan.later_u_planned,
                carbs_additional_g: extraCarbs,
                params: {
                    cr_g_per_u: mealParams.icr,
                    isf_mgdl_per_u: mealParams.isf,
                    target_bg_mgdl: mealParams.target,
                    round_step_u: calcParams.round_step_u || 0.05,
                    max_bolus_u: calcParams.max_bolus_u || 10,
                    stale_bg_minutes: 15
                },
                nightscout: {
                    url: nsConfig.url,
                    token: nsConfig.token,
                    units: nsConfig.units || "mgdl"
                }
            };

            const data = await recalcSecondBolus(payload);

            resDiv.hidden = false;

            let recHtml = `${data.u2_recommended_u} U`;
            if (data.cap_u && data.u2_recommended_u >= data.cap_u) {
                recHtml += `<small> (Max)</small>`;
            }
            recDiv.innerHTML = recHtml;

            let det = "";
            if (data.bg_now_mgdl) {
                det += `<div><strong>BG:</strong> ${Math.round(data.bg_now_mgdl)} mg/dL(${data.bg_age_min} min)</div>`;
            }
            if (data.iob_now_u !== null) {
                det += `<div><strong>IOB:</strong> ${data.iob_now_u.toFixed(2)} U</div>`;
            }
            detailsDiv.innerHTML = det;

            warnList.innerHTML = "";
            if (data.warnings && data.warnings.length) {
                data.warnings.forEach(w => {
                    const li = document.createElement("li");
                    li.textContent = w;
                    warnList.appendChild(li);
                });
            }

        } catch (e) {
            errDisplay.textContent = e.message;
            errDisplay.hidden = false;
        } finally {
            btnRecalc.disabled = false;
            btnRecalc.textContent = "🔁 Recalcular U2 ahora";
        }
    };
}

async function updateIOB() {
    const iobValEl = document.getElementById('metric-iob-val');
    const iobCircle = document.querySelector('.iob-progress');

    if (!iobValEl) return;

    if (iobValEl.textContent === '--') iobValEl.innerHTML = '<span class="loading-dots">...</span>';

    try {
        const nsConfig = getLocalNsConfig();
        const data = await getIOBData(nsConfig && nsConfig.url ? nsConfig : null);

        const info = data.iob_info || { status: 'ok', iob_u: data.iob_total };
        const val = typeof info.iob_u === 'number' ? info.iob_u : (data.iob_total || 0.0);

        if (info.status === 'unavailable') {
            iobValEl.textContent = "N/A";
            iobValEl.title = info.reason || "No disponible";
            iobValEl.style.color = "var(--text-muted)";
            if (iobCircle) {
                iobCircle.style.stroke = "var(--border-input)";
                iobCircle.style.strokeDashoffset = 100;
            }
        } else {
            iobValEl.textContent = val.toFixed(2);
            iobValEl.style.color = "";

            if (info.status === 'partial') {
                iobValEl.textContent += "⚠️";
                iobValEl.title = "Parcial: " + (info.reason || "Datos incompletos");
            } else {
                iobValEl.title = "";
            }

            if (iobCircle) {
                const maxScale = 8.0;
                const percent = Math.min(100, (Math.max(0, val) / maxScale) * 100);
                iobCircle.style.strokeDashoffset = 100 - percent;

                if (info.status === 'partial') iobCircle.style.stroke = "var(--warning)";
                else if (val > 5) iobCircle.style.stroke = "var(--warning)";
                else iobCircle.style.stroke = "var(--primary)";
            }
        }

        return data; // Return full data for other consumers (COB)

    } catch (e) {
        console.error("IOB Fetch Error", e);
        return null;
    }
}

async function updateMetrics() {
    const config = getLocalNsConfig();
    // Removed !config return to allow server fallback

    // 1. IOB (returns full status data including COB)
    const statusData = await updateIOB();

    if (statusData && typeof statusData.cob_total !== 'undefined') {
        const lblCob = document.getElementById('metric-cob');
        if (lblCob) lblCob.innerHTML = `${statusData.cob_total} <span class="metric-unit">g</span>`;
    }

    // 2. Last Bolus
    try {
        const treatments = await fetchTreatments({ ...config, count: 50 });
        // Sort explicitly by date desc just in case
        treatments.sort((a, b) => new Date(b.created_at || b.date) - new Date(a.created_at || a.date));

        const lastBolus = treatments.find(t => {
            const val = parseFloat(t.insulin);
            // Must be > 0 and NOT a temp basal (usually eventType 'Temp Basal')
            // Some NS entries might have insulin=null
            return (val && val > 0 && t.eventType !== 'Temp Basal');
        });

        const lbl = document.getElementById('metric-last');
        if (lbl) {
            if (lastBolus) {
                lbl.innerHTML = `${lastBolus.insulin} <span class="metric-unit">U</span>`;
            } else {
                lbl.innerHTML = `-- <span class="metric-unit">U</span>`;
            }
        }

    } catch (e) { console.error("Metrics Loop Error", e); }
}

async function updateActivity() {
    const config = getLocalNsConfig();
    const list = document.getElementById('home-activity-list');
    if (!list) return;

    try {
        const full = await fetchTreatments({ ...config, count: 20 });
        // Filter: has insulin OR has carbs
        const valid = full.filter(t => {
            const u = parseFloat(t.insulin);
            const c = parseFloat(t.carbs);
            return (u > 0 || c > 0);
        });

        const top3 = valid.slice(0, 3);

        list.innerHTML = "";
        top3.forEach(t => {
            const u = parseFloat(t.insulin) || 0;
            const c = parseFloat(t.carbs) || 0;

            // Heuristic for icon
            const isBolus = u > 0;
            const isCarb = c > 0 && u === 0; // Pure carb entry? or mix? 
            // If both, prioritize Bolus icon usually, or fork icon

            // Logic: if insulin > 0 -> Syringe. Else if carbs > 0 -> Cookie.
            const icon = (u > 0) ? "💉" : "🍪";

            const date = new Date(t.created_at || t.timestamp || t.date);
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            let valStr = "";
            if (u > 0) valStr += `${u} U `;
            if (c > 0) valStr += `${c} g`;

            const el = document.createElement('div');
            el.className = 'activity-item';
            el.innerHTML = `
                <div class="act-icon" style="${u > 0 ? '' : 'background:#fff7ed; color:#f97316'}">${icon}</div>
                <div class="act-details">
                    <div class="act-val">${valStr}</div>
                    <div class="act-sub">${t.notes || t.eventType || 'Entrada'}</div>
                </div>
                <div class="act-time">${timeStr}</div>
            `;
            list.appendChild(el);
        });

        if (top3.length === 0) {
            list.innerHTML = "<div class='hint' style='text-align:center; padding:1rem;'>Sin actividad reciente</div>";
        }


    } catch (e) {
        console.warn(e);
        if (list) list.innerHTML = "<div class='hint' style='text-align:center; color:var(--error)'>Error cargando</div>";
    }
}

async function updateGlucoseUI() {
    const config = getLocalNsConfig();
    // Removed config check
    try {
        const res = await getCurrentGlucose(config);
        state.currentGlucose.data = res;
        state.currentGlucose.timestamp = Date.now();

        const valEl = document.querySelector('.gh-value');
        if (valEl) {
            valEl.textContent = Math.round(res.bg_mgdl);
            const arrEl = document.querySelector('.gh-arrow');
            if (arrEl) arrEl.textContent = res.trendArrow || formatTrend(res.trend, false);
            const timeEl = document.querySelector('.gh-time');
            if (timeEl) timeEl.textContent = `Hace ${Math.round(res.age_minutes)} min`;
        }
    } catch (e) { console.error(e); }
}

export async function renderHome() {
    const app = document.getElementById("app");

    if (state.user && !state.settingsSynced) {
        state.settingsSynced = true;
        syncSettings();
    }

    app.innerHTML = `
    ${renderHeader("Bolus AI")}
    <main class="page">
      <!-- Glucose Hero -->
      <section class="card glucose-hero">
        <div class="gh-header">
            <div class="gh-title">Glucosa Actual</div>
            <button class="gh-refresh" id="refresh-bg-btn">↻</button>
        </div>
        <div class="gh-value-group">
            <span class="gh-value">--</span>
            <div class="gh-unit-group">
                <span class="gh-arrow">--</span>
                <span class="gh-unit">mg/dL</span>
            </div>
        </div>
        <div class="gh-status-pill">
            <span class="gh-time">-- min</span>
        </div>
      </section>

      <!-- Dual Bolus Panel Container -->
      <div id="u2-panel-container" hidden style="margin-bottom:1rem"></div>

      <!-- Metrics -->
      <div class="metrics-grid">
        <div class="metric-tile iob-tile">
            <div class="metric-head"><span class="metric-icon">💧</span> IOB</div>
            <div class="iob-circle-container">
               <svg class="iob-ring" viewBox="0 0 100 100">
                  <circle class="iob-track" cx="50" cy="50" r="40" />
                  <circle class="iob-progress" cx="50" cy="50" r="40" pathLength="100" />
               </svg>
               <div class="iob-value-center">
                  <span id="metric-iob-val">--</span>
                  <span class="unit">U</span>
               </div>
            </div>
        </div>
        <div class="metric-tile cob">
            <div class="metric-head"><span class="metric-icon">🍪</span> COB</div>
            <div class="metric-val" id="metric-cob">-- <span class="metric-unit">g</span></div>
        </div>
        <div class="metric-tile last">
            <div class="metric-head"><span class="metric-icon">💉</span> Último</div>
            <div class="metric-val" id="metric-last">-- <span class="metric-unit">U</span></div>
        </div>
      </div>

      <!-- Quick Actions -->
      <h3 class="section-title" style="margin-bottom:1rem">Acciones Rápidas</h3>
      <div class="qa-grid">
        <button class="qa-btn qa-photo" onclick="navigate('#/scan')">
            <div class="qa-icon-box">📷</div>
            <span class="qa-label">Foto Plato</span>
        </button>
        <button class="qa-btn qa-calc" onclick="navigate('#/bolus')">
            <div class="qa-icon-box">🧮</div>
            <span class="qa-label">Calcular</span>
        </button>
        <button class="qa-btn qa-scale" onclick="navigate('#/scan')">
            <div class="qa-icon-box">⚖️</div>
            <span class="qa-label">Báscula</span>
        </button>
        <button class="qa-btn qa-food" onclick="navigate('#/bolus')">
            <div class="qa-icon-box">🍴</div>
            <span class="qa-label">Alimentos</span>
        </button>
      </div>

      <!-- Activity -->
      <div class="section-head">
        <h3 class="section-title" style="margin:0">Actividad Reciente</h3>
        <span class="link-btn" onclick="navigate('#/history')">Ver todo</span>
      </div>
      <div class="activity-list" id="home-activity-list">
         <div class="spinner">Cargando...</div>
      </div>
    </main>
    ${renderBottomNav('home')}
  `;

    // Handlers
    const refreshBtn = document.querySelector("#refresh-bg-btn");
    if (refreshBtn) refreshBtn.onclick = () => {
        updateGlucoseUI();
        updateMetrics();
        updateActivity();
    };

    // Initial Load & Dual Panel
    updateGlucoseUI();
    updateMetrics();
    updateActivity();
    renderDualPanel();
}
