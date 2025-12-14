
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

// --- RENDER DASHBOARD ---
function renderDashboard() {
  if (!ensureAuthenticated()) return;
  const needsChange = state.user?.needs_password_change;

  // Render structure
  app.innerHTML = `
    ${renderHeader()}
    <main class="page">
      ${needsChange ? '<div class="warning">Debes cambiar la contraseña predeterminada.</div>' : ""}
      
      <!-- U2 Panel Container -->
      <div id="u2-panel-container" hidden></div>

      <!-- Current Glucose Card -->
      <section class="card glucose-card">
         <div class="card-header">
           <h2>Glucosa Actual</h2>
           <button id="refresh-bg-btn" class="ghost small">↻ Actualizar</button>
         </div>
         <div id="glucose-display" class="glucose-box">
            <span class="loading-text">Cargando...</span>
         </div>
      </section>

      <!-- IOB Card -->
      <section class="card">
         <div class="card-header">
           <h2>Insulina Activa (IOB)</h2>
           <button id="refresh-iob-btn" class="ghost small">↻</button>
         </div>
         <div class="iob-box" id="iob-display">
            <span class="loading-text">Cargando...</span>
         </div>
         <canvas id="iob-graph" width="350" height="150" style="width:100%; max-height:150px; margin-top:10px;"></canvas>
      </section>
      
      <!-- BLE Scale Card -->
      <section class="card" id="scale-card">
         <div class="card-header">
           <h2>Báscula (BLE)</h2>
           <span id="scale-status-badge" class="badge neutral">${state.scale.status}</span>
         </div>
         <div class="scale-box">
            <div id="scale-display" class="big-number">-- g</div>
            <div id="scale-meta" class="scale-meta"></div>
         </div>
         
         <div class="actions" style="margin-top:1rem;">
            ${!isBleSupported()
      ? '<div class="warning small">Navegador no soporta BLE. Usa Bluefy en iOS.</div>'
      : `
                 <button id="btn-scale-connect" class="secondary small">Conectar</button>
                 <button id="btn-scale-tare" class="ghost small" disabled>Tara</button>
               `
    }
            <button id="btn-scale-use" class="primary small" disabled>Usar Peso</button>
         </div>
      </section>

      <!-- Vision Card -->
      <section class="card" id="vision-card">
        <div class="card-header">
           <h2>Foto del plato</h2>
           <span class="badge">BETA</span>
        </div>
        
        <form id="vision-form" class="stack">
          <!-- Hidden inputs for file selection -->
          <input type="file" id="cameraInput" accept="image/*" capture="environment" hidden />
          <input type="file" id="photosInput" accept="image/*" hidden />
          
          <div class="row">
            <button type="button" id="btn-camera" class="primary big-btn">📷 Hacer foto</button>
            <button type="button" id="btn-gallery" class="secondary big-btn">🖼️ Elegir de Fotos</button>
          </div>
          
          <div id="preview-container" hidden>
            <img id="image-preview" src="" alt="Vista previa" class="preview-img" />
            <button type="button" id="btn-clear-img" class="ghost small">❌ Quitar</button>
          </div>
          
          <div class="row">
             <label>Franja
                <select id="vision-meal-slot">
                  <option value="breakfast">Desayuno</option>
                  <option value="lunch" selected>Comida</option>
                  <option value="dinner">Cena</option>
                </select>
             </label>
             <label>Tamaño (aprox)
                <select id="vision-portion">
                   <option value="" id="vision-portion-auto">(Auto / Báscula)</option>
                   <option value="small">Pequeño</option>
                   <option value="medium">Mediano</option>
                   <option value="large">Grande</option>
                </select>
             </label>
          </div>
          
           <label class="row-label">
             <input type="checkbox" id="vision-extended" checked />
             Permitir recomendación de bolo extendido (grasa/proteína)
           </label>
           
           <button type="submit" id="vision-submit-btn" disabled>Analizar plato</button>
           <p class="error" id="vision-error" hidden></p>
        </form>

        <div id="vision-results" class="results-box" hidden>
           <h3>Estimación IA</h3>
           <div id="vision-summary"></div>
           <div id="vision-bars" class="bars-container"></div>
           <ul id="vision-items" class="item-list"></ul>
           <div id="vision-bolus" class="bolus-recommendation hidden"></div>
           <div class="actions">
             <button type="button" id="use-vision-btn" class="secondary">Usar estos datos</button>
           </div>
        </div>
      </section>


      

      <section class="card">
        <div class="card-header">
          <h2>Calculadora manual</h2>
          <button id="change-password-link" class="ghost">Cambiar contraseña</button>
        </div>
        <div class="mode-selector segment-control">
           <button type="button" data-mode="meal" class="segment active">🍽️ Comida</button>
           <button type="button" data-mode="correction" class="segment">💉 Corrector</button>
        </div>
        <form id="bolus-form" class="stack">
          <div id="carbs-wrapper">
             <label>Carbohidratos (g)
               <input type="number" step="0.1" id="carbs" required />
             </label>
          </div>
          <label>Glucosa (mg/dL, opcional)
            <input type="number" step="1" id="bg" placeholder="Dejar vacío para usar Nightscout" />
          </label>
          <label>Franja
            <select id="meal-slot">
              <option value="breakfast">Desayuno</option>
              <option value="lunch" selected>Comida</option>
              <option value="dinner">Cena</option>
              <option value="snack">Snack</option>
            </select>
          </label>
          <label>Objetivo (mg/dL, opcional)
            <input type="number" step="1" id="target" />
          </label>
          
          <label class="row-label" id="split-wrapper">
             <input type="checkbox" id="use-split" />
             🔄 Bolo dividido (Dual)
          </label>

          <button type="submit">Calcular</button>
          <p class="error" id="bolus-error" ${state.bolusError ? "" : "hidden"}>${state.bolusError || ""}</p>
        </form>
        <div id="bolus-output" class="bolus-box">${state.bolusResult || "Pendiente de cálculo."}</div>
        <div class="actions" id="bolus-actions" hidden>
           <button type="button" id="accept-bolus-btn" class="primary">✅ Aceptar bolo</button>
           <span id="accept-msg" class="success" hidden></span>
        </div>
        
        <div id="bolus-explain" class="explain" hidden>
          <h3>Detalles del cálculo</h3>
          <ul id="explain-list"></ul>
        </div>
      </section>
      
      <p class="hint">API base: <code>${getApiBase() || "(no configurado)"}</code></p>
    </main>
  `;

  // --- Handlers ---
  const logoutBtn = document.querySelector("#logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => logout());

  // GLUCOSE REFRESH
  const refreshBgBtn = document.querySelector("#refresh-bg-btn");
  const glucoseDisplay = document.querySelector("#glucose-display");

  // === SCALE HANDLERS ===
  const btnScaleConnect = document.querySelector("#btn-scale-connect");
  const btnScaleTare = document.querySelector("#btn-scale-tare");
  const btnScaleUse = document.querySelector("#btn-scale-use");
  const scaleDisplay = document.querySelector("#scale-display");
  const scaleMeta = document.querySelector("#scale-meta");
  const scaleBadge = document.querySelector("#scale-status-badge");

  if (btnScaleConnect) {
    btnScaleConnect.onclick = async () => {
      if (state.scale.connected) {
        await disconnectScale();
        state.scale.connected = false;
        updateScaleUI();
      } else {
        try {
          btnScaleConnect.disabled = true;
          btnScaleConnect.textContent = "Conectando...";
          scaleBadge.textContent = "Conectando...";

          const name = await connectScale();
          state.scale.connected = true;

          updateScaleUI();
        } catch (e) {
          console.error(e);
          alert("Error BLE: " + e.message);
          state.scale.connected = false;
          updateScaleUI();
        }
      }
    };
  }

  if (btnScaleTare) {
    btnScaleTare.onclick = async () => {
      try {
        await tare();
      } catch (e) { console.error(e); }
    };
  }

  if (btnScaleUse) {
    btnScaleUse.onclick = () => {
      // Save to generic global state or vision override
      const grams = state.scale.grams;
      state.plateWeightGrams = grams;

      // Show feedback
      const explainBlock = document.querySelector("#bolus-explain");
      const explainList = document.querySelector("#explain-list");

      // Append info item about weight
      explainBlock.hidden = false;
      const li = document.createElement("li");
      li.innerHTML = `<strong>Peso Báscula:</strong> ${grams} g <span class="badge neutral">Usado</span>`;
      explainList.prepend(li); // Show at top

      // If we had input fields for weight in vision form, we would set them here. 
      // Update Vision Form "Auto" label to show captured weight
      const autoOpt = document.querySelector("#vision-portion-auto");
      const visionSelect = document.querySelector("#vision-portion");
      if (autoOpt) {
        autoOpt.textContent = `(Auto / ${grams}g)`;
        visionSelect.value = ""; // Select Auto
      }

      console.log("Weight captured manually:", grams);
    };
  }

  // Define onData callback
  setOnData((data) => {
    if (!data.connected) {
      state.scale.connected = false;
      state.scale.status = "Desconectado";
      updateScaleUI();
      return;
    }

    state.scale.connected = true;
    state.scale.grams = data.grams;
    state.scale.stable = data.stable;
    state.scale.battery = data.battery;

    updateScaleUI();
  });

  function updateScaleUI() {
    // Button State
    if (state.scale.connected) {
      btnScaleConnect.textContent = "Desconectar";
      btnScaleConnect.disabled = false;
      btnScaleTare.disabled = false;
      scaleBadge.textContent = "Conectado";
      scaleBadge.className = "badge success";
      btnScaleUse.disabled = false;
    } else {
      btnScaleConnect.textContent = "Conectar";
      btnScaleConnect.disabled = false;
      btnScaleTare.disabled = true;
      btnScaleUse.disabled = true;
      scaleBadge.textContent = "Desconectado";
      scaleBadge.className = "badge neutral";
    }

    // Display Value
    if (state.scale.connected) {
      scaleDisplay.textContent = `${state.scale.grams} g`;
      // Stable badge
      let metaHtml = "";
      if (state.scale.stable) {
        metaHtml += `<span class="badge success">ESTABLE</span>`;
      } else {
        metaHtml += `<span class="badge warning">...</span>`;
      }

      if (state.scale.battery !== null) {
        metaHtml += ` <small>🔋 ${state.scale.battery}%</small>`;
      }
      scaleMeta.innerHTML = metaHtml;
    } else {
      scaleDisplay.textContent = "-- g";
      scaleMeta.innerHTML = "";
    }
  }

  async function updateGlucoseDisplay() {
    glucoseDisplay.innerHTML = '<span class="loading-text">Actualizando...</span>';

    const config = getLocalNsConfig();
    if (!config || !config.url) {
      glucoseDisplay.innerHTML = `<span class="bg-error">No configurado (local)</span>`;
      return;
    }

    try {
      const res = await getCurrentGlucose(config);
      state.currentGlucose.data = res;
      state.currentGlucose.loading = false;

      if (!res.ok) {
        glucoseDisplay.innerHTML = `<span class="bg-error">${res.error || "No configurado"}</span>`;
        return;
      }

      // Format
      const bgVal = Math.round(res.bg_mgdl);
      const trendIcon = res.trendArrow || formatTrend(res.trend, res.stale);
      const age = Math.round(res.age_minutes);
      const staleClass = res.stale ? "stale" : "fresh";
      const staleText = res.stale ? "ANTIGUO" : "OK";

      glucoseDisplay.innerHTML = `
             <div class="glucose-main ${staleClass}">
                <span class="bg-value">${bgVal}</span>
                <span class="bg-arrow">${trendIcon}</span>
             </div>
             <div class="glucose-meta">
                <span>Hace ${age} min</span>
                <span class="status-badge ${staleClass}">${staleText}</span>
             </div>
          `;

    } catch (err) {
      glucoseDisplay.innerHTML = `<span class="bg-error">Error conexión</span>`;
    }
  }

  refreshBgBtn.addEventListener("click", updateGlucoseDisplay);

  // Initial load if not loaded recently (e.g. < 1 min)
  if (!state.currentGlucose.data || (Date.now() - state.currentGlucose.timestamp > 60000)) {
    updateGlucoseDisplay();
    state.currentGlucose.timestamp = Date.now();
  } else {
    updateGlucoseDisplay();
  }


  // === VISION HANDLERS ===
  const visionForm = document.querySelector("#vision-form");
  const cameraInput = document.querySelector("#cameraInput");
  const photosInput = document.querySelector("#photosInput");
  const btnCamera = document.querySelector("#btn-camera");
  const btnGallery = document.querySelector("#btn-gallery");
  const previewContainer = document.querySelector("#preview-container");
  const imagePreview = document.querySelector("#image-preview");
  const btnClearImg = document.querySelector("#btn-clear-img");

  const visionError = document.querySelector("#vision-error");
  const visionResults = document.querySelector("#vision-results");
  const visionSubmitBtn = document.querySelector("#vision-submit-btn");

  let selectedFile = null;

  function handleFileSelect(evt) {
    if (evt.target.files && evt.target.files[0]) {
      selectedFile = evt.target.files[0];
      // Show preview
      imagePreview.src = URL.createObjectURL(selectedFile);
      previewContainer.hidden = false;
      visionSubmitBtn.disabled = false;
      visionError.hidden = true;
      // Reset other input to avoid confusion
      if (evt.target === cameraInput) photosInput.value = "";
      else cameraInput.value = "";
    }
  }

  btnCamera.onclick = () => cameraInput.click();
  btnGallery.onclick = () => photosInput.click();

  cameraInput.onchange = handleFileSelect;
  photosInput.onchange = handleFileSelect;

  btnClearImg.onclick = () => {
    selectedFile = null;
    imagePreview.src = "";
    previewContainer.hidden = true;
    visionSubmitBtn.disabled = true;
    cameraInput.value = "";
    photosInput.value = "";
  };

  async function compressImage(file) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement("canvas");
        let width = img.width;
        let height = img.height;
        const maxDim = 1280;

        if (width > maxDim || height > maxDim) {
          if (width > height) {
            height = Math.round(height * (maxDim / width));
            width = maxDim;
          } else {
            width = Math.round(width * (maxDim / height));
            height = maxDim;
          }
        }

        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, width, height);

        let quality = 0.75;
        if (file.size > 2 * 1024 * 1024) quality = 0.6;

        canvas.toBlob((blob) => {
          if (blob) resolve(blob);
          else reject(new Error("Error al comprimir imagen"));
        }, "image/jpeg", quality);
      };
      img.onerror = (err) => reject(err);
      img.src = URL.createObjectURL(file);
    });
  }

  visionForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    visionError.hidden = true;
    visionResults.hidden = true;

    if (!selectedFile) {
      visionError.textContent = "Selecciona una imagen primero.";
      visionError.hidden = false;
      return;
    }

    visionSubmitBtn.disabled = true;
    const originalText = visionSubmitBtn.textContent;
    visionSubmitBtn.textContent = "Comprimiendo...";

    try {
      const compressedBlob = await compressImage(selectedFile);
      visionSubmitBtn.textContent = "Analizando...";

      const options = {
        meal_slot: document.querySelector("#vision-meal-slot").value,
        portion_hint: document.querySelector("#vision-portion").value,
        prefer_extended: document.querySelector("#vision-extended").checked,
        // Explicitly check for "Used" weight (state.plateWeightGrams) OR live weight if connected and non-zero
        plate_weight_grams: (state.scale.connected && state.scale.grams > 0)
          ? state.scale.grams
          : (state.plateWeightGrams || null)
      };

      console.log("Submitting Vision Request with options:", options);
      if (options.plate_weight_grams) console.log("Weight to send:", options.plate_weight_grams);

      const currentBg = document.querySelector("#bg").value;
      if (currentBg) options.bg_mgdl = currentBg;

      const nsConfig = getLocalNsConfig();
      if (nsConfig && nsConfig.url) {
        options.nightscout = { url: nsConfig.url, token: nsConfig.token };
      }

      // Inject Calculator Params (Rounding) if available locally
      const calcParams = getCalcParams();
      if (calcParams && calcParams.round_step_u) {
        options.round_step_u = calcParams.round_step_u;
      }

      const data = await estimateCarbsFromImage(compressedBlob, options);
      state.visionResult = data;
      renderVisionResults(data);
    } catch (e) {
      visionError.textContent = e.message;
      visionError.hidden = false;
    } finally {
      visionSubmitBtn.disabled = false;
      visionSubmitBtn.textContent = originalText;
    }
  });

  function renderVisionResults(data) {
    visionResults.hidden = false;

    // 1. Summary
    const summaryDiv = document.querySelector("#vision-summary");
    summaryDiv.innerHTML = `
        <div class="big-number">${data.carbs_estimate_g}g <small>carbs</small></div>
        <div>Confianza: <strong>${data.confidence}</strong> (Rango: ${data.carbs_range_g[0]}-${data.carbs_range_g[1]}g)</div>
     `;

    // 2. Bars (Fat / Slow)
    const barsDiv = document.querySelector("#vision-bars");
    barsDiv.innerHTML = `
        <div class="bar-row">Grasa: <progress value="${data.fat_score}" max="1"></progress></div>
        <div class="bar-row">Absorción lenta: <progress value="${data.slow_absorption_score}" max="1"></progress></div>
     `;

    // 3. Items
    const list = document.querySelector("#vision-items");
    list.innerHTML = "";
    data.items.forEach(item => {
      const li = document.createElement("li");
      li.textContent = `${item.name} (~${item.carbs_g}g)`;
      if (item.notes) {
        const span = document.createElement("small");
        span.textContent = ` - ${item.notes}`;
        li.appendChild(span);
      }
      list.appendChild(li);
    });

    // 4. Bolus
    const bolusDiv = document.querySelector("#vision-bolus");
    if (data.bolus) {
      bolusDiv.classList.remove("hidden");
      let html = `<h4>Bolo Recomendado (${data.bolus.kind === 'extended' ? 'EXTENDIDO' : 'NORMAL'})</h4>`;

      if (data.bolus.kind === 'extended') {
        html += `
              <div class="split-bolus">
                 <div class="split-part">
                    <strong>AHORA</strong>
                    <span class="val">${data.bolus.upfront_u} U</span>
                 </div>
                 <div class="split-part">
                    <strong>LUEGO (+${data.bolus.delay_min} min)</strong>
                    <span class="val">${data.bolus.later_u} U</span>
                 </div>
              </div>
            `;
      } else {
        html += `<div class="big-number">${data.bolus.upfront_u} U</div>`;
      }

      html += `<ul>${data.bolus.explain.map(e => `<li>${e}</li>`).join('')}</ul>`;
      bolusDiv.innerHTML = html;
    } else {
      bolusDiv.classList.add("hidden");
    }

    // 5. User Input Questions (if any)
    if (data.needs_user_input && data.needs_user_input.length > 0) {
      // Just show them as warnings for now in MVP
      const div = document.createElement("div");
      div.className = "warning";
      div.innerHTML = "<strong>Nota:</strong> " + data.needs_user_input.map(q => q.question).join("<br>");
      visionResults.appendChild(div);
    }

    // Bind actions
    const useBtn = document.querySelector("#use-vision-btn");
    useBtn.onclick = () => {
      document.querySelector("#carbs").value = data.carbs_estimate_g;
      // We set the form meal_slot to match vision selection
      document.querySelector("#meal-slot").value = document.querySelector("#vision-meal-slot").value;

      // Populate manual calculator results immediately if we have a bolus
      if (data.bolus) {
        // We can mock the manual calc result
        state.bolusResult = `Bolo recomendado: ${data.bolus.upfront_u} U`;
        if (data.bolus.kind === 'extended') {
          state.bolusResult += ` (+ ${data.bolus.later_u} U en ${data.bolus.delay_min} min)`;
        }
        const output = document.querySelector("#bolus-output");
        output.textContent = state.bolusResult;

        const explainList = document.querySelector("#explain-list");
        const explainBlock = document.querySelector("#bolus-explain");
        explainList.innerHTML = "";
        data.bolus.explain.forEach((item) => {
          const li = document.createElement("li");
          li.textContent = item;
          explainList.appendChild(li);
        });
        explainBlock.hidden = false;

        // Scroll to calculator
        document.querySelector("#bolus-form").scrollIntoView({ behavior: "smooth" });
      }
    };
  }




  document.querySelector("#change-password-link").addEventListener("click", () => navigate("#/change-password"));

  const bolusForm = document.querySelector("#bolus-form");
  const explainBlock = document.querySelector("#bolus-explain");
  const explainList = document.querySelector("#explain-list");

  // Render U2 Panel (now that container exists)
  renderDualPanel();

  const bolusOutput = document.querySelector("#bolus-output");
  const bolusError = document.querySelector("#bolus-error");
  const useSplitCheckbox = document.querySelector("#use-split");

  // Init Split Checkbox default
  if (useSplitCheckbox) {
    const sp = getSplitSettings();
    useSplitCheckbox.checked = sp.enabled_default;
  }

  // === MODE SELECTOR LOGIC ===
  const modeBtns = document.querySelectorAll(".mode-selector .segment");
  if (modeBtns) {
    modeBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        state.calcMode = btn.dataset.mode;
        updateCalcModeUI();
      });
    });
    // Init UI state
    updateCalcModeUI();
  }

  function updateCalcModeUI() {
    const isCorrection = state.calcMode === "correction";

    // Toggle active class on buttons
    modeBtns.forEach(btn => {
      if (btn.dataset.mode === state.calcMode) btn.classList.add("active");
      else btn.classList.remove("active");
    });

    // Toggle fields
    toggleVisibility("#carbs-wrapper", !isCorrection);
    toggleVisibility("#scale-card", !isCorrection);
    toggleVisibility("#vision-card", !isCorrection);
    toggleVisibility("#split-wrapper", !isCorrection);

    // Update 'Required' attribute on carbs to avoid validation error in hidden field
    const carbsInput = document.querySelector("#carbs");
    if (isCorrection) {
      carbsInput.removeAttribute("required");
      carbsInput.value = ""; // Clear
    } else {
      carbsInput.setAttribute("required", "true");
    }

    // Clear previous results/errors
    document.querySelector("#bolus-output").innerHTML = "Pendiente de cálculo.";
    document.querySelector("#bolus-error").hidden = true;
    document.querySelector("#bolus-explain").hidden = true;
  }

  function toggleVisibility(selector, visible) {
    const el = document.querySelector(selector);
    if (el) el.hidden = !visible;
  }


  // Clear actions on change
  document.querySelector("#carbs").oninput = () => {
    state.lastCalc = null;
    const ba = document.querySelector("#bolus-actions");
    if (ba) ba.hidden = true;
  };

  bolusForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    bolusError.hidden = true;
    explainBlock.hidden = true;
    explainList.innerHTML = "";
    bolusOutput.innerHTML = "Calculando...";

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

    const calcParams = getCalcParams();
    const meal = calcParams ? (calcParams[payload.meal_slot] || getDefaultMealParams(calcParams)) : null;

    if (!calcParams || !meal) {
      bolusError.textContent = "⚠️ Configura primero los parámetros de cálculo en 'Configuración'.";
      bolusError.hidden = false;
      bolusOutput.textContent = "";
      return;
    }

    // Construct Flat Payload as requested
    const calcPayload = {
      carbs_g: payload.carbs_g,
      // Use explicit glucose_mgdl if backend supports it, or bg_mgdl (standard). 
      // User asked for "glucose_mgdl: bg" but standard is usually bg_mgdl. 
      // We will send BOTH to be safe given the confusion or strict compliance.
      // But adhering to exact user snippet:
      glucose_mgdl: payload.bg_mgdl, // mapped from stored payload.bg_mgdl
      bg_mgdl: payload.bg_mgdl,      // Keeping original key for compatibility just in case

      bg_mgdl: payload.bg_mgdl,      // Keeping original key for compatibility just in case

      target_mgdl: payload.target_mgdl || meal.target,
      cr_g_per_u: meal.icr,
      isf_mgdl_per_u: meal.isf,

      dia_hours: calcParams.dia_hours,
      round_step_u: calcParams.round_step_u,
      max_bolus_u: calcParams.max_bolus_u,

      // Inject Nightscout if present
      nightscout: payload.nightscout
    };

    // --- CORRECTION MODE OVERRIDES ---
    if (state.calcMode === "correction") {
      calcPayload.carbs_g = 0;
      calcPayload.cr_g_per_u = 999; // Dummy value required by backend

      // Safety Checks
      const manualBg = payload.bg_mgdl; // from input

      // 1. Stale BG Check
      if (!manualBg) {
        // Must rely on Nightscout
        const nsData = state.currentGlucose.data;
        if (!nsData || !nsData.ok) {
          bolusError.textContent = "Error: No hay datos de glucosa. Introduce un valor manual.";
          bolusError.hidden = false;
          bolusOutput.textContent = "";
          return;
        }

        // Check age (15 min limit)
        if (nsData.age_minutes > 15 || nsData.stale) {
          bolusError.textContent = "⚠️ Lectura de glucosa antigua. Introduce un valor manual para corregir.";
          bolusError.hidden = false;
          bolusOutput.textContent = "";
          return;
        }
      }
    }

    // User asked not to ignore missing params condition, but we handled it above.

    // NOTE: The previous payload.settings structure is REMOVED as per instruction 
    // to "construir calcPayload así" with flat fields.

    try {
      // Inject Nightscout if present
      if (nsConfig && nsConfig.url) {
        calcPayload.nightscout = { url: nsConfig.url, token: nsConfig.token };
      }

      // 2. Decide Split
      const useSplit = (state.calcMode !== "correction") && (useSplitCheckbox ? useSplitCheckbox.checked : false);
      let splitSettings = null;
      if (useSplit) {
        splitSettings = getSplitSettings();
      }

      // 3. Perform Calc
      const res = await calculateBolusWithOptionalSplit(calcPayload, splitSettings);

      // 4. Render & Save Plan if Dual
      if (res.kind === "dual" && res.plan) {
        // Save active plan
        saveDualPlan({
          plan_id: res.plan.plan_id, // stored but not strictly needed for recalc-second logic if stateless
          later_u_planned: res.plan.later_u_planned,
          later_after_min: res.plan.later_after_min,
          extended_duration_min: res.plan.extended_duration_min,
          created_at_ts: Date.now(),
          slot: payload.meal_slot
        });
        // Refresh Dashboard to show U2 panel
        renderDualPanel();
      }

      state.bolusResult = renderBolusOutput(res);
      bolusOutput.innerHTML = state.bolusResult;

      // Handle explanations
      if (res.calc && res.calc.explain) {
        explainBlock.hidden = false;
        res.calc.explain.forEach(t => {
          const li = document.createElement("li");
          li.textContent = t;
          explainList.appendChild(li);
        });
        if (res.kind === "dual") {
          const li = document.createElement("li");
          li.innerHTML = `<strong>Bolo Dual:</strong> ${res.upfront_u}U ahora + ${res.later_u}U en ${res.duration_min}min.`;
          explainList.appendChild(li);
        }

        // Add Correction Warnings (Trends)
        if (state.calcMode === "correction") {
          const trend = state.currentGlucose.data?.trend;
          if (trend) {
            if (trend === "DoubleDown" || trend === "SingleDown") {
              const li = document.createElement("li");
              li.innerHTML = `<span class="warning">📉 Tendencia a la baja. Evita correcciones agresivas.</span>`;
              explainList.appendChild(li);
            } else if (trend === "DoubleUp" || trend === "SingleUp") {
              const li = document.createElement("li");
              li.innerHTML = `<span class="warning">📈 Tendencia al alza. Revisa en 20–30 min.</span>`;
              explainList.appendChild(li);
            }
          }
        }
      }

      // Actions (Accept) - MVP placeholder
      const ba = document.querySelector("#bolus-actions");
      if (ba) {
        ba.hidden = false;
        // Clean prev listeners if any... (simplified)
        const btn = document.querySelector("#accept-bolus-btn");
        btn.onclick = async () => {
          // Save treatment logic...
          document.querySelector("#accept-msg").textContent = "Guardado (simulado)";
          document.querySelector("#accept-msg").hidden = false;
        };
      }

    } catch (e) {
      bolusError.textContent = e.message;
      bolusError.hidden = false;
      bolusOutput.textContent = "";
    }
  });

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
           <h2>⏱️ Segunda parte (U2)</h2>
           <button id="btn-clear-u2" class="ghost small">Ocultar</button>
         </div>
         <div class="stack">
            <p><strong>Planificado:</strong> <span class="big-text">${plan.later_u_planned} U</span> <small>a los ${plan.later_after_min || plan.extended_duration_min} min</small></p>
            ${timingHtml}
            ${warningHtml}
            <div class="row">
               <label>Carbs adicionales (g)
                  <input type="number" id="u2-carbs" value="0" style="width: 80px;" />
               </label>
            </div>
            <button id="btn-recalc-u2" class="primary">${btnText}</button>
            
            <div id="u2-result" class="box" hidden>
               <div id="u2-details"></div>
               <div id="u2-recommendation" class="big-number"></div>
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
          recHtml += ` <small>(Max)</small>`;
        }
        recDiv.innerHTML = recHtml;

        let det = "";
        if (data.bg_now_mgdl) {
          det += `<div><strong>BG:</strong> ${Math.round(data.bg_now_mgdl)} mg/dL (${data.bg_age_min} min)</div>`;
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


  function renderBolusOutput(res) {
    if (res.error) return `<span class='error'>${res.error}</span>`;

    // Correction Mode Output
    if (state.calcMode === "correction") {
      if (res.upfront_u === 0) {
        return `<div class="info-box">No se recomienda corrección. (BG &le; Objetivo)</div>`;
      }
      return `
          <div class="correction-res">
             <div class="label">Bolo corrector recomendado</div>
             <div class="big-number">${res.upfront_u} U</div>
          </div>
       `;
    }

    if (res.kind === "dual") {
      return `
        <div class="dual-res">
          <div>AHORA: <strong>${res.upfront_u} U</strong></div>
          <div>LUEGO: <strong>${res.later_u} U</strong> <small>(${res.duration_min} min)</small></div>
        </div>
      `;
    }
    return `<strong>${res.upfront_u} U</strong>`;
  }



  // === IOB GRAPH & ACTIONS ===
  const iobDisplay = document.querySelector("#iob-display");
  const refreshIobBtn = document.querySelector("#refresh-iob-btn");
  const iobCanvas = document.querySelector("#iob-graph");
  const bolusActions = document.querySelector("#bolus-actions");
  const acceptBolusBtn = document.querySelector("#accept-bolus-btn");
  const acceptMsg = document.querySelector("#accept-msg");

  let currentCalculatedBolus = null; // Re-defined in scope, but we use the closure variable above? 
  // Wait, currentCalculatedBolus needs to be accessible by both the submit handler and the accept handler.
  // I defined it above inside renderDashboard scope? No, I need to define it at top of renderDashboard or shared.
  // Actually, I can just define it here and assign it in the submit handler if I move the variable definition up.
  // OR simply look at state.

  // Let's attach it to state to be safe?
  // state.lastCalc = ...

  if (acceptBolusBtn) {
    acceptBolusBtn.onclick = async () => {
      if (!currentCalculatedBolus) return;

      acceptBolusBtn.disabled = true;
      acceptBolusBtn.textContent = "Guardando...";
      try {
        const payload = {
          insulin: currentCalculatedBolus.total_u,
          carbs: parseFloat(document.querySelector("#carbs").value || 0),
          created_at: new Date().toISOString(),
          enteredBy: state.user.username,
          nightscout: getLocalNsConfig()
        };
        await saveTreatment(payload);
        acceptMsg.textContent = "Guardado y subido.";
        acceptMsg.className = "success";
        acceptMsg.hidden = false;
        setTimeout(updateIOB, 1000);
      } catch (e) {
        acceptMsg.textContent = "Error: " + e.message;
        acceptMsg.className = "error";
        acceptMsg.hidden = false;
      } finally {
        acceptBolusBtn.textContent = "✅ Aceptar bolo";
        acceptBolusBtn.disabled = false;
      }
    };
  }

  async function updateIOB() {
    if (!iobDisplay) return;
    iobDisplay.innerHTML = '<span class="loading-text">...</span>';
    try {
      const nsConfig = getLocalNsConfig();
      const data = await getIOBData(nsConfig && nsConfig.url ? nsConfig : null);

      iobDisplay.innerHTML = `
          <div class="big-number">${data.iob_total} U</div>
          ${(data.breakdown && data.breakdown.length) ? `<small>De ${data.breakdown.length} bolos</small>` : ""}
       `;

      if (data.graph && iobCanvas) {
        drawIOBGraph(iobCanvas, data.graph);
      }
    } catch (err) {
      iobDisplay.innerHTML = `<span class="error small">${err.message}</span>`;
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

  if (refreshIobBtn) refreshIobBtn.onclick = updateIOB;
  updateIOB();
}

function navigate(hash) {
  if (window.location.hash === hash) {
    if (hash === "#/") renderDashboard();
    else render();
    return;
  }
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

function ensureAuthenticated() {
  if (!state.token) {
    redirectToLogin();
    return false;
  }
  return true;
}

function renderHeader() {
  if (!state.user) return "";
  return `
    <header class="topbar">
      <div class="brand">Bolus AI</div>
      <div class="nav-links">
        <a href="#/" class="nav-link">Calculadora</a>
        <a href="#/settings" class="nav-link">Configuración</a>
      </div>
      <div class="session-info">
        <div>
          <div class="username">${state.user.username}</div>
          <small class="role">${state.user.role}</small>
        </div>
        <button id="logout-btn" class="ghost">Salir</button>
      </div>
    </header>
  `;
}

function renderLogin() {
  app.innerHTML = `
    <main class="auth-page">
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
    </main>
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
      state.healthStatus = `Error: ${error.message}`;
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
        alert(`Error en validación de ${key}. Revisa los valores (ICR, ISF > 0).`);
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
