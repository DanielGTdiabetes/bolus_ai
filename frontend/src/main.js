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
  getCalcSettings,
  saveCalcSettings,
} from "./lib/api";

// ... existing state ...
// ...

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
             
             <hr/>
             
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
        </div>

      </section>
    </main>
  `;

  // -- TAB LOGIC --
  const tabNs = document.querySelector("#tab-ns");
  const tabCalc = document.querySelector("#tab-calc");
  const panelNs = document.querySelector("#panel-ns");
  const panelCalc = document.querySelector("#panel-calc");

  tabNs.onclick = () => {
    tabNs.classList.add("active"); tabCalc.classList.remove("active");
    panelNs.hidden = false; panelCalc.hidden = true;
  };
  tabCalc.onclick = () => {
    tabCalc.classList.add("active"); tabNs.classList.remove("active");
    panelCalc.hidden = false; panelNs.hidden = true;
  };

  // -- NS LOGIC (Existing) --
  // Copy existing NS logic here...
  const logoutBtn = document.querySelector("#logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => logout());

  // Re-implement NS logic simply
  initNsPanel();

  // -- CALC LOGIC --
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
  // Default structure
  const defaults = {
    breakfast: { icr: 10, isf: 50, target: 110 },
    lunch: { icr: 10, isf: 50, target: 110 },
    dinner: { icr: 10, isf: 50, target: 110 },
    dia_hours: 4,
    round_step_u: 0.1,
    max_bolus_u: 10
  };

  let currentSettings = getCalcSettings() || defaults;
  let currentSlot = "breakfast";

  const form = document.querySelector("#calc-form");
  const icrInput = document.querySelector("#slot-icr");
  const isfInput = document.querySelector("#slot-isf");
  const targetInput = document.querySelector("#slot-target");

  // Load globals
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

  // Save current inputs to memory object on slot switch
  function saveCurrentSlotToMemory() {
    currentSettings[currentSlot] = {
      icr: parseFloat(icrInput.value),
      isf: parseFloat(isfInput.value),
      target: parseFloat(targetInput.value)
    };
  }

  document.querySelectorAll(".sub-tab").forEach(btn => {
    btn.onclick = () => {
      saveCurrentSlotToMemory();
      loadSlot(btn.dataset.slot);
    };
  });

  loadSlot("breakfast"); // Init

  form.onsubmit = (e) => {
    e.preventDefault();
    saveCurrentSlotToMemory(); // Ensure last edit is saved

    // Update globals
    currentSettings.dia_hours = parseFloat(document.querySelector("#global-dia").value);
    currentSettings.round_step_u = parseFloat(document.querySelector("#global-step").value);
    currentSettings.max_bolus_u = parseFloat(document.querySelector("#global-max").value);

    // Persist
    saveCalcSettings(currentSettings);

    const msg = document.querySelector("#calc-msg");
    msg.textContent = "Configuración guardada.";
    msg.hidden = false;
    setTimeout(() => msg.hidden = true, 3000);
  };
}

// ... existing renderHeader ...

// ... existing renderLogin ...

// ... existing renderChangePassword ...

// ... existing NS_STORAGE_KEY ... (can remove if duplicative or keep local)

// ... existing getLocalNsConfig (keep common) ...


// ... existing render part of file ...
// UPDATE BOLUS FORM SUBMIT TO USE STATLESS CALC

// Find bolusForm listener inside renderDashboard and replace it:

bolusForm.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  bolusError.hidden = true;
  explainBlock.hidden = true;
  explainList.innerHTML = "";
  bolusOutput.textContent = "Calculando...";

  const payload = {
    carbs_g: parseFloat(document.querySelector("#carbs").value || "0"),
    meal_slot: document.querySelector("#meal-slot").value,
  };

  // Optional BG/Target overrides
  const bg = document.querySelector("#bg").value;
  if (bg) payload.bg_mgdl = parseFloat(bg);
  const target = document.querySelector("#target").value;
  if (target) payload.target_mgdl = parseFloat(target);

  // INJECT SETTINGS
  const nsConfig = getLocalNsConfig();
  if (nsConfig && nsConfig.url) {
    payload.nightscout = { url: nsConfig.url, token: nsConfig.token };
  }

  const calcSettings = getCalcSettings();
  if (calcSettings) {
    payload.settings = calcSettings;
  } else {
    bolusError.textContent = "⚠️ Configura primero los parámetros de cálculo en 'Configuración'.";
    bolusError.hidden = false;
    bolusOutput.textContent = "";
    return;
  }

  try {
    const data = await calculateBolus(payload);
    state.bolusError = "";
    state.bolusResult = `Recomendación: ${data.total_u} U`;
    bolusOutput.textContent = state.bolusResult;

    if (data.iob_u > 0) {
      state.bolusResult += ` (IOB Restado: ${data.iob_u} U)`;
      bolusOutput.textContent = state.bolusResult;
    }

    // Additional Warnings
    if (data.warnings && data.warnings.length > 0) {
      const warnDiv = document.createElement("div");
      warnDiv.className = "warning";
      warnDiv.innerHTML = data.warnings.join("<br>");
      explainBlock.appendChild(warnDiv);
    }

    if (Array.isArray(data.explain) && data.explain.length) {
      explainBlock.hidden = false;
      data.explain.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        explainList.appendChild(li);
      });
    }
  } catch (error) {
    state.bolusError = error.message;
    bolusError.textContent = state.bolusError;
    bolusError.hidden = false;
    bolusOutput.textContent = "";
  }
});

function render() {
  const route = window.location.hash || "#/";
  if (!state.token && route !== "#/login") {
    redirectToLogin();
    return;
  }

  if (route === "#/login") {
    renderLogin();
  } else if (route === "#/change-password") {
    renderChangePassword();
  } else if (route === "#/settings") {
    renderSettings();
  } else {
    renderDashboard();
  }
}

bootstrapSession();
render();
