
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

function saveCalcParams(params) {
  localStorage.setItem(CALC_PARAMS_KEY, JSON.stringify(params));
}

const state = {
  token: getStoredToken(),
  user: getStoredUser(),
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

async function updateIOB() {
  if (!iobDisplay) return;
  iobDisplay.innerHTML = '<span class="loading-text">...</span>';
  try {
    const nsConfig = getLocalNsConfig();
    const data = await getIOBData(nsConfig && nsConfig.url ? nsConfig : null);

    iobDisplay.innerHTML = `
    < div class="big-number" > ${data.iob_total} U</div >
      ${(data.breakdown && data.breakdown.length) ? `<small>De ${data.breakdown.length} bolos</small>` : ""}
  `;

    if (data.graph && iobCanvas) {
      drawIOBGraph(iobCanvas, data.graph);
    }
  } catch (err) {
    iobDisplay.innerHTML = `< span class="error small" > ${err.message}</span > `;
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

// --- HELPER FUNCTIONS FOR UI ---
async function updateMetrics() {
  // 1. IOB
  await updateIOB();

  // 2. COB (Mock for now or fetch)
  // 3. Last Bolus
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

function renderHeader(title = "Bolus AI", showBack = false) {
  if (!state.user) return "";
  return `
      <header class="topbar">
        ${showBack
      ? `<div class="header-action" onclick="window.history.back()">‹</div>`
      : `<div class="header-profile">👤</div>`
    }
        <div class="header-title-group">
          <div class="header-title">${title}</div>
          ${!showBack ? `<div class="header-subtitle">Tu asistente de diabetes</div>` : ''}
        </div>
        <div class="header-action has-dot" id="notifications-btn">🔔</div>
      </header>
    `;
}

function renderBottomNav(activeTab = 'home') {
  return `
      <nav class="bottom-nav">
        <button class="nav-btn ${activeTab === 'home' ? 'active' : ''}" onclick="navigate('#/')">
          <span class="nav-icon">🏠</span>
          <span class="nav-lbl">Inicio</span>
        </button>
        <button class="nav-btn ${activeTab === 'scan' ? 'active' : ''}" onclick="navigate('#/scan')">
          <span class="nav-icon">📷</span>
          <span class="nav-lbl">Escanear</span>
        </button>
        <button class="nav-btn ${activeTab === 'bolus' ? 'active' : ''}" onclick="navigate('#/bolus')">
          <span class="nav-icon">🧮</span>
          <span class="nav-lbl">Bolo</span>
        </button>
        <button class="nav-btn ${activeTab === 'history' ? 'active' : ''}" onclick="navigate('#/history')">
          <span class="nav-icon">⏱️</span>
          <span class="nav-lbl">Historial</span>
        </button>
        <button class="nav-btn ${activeTab === 'settings' ? 'active' : ''}" onclick="navigate('#/settings')">
          <span class="nav-icon">⚙️</span>
          <span class="nav-lbl">Ajustes</span>
        </button>
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
              <input type="number" step="1" id="slot-isf" required min="5" />
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
              <option value="0.1">0.1 U</option>
              <option value="0.5">0.5 U</option>
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
                  <option value="0.1">0.1</option>
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
    round_step_u: 0.1,
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

function render() {
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
    renderSettings(); // Already exists
  } else if (route === "#/scan") {
    renderScan();
  } else if (route === "#/bolus") {
    renderBolus();
  } else if (route === "#/history") {
    renderHistory();
  } else {
    renderHome(); // Default to Home
  }
}

// --- VIEW: HOME (Inicio) ---
async function renderHome() {
  const glucoseData = state.currentGlucose.data || {};
  const bgValue = glucoseData.bg_mgdl ? Math.round(glucoseData.bg_mgdl) : '--';
  const trendArrow = glucoseData.trendArrow || '→';
  const ageMin = glucoseData.age_minutes ? Math.round(glucoseData.age_minutes) : '--';
  const isStale = glucoseData.stale;

  app.innerHTML = `
    ${renderHeader("Bolus AI")}
    <main class="page">
      <!-- Glucose Hero -->
      <section class="card glucose-hero">
        <div class="gh-header">
          <div>
            <div class="gh-title">Glucosa Actual</div>
            <div class="gh-source">Nightscout</div>
          </div>
          <button class="gh-refresh" id="refresh-bg-btn">↻</button>
        </div>
        <div class="gh-value-group">
            <span class="gh-value">${bgValue}</span>
            <div class="gh-unit-group">
                <span class="gh-arrow">${trendArrow}</span>
                <span class="gh-unit">mg/dL</span>
            </div>
        </div>
        <div class="gh-status-pill">
            <span>En rango</span>
            <span style="font-weight:400; color:var(--success)">•</span>
            <span class="gh-time">Hace ${ageMin} min</span>
        </div>
      </section>

      <!-- Metrics -->
      <div class="metrics-grid">
        <div class="metric-tile">
            <div class="metric-head"><span class="metric-icon">💧</span> IOB</div>
            <div class="metric-val" id="metric-iob">-- <span class="metric-unit">U</span></div>
        </div>
        <div class="metric-tile cob">
            <div class="metric-head"><span class="metric-icon">🍪</span> COB</div>
            <div class="metric-val">-- <span class="metric-unit">g</span></div>
        </div>
        <div class="metric-tile last">
            <div class="metric-head"><span class="metric-icon">💉</span> Último</div>
            <div class="metric-val">-- <span class="metric-unit">U</span></div>
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
      <div class="activity-list">
        <!-- Mock Data -->
        <div class="activity-item">
            <div class="act-icon">💉</div>
            <div class="act-details">
                <div class="act-val">3.5 U</div>
                <div class="act-sub">Almuerzo</div>
            </div>
            <div class="act-time">12:30</div>
        </div>
        <div class="activity-item">
            <div class="act-icon" style="color:#f59e0b">🍪</div>
            <div class="act-details">
                <div class="act-val">45 g</div>
                <div class="act-sub">Pasta</div>
            </div>
            <div class="act-time">12:28</div>
        </div>
      </div>
    </main>
    ${renderBottomNav('home')}
  `;

  // Handlers
  const refreshBtn = document.querySelector("#refresh-bg-btn");
  if (refreshBtn) refreshBtn.onclick = () => updateGlucoseUI();

  // Load Data
  updateGlucoseUI();
  updateMetrics();
}

// --- VIEW: SCAN (Foto) ---
function renderScan() {
  app.innerHTML = `
    ${renderHeader("Foto del Plato", true)}
    <main class="page">
      <div class="camera-placeholder" onclick="document.getElementById('cameraInput').click()">
        <div class="camera-icon-big">📷</div>
        <div>Toca para tomar foto</div>
      </div>

      <div class="vision-actions">
        <button class="btn-primary" onclick="document.getElementById('cameraInput').click()">
            📷 Tomar Foto
        </button>
        <button class="btn-secondary" onclick="document.getElementById('photosInput').click()">
            🖼️ Subir desde Galería
        </button>
      </div>

      <!-- Hidden Inputs -->
      <input type="file" id="cameraInput" accept="image/*" capture="environment" hidden />
      <input type="file" id="photosInput" accept="image/*" hidden />

      <div class="card tips-card">
        <h4 style="margin-top:0">Consejos para mejores resultados:</h4>
        <ul style="padding-left:1.5rem; color:var(--text-secondary); font-size:0.9rem;">
            <li>Buena iluminación natural</li>
            <li>Foto desde arriba, mostrando todo el plato</li>
            <li>Evita sombras y reflejos</li>
        </ul>
      </div>

      <!-- Results Overlay will be handled by logic or nav to Bolus with params -->
    </main>
    ${renderBottomNav('scan')}
  `;

  // Attach handlers
  const fileInputs = [document.getElementById('cameraInput'), document.getElementById('photosInput')];

  const handleImg = async (e) => {
    if (!e.target.files || !e.target.files.length) return;
    const file = e.target.files[0];

    // Show loading state
    const actions = document.querySelector('.vision-actions');
    const originalContent = actions.innerHTML;
    actions.innerHTML = '<div class="spinner">⏳ Analizando...</div>';

    try {
      // 1. Estimate
      const result = await estimateCarbsFromImage(file);
      state.visionResult = result;

      // 2. Navigate to Bolus with Pre-fill
      // We can pass data via state or URL. Using state is cleaner.
      state.tempCarbs = result.carbs_estimate_g;

      // Notify user
      actions.innerHTML = '<div class="success-msg">✅ ¡Listo!</div>';
      setTimeout(() => navigate('#/bolus'), 500);

    } catch (err) {
      console.error(err);
      actions.innerHTML = `<div class="error-msg">❌ Error: ${err.message}</div>`;
      setTimeout(() => actions.innerHTML = originalContent, 3000);
    }
  };

  fileInputs.forEach(input => {
    if (input) input.onchange = handleImg;
  });
}

// --- VIEW: BOLUS (Calcular) ---
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
         <!-- Slider could go here -->
         <input type="range" min="40" max="400" id="bg-slider" class="w-full mt-md">
      </div>

      <!-- Carbs Input -->
       <div class="form-group">
         <div class="label-row">
            <span class="label-text">🍪 Carbohidratos</span>
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

      <!-- IOB Banner -->
      <div style="background:#eff6ff; padding:1rem; border-radius:12px; display:flex; justify-content:space-between; align-items:center; margin-bottom:2rem;">
        <div>
            <div style="font-weight:600; color:#1e40af">Insulina Activa (IOB)</div>
            <div style="font-size:0.8rem; color:#60a5fa">Se restará del bolo</div>
        </div>
        <div style="font-size:1.5rem; font-weight:700; color:#1e40af">1.8 <span style="font-size:1rem">U</span></div>
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

  // Pre-fill Carbs from Vision if available
  if (state.tempCarbs) {
    if (carbsInput) carbsInput.value = state.tempCarbs;
    state.tempCarbs = null; // Clear
  }

  // Presets
  window.addCarbs = (val) => {
    if (carbsInput) carbsInput.value = val;
    document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
    event.target.classList.add('active');
  };

  // Calculate Action
  if (calcBtn) {
    calcBtn.onclick = async () => {
      calcBtn.disabled = true;
      calcBtn.textContent = "Calculando...";

      try {
        const carbs = parseFloat(carbsInput.value || 0);
        const bg = parseFloat(bgInput.value || 0);

        // Get Config
        // For now assuming 'lunch' or derive from time?
        // Let's default to 'lunch' or user choice if we had a selector.
        // We'll use 'meal_slot' from state or default.
        const slot = "lunch"; // Simplify for now
        const calcParams = getCalcParams();
        const meal = calcParams ? (calcParams[slot] || getDefaultMealParams(calcParams)) : null;

        if (!meal) throw new Error("Configura tus parámetros (ICR/ISF) en Ajustes.");

        const payload = {
          carbs_g: carbs,
          glucose_mgdl: bg,
          bg_mgdl: bg,
          target_mgdl: meal.target,
          cr_g_per_u: meal.icr,
          isf_mgdl_per_u: meal.isf,
          dia_hours: calcParams?.dia_hours || 4,
          round_step_u: calcParams?.round_step_u || 0.1,
          max_bolus_u: calcParams?.max_bolus_u || 10
        };

        const res = await calculateBolusWithOptionalSplit(payload, null);

        // Render Result overlay or replace button
        calcBtn.hidden = true;

        // Show Result Card
        const resHtml = `
                <div class="card result-card" style="margin-top:1rem; border:2px solid var(--primary);">
                    <div style="text-align:center">
                        <div class="text-muted">Bolo Recomendado</div>
                        <div class="big-number" style="color:var(--primary)">${res.upfront_u} U</div>
                        ${res.kind === 'dual' ? `<div class="text-muted">+ ${res.later_u} U extendido</div>` : ''}
                    </div>
                    ${res.calc?.explain ? `<ul class="explain-list" style="margin-top:1rem; font-size:0.8rem; text-align:left; color:#64748b">${res.calc.explain.map(t => `<li>${t}</li>`).join('')}</ul>` : ''}
                    <button id="btn-accept" class="btn-primary" style="background:var(--success); margin-top:1rem;">✅ Administrar</button>
                    <button class="btn-ghost" onclick="renderBolus()" style="margin-top:0.5rem">Cancelar</button>
                </div>
             `;

        const container = document.querySelector('main.page');
        const div = document.createElement('div');
        div.innerHTML = resHtml;
        container.appendChild(div);
        div.scrollIntoView({ behavior: 'smooth' });

        document.getElementById('btn-accept').onclick = async () => {
          try {
            // Save Treatment
            await saveTreatment({
              insulin: res.total_u,
              carbs: carbs,
              created_at: new Date().toISOString(),
              enteredBy: state.user.username
            });
            alert("Guardado en Nightscout");
            navigate('#/');
          } catch (e) {
            alert("Error guardando: " + e.message);
          }
        };

      } catch (e) {
        alert(e.message);
        calcBtn.disabled = false;
        calcBtn.textContent = "Calcular Bolo";
      }
    };
  }
}

// --- VIEW: HISTORY ---
function renderHistory() {
  app.innerHTML = `
      ${renderHeader("Historial", true)}
      <main class="page">
        <!-- Stats Row -->
        <div class="metrics-grid">
            <div class="metric-tile" style="background:#eff6ff; text-align:center; padding:1.5rem 0.5rem">
                <div style="font-size:1.5rem; font-weight:800; color:#2563eb">12.4</div>
                <div style="font-size:0.7rem; color:#93c5fd; font-weight:700">INSULINA HOY</div>
            </div>
            <div class="metric-tile" style="background:#fff7ed; text-align:center; padding:1.5rem 0.5rem">
                <div style="font-size:1.5rem; font-weight:800; color:#f97316">145</div>
                <div style="font-size:0.7rem; color:#fdba74; font-weight:700">CARBOS HOY</div>
            </div>
            <div class="metric-tile" style="background:#dcfce7; text-align:center; padding:1.5rem 0.5rem">
                <div style="font-size:1.5rem; font-weight:800; color:#16a34a">72%</div>
                <div style="font-size:0.7rem; color:#86efac; font-weight:700">EN RANGO</div>
            </div>
        </div>

        <h4 style="margin-bottom:1rem; color:var(--text-muted)">Hoy</h4>
        
        <div class="activity-list">
             <!-- Mock History Items -->
             <div class="activity-item">
                <div class="act-icon" style="background:#eff6ff; color:#2563eb">💉</div>
                <div class="act-details">
                    <div class="act-val">3.5 U <span style="font-size:0.8rem; font-weight:400; background:#f1f5f9; padding:2px 6px; border-radius:4px;">142 mg/dL</span></div>
                    <div class="act-sub">Almuerzo</div>
                </div>
                <div class="act-time">12:30 ›</div>
             </div>

             <div class="activity-item">
                <div class="act-icon" style="background:#fff7ed; color:#f97316">🍪</div>
                <div class="act-details">
                    <div class="act-val">45 g</div>
                    <div class="act-sub">Pasta</div>
                </div>
                <div class="act-time">12:28 ›</div>
             </div>
        </div>
      </main>
      ${renderBottomNav('history')}
    `;
}

// Router invoke
render();
