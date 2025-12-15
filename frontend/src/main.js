
import {
  changePassword,
  fetchHealth,
  fetchMe,
  getApiBase,
  getStoredToken,
  getStoredUser,
  loginRequest,
  logout,
  calculateBolus,
  saveSession,
  setUnauthorizedHandler,
  getNightscoutStatus,
  testNightscout,
  saveNightscoutConfig,
  estimateCarbsFromImage,
  getCurrentGlucose,
  saveTreatment,
  getIOBData,
  calculateBolusWithOptionalSplit,
  recalcSecondBolus,
  fetchTreatments,
  createBasalEntry,
  getBasalEntries,
  createBasalCheckin,
  getBasalCheckins,
  getBasalActive,
  getLatestBasal,
  runNightScan,
  getBasalAdvice,
  runAnalysis,
  getAnalysisSummary,
  generateSuggestions,
  getSuggestions,
  acceptSuggestion,
  rejectSuggestion,
  evaluateSuggestion,
  getEvaluations,
  getBasalTimeline,
  evaluateBasalChange,
  getNotificationsSummary,
  markNotificationsSeen,
  getSettings,
  putSettings,
  importSettings
} from "./lib/api";

import {
  connectScale,
  disconnectScale,
  tare,
  setOnData,
  isBleSupported
} from "./lib/bleScale";

const CALC_PARAMS_KEY = "bolusai_calc_params";
const LEGACY_CALC_SETTINGS_KEY = "bolusai_calc_settings";
const SPLIT_SETTINGS_KEY = "bolusai_split_settings";

function getDefaultMealParams(calcParams) {
  return calcParams?.lunch ?? null; // default comida
}

function getSplitSettings() {
  try {
    const raw = localStorage.getItem(SPLIT_SETTINGS_KEY);
    return raw ? JSON.parse(raw) : {
      enabled_default: false,
      percent_now: 70,
      duration_min: 120,
      later_after_min: 120,
      round_step_u: 0.5
    };
  } catch (e) {
    return {
      enabled_default: false,
      percent_now: 70,
      duration_min: 120,
      later_after_min: 120,
      round_step_u: 0.5
    };
  }
}

function saveSplitSettings(settings) {
  localStorage.setItem(SPLIT_SETTINGS_KEY, JSON.stringify(settings));
}

function getCalcParams() {
  try {
    // 1. Try new Key
    const raw = localStorage.getItem(CALC_PARAMS_KEY);
    if (raw) return JSON.parse(raw);

    // 2. Fallback Legacy
    const legacy = localStorage.getItem(LEGACY_CALC_SETTINGS_KEY);
    if (legacy) {
      console.log("Migrating legacy calc settings...");
      const parsed = JSON.parse(legacy);
      saveCalcParams(parsed); // Migrate
      return parsed;
    }
    return null;
  } catch (e) {
    return null;
  }
}

const SETTINGS_VERSION_KEY = "bolusai_settings_version";

function getSettingsVersion() {
  return parseInt(localStorage.getItem(SETTINGS_VERSION_KEY) || "0", 10);
}

function saveSettingsVersion(v) {
  localStorage.setItem(SETTINGS_VERSION_KEY, String(v));
}

// Sync Logic
async function syncSettings() {
  if (!state.user) return;

  // 1. Load Local
  const local = getCalcParams();

  try {
    // 2. Fetch Server
    const serverRes = await getSettings();
    const serverSettings = serverRes.settings;
    const serverVersion = serverRes.version;

    if (serverSettings) {
      // Server has data. Trust server? 
      // Prompt says: "Server hat settings -> save to localStorage (cache), use settings".
      saveCalcParams(serverSettings, true); // true = skip sync
      saveSettingsVersion(serverVersion);
      console.log("Settings synced from server (v" + serverVersion + ")");
    } else if (local) {
      // Server empty, Local exists -> Import
      console.log("Importing local settings to server...");
      const importRes = await importSettings(local);
      saveSettingsVersion(importRes.version);
      if (importRes.imported) console.log("Settings imported.");
    } else {
      // Both empty. Create Defaults?
      // "Server vacio y local vacio -> Crear defaults"
      // We usually let UI handle defaults or create via PUT.
      // But let's leave it until user saves settings.
    }

  } catch (e) {
    console.error("Sync failed:", e);
  }
}

function saveCalcParams(params, skipSync = false) {
  localStorage.setItem(CALC_PARAMS_KEY, JSON.stringify(params));

  if (!skipSync && state.user) {
    triggerBackendSave(params);
  }
}

async function triggerBackendSave(params) {
  const version = getSettingsVersion();
  try {
    const res = await putSettings(params, version);
    saveSettingsVersion(res.version);
    console.log("Settings saved to backend (v" + res.version + ")");
  } catch (e) {
    if (e.isConflict) {
      handleSettingsConflict(e, params);
    } else {
      console.error("Save settings error:", e);
    }
  }
}

function handleSettingsConflict(errorData, localParams) {
  // Show Modal
  const modal = document.createElement('dialog');
  modal.style = "border:none; border-radius:12px; padding:2rem; box-shadow:0 25px 50px -12px rgba(0,0,0,0.25); max-width:400px";
  modal.innerHTML = `
      <h3 style="margin-top:0">Conflicto de sincronización</h3>
      <p>Se han detectado cambios en otro dispositivo (v${errorData.serverVersion}).</p>
      <div style="display:flex; flex-direction:column; gap:0.5rem; margin-top:1rem;">
        <button id="btn-use-server" style="background:var(--primary); color:white; border:none; padding:10px; border-radius:8px; cursor:pointer;">Usar servidor (recomendado)</button>
        <button id="btn-overwrite" style="background:#e2e8f0; color:#334155; border:none; padding:10px; border-radius:8px; cursor:pointer;">Sobrescribir servidor</button>
      </div>
    `;
  document.body.appendChild(modal);
  modal.showModal();

  document.getElementById('btn-use-server').onclick = () => {
    // Adopt server settings
    saveCalcParams(errorData.serverSettings, true);
    saveSettingsVersion(errorData.serverVersion);
    modal.close();
    document.body.removeChild(modal);
    alert("Configuración actualizada desde el servidor.");
    // Reload if generic (e.g. reload page) or just update state?
    // Updating localStorage is handled. If current view depends on it, it might need refresh.
    // For simplicity, we can reload or notify. 
    if (window.location.hash.includes("settings")) {
      renderSettings(); // Re-render settings view
    }
  };

  document.getElementById('btn-overwrite').onclick = async () => {
    // Force update using server version as base + local params
    try {
      const res = await putSettings(localParams, errorData.serverVersion);
      saveSettingsVersion(res.version);
      modal.close();
      document.body.removeChild(modal);
      alert("Servidor sobrescrito.");
    } catch (e) {
      modal.close();
      document.body.removeChild(modal);
      alert("Error al sobrescribir: " + e.message);
    }
  };
}

const state = {
  token: getStoredToken(),
  user: getStoredUser(),
  settingsSynced: false,
  loadingUser: false,
  bolusResult: null,
  bolusError: "",
  healthStatus: "Pulsa el botón para comprobar.",
  visionResult: null,
  visionError: null,
  plateWeightGrams: null, // Temporary weight usage
  scale: {
    connected: false,
    grams: 0,
    stable: false,
    battery: null,
    status: "Desconectado"
  },
  currentGlucose: {
    loading: false,
    data: null, // { bg_mgdl, trend, age, stale, ok, error }
    timestamp: 0
  },
  activeDualPlan: null,
  activeDualTimer: null,
  calcMode: "meal",
  plateBuilder: {
    entries: [],
    carbs_total: 0,
    mode_weight: "single", // "single" | "incremental"
    weight_base_grams: 0,
    base_history: [],
  },
  scaleReading: {
    grams: null,
    stable: false,
    battery: null,
    lastUpdateTs: 0,
    window: [] // [{ts, grams}]
  }
};

const app = document.getElementById("app");

// Helper to format Trend
function formatTrend(trend, stale) {
  if (stale) return "⚠️";
  const icons = {
    "DoubleUp": "↑↑",
    "SingleUp": "↑",
    "FortyFiveUp": "↗",
    "Flat": "→",
    "FortyFiveDown": "↘",
    "SingleDown": "↓",
    "DoubleDown": "↓↓"
  };
  return icons[trend] || trend || "";
}

// --- SCALER HELPER ---
// --- SCALER HELPER WITH DERIVED STABILITY ---

function getDerivedStability() {
  const w = state.scaleReading?.window || [];
  if (w.length < 3) return { derivedStable: false, delta: null };
  const grams = w.map(p => p.grams);
  const delta = Math.max(...grams) - Math.min(...grams);
  // Stable if variation <= 2g in the window
  return { derivedStable: delta <= 2, delta };
}

function getPlateBuilderReading() {
  const r = state.scaleReading || {};
  const { derivedStable, delta } = getDerivedStability();

  // Use DERIVED stability for strict incremental checks
  // Fallback to flag if derived logic fails somehow? No, trust derived.
  // Actually, allow if purely stable by flag OR derived?
  // User asked: "usar estabilidad derivada SIEMPRE para incremental"

  return {
    grams: typeof r.grams === "number" ? r.grams : null,
    stable: derivedStable, // OVERRIDE stable flag
    battery: r.battery ?? null,
    ageMs: r.lastUpdateTs ? (Date.now() - r.lastUpdateTs) : null,
    delta: delta,
    connected: state.scale.connected // keep connection status
  };
}

// Legacy helper for Main Card (optional, or redirect to above)
function getScaleReading() {
  return getPlateBuilderReading();
}

// --- RENDER FUNCTIONS REMOVED HERE, MOVED TO MODULAR VIEWS BELOW --- 
// (renderDashboard replaced by renderHome, renderScan, renderBolus above)
// --- DUAL PLAN HELPERS (Kept) ---

// --- DUAL PLAN HELPERS ---
const DUAL_PLAN_KEY = "bolusai_active_dual_plan";

function getDualPlan() {
  try {
    const raw = localStorage.getItem(DUAL_PLAN_KEY);
    if (!raw) return null;
    const plan = JSON.parse(raw);
    // Optional: expire after 6 hours?
    if (Date.now() - plan.created_at_ts > 6 * 60 * 60 * 1000) {
      localStorage.removeItem(DUAL_PLAN_KEY);
      return null;
    }
    return plan;
  } catch (e) { return null; }
}

function getDualPlanTiming(plan) {
  if (!plan?.created_at_ts || !plan?.later_after_min) return null;
  const elapsed_min = Math.floor((Date.now() - plan.created_at_ts) / 60000);
  const duration = plan.extended_duration_min || plan.later_after_min;
  const remaining_min = Math.max(0, duration - elapsed_min);
  return { elapsed_min, remaining_min };
}

function saveDualPlan(plan) {
  state.activeDualPlan = plan;
  localStorage.setItem(DUAL_PLAN_KEY, JSON.stringify(plan));
}

// --- U2 PANEL LOGIC ---
function renderDualPanel() {
  const parent = document.querySelector("#u2-panel-container");
  if (!parent) return; // Should be in HTML

  // Clear existing timer to avoid multiples
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

  // Calc Timing
  const timing = getDualPlanTiming(plan);
  let timingHtml = "";
  let btnText = "🔁 Recalcular U2 ahora";
  let warningHtml = "";

  if (timing) {
    const { elapsed_min, remaining_min } = timing;

    timingHtml = `
    < div class="u2-timing" >
            <span>Transcurrido: <strong>${elapsed_min} min</strong></span>
            <span>U2 en: <strong>${remaining_min} min</strong></span>
         </div >
    `;

    if (remaining_min === 0) {
      warningHtml = `< div class="warning success-border" >✅ U2 lista para administrar</div > `;
      btnText = "🔁 Recalcular U2 ahora";
    } else if (remaining_min < 20) {
      warningHtml = `< div class="warning" >⚠️ Muy cerca del momento de U2; recalcula justo antes de ponerla</div > `;
      btnText = `Recalcular U2(en ${remaining_min} min)`;
    } else {
      btnText = `Recalcular U2(en ${remaining_min} min)`;
    }
  } else {
    timingHtml = `< small > (sin contador)</small > `;
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
               <div class="u2-timer-big">${remaining_min} min</div>
               <div style="font-size:0.9rem; color:#64748b;">para la segunda dosis</div>
            </div>

            <div style="display:flex; justify-content:space-around; background:#fff; padding:0.5rem; border-radius:8px;">
               <div class="text-center">
                  <div class="small text-muted">Planificado</div>
                  <strong style="font-size:1.2rem; color:#2563eb;">${plan.later_u_planned} U</strong>
               </div>
               <div class="text-center">
                   <div class="small text-muted">Transcurrido</div>
                   <strong>${elapsed_min} min</strong>
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

  // Start Timer to refresh UI every 15s
  state.activeDualTimer = setInterval(() => {
    // Only re-render if plan still active
    if (getDualPlan()) renderDualPanel();
  }, 15000);

  // Handlers
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
          cr_g_per_u: mealParams.icr, // mapped
          isf_mgdl_per_u: mealParams.isf, // mapped
          target_bg_mgdl: mealParams.target, // mapped
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

      // Render Results
      resDiv.hidden = false;

      let recHtml = `${data.u2_recommended_u} U`;
      if (data.cap_u && data.u2_recommended_u >= data.cap_u) {
        recHtml += ` < small > (Max)</small > `;
      }
      recDiv.innerHTML = recHtml;

      let det = "";
      if (data.bg_now_mgdl) {
        det += `< div > <strong>BG:</strong> ${Math.round(data.bg_now_mgdl)} mg / dL(${data.bg_age_min} min)</div > `;
      }
      if (data.iob_now_u !== null) {
        det += `< div > <strong>IOB:</strong> ${data.iob_now_u.toFixed(2)} U</div > `;
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


function renderBolusOutput(res) {
  if (res.error) return `< span class='error' > ${res.error}</span > `;

  // Correction Mode Output
  if (state.calcMode === "correction") {
    if (res.upfront_u === 0) {
      return `< div class="info-box" > No se recomienda corrección. (BG & le; Objetivo)</div > `;
    }
    return `
    < div class="correction-res" >
             <div class="label">Bolo corrector recomendado</div>
             <div class="big-number">${res.upfront_u} U</div>
          </div >
    `;
  }

  if (res.kind === "dual") {
    return `
    < div class="dual-res" >
          <div>AHORA: <strong>${res.upfront_u} U</strong></div>
          <div>LUEGO: <strong>${res.later_u} U</strong> <small>(${res.duration_min} min)</small></div>
        </div >
    `;
  }
  return `< strong > ${res.upfront_u} U</strong > `;
}



// --- IOB HELPERS (Kept) ---

// --- IOB HELPERS (Kept) ---

async function updateIOB() {
  const iobValEl = document.getElementById('metric-iob-val');
  const iobCircle = document.querySelector('.iob-progress');

  if (!iobValEl) return;

  // Set Loading/Default
  if (iobValEl.textContent === '--') iobValEl.innerHTML = '<span class="loading-dots">...</span>';

  try {
    const nsConfig = getLocalNsConfig();
    const data = await getIOBData(nsConfig && nsConfig.url ? nsConfig : null);

    // Get info if present (Robust Update)
    const info = data.iob_info || { status: 'ok', iob_u: data.iob_total };
    const val = typeof info.iob_u === 'number' ? info.iob_u : (data.iob_total || 0.0);

    // Logic Display
    if (info.status === 'unavailable') {
      iobValEl.textContent = "N/A";
      iobValEl.title = info.reason || "No disponible";
      iobValEl.style.color = "var(--text-muted)";
      if (iobCircle) {
        iobCircle.style.stroke = "var(--border-input)"; // Gray
        iobCircle.style.strokeDashoffset = 100; // Empty
      }
    } else {
      iobValEl.textContent = val.toFixed(2);
      iobValEl.style.color = ""; // reset

      if (info.status === 'partial') {
        iobValEl.textContent += "⚠️";
        iobValEl.title = "Parcial: " + (info.reason || "Datos incompletos");
      } else {
        iobValEl.title = "";
      }

      // Graph Circle
      if (iobCircle) {
        const maxScale = 8.0;
        const percent = Math.min(100, (Math.max(0, val) / maxScale) * 100);
        iobCircle.style.strokeDashoffset = 100 - percent;

        if (info.status === 'partial') iobCircle.style.stroke = "var(--warning)"; // Orange
        else if (val > 5) iobCircle.style.stroke = "var(--warning)";
        else iobCircle.style.stroke = "var(--primary)";
      }
    }

    return data;

  } catch (e) {
    console.error("IOB Fetch Error", e);
    return null;
  }
}



function drawIOBGraph(canvas, points) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  if (!points || points.length < 2) return;

  const maxIOB = Math.max(...points.map(p => p.iob), 0.1);
  const durationMin = points[points.length - 1].min_from_now;
  const padL = 30; const padB = 20;
  const W = width - padL; const H = height - padB;

  const x = (min) => padL + (min / durationMin) * W;
  const y = (val) => H - (val / maxIOB) * H;

  ctx.strokeStyle = "#e2e8f0"; ctx.lineWidth = 1; ctx.beginPath();
  for (let i = 0; i <= durationMin; i += 60) {
    ctx.moveTo(x(i), 0); ctx.lineTo(x(i), H);
    ctx.fillStyle = "#64748b"; ctx.font = "10px sans-serif"; ctx.fillText(i + "m", x(i), height - 5);
  }
  ctx.stroke();

  ctx.fillStyle = "rgba(59, 130, 246, 0.2)"; ctx.beginPath(); ctx.moveTo(x(0), H);
  points.forEach(p => ctx.lineTo(x(p.min_from_now), y(p.iob)));
  ctx.lineTo(x(durationMin), H); ctx.closePath(); ctx.fill();

  ctx.strokeStyle = "#2563eb"; ctx.lineWidth = 2; ctx.beginPath();
  points.forEach((p, i) => {
    if (i === 0) ctx.moveTo(x(p.min_from_now), y(p.iob));
    else ctx.lineTo(x(p.min_from_now), y(p.iob));
  });
  ctx.stroke();
}

// (Old vision logic removed)

// --- BASAL UI ---

// --- HELPER FUNCTIONS FOR UI ---
async function updateMetrics() {
  const config = getLocalNsConfig();
  if (!config) return;

  // 1. IOB (returns full status data including COB)
  const statusData = await updateIOB();

  if (statusData && typeof statusData.cob_total !== 'undefined') {
    const lblCob = document.getElementById('metric-cob');
    if (lblCob) lblCob.innerHTML = `${statusData.cob_total} <span class="metric-unit">g</span>`;
  }

  // 2. Last Bolus
  try {
    const treatments = await fetchTreatments({ ...config, count: 100 }); // fetch more to find valid bolus
    // Filter for valid insulin events (Meal Bolus, Correction Bolus, or just insulin > 0)
    // EXCLUDE Temp Basal explicitly
    const lastBolus = treatments.find(t => {
      const val = parseFloat(t.insulin);
      return (!isNaN(val) && val > 0 && t.eventType !== 'Temp Basal');
    });

    const lbl = document.getElementById('metric-last');
    if (lbl) {
      if (lastBolus) {
        lbl.innerHTML = `${lastBolus.insulin} <span class="metric-unit">U</span>`;
        // Optional: Add Time ago?
        // const mins = Math.round((Date.now() - new Date(lastBolus.created_at).getTime())/60000);
        // lbl.title = `${mins} min ago`;
      } else {
        lbl.innerHTML = `-- <span class="metric-unit">U</span>`;
      }
    }

  } catch (e) { console.error("Metrics Loop Error", e); }
}

async function updateActivity() {
  const config = getLocalNsConfig();
  const list = document.getElementById('home-activity-list');
  if (!list || !config) return;

  try {
    const fullTreatments = await fetchTreatments({ ...config, count: 100 });
    // Filter before slicing to avoid showing 3 empty/invalid items
    const validTreatments = fullTreatments.filter(t => {
      const u = parseFloat(t.insulin);
      const c = parseFloat(t.carbs);
      return (u > 0 || c > 0);
    });

    const treatments = validTreatments.slice(0, 3); // Top 3

    list.innerHTML = "";
    treatments.forEach(t => {
      const u = parseFloat(t.insulin);
      const c = parseFloat(t.carbs);
      const isBolus = u > 0;
      const isCarb = c > 0;

      const el = document.createElement('div');
      el.className = 'activity-item';
      const icon = isBolus ? "💉" : "🍪";
      const date = new Date(t.created_at || t.timestamp || t.date);
      const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

      let valStr = "";
      if (isBolus) valStr += `${u} U `;
      if (isCarb) valStr += `${c} g`;

      el.innerHTML = `
                <div class="act-icon" style="${isBolus ? '' : 'background:#fff7ed; color:#f97316'}">${icon}</div>
                <div class="act-details">
                    <div class="act-val">${valStr}</div>
                    <div class="act-sub">${t.notes || 'Entrada'}</div>
                </div>
                <div class="act-time">${time}</div>
            `;
      list.appendChild(el);
    });

    if (treatments.length === 0) {
      list.innerHTML = "<div class='hint' style='text-align:center; padding:1rem;'>Sin actividad reciente</div>";
    }

  } catch (e) {
    // Silent fail for widget
    console.warn(e);
    if (list) list.innerHTML = "<div class='hint' style='text-align:center; color:var(--error)'>Error cargando</div>";
  }
}

function ensureAuthenticated() {
  if (!state.token) {
    navigate('#/login');
    return false;
  }
  return true;
}

async function updateGlucoseUI() {
  const config = getLocalNsConfig();
  if (!config || !config.url) return;
  try {
    const res = await getCurrentGlucose(config);
    state.currentGlucose.data = res;
    state.currentGlucose.timestamp = Date.now();
    // Re-render handled by current view calling updateGlucoseUI or purely data update?
    // If we are in renderHome, we might want to update partial DOM if it exists
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

function navigate(hash) {
  window.location.hash = hash;
}
window.navigate = navigate;
window.logout = logout;

function redirectToLogin() {
  navigate("#/login");
}

setUnauthorizedHandler(() => {
  state.token = null;
  state.user = null;
  redirectToLogin();
  render();
});

window.addEventListener("hashchange", () => render());



async function bootstrapSession() {
  if (!state.token) {
    redirectToLogin();
    render();
    return;
  }
  state.loadingUser = true;
  render();
  try {
    const me = await fetchMe();
    state.user = me;
    saveSession(state.token, me);
    if (me.needs_password_change) {
      navigate("#/change-password");
    } else {
      if (window.location.hash === "#/login" || !window.location.hash) {
        navigate("#/");
      } else {
        render();
      }
    }
  } catch (error) {
    state.user = null;
    state.token = null;
    redirectToLogin();
  } finally {
    state.loadingUser = false;
  }
}

// Global Handler for Profile Menu
window.toggleProfileMenu = function () {
  const menu = document.getElementById('profile-menu');
  if (menu) {
    const isHidden = menu.style.display === 'none';
    menu.style.display = isHidden ? 'block' : 'none';

    if (isHidden) {
      // Add click-outside listener
      setTimeout(() => {
        const closer = (e) => {
          if (!menu.contains(e.target) && e.target.id !== 'profile-btn') {
            menu.style.display = 'none';
            window.removeEventListener('click', closer);
          }
        };
        window.addEventListener('click', closer);
      }, 0);
    }
  }
};

function renderHeader(title = "Bolus AI", showBack = false) {
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

function renderBottomNav(activeTab = 'home') {
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
function renderLogin() {
  app.innerHTML = `
      <section class="card auth-card">
        <h1>Inicia sesión</h1>
        <p class="hint">API base: <code>${getApiBase() || "(no configurado)"}</code></p>
        <form id="login-form" class="stack">
          <label>Usuario
            <input type="text" id="login-username" autocomplete="username" required />
          </label>
          <label>Contraseña
            <input type="password" id="login-password" autocomplete="current-password" required />
          </label>
          <button type="submit">Entrar</button>
          <p class="hint">Se mantendrá la sesión (localStorage).</p>
          <p class="error" id="login-error" hidden></p>
        </form>
      </section>
    </main >
    `;

  const form = document.querySelector("#login-form");
  const errorBox = document.querySelector("#login-error");
  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    errorBox.hidden = true;
    const username = document.querySelector("#login-username").value.trim();
    const password = document.querySelector("#login-password").value;
    try {
      const data = await loginRequest(username, password);
      state.token = data.access_token;
      state.user = data.user;
      if (data.user.needs_password_change) {
        navigate("#/change-password");
      } else {
        navigate("#/");
      }
      render();
    } catch (error) {
      errorBox.textContent = error.message || "No se pudo iniciar sesión";
      errorBox.hidden = false;
    }
  });
}

function renderChangePassword() {
  if (!ensureAuthenticated()) return;
  app.innerHTML = `
    ${renderHeader()}
  <main class="page narrow">
    <section class="card auth-card">
      <h2>Cambiar contraseña</h2>
      <p class="hint">Introduce tu contraseña actual y una nueva (mínimo 8 caracteres).</p>
      <form id="password-form" class="stack">
        <label>Contraseña actual
          <input type="password" id="old-password" autocomplete="current-password" required />
        </label>
        <label>Nueva contraseña
          <input type="password" id="new-password" autocomplete="new-password" required minlength="8" />
        </label>
        <button type="submit">Actualizar</button>
        <p class="error" id="password-error" hidden></p>
        <p class="success" id="password-success" hidden>Contraseña actualizada.</p>
      </form>
    </section>
  </main>
  `;

  const form = document.querySelector("#password-form");
  const err = document.querySelector("#password-error");
  const ok = document.querySelector("#password-success");
  const logoutBtn = document.querySelector("#logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => logout());

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    err.hidden = true;
    ok.hidden = true;
    const oldPass = document.querySelector("#old-password").value;
    const newPass = document.querySelector("#new-password").value;
    try {
      const result = await changePassword(oldPass, newPass);
      state.user = result.user || state.user;
      saveSession(state.token, state.user);
      ok.hidden = false;
      navigate("#/");
      render();
    } catch (error) {
      err.textContent = error.message || "No se pudo actualizar";
      err.hidden = false;
    }
  });
}

const NS_STORAGE_KEY = "bolusai_ns_config";

function getLocalNsConfig() {
  try {
    return JSON.parse(localStorage.getItem(NS_STORAGE_KEY));
  } catch (e) {
    return null;
  }
}

function saveLocalNsConfig(config) {
  localStorage.setItem(NS_STORAGE_KEY, JSON.stringify(config));
}

function renderSettings() {
  if (!ensureAuthenticated()) return;

  app.innerHTML = `
    ${renderHeader()}
  <main class="page">
    <section class="card">
      <div class="tabs">
        <button id="tab-ns" class="tab active">Conexión Nightscout</button>
        <button id="tab-calc" class="tab">Parámetros Cálculo</button>
      </div>

      <div id="panel-ns">
        <h2>Nightscout</h2>
        <p class="hint">La configuración se guarda en <strong>este dispositivo</strong>.</p>

        <form id="ns-form" class="stack">
          <label>URL
            <input type="url" id="ns-url" placeholder="https://tusitio.herokuapp.com" required />
          </label>
          <label>Token / API Secret
            <input type="password" id="ns-token" placeholder="Dejar vacío si es público" />
          </label>
          <div class="actions">
            <button type="button" id="ns-test-btn" class="secondary">Probar</button>
            <button type="submit">Guardar</button>
          </div>
          <div id="ns-status-box" class="status-box hidden"></div>
        </form>
      </div>

      <div id="panel-calc" hidden>
        <h2>Parámetros Clínicos</h2>
        <p class="hint warning">Ajusta con ayuda de tu endocrino. Se guardan en navegador.</p>

        <form id="calc-form" class="stack">
          <!-- Slots Tabs inside form -->
          <div class="sub-tabs">
            <button type="button" data-slot="breakfast" class="sub-tab active">Desayuno</button>
            <button type="button" data-slot="lunch" class="sub-tab">Comida</button>
            <button type="button" data-slot="dinner" class="sub-tab">Cena</button>
            <button type="button" data-slot="snack" class="sub-tab">Snack</button>
          </div>

          <div id="slot-fields">
            <label>Ratio Insulina/Carbs (ICR)
              <input type="number" step="0.1" id="slot-icr" required min="1" />
              <small>1u por X gramos</small>
            </label>
            <label>Factor Sensibilidad (ISF)
              <input type="number" step="0.01" id="slot-isf" required min="5" />
              <small>1u baja X mg/dL</small>
            </label>
            <label>Objetivo (Target)
              <input type="number" step="1" id="slot-target" required min="70" max="200" />
              <small>mg/dL</small>
            </label>
          </div>

          <hr />

          <label>Duración Insulina Activa (DIA)
            <input type="number" step="0.5" id="global-dia" required min="2" max="8" value="4" />
            <small>Horas</small>
          </label>

          <label>Paso de redondeo
            <select id="global-step">
              <option value="0.5">0.5 U (Mínimo)</option>
              <option value="1.0">1.0 U</option>
            </select>
          </label>

          <label>Máximo Bolo (Seguridad)
            <input type="number" step="0.5" id="global-max" required min="1" max="50" value="10" />
            <small>Unidades límite por bolo</small>
          </label>

          <button type="submit">Guardar Parámetros</button>
          <p id="calc-msg" class="success" hidden></p>
        </form>

        <hr style="margin: 2rem 0" />

        <!-- ADVANCED SPLIT SETTINGS -->
        <details id="advanced-settings">
          <summary>Avanzado (Bolo Dividido)</summary>
          <form id="split-form" class="stack" style="margin-top: 1rem; border: 1px solid #e2e8f0; padding: 1rem; border-radius: 8px;">
            <label class="row-label">
              <input type="checkbox" id="split-default-enabled" />
              Activar bolo dividido por defecto
            </label>

            <div class="row">
              <label>
                % Ahora
                <input type="number" id="split-percent" min="10" max="90" required />
              </label>
              <label>
                Redondeo (U)
                <select id="split-step">
                  <option value="0.5">0.5</option>
                  <option value="1.0">1.0</option>
                </select>
              </label>
            </div>

            <div class="row">
              <label>
                Duración Extendida (min)
                <input type="number" id="split-duration" min="30" max="480" step="15" required />
              </label>
              <label>
                Recordar 2ª parte tras (min)
                <input type="number" id="split-later-min" min="15" max="360" step="15" required />
              </label>
            </div>

            <button type="submit" class="secondary">Guardar Avanzado</button>
          </form>
        </details>
      </div>

    </section>

    <section class="card">
      <div class="card-header">
        <h2>Estado del backend</h2>
        <button id="health-btn" class="ghost">Comprobar</button>
      </div>
      <pre id="health-output">${state.healthStatus}</pre>
    </section>
  </main>
  `;

  const tabNs = document.querySelector("#tab-ns");
  const tabCalc = document.querySelector("#tab-calc");
  const panelNs = document.querySelector("#panel-ns");
  const panelCalc = document.querySelector("#panel-calc");

  document.querySelector("#health-btn").addEventListener("click", async () => {
    const output = document.querySelector("#health-output");
    output.textContent = "Consultando...";
    try {
      const health = await fetchHealth();
      state.healthStatus = JSON.stringify(health, null, 2);
      output.textContent = state.healthStatus;
    } catch (error) {
      state.healthStatus = `Error: ${error.message} `;
      output.textContent = state.healthStatus;
    }
  });

  tabNs.onclick = () => {
    tabNs.classList.add("active"); tabCalc.classList.remove("active");
    panelNs.hidden = false; panelCalc.hidden = true;
  };
  tabCalc.onclick = () => {
    tabCalc.classList.add("active"); tabNs.classList.remove("active");
    panelCalc.hidden = false; panelNs.hidden = true;
  };

  const logoutBtn = document.querySelector("#logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => logout());

  initNsPanel();
  initCalcPanel();
}

function initNsPanel() {
  const form = document.querySelector("#ns-form");
  const urlInput = document.querySelector("#ns-url");
  const tokenInput = document.querySelector("#ns-token");
  const testBtn = document.querySelector("#ns-test-btn");
  const statusBox = document.querySelector("#ns-status-box");

  const saved = getLocalNsConfig();
  if (saved) {
    urlInput.value = saved.url || "";
    tokenInput.value = saved.token || "";
  }

  testBtn.onclick = async () => {
    statusBox.textContent = "Probando...";
    statusBox.className = "status-box neutral";
    statusBox.classList.remove("hidden");
    try {
      const res = await testNightscout({ url: urlInput.value, token: tokenInput.value });
      statusBox.textContent = res.ok ? "Conectado OK" : (res.message || "Error");
      statusBox.className = res.ok ? "status-box success" : "status-box error";
    } catch (e) {
      statusBox.textContent = e.message;
      statusBox.className = "status-box error";
    }
  };

  form.onsubmit = (e) => {
    e.preventDefault();
    if (!urlInput.value) return;
    saveLocalNsConfig({ url: urlInput.value.trim(), token: tokenInput.value.trim() });
    statusBox.textContent = "Guardado.";
    statusBox.className = "status-box success";
    statusBox.classList.remove("hidden");
  };
}

function initCalcPanel() {
  const defaults = {
    breakfast: { icr: 10, isf: 50, target: 110 },
    lunch: { icr: 10, isf: 50, target: 110 },
    dinner: { icr: 10, isf: 50, target: 110 },
    snack: { icr: 10, isf: 50, target: 110 }, // New Snack Slot
    dia_hours: 4,
    round_step_u: 0.5,
    max_bolus_u: 10
  };

  let currentSettings = getCalcParams() || defaults;

  // Migration: Ensure snack exists if loading old settings
  if (!currentSettings.snack) {
    currentSettings.snack = { ...defaults.snack }; // use defaults or clone lunch
  }

  let currentSlot = "breakfast";

  const form = document.querySelector("#calc-form");
  const icrInput = document.querySelector("#slot-icr");
  const isfInput = document.querySelector("#slot-isf");
  const targetInput = document.querySelector("#slot-target");

  document.querySelector("#global-dia").value = currentSettings.dia_hours;
  document.querySelector("#global-step").value = currentSettings.round_step_u;
  document.querySelector("#global-max").value = currentSettings.max_bolus_u;

  function loadSlot(slot) {
    currentSlot = slot;
    document.querySelectorAll(".sub-tab").forEach(b => b.classList.toggle("active", b.dataset.slot === slot));
    const data = currentSettings[slot];
    icrInput.value = data.icr;
    isfInput.value = data.isf;
    targetInput.value = data.target;
  }

  function saveCurrentSlotToMemory() {
    // Minimum validation already handled by input min attributes, but we ensure parsing
    currentSettings[currentSlot] = {
      icr: parseFloat(icrInput.value) || 10,
      isf: parseFloat(isfInput.value) || 50,
      target: parseFloat(targetInput.value) || 110
    };
  }

  document.querySelectorAll(".sub-tab").forEach(btn => {
    btn.onclick = () => {
      saveCurrentSlotToMemory();
      loadSlot(btn.dataset.slot);
    };
  });

  loadSlot("breakfast");

  form.onsubmit = (e) => {
    e.preventDefault();
    // Ensure current slot inputs are flushed to memory
    saveCurrentSlotToMemory();

    // 1. Read Globals (Global Inputs)
    const diaVal = parseFloat(document.querySelector("#global-dia").value);
    const stepVal = parseFloat(document.querySelector("#global-step").value);
    const maxVal = parseFloat(document.querySelector("#global-max").value);

    // 2. Validate Globals
    if (isNaN(diaVal) || diaVal <= 0) {
      alert("DIA (Duración) debe ser > 0.");
      return;
    }
    if (isNaN(stepVal) || stepVal <= 0) {
      alert("Round Step debe ser > 0.");
      return;
    }
    if (isNaN(maxVal) || maxVal <= 0) {
      alert("Max Bolus debe ser > 0.");
      return;
    }

    // 3. Construct the Final Object explicitely
    // We already have 'currentSettings' holding the slot data

    // Check missing slots (parity with migration)
    if (!currentSettings.snack) currentSettings.snack = { ...defaults.snack };

    const finalParams = {
      breakfast: { ...currentSettings.breakfast },
      lunch: { ...currentSettings.lunch },
      dinner: { ...currentSettings.dinner },
      snack: { ...currentSettings.snack },
      dia_hours: diaVal,
      round_step_u: stepVal,
      max_bolus_u: maxVal
    };

    // 4. Validate Slots deeply
    for (const key of ["breakfast", "lunch", "dinner", "snack"]) {
      const s = finalParams[key];
      if (!s || s.icr <= 0 || s.isf <= 0 || s.target < 0) {
        alert(`Error en validación de ${key}. Revisa los valores(ICR, ISF > 0).`);
        return;
      }
    }

    // 5. Persist
    saveCalcParams(finalParams);

    // Update local variable to stay in sync
    currentSettings = finalParams;

    console.log("Calculated parameters saved:", finalParams);

    const msg = document.querySelector("#calc-msg");
    msg.textContent = "Guardado en localStorage OK.";
    msg.hidden = false;
    setTimeout(() => msg.hidden = true, 3000);
  };

  // Auto-save defaults if storage is empty
  if (!getCalcParams()) {
    console.log("No calc params found, saving defaults...");
    saveCalcParams(defaults);
    currentSettings = defaults; // Ensure sync
  }

  const splitForm = document.querySelector("#split-form");
  const splitSettings = getSplitSettings();

  document.querySelector("#split-default-enabled").checked = splitSettings.enabled_default;
  document.querySelector("#split-percent").value = splitSettings.percent_now;
  document.querySelector("#split-duration").value = splitSettings.duration_min;
  document.querySelector("#split-later-min").value = splitSettings.later_after_min;
  document.querySelector("#split-step").value = splitSettings.round_step_u;

  splitForm.onsubmit = (e) => {
    e.preventDefault();
    const newSettings = {
      enabled_default: document.querySelector("#split-default-enabled").checked,
      percent_now: parseInt(document.querySelector("#split-percent").value),
      duration_min: parseInt(document.querySelector("#split-duration").value),
      later_after_min: parseInt(document.querySelector("#split-later-min").value),
      round_step_u: parseFloat(document.querySelector("#split-step").value)
    };
    saveSplitSettings(newSettings);
    // Force reload split settings? The dashboard reads them on submit, so it's fine.
    alert("Configuración de bolo dividido guardada.");
  };
}

// --- ROUTER & VIEWS ---

async function render() {
  const route = window.location.hash || "#/";
  if (!state.user && route !== "#/login") {
    renderLogin();
    return;
  }

  if (route === "#/login") {
    renderLogin();
  } else if (route === "#/change-password") {
    renderChangePassword();
  } else if (route === "#/settings") {
    renderSettings();
  } else if (route === "#/scan") {
    renderScan();
  } else if (route === "#/bolus") {
    renderBolus();
  } else if (route === "#/basal") {
    await renderBasal();
  } else if (route === "#/history") {
    renderHistory();
  } else if (route === "#/patterns") {
    renderPatterns();
  } else if (route === "#/suggestions") {
    renderSuggestions();
  } else {
    await renderHome();
  }

  if (state.user && window.checkNotifications && route !== "#/login") {
    window.checkNotifications();
  }
}


// --- VIEW: HOME (Inicio) ---
async function renderHome() {
  if (state.user && !state.settingsSynced) {
    state.settingsSynced = true;
    syncSettings();
  }
  // Ensure we have user config
  const config = getLocalNsConfig();

  // Basic Shell
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

  // Initial Load
  updateGlucoseUI();
  updateMetrics();
  updateActivity();

  // Restore Dual Bolus Panel if active
  if (state.lastBolusPlan) {
    const activeCard = document.createElement('div');
    activeCard.className = "card";
    activeCard.style.cssText = "background:#f0fdfa; border:1px solid #ccfbf1; margin-bottom:1.5rem";
    activeCard.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem">
            <span style="font-weight:700; color:#0f766e">🌊 Bolo Extendido Activo</span>
            <span style="font-size:0.8rem; background:white; padding:2px 6px; border-radius:4px; border:1px solid #ccfbf1">
               ${state.lastBolusPlan.later_u_planned} U pend.
            </span>
        </div>
        <div style="font-size:0.85rem; color:#0d9488; margin-bottom:0.8rem">
           Finaliza en aprox: ${state.lastBolusPlan.extended_duration_min || 120} min
        </div>
        <div style="display:flex; gap:0.5rem">
             <button id="btn-dash-extra" class="btn-primary" style="font-size:0.85rem; padding:6px 12px; flex:1">
                ➕ Añadir Extra
             </button>
        </div>
      `;

    // We insert after the header (which is not in main)
    // Actually we insert at top of main
    const main = document.querySelector('main.page');
    if (main) main.prepend(activeCard);

    const btnDashExtra = activeCard.querySelector('#btn-dash-extra');
    if (btnDashExtra) {
      btnDashExtra.onclick = () => {
        // We go to a special view or render the Bolus Result View passing the stored plan?
        // The BolusResult view expects a 'res' object.
        // We can reconstruct a 'res' object from state.lastBolusPlan
        // Not perfect but works for MVP.

        state.calcMode = 'dual_extra'; // Mark mode

        // Construct mock res
        const mockRes = {
          kind: 'dual',
          upfront_u: state.lastBolusPlan.now_u,
          later_u: state.lastBolusPlan.later_u_planned,
          duration_min: state.lastBolusPlan.extended_duration_min || 120,
          plan: state.lastBolusPlan
        };

        // Clear app
        app.innerHTML = `
                ${renderHeader("Añadir Extra", true)}
                <main class="page"></main>
                ${renderBottomNav('home')}
             `;
        renderBolusResult(mockRes);
      };
    }
  }
}

// --- VIEW: SCAN (Foto + Báscula) ---
function renderScan() {
  app.innerHTML = `
    ${renderHeader("Escanear / Pesar", true)}
    <main class="page">
      <!-- Camera Zone -->
      <div class="camera-placeholder" onclick="document.getElementById('cameraInput').click()">
        <div class="camera-icon-big">📷</div>
        <div>Toca para tomar foto</div>
      </div>

      <div class="vision-actions">
        <button class="btn-primary" onclick="document.getElementById('cameraInput').click()">
            📷 Cámara
        </button>
        <button class="btn-secondary" onclick="document.getElementById('photosInput').click()">
            🖼️ Galería
        </button>
      </div>
      
      <!-- Hidden Inputs -->
      <input type="file" id="cameraInput" accept="image/*" capture="environment" hidden />
      <input type="file" id="photosInput" accept="image/*" hidden />

      <!-- Scale Zone -->
      <div class="card scale-card" style="margin-top:1.5rem">
        <h3 style="margin:0 0 1rem 0">⚖️ Báscula Bluetooth</h3>
        <div style="display:flex; justify-content:space-between; align-items:center">
            <div id="scale-status" class="status-badge">Desconectado</div>
            <div style="text-align:right">
                <div id="scale-weight" style="font-size:2rem; font-weight:800; color:var(--primary)">0 g</div>
            </div>
        </div>
        <div style="display:flex; gap:0.5rem; margin-top:1rem;">
             <button id="btn-scale-conn" class="btn-secondary" style="flex:1">Conectar</button>
             <button id="btn-scale-tare" class="btn-ghost" disabled>Tarar</button>
             <button id="btn-scale-use" class="btn-primary" disabled>Usar Peso</button>
        </div>
      </div>

      <!-- Plate Builder Section -->
      <div id="plate-builder-area" class="card" style="margin-top:1.5rem">
         <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem">
            <h3 style="margin:0">🍽️ Mi Plato</h3>
            <span style="font-weight:700; color:var(--primary)"><span id="plate-total-carbs">0</span>g Total</span>
         </div>
         
         <div id="plate-entries" style="font-size:0.9rem; margin-bottom:1rem; min-height:50px">
            <!-- Entries go here -->
            <div class="text-muted" style="text-align:center; padding:1rem">Plato vacío</div>
         </div>
         
         <div style="display:flex; gap:0.5rem">
            <button id="btn-finalize-plate" class="btn-primary" style="flex:1" hidden>🧮 Calcular con Total</button>
            <!-- If we are in 'dual_extra' mode, show specific button -->
            <button id="btn-finalize-plate-extra" class="btn-secondary" style="flex:1; background:#0f766e; color:white" hidden>➕ Añadir al Extendido</button>
         </div>
      </div>

    </main>
    ${renderBottomNav('scan')}
  `;

  // --- VISION HANDLERS ---
  const fileInputs = [document.getElementById('cameraInput'), document.getElementById('photosInput')];

  const handleImg = async (e) => {
    if (!e.target.files || !e.target.files.length) return;
    const file = e.target.files[0];

    // 1. Preview
    const reader = new FileReader();
    reader.onload = (ev) => {
      const previewEl = document.querySelector('.camera-placeholder');
      previewEl.innerHTML = `<img src="${ev.target.result}" style="width:100%; height:100%; object-fit:contain; border-radius:12px">`;
      // Save for entry
      state.currentImageBase64 = ev.target.result;
    };
    reader.readAsDataURL(file);

    // Show loading...
    const actions = document.querySelector('.vision-actions');
    const originalContent = actions.innerHTML; // Keep buttons
    actions.innerHTML = '<div class="spinner">⏳ Analizando IA...</div>';

    try {
      const options = {};

      // Calculate NET weight for this new entry
      // If scale is connected, we use (Current Scale Weight - Sum of previous entries weights)
      let netWeight = null;

      if (state.scale?.grams > 0) {
        // Calculate sum of existing weights in plate
        const previousWeight = state.plateBuilder.entries.reduce((sum, e) => sum + (e.weight || 0), 0);
        netWeight = Math.max(0, state.scale.grams - previousWeight);

        options.plate_weight_grams = netWeight;
        console.log(`Peso Neto calculado: ${netWeight}g (Bruto: ${state.scale.grams}g - Prev: ${previousWeight}g)`);
      }

      // Pass existing items context
      if (state.plateBuilder.entries.length > 0) {
        options.existing_items = state.plateBuilder.entries.map(e => e.name).join(", ");
      }

      const result = await estimateCarbsFromImage(file, options);

      // Auto-add to plate or ask?
      // For smooth flow, let's add to plate directly and notify.
      const entry = {
        carbs: result.carbs_estimate_g,
        weight: netWeight, // Store the net weight used
        img: state.currentImageBase64,
        name: result.food_name || "Alimento IA"
      };

      state.plateBuilder.entries.push(entry);
      updatePlateUI();

      actions.innerHTML = `<div class="success-msg" style="text-align:center">✅ Añadido: ${result.carbs_estimate_g}g</div>`;

      // Restore buttons after delay so user can add more
      setTimeout(() => {
        actions.innerHTML = originalContent;
      }, 2000);

    } catch (err) {
      console.error(err);
      actions.innerHTML = `<div class="error-msg">❌ ${err.message}</div>`;
      setTimeout(() => actions.innerHTML = originalContent, 3000);
    }
  };

  fileInputs.forEach(input => {
    if (input) input.onchange = handleImg;
  });



  // --- SCALE HANDLERS ---
  const btnConn = document.getElementById('btn-scale-conn');
  const btnTare = document.getElementById('btn-scale-tare');
  const btnUse = document.getElementById('btn-scale-use');
  const lblWeight = document.getElementById('scale-weight');
  const lblStatus = document.getElementById('scale-status');

  const updateScaleUI = () => {
    const s = state.scale;
    if (lblWeight) lblWeight.textContent = (s.grams !== null && s.grams !== undefined) ? `${s.grams} g` : "--";
    if (lblStatus) {
      lblStatus.textContent = s.connected ? "Conectado" : "Desconectado";
      lblStatus.className = s.connected ? "status-badge success" : "status-badge";
    }

    if (btnConn) {
      if (s.connected) {
        btnConn.textContent = "Desconectar";
        btnTare.disabled = false;
        btnUse.disabled = false;
      } else {
        btnConn.textContent = "Conectar";
        btnTare.disabled = true;
        btnUse.disabled = true;
      }
    }
  };

  // Callback logic - defined cleanly to be reusable
  const handleScaleData = (data) => {
    // guard against disconnect events having no grams
    if (typeof data.grams === 'number') {
      state.scale.grams = data.grams;
    }
    if (typeof data.stable === 'boolean') {
      state.scale.stable = data.stable;
    }
    if (typeof data.connected === 'boolean') {
      state.scale.connected = data.connected;
    }
    updateScaleUI();
  };

  btnConn.onclick = async () => {
    if (state.scale.connected) {
      await disconnectScale();
      state.scale.connected = false;
      updateScaleUI();
    } else {
      try {
        btnConn.textContent = "Conectando...";
        await connectScale();
        state.scale.connected = true;
        setOnData(handleScaleData); // bind
        updateScaleUI();
      } catch (e) {
        alert("Error conectando: " + e.message);
        state.scale.connected = false;
        updateScaleUI();
      }
    }
  };

  btnTare.onclick = async () => {
    await tare();
  };

  // Re-bind if already connected (e.g. view reload)
  if (state.scale.connected) {
    setOnData(handleScaleData);
  }

  // Init
  updateScaleUI();

  // --- PLATE BUILDER LOGIC ---
  const plateList = document.getElementById('plate-entries');
  const btnFinPlate = document.getElementById('btn-finalize-plate');
  const btnFinPlateExtra = document.getElementById('btn-finalize-plate-extra');
  const plateTotalEl = document.getElementById('plate-total-carbs');

  // Reset builder on load if empty (optional, or keep state)
  if (!state.plateBuilder) state.plateBuilder = { entries: [], total: 0 };

  const updatePlateUI = () => {
    plateList.innerHTML = "";
    let total = 0;
    state.plateBuilder.entries.forEach((entry, idx) => {
      total += entry.carbs;
      const li = document.createElement('div');
      li.className = "plate-entry";
      li.style.cssText = "display:flex; justify-content:space-between; align-items:center; padding:0.5rem; border-bottom:1px solid #eee";
      li.innerHTML = `
             <div style="display:flex; align-items:center; gap:0.5rem">
                ${entry.img ? `<img src="${entry.img}" style="width:40px; height:40px; object-fit:cover; border-radius:6px">` : '<span>🥣</span>'}
                <div>
                   <div style="font-weight:600">${entry.carbs}g carbs</div>
                   <div style="font-size:0.7rem; color:#888">${entry.weight ? entry.weight + 'g peso' : 'Estimado'}</div>
                </div>
             </div>
             <button onclick="removePlateEntry(${idx})" class="btn-ghost" style="color:red; padding:0.2rem">✕</button>
          `;
      plateList.appendChild(li);
    });
    state.plateBuilder.total = total;
    if (plateTotalEl) plateTotalEl.textContent = total;

    // Visibility Logic
    const hasEntries = state.plateBuilder.entries.length > 0;

    if (btnFinPlate) btnFinPlate.hidden = !hasEntries;

    if (btnFinPlateExtra) {
      // Only show if we have an active bolus plan AND entries
      btnFinPlateExtra.hidden = !(hasEntries && state.lastBolusPlan);
      // Prioritize extra button if active
      if (!btnFinPlateExtra.hidden && btnFinPlate) btnFinPlate.hidden = true;
    }
  };

  // Global remover
  window.removePlateEntry = (idx) => {
    state.plateBuilder.entries.splice(idx, 1);
    updatePlateUI();
  };

  if (btnFinPlate) {
    btnFinPlate.onclick = () => {
      state.tempCarbs = state.plateBuilder.total;
      state.tempReason = "plate_builder";
      navigate('#/bolus');
    };
  }

  if (btnFinPlateExtra) {
    btnFinPlateExtra.onclick = () => {
      // Mock Nav to Extra View
      state.calcMode = 'dual_extra';

      const mockRes = {
        kind: 'dual',
        upfront_u: state.lastBolusPlan.now_u,
        later_u: state.lastBolusPlan.later_u_planned,
        duration_min: state.lastBolusPlan.extended_duration_min || 120,
        plan: state.lastBolusPlan
      };

      app.innerHTML = `
              ${renderHeader("Añadir Extra", true)}
              <main class="page"></main>
              ${renderBottomNav('home')}
           `;

      // We need to render content into main
      // renderBolusResult(mockRes) appends to main.page
      renderBolusResult(mockRes);

      // Wait for render then pre-fill
      setTimeout(() => {
        const inp = document.getElementById('u2-extra-carbs');
        if (inp) inp.value = state.plateBuilder.total;

        // Auto trigger recalc
        const btn = document.getElementById('btn-recalc-u2');
        if (btn) btn.click();
      }, 150);
    };
  }

  if (btnUse) {
    btnUse.onclick = () => {
      // Scale Use
      state.tempCarbs = state.scale.grams;
      navigate('#/bolus');
    };
  }

  // Connect add button (only active after analysis)
  // Logic inside handleImg will enable/handle this.

  // Initial render
  updatePlateUI();
}


function renderBolusResult(res) {
  const calcBtn = document.getElementById('btn-calc-bolus');
  if (calcBtn) calcBtn.hidden = true;

  // Remove existing result if any
  const existing = document.querySelector('.result-card');
  if (existing) existing.remove();

  const container = document.querySelector('main.page');
  // If not on main page (e.g. somehow), use app
  const target = container || app;

  const div = document.createElement('div');

  // Save plan to state mostly for runtime usage
  if (res.kind === 'dual') {
    state.lastBolusPlan = res.plan;
    state.bolusPlanCreatedAt = Date.now();
  }

  div.innerHTML = `
        <div class="card result-card" style="margin-top:1rem; border:2px solid var(--primary);">
            <div style="text-align:center">
                <div class="text-muted">Bolo Recomendado</div>
                <div style="display:flex; justify-content:center; align-items:baseline; gap:5px;">
                   <input type="number" id="final-bolus-input" value="${res.upfront_u}" step="0.5" class="big-number-input" style="width:140px; text-align:right; font-size:3rem; color:var(--primary); font-weight:800; border:none; border-bottom:2px dashed var(--primary); outline:none; background:transparent;">
                   <span style="font-size:1.5rem; font-weight:700; color:var(--primary)">U</span>
                </div>
                ${res.kind === 'dual' ? `
                    <div class="text-muted" id="dual-breakdown">
                        + <span id="val-later-u">${res.later_u}</span> U extendido (${res.duration_min} min)
                    </div>
                ` : ''}
            </div>
            
            ${res.calc?.explain ? `
                <ul class="explain-list" style="margin-top:1rem; font-size:0.8rem; text-align:left; color:#64748b">
                    ${res.calc.explain.map(t => `<li>${t}</li>`).join('')}
                </ul>
            ` : ''}

            ${res.warnings && res.warnings.length ? `
                <div style="background:#fff7ed; color:#c2410c; padding:0.8rem; margin:1rem 0; border-radius:8px; font-size:0.85rem; text-align:left; border:1px solid #fed7aa;">
                    <strong>⚠️ Atención:</strong><br>
                    ${res.warnings.map(w => `• ${w}`).join('<br>')}
                </div>
            ` : ''}

            <!-- EXTRA CARBS SECTION (Dual Only) -->
            ${res.kind === 'dual' ? `
                <div id="extra-carbs-block" style="margin-top:1rem; padding-top:1rem; border-top:1px dashed #eee;">
                    <div style="font-weight:600; font-size:0.9rem; color:#0f766e">➕ Añadir extra (postre / más)</div>
                    <div style="display:flex; gap:0.5rem; margin-top:0.5rem">
                        <input type="number" id="u2-extra-carbs" placeholder="g Carbs" style="width:80px; text-align:center; border:1px solid #ccc; border-radius:6px">
                        <button id="btn-recalc-u2" class="btn-ghost" style="font-size:0.8rem; border:1px solid var(--primary); color:var(--primary)">Recalcular 2ª parte</button>
                    </div>

                    <!-- Quick Import from Plate (if entries exist) -->
                    ${state.plateBuilder && state.plateBuilder.entries.length > 0 ? `
                        <div style="margin-top:0.5rem">
                           <button id="btn-import-plate-extra" class="btn-secondary" style="font-size:0.8rem; width:100%">
                              🍽️ Importar ${state.plateBuilder.total}g del Plato
                           </button>
                        </div>
                    ` : ''}

                    <div id="u2-recalc-result" style="margin-top:0.5rem; display:none; background:#f0fdfa; padding:0.5rem; border-radius:6px; font-size:0.8rem;">
                        <!-- dynamic content -->
                    </div>
                </div>
            ` : ''}

            <div style="display:flex; gap:0.5rem; margin-top:1rem">
                <button id="btn-accept" class="btn-primary" style="background:var(--success); flex:1">✅ Administrar</button>
                <button id="btn-cancel-res" class="btn-ghost" style="flex:1">Cancelar</button>
            </div>
        </div>
    `;

  target.appendChild(div);
  div.scrollIntoView({ behavior: 'smooth' });

  // --- HANDLERS ---

  // 0. Cancel Handler
  const btnCancel = div.querySelector('#btn-cancel-res');
  if (btnCancel) {
    btnCancel.onclick = () => {
      renderBolus();
    };
  }

  // 1. Recalc U2 Handler
  if (res.kind === 'dual') {
    const btnRecalc = div.querySelector('#btn-recalc-u2');
    const inpExtra = div.querySelector('#u2-extra-carbs');
    const resContainer = div.querySelector('#u2-recalc-result');
    const btnImport = div.querySelector('#btn-import-plate-extra');

    // Import Logic
    if (btnImport) {
      btnImport.onclick = () => {
        inpExtra.value = state.plateBuilder.total;
        btnRecalc.click();
      }
    }

    btnRecalc.onclick = async () => {
      const extra = parseFloat(inpExtra.value);
      if (!extra || extra <= 0) {
        alert("Introduce hidratos extra primero.");
        return;
      }

      btnRecalc.textContent = "Calculando...";
      btnRecalc.disabled = true;

      try {
        // Prepare Payload
        const slot = document.getElementById('meal-slot').value;
        const mealParams = getCalcParams();
        const slotParams = mealParams[slot];

        // key safety
        const nsConfig = getLocalNsConfig ? getLocalNsConfig() : {};

        const payload = {
          later_u_planned: state.lastBolusPlan.later_u_planned, // original planned
          carbs_additional_g: extra,
          params: {
            cr_g_per_u: slotParams.icr,
            isf_mgdl_per_u: slotParams.isf,
            target_bg_mgdl: slotParams.target,
            round_step_u: mealParams.round_step_u || 0.5,
            max_bolus_u: mealParams.max_bolus_u || 15,
            stale_bg_minutes: 15
          },
          nightscout: {
            url: nsConfig.url || "",
            token: nsConfig.token || ""
          }
        };

        // Call API
        const u2Res = await recalcSecondBolus(payload);
        state.lastRecalcSecond = u2Res;

        // Render Result
        resContainer.style.display = 'block';
        resContainer.innerHTML = `
                    <div style="font-weight:700; color:#0f766e">Recomendado: ${u2Res.u2_recommended_u} U</div>
                    <div style="color:#666">
                       (Componentes: +${u2Res.components?.meal_u || 0}U comida, -${u2Res.components?.iob_applied_u || 0}U IOB)
                    </div>
                    ${u2Res.warnings && u2Res.warnings.length ? `<div style="color:orange; margin-top:0.5rem; font-size:0.8rem">⚠️ ${u2Res.warnings.join('<br>')}</div>` : ''}
                    
                    <button id="btn-use-u2" class="btn-primary" style="margin-top:0.5rem; padding:0.3rem; font-size:0.8rem; width:100%">Usar esta 2ª parte</button>
                    <button id="btn-clear-u2" class="btn-ghost" style="margin-top:0.2rem; padding:0.2rem; font-size:0.7rem; width:100%">Limpiar</button>
                `;

        // Bind actions
        const btnUse = resContainer.querySelector('#btn-use-u2');
        const btnClear = resContainer.querySelector('#btn-clear-u2');

        btnUse.onclick = () => {
          // Update UI
          document.getElementById('val-later-u').textContent = u2Res.u2_recommended_u;
          // Mutate res closure
          res.later_u = u2Res.u2_recommended_u;
          // Plan Update
          if (state.lastBolusPlan) {
            state.lastBolusPlan.later_u_planned = u2Res.u2_recommended_u;
          }
          resContainer.style.display = 'none';
          inpExtra.value = "";
        };

        btnClear.onclick = () => {
          resContainer.style.display = 'none';
          inpExtra.value = "";
          state.lastRecalcSecond = null;
          btnRecalc.textContent = "Recalcular 2ª parte";
          btnRecalc.disabled = false;
        };

      } catch (e) {
        alert("Error recalculando: " + e.message);
        btnRecalc.textContent = "Recalcular 2ª parte";
        btnRecalc.disabled = false;
      }
    };
  }

  // 2. Accept Handler
  div.querySelector('#btn-accept').onclick = async () => {
    try {
      const carbs = parseFloat(document.getElementById('carbs').value || 0);
      const bg = parseFloat(document.getElementById('bg').value || 0);

      // Read Manual Override
      const finalInsulin = parseFloat(div.querySelector('#final-bolus-input').value);
      if (isNaN(finalInsulin) || finalInsulin < 0) throw new Error("Valor de insulina no válido");

      // Update plan if dual
      if (res.kind === 'dual' && state.lastBolusPlan) {
        state.lastBolusPlan.now_u = finalInsulin;
      }

      const dateInput = document.getElementById('bolus-date');
      let customDate = new Date();
      if (dateInput && dateInput.value) {
        customDate = new Date(dateInput.value);
      }

      const treatment = {
        eventType: "Meal Bolus",
        created_at: customDate.toISOString(),
        carbs: carbs,
        insulin: finalInsulin,
        enteredBy: state.user?.username || "BolusAI",
        notes: `BolusAI: ${res.kind === 'dual' ? 'Dual' : 'Normal'}. Gr: ${carbs}g. BG: ${bg}`
      };

      if (res.kind === 'dual') {
        treatment.notes += ` (Split: ${res.upfront_u} now + ${res.later_u} over ${res.duration_min}m)`;
      }

      await saveTreatment(treatment);
      alert("Bolo registrado con éxito.");
      navigate('#/');
    } catch (e) {
      alert("Error guardando tratamiento: " + e.message);
    }
  };
}


// --- VIEW: BOLUS (Calcular) ---

function renderPlateSummary() {
  if (!state.plateBuilder || !state.plateBuilder.entries.length) return "";

  const items = state.plateBuilder.entries.map(e => {
    return `<div style="display:flex; justify-content:space-between; font-size:0.85rem; padding:4px 0; border-bottom:1px dashed #eee">
            <span>${e.name || 'Alimento detectado'}</span>
            <strong>${e.carbs}g</strong>
        </div>`;
  }).join('');

  return `
    <div class="card" style="background:#f0fdfa; border:1px solid #ccfbf1; margin-bottom:1.5rem">
       <div style="font-weight:700; color:#0f766e; margin-bottom:0.5rem">🥗 Resumen del Plato</div>
       ${items}
       <div style="text-align:right; margin-top:0.5rem; font-size:0.8rem; color:#0d9488">Total calculado por IA</div>
    </div>
    `;
}

function renderBolus() {
  app.innerHTML = `
    ${renderHeader("Calcular Bolo", true)}
    <main class="page">
      
      <!-- Glucose Input -->
      <div class="form-group">
         <div class="label-row">
            <span class="label-text">💧 Glucosa Actual</span>
         </div>
         <div style="position:relative">
            <input type="number" id="bg" placeholder="mg/dL" class="text-center" style="font-size:1.5rem; color:var(--primary); font-weight:800;">
            <span style="position:absolute; right:1rem; top:1rem; color:var(--text-muted)">mg/dL</span>
         </div>
         <input type="range" min="40" max="400" id="bg-slider" class="w-full mt-md">
      </div>

      <!-- Date/Time Input -->
      <div class="form-group">
          <label style="font-size:0.85rem; color:#64748b; margin-bottom:0.3rem; display:block">Fecha / Hora</label>
          <input type="datetime-local" id="bolus-date" style="width:100%; padding:0.5rem; border:1px solid #cbd5e1; border-radius:8px; background:#fff; font-family:inherit;">
      </div>

      <!-- Mode / Slot Selector -->
      <div style="display:flex; gap:0.5rem; margin-bottom:1.5rem; justify-content:center;">
          <select id="meal-slot" style="padding:0.5rem; border-radius:8px; border:1px solid #cbd5e1; background:#fff;">
              <option value="breakfast">Desayuno</option>
              <option value="lunch" selected>Comida</option>
              <option value="dinner">Cena</option>
              <option value="snack">Snack</option>
          </select>
          <div style="display:flex; align-items:center; gap:0.5rem">
             <input type="checkbox" id="chk-correction-only" style="width:20px; height:20px;">
             <label for="chk-correction-only" style="font-size:0.9rem">Solo Corrección</label>
          </div>
      </div>

      <!-- AI Plate Summary (if any) -->
      ${renderPlateSummary()}

      <!-- Carbs Input -->
       <div class="form-group">
         <div class="label-row">
            <span class="label-text">🍪 Carbohidratos Totales</span>
         </div>
         <div style="position:relative">
            <input type="number" id="carbs" placeholder="0" class="text-center" style="font-size:1.5rem; font-weight:800;">
            <span style="position:absolute; right:1rem; top:1rem; color:var(--text-muted)">g</span>
         </div>
         <div class="carb-presets">
            <button class="preset-chip" onclick="addCarbs(0)">0g</button>
            <button class="preset-chip" onclick="addCarbs(15)">15g</button>
            <button class="preset-chip" onclick="addCarbs(30)">30g</button>
            <button class="preset-chip active" onclick="addCarbs(45)">45g</button>
            <button class="preset-chip" onclick="addCarbs(60)">60g</button>
         </div>
      </div>

      <!-- Config Summary -->
      <div class="card" style="background:#f8fafc; border:none;">
        <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:1rem;">
            <span>⚙️ Configuración Actual</span>
        </div>
        <div style="display:flex; justify-content:space-between; text-align:center;">
             <div>
                <div style="font-weight:700; font-size:1.2rem;">100</div>
                <div style="font-size:0.75rem; color:var(--text-muted)">OBJETIVO</div>
             </div>
             <div>
                <div style="font-weight:700; font-size:1.2rem;">1:30</div>
                <div style="font-size:0.75rem; color:var(--text-muted)">ISF</div>
             </div>
             <div>
                <div style="font-weight:700; font-size:1.2rem;">1:10</div>
                <div style="font-size:0.75rem; color:var(--text-muted)">I:C</div>
             </div>
        </div>
      </div>

      <!-- Dual Bolus Controls -->
       <div class="card" style="margin-bottom:1.5rem">
         <div style="display:flex; justify-content:space-between; align-items:center;">
             <div style="font-weight:600">🌊 Bolo Dual / Extendido</div>
             <input type="checkbox" id="chk-dual-enabled" class="toggle-switch">
         </div>
         <div id="dual-info" hidden style="margin-top:0.5rem; font-size:0.8rem; color:var(--text-muted); background:#f8fafc; padding:0.5rem; border-radius:6px;">
             <!-- Info populated by JS -->
         </div>
       </div>

      <!-- IOB Banner -->
      <div style="background:#eff6ff; padding:1rem; border-radius:12px; display:flex; justify-content:space-between; align-items:center; margin-bottom:2rem;">
        <div>
            <div style="font-weight:600; color:#1e40af">Insulina Activa (IOB)</div>
            <div style="font-size:0.8rem; color:#60a5fa">Se restará del bolo</div>
        </div>
        <div id="iob-display-value" style="font-size:1.5rem; font-weight:700; color:#1e40af">-- <span style="font-size:1rem">U</span></div>
      </div>

      <button class="btn-primary" id="btn-calc-bolus">Calcular Bolo</button>

    </main>
    ${renderBottomNav('bolus')}
  `;

  // Handlers
  const bgInput = document.getElementById('bg');
  const bgSlider = document.getElementById('bg-slider');
  const carbsInput = document.getElementById('carbs');
  const calcBtn = document.getElementById('btn-calc-bolus');
  const dateInput = document.getElementById('bolus-date');

  // Init Date
  if (dateInput) {
    const now = new Date();
    // Local ISO format: YYYY-MM-DDTHH:mm
    const localIso = new Date(now.getTime() - (now.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
    dateInput.value = localIso;
  }

  // Sync Slider
  if (bgInput && bgSlider) {
    bgSlider.oninput = (e) => bgInput.value = e.target.value;
    bgInput.oninput = (e) => bgSlider.value = e.target.value;
    // Set initial
    if (state.currentGlucose.data?.bg_mgdl) {
      bgInput.value = Math.round(state.currentGlucose.data.bg_mgdl);
      bgSlider.value = bgInput.value;
    }
  }

  // Pre-fill Carbs from Vision/Plate if available
  // check tempCarbs explicitly
  if (state.tempCarbs !== null && state.tempCarbs !== undefined) {
    if (carbsInput) carbsInput.value = state.tempCarbs;
    // Do NOT clear immediately if we want to persist on re-renders,
    // but usually 'temp' implies one-time consumption. 
    // Let's clear it so if user goes back and forth it doesn't get stuck?
    // Actually better to keep it until action taken? 
    // For now, clear to match old behavior.
    state.tempCarbs = null;
  }

  // Presets
  // Presets
  window.addCarbs = (val) => {
    if (carbsInput) {
      carbsInput.value = val;
      // Uncheck correction mode if setting carbs
      const chk = document.getElementById('chk-correction-only');
      if (chk) chk.checked = false;
    }
    document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
    event.target.classList.add('active');
  };

  // Correction Toggle Handler
  const chkCorr = document.getElementById('chk-correction-only');
  // Removed invalid querySelector with :contains

  if (chkCorr) {
    chkCorr.onchange = () => {
      if (chkCorr.checked) {
        if (carbsInput) {
          carbsInput.value = 0;
          carbsInput.parentElement.parentElement.classList.add('disabled-block'); // Visual feedback
        }
      } else {
        if (carbsInput) carbsInput.parentElement.parentElement.classList.remove('disabled-block');
      }
    }
  }

  // Sync Dual Controls
  const chkDual = document.getElementById('chk-dual-enabled');
  const divDualInfo = document.getElementById('dual-info');

  if (chkDual && divDualInfo) {
    const updateInfo = () => {
      const s = getSplitSettings() || {};
      divDualInfo.textContent = `Configurado: ${s.percent_now || 70}% ahora, resto en ${s.duration_min || 120} min.`;
      divDualInfo.hidden = !chkDual.checked;
    };

    chkDual.onchange = updateInfo;

    // Init default
    const defs = getSplitSettings();
    if (defs && defs.enabled_default) {
      chkDual.checked = true;
    }
    updateInfo();
  }

  // Sync IOB
  const iobEl = document.getElementById('iob-display-value');
  const iobBanner = iobEl ? iobEl.parentElement : null;

  if (iobEl) {
    const nsConfig = getLocalNsConfig();
    if (nsConfig && nsConfig.url) {
      getIOBData(nsConfig).then(d => {
        // Robust Handling
        const info = d.iob_info || {};
        const val = typeof info.iob_u === 'number' ? info.iob_u : (d.iob_total || 0.0);

        if (info.status === 'unavailable') {
          iobEl.innerHTML = `⚠️ N/A`;
          if (iobBanner) {
            iobBanner.style.background = "#fff1f2"; // Light Red
            iobBanner.querySelector('div').style.color = "#881337"; // Dark Red
            iobBanner.querySelector('div:last-child').style.color = "#be123c"; // Red
            // Add reason subtitle
            const sub = document.createElement('div');
            sub.style.fontSize = "0.7rem";
            sub.style.color = "#be123c";
            sub.textContent = info.reason;
            iobBanner.children[0].appendChild(sub);
          }
        } else if (info.status === 'partial') {
          iobEl.innerHTML = `${val.toFixed(2)}⚠️ <span style="font-size:1rem">U</span>`;
          if (iobBanner) iobBanner.style.background = "#fff7ed"; // Orange light
        } else {
          iobEl.innerHTML = `${val.toFixed(2)} <span style="font-size:1rem">U</span>`;
        }
      }).catch(err => {
        console.error("IOB Fetch Error", err);
        iobEl.innerHTML = `? <span style="font-size:1rem">U</span>`;
      });
    } else {
      iobEl.innerHTML = `N/A`;
    }
  }

  // Calculate Action
  if (calcBtn) {
    calcBtn.onclick = async () => {
      calcBtn.textContent = "Calculando...";
      calcBtn.disabled = true;

      try {
        const bg = parseFloat(bgInput.value);
        const carbs = parseFloat(carbsInput.value) || 0;
        const slot = document.getElementById('meal-slot').value;
        const isCorrection = document.getElementById('chk-correction-only').checked;

        if (isNaN(bg)) {
          throw new Error("Introduce tu glucosa actual.");
        }

        // Get Settings
        const mealParams = getCalcParams();
        // Fallback if no params found at all
        if (!mealParams) {
          throw new Error("No hay configuración de ratios. Ve a Ajustes y guarda tus datos.");
        }
        const slotParams = mealParams[slot];

        // Validate slot params
        if (!slotParams || !slotParams.icr || !slotParams.isf || !slotParams.target) {
          // Try defaults or error
          throw new Error(`Faltan datos para el horario '${slot}'. Configúralos en ajustes.`);
        }

        // Fix: Use "lunch" as fallback for "snack" to satisfy backend enum,
        // but pass explicit ratios so the calculation uses the 'snack' values.
        const effectiveSlot = ["breakfast", "lunch", "dinner"].includes(slot) ? slot : "lunch";

        // Use params from storage (Hybrid Mode)
        // We lift them to root because backend expects BolusRequestV2 in flat mode (Hybrid)
        const payload = {
          carbs_g: isCorrection ? 0 : carbs,
          bg_mgdl: bg,
          meal_slot: effectiveSlot,

          // Flattened params for Stateless/Hybrid mode
          target_mgdl: slotParams.target,
          cr_g_per_u: slotParams.icr,
          isf_mgdl_per_u: slotParams.isf,

          dia_hours: mealParams.dia_hours || 4.0,
          round_step_u: mealParams.round_step_u || 0.5,
          max_bolus_u: mealParams.max_bolus_u || 15,
        };

        console.log("Sending Bolus Calc Payload:", payload);

        // Split Logic
        const isDual = document.getElementById('chk-dual-enabled').checked;
        let splitSettings = getSplitSettings() || {};

        // Override enabled flag if manually checked
        if (isDual) {
          splitSettings = {
            ...splitSettings,
            enabled: true
          };
        } else {
          splitSettings = {
            ...splitSettings,
            enabled: false
          };
        }

        // Check logic: Enabled manually OR (default enabled AND not correction only AND carbs > 0)
        // actually, if we have manual UI, we trust the UI 'isDual' state mainly.
        // But if user didn't touch it? logic should match UI initialization.
        // UI initialization sets check based on default. So trusting UI is safe.

        const useSplit = (isDual && !isCorrection && carbs > 0);

        const res = await calculateBolusWithOptionalSplit(payload, useSplit ? splitSettings : null);

        state.bolusResult = res;
        renderBolusResult(res);

      } catch (err) {
        console.error(err);
        alert("Error al calcular: " + err.message);
        calcBtn.textContent = "Calcular Bolo";
        calcBtn.disabled = false;
      }
    };
  }
}


// --- VIEW: HISTORY ---
async function renderHistory() {
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

    // Filter useful items
    const validItems = treatments.filter(t => {
      const u = parseFloat(t.insulin);
      const c = parseFloat(t.carbs);
      // Keep if explicit bolus/carb > 0, or if eventType marks it relevant (even if 0, might be useful?)
      // Focusing on values > 0 as per user expectation
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

      // Stats Accumulation
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

    // Update Stats
    document.getElementById('hist-daily-insulin').textContent = todayInsulin.toFixed(1);
    document.getElementById('hist-daily-carbs').textContent = Math.round(todayCarbs);

  } catch (e) {
    if (document.getElementById('full-history-list'))
      document.getElementById('full-history-list').innerHTML = `<div class="error-msg">${e.message}</div>`;
  }
}


// --- VIEW: PATTERNS ---
async function renderPatterns() {
  if (!ensureAuthenticated()) return;
  app.innerHTML = `
        ${renderHeader("Patrones", true)}
        <main class="page">
            <section class="card">
                <h3>Análisis Post-Bolo</h3>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
                    <select id="analysis-days" style="padding:0.5rem; border-radius:6px; font-size:1rem;">
                        <option value="14">14 días</option>
                        <option value="30" selected>30 días</option>
                        <option value="60">60 días</option>
                    </select>
                    <button id="btn-recalc-patterns" class="btn-primary" style="padding:0.5rem 1rem; font-size:0.9rem;">Recalcular</button>
                </div>
                
                <div id="patterns-status" style="margin-bottom:1rem; font-size:0.9rem; color:#64748b;"></div>
                
                <div id="patterns-content">
                    <div class="spinner">Cargando datos...</div>
                </div>
                
                <div id="patterns-quality" style="margin-top:2rem; font-size:0.8rem; color:#94a3b8; border-top:1px solid #e2e8f0; padding-top:1rem;"></div>
            </section>
        </main>
        ${renderBottomNav('patterns')}
    `;

  // Bind
  const selDays = document.getElementById('analysis-days');
  const btnRecalc = document.getElementById('btn-recalc-patterns');

  // Load
  loadSummary(parseInt(selDays.value));

  selDays.onchange = () => loadSummary(parseInt(selDays.value));

  btnRecalc.onclick = async () => {
    btnRecalc.disabled = true;
    btnRecalc.textContent = "Analizando...";
    const statusEl = document.getElementById('patterns-status');
    statusEl.textContent = "Calculando patrones... esto puede tardar unos segundos.";

    try {
      const res = await runAnalysis(parseInt(selDays.value));
      statusEl.textContent = `Análisis completado: ${res.boluses} bolos analizados.`;
      statusEl.style.color = "var(--success)";
      await loadSummary(parseInt(selDays.value));
    } catch (e) {
      statusEl.textContent = "Error: " + e.message;
      statusEl.style.color = "var(--error)";
    } finally {
      btnRecalc.disabled = false;
      btnRecalc.textContent = "Recalcular";
    }
  };
}

async function loadSummary(days) {
  const container = document.getElementById('patterns-content');
  const qContainer = document.getElementById('patterns-quality');
  container.innerHTML = `<div class="spinner">Cargando...</div>`;

  try {
    const data = await getAnalysisSummary(days);

    // Insights
    let html = "";

    if (data.insights && data.insights.length > 0) {
      html += `<ul style="background:#f0fdf4; padding:1rem; border-radius:8px; border:1px solid #bbf7d0; margin-bottom:1.5rem;">`;
      data.insights.forEach(i => {
        html += `<li style="margin-bottom:0.5rem; color:#166534;"><strong>${i}</strong></li>`;
      });
      html += `</ul>`;
    } else {
      html += `<div style="padding:1rem; color:#64748b; font-style:italic; text-align:center;">No se detectaron patrones claros o faltan datos (min 5).</div>`;
    }

    // Table
    html += `<div style="overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; font-size:0.9rem;">
                <thead>
                    <tr style="background:#f8fafc; border-bottom:2px solid #e2e8f0;">
                        <th style="padding:0.5rem; text-align:left;">Comida</th>
                        <th style="padding:0.5rem; text-align:center;">2h</th>
                        <th style="padding:0.5rem; text-align:center;">3h</th>
                        <th style="padding:0.5rem; text-align:center;">5h</th>
                    </tr>
                </thead>
                <tbody>`;

    const meals = ["breakfast", "lunch", "dinner", "snack"];
    const mealLabels = { breakfast: "Desayuno", lunch: "Comida", dinner: "Cena", snack: "Snack" };

    meals.forEach(m => {
      const row = data.by_meal ? data.by_meal[m] : null;
      if (!row) return;

      html += `<tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:0.8rem 0.5rem; font-weight:600;">${mealLabels[m] || m}</td>`;

      [2, 3, 5].forEach(h_num => {
        const w = row[`${h_num}h`]; // {short, ok, over, missing}
        const total = w ? (w.short + w.ok + w.over) : 0;
        let cellContent = "";

        if (!w || total < 5) {
          cellContent = `<span style="color:#cbd5e1; font-size:0.8rem;">(n=${total})</span>`;
        } else {
          if (w.short > 0) cellContent += `<span class="chip" style="background:#fef3c7; color:#b45309; border:1px solid #fcd34d; font-size:0.75rem; padding:2px 4px; border-radius:4px; margin-right:2px;">Corto:${w.short}</span> `;
          if (w.over > 0) cellContent += `<span class="chip" style="background:#fee2e2; color:#b91c1c; border:1px solid #fca5a5; font-size:0.75rem; padding:2px 4px; border-radius:4px; margin-right:2px;">Mucha:${w.over}</span> `;
          if (w.ok > 0) cellContent += `<span class="chip" style="background:#dcfce7; color:#15803d; border:1px solid #86efac; font-size:0.75rem; padding:2px 4px; border-radius:4px;">OK:${w.ok}</span> `;
        }
        html += `<td style="padding:0.5rem; text-align:center; vertical-align:top;">${cellContent || "-"}</td>`;
      });
      html += `</tr>`;
    });

    html += `</tbody></table></div>`;
    container.innerHTML = html;

    // Quality
    const dq = data.data_quality || {};
    qContainer.innerHTML = `Calidad de datos: ${dq.iob_unavailable_events || 0} eventos con IOB no disponible (excluidos). Total eventos: ${dq.total_events || 0}.`;

  } catch (e) {
    container.innerHTML = `<div class="error">Error cargando resumen: ${e.message}</div>`;
  }
}

// --- VIEW: SUGGESTIONS ---
async function renderSuggestions() {
  if (!ensureAuthenticated()) return;
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

  // Init Style
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
      // We want LIST of accepted suggestions, AND their evaluation status.
      // Currently getting accepted suggestions works via getSuggestions("accepted").
      // But we also want the evaluation.
      // Option A: getSuggestions returns stored evaluation in JSON? No, models separate.
      // Option B: getEvaluations returns evaluations, we join manually?
      // Better: getEvaluations should return what we need. 
      // The backend endpoint /api/suggestions/evaluations returns SuggestionEvaluation list.
      // But that only returns evaluated ones. What about accepted but NOT evaluated?
      // We need a unified list or logic.
      // Since User requested: "SI han pasado menos de days... Botón Evaluar".

      // Let's fetch ACCEPTED suggestions, and also fetch EVALUATIONS.
      const [accepted, evaluations] = await Promise.all([
        getSuggestions("accepted"),
        getEvaluations()
      ]);

      // Create map of Eval by SuggestionID
      const evalMap = {};
      evaluations.forEach(e => evalMap[e.suggestion_id] = e);

      if (accepted.length === 0) {
        histList.innerHTML = `<div style="text-align:center; padding:3rem; color:#94a3b8; font-style:italic;">No hay historial de cambios aceptados.</div>`;
        return;
      }

      histList.innerHTML = accepted.map(s => {
        const ev = evalMap[s.id];
        const resolvedDate = new Date(s.resolved_at); // when it was accepted

        // Diff in days to now
        const now = new Date();
        const diffTime = Math.abs(now - resolvedDate);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

        let impactHtml = "";

        if (ev) {
          // Status: Evaluated
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
          // Not evaluated
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
                         <small style="color:#94a3b8">${resolvedDate.toLocaleDateString()}</small>
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

  window.handleEvaluate = async (id) => {
    try {
      // visual feedback?
      const btn = document.activeElement;
      if (btn) btn.textContent = "Evaluando...";

      const res = await evaluateSuggestion(id, 7);
      alert(`Evaluación completada: ${res.summary}`);
      loadHistory();
    } catch (e) {
      alert(e.message);
    }
  };


  // Global handlers for buttons in HTML maps
  window.handleReject = async (id) => {
    const reason = prompt("¿Motivo del rechazo? (Opcional)");
    if (reason === null) return; // cancelled
    try {
      await rejectSuggestion(id, reason || "Rechazado por usuario");
      loadList(); // Refresh
    } catch (e) {
      alert(e.message);
    }
  };

  window.handleAccept = (id, slotRaw, paramRaw) => {
    // 1. Get current config
    const settings = getCalcParams();
    if (!settings) {
      alert("Error: No se encontró configuración local.");
      return;
    }

    // Slot mapping: backend uses 'breakfast', settings uses 'breakfast' keys
    // Param mapping: backend 'icr' -> settings 'icr', 'isf' -> 'isf', 'target' -> 'target'
    const slotData = settings[slotRaw];
    if (!slotData) {
      alert(`Error: No existe configuración para ${slotRaw}`);
      return;
    }

    const currentVal = slotData[paramRaw]; // e.g. slotData.icr

    // 2. Open Modal
    document.getElementById('accept-current-val').textContent = currentVal;
    document.getElementById('accept-new-val').value = currentVal; // prefill
    document.getElementById('accept-modal-desc').textContent = `Estás revisando el ${paramRaw.toUpperCase()} para ${slotRaw}.`;

    // Setup Bindings
    const btnSave = document.getElementById('btn-modal-confirm');
    const btnCancel = document.getElementById('btn-modal-cancel');

    // Clear previous listeners to avoid dupes (rough way: replacing element or just proper scoping)
    // Since we render modal in HTML string each time we verify 'renderSuggestions', events are fresh? 
    // No, 'renderSuggestions' overwrites app.innerHTML, so new DOM elements each time.
    // BUT window.handleAccept is global, it refers to current DOM.

    // Simple 'onclick' will work.
    btnCancel.onclick = () => modal.close();

    btnSave.onclick = async () => {
      const newVal = parseFloat(document.getElementById('accept-new-val').value);
      if (isNaN(newVal) || newVal <= 0) {
        alert("Valor inválido");
        return;
      }

      // 3. Apply Change locally
      settings[slotRaw][paramRaw] = newVal;
      saveCalcParams(settings);

      // 4. Call API Accept
      try {
        btnSave.textContent = "Guardando...";
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
        btnSave.textContent = "Guardar";
      }
    };

    modal.showModal();
  };
}


// --- VIEW: BASAL ---
async function renderBasal() {
  if (!ensureAuthenticated()) return;

  app.innerHTML = `
    ${renderHeader("Basal Advisor", true)}
    <main class="page">
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

  // 1. Load Advice (3 days default)
  try {
    const advice = await getBasalAdvice(3);
    const card = document.getElementById('basal-advice-card');
    const content = document.getElementById('basal-advice-content');

    let color = "#64748b"; // default
    let icon = "ℹ️";

    // Simple heuristic for UI color based on message keywords
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

        // Wake formatting
        let wakeHtml = "--";
        if (item.wake_bg !== null) {
          wakeHtml = `<strong>${Math.round(item.wake_bg)}</strong>`;
          if (item.wake_trend) wakeHtml += ` <small style="color:#94a3b8">${item.wake_trend}</small>`;
        }

        // Night formatting
        let nightHtml = `<span style="color:#cbd5e1">--</span>`;
        if (item.night_had_hypo === true) {
          nightHtml = `<span style="color:var(--danger); font-weight:700">🌙 < 70</span>`;
          if (item.night_events_below_70 > 1) nightHtml += ` (${item.night_events_below_70})`;
        } else if (item.night_had_hypo === false) {
          nightHtml = `<span style="color:var(--success)">OK</span>`;
        } else {
          // Scan button?
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

  // 3. Eval Handlers
  const handleEval = async (days) => {
    const resContainer = document.getElementById('basal-eval-result');
    const btn = document.getElementById(`btn-eval-${days}`);

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

  // Method to scan night (global for onclick)
  window.handleScanNight = async (dateStr) => {
    try {
      const config = getLocalNsConfig();
      if (!config || !config.url) {
        alert("Configura Nightscout primero.");
        return;
      }
      // Simple visual feedback
      const btn = document.activeElement;
      if (btn) btn.textContent = "🔍...";

      await runNightScan(config, dateStr);
      renderBasal(); // Refresh logic
    } catch (e) {
      alert(e.message);
    }
  };
}

// Router invoke
render();
