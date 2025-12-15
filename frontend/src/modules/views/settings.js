import { state, saveCalcParams, getCalcParams, getSplitSettings, saveSplitSettings } from '../core/store.js';
import { navigate, ensureAuthenticated } from '../core/router.js';
import { renderHeader, renderBottomNav } from '../components/layout.js';
import { getLocalNsConfig, saveLocalNsConfig, testNightscout, fetchHealth, logout, exportUserData } from '../../lib/api.js';

export function renderSettings() {
  if (!ensureAuthenticated()) return;
  const app = document.getElementById("app");

  app.innerHTML = `
    ${renderHeader()}
  <main class="page">
    <section class="card">
      <div class="tabs">
        <button id="tab-ns" class="tab active">Conexión Nightscout</button>
        <button id="tab-calc" class="tab">Parámetros Cálculo</button>
        <button id="tab-data" class="tab">Datos</button>
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

    <div id="panel-data" hidden>
        <section class="card">
            <h2>Datos y Privacidad</h2>
            <div style="margin-top: 1rem; padding: 1rem; background: #f8fafc; border-radius: 8px;">
                <h3 style="font-size: 1.1rem; margin-bottom: 0.5rem;">Exportar Historial</h3>
                <p style="margin-bottom: 1rem; color: #64748b;">Descarga una copia de seguridad de todos tus datos (basales, ajustes, sugerencias) en formato JSON.</p>
                <button id="export-btn" class="secondary" style="width: 100%;">📥 Descargar Todo (JSON)</button>
            </div>
            
            <div style="margin-top: 1rem; padding: 1rem; background: #f8fafc; border-radius: 8px;">
                 <h3 style="font-size: 1.1rem; margin-bottom: 0.5rem;">Notificaciones</h3>
                 <p style="margin-bottom: 1rem; color: #64748b;">Recibe alertas sobre análisis de noches y sugerencias de cambios basales.</p>
                 <button id="push-btn" class="ghost" style="width: 100%;">🔔 Activar Notificaciones</button>
            </div>
        </section>
    </div>
  </main>
  `;

  const tabNs = document.querySelector("#tab-ns");
  const tabCalc = document.querySelector("#tab-calc");
  const tabData = document.querySelector("#tab-data");
  const panelNs = document.querySelector("#panel-ns");
  const panelCalc = document.querySelector("#panel-calc");
  const panelData = document.querySelector("#panel-data");

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
    tabNs.classList.add("active"); tabCalc.classList.remove("active"); tabData.classList.remove("active");
    panelNs.hidden = false; panelCalc.hidden = true; panelData.hidden = true;
  };
  tabCalc.onclick = () => {
    tabCalc.classList.add("active"); tabNs.classList.remove("active"); tabData.classList.remove("active");
    panelCalc.hidden = false; panelNs.hidden = true; panelData.hidden = true;
  };
  tabData.onclick = () => {
    tabData.classList.add("active"); tabNs.classList.remove("active"); tabCalc.classList.remove("active");
    panelData.hidden = false; panelNs.hidden = true; panelCalc.hidden = true;
  };

  document.querySelector("#export-btn").onclick = async () => {
    const btn = document.querySelector("#export-btn");
    const originalText = btn.textContent;
    btn.textContent = "Generando... ⏳";
    btn.disabled = true;

    try {
      const data = await exportUserData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bolus_ai_export_${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      btn.textContent = "¡Descarga lista! ✅";
    } catch (e) {
      alert("Error al exportar: " + e.message);
      btn.textContent = "Error ❌";
    } finally {
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 3000);
    }
  };

  document.querySelector("#push-btn").onclick = async () => {
    const btn = document.querySelector("#push-btn");
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      alert("Este navegador no soporta notificaciones Push.");
      return;
    }

    const perm = await Notification.requestPermission();
    if (perm !== "granted") {
      alert("Permiso denegado.");
      return;
    }

    // Note: In real app, we need VAPID public key from backend
    // const vapidKey = await getVapidKey(); 
    // For this scaffolding, we just show success to UX
    alert("Permisos concedidos. (Falta integración VAPID backend)");
    btn.textContent = "✅ Activadas";
    btn.disabled = true;
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
    snack: { icr: 10, isf: 50, target: 110 },
    dia_hours: 4,
    round_step_u: 0.5,
    max_bolus_u: 10
  };

  let currentSettings = getCalcParams() || defaults;

  if (!currentSettings.snack) {
    currentSettings.snack = { ...defaults.snack };
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
    saveCurrentSlotToMemory();

    const diaVal = parseFloat(document.querySelector("#global-dia").value);
    const stepVal = parseFloat(document.querySelector("#global-step").value);
    const maxVal = parseFloat(document.querySelector("#global-max").value);

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

    for (const key of ["breakfast", "lunch", "dinner", "snack"]) {
      const s = finalParams[key];
      if (!s || s.icr <= 0 || s.isf <= 0 || s.target < 0) {
        alert(`Error en validación de ${key}. Revisa los valores(ICR, ISF > 0).`);
        return;
      }
    }

    saveCalcParams(finalParams);
    currentSettings = finalParams;

    console.log("Calculated parameters saved:", finalParams);

    const msg = document.querySelector("#calc-msg");
    msg.textContent = "Guardado en localStorage OK.";
    msg.hidden = false;
    setTimeout(() => msg.hidden = true, 3000);
  };

  if (!getCalcParams()) {
    console.log("No calc params found, saving defaults...");
    saveCalcParams(defaults);
    currentSettings = defaults;
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
    alert("Configuración de bolo dividido guardada.");
  };
}
