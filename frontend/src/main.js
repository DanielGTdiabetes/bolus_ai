import {
  changePassword,
  fetchHealth,
  fetchMe,
  getApiBase,
  getStoredToken,
  getStoredUser,
  loginRequest,
  logout,
  recommendBolus,
  saveSession,
  setUnauthorizedHandler,
  getNightscoutStatus,
  testNightscout,
  saveNightscoutConfig,
  estimateCarbsFromImage,
} from "./lib/api.js";

// ... existing state ...
const state = {
  token: getStoredToken(),
  user: getStoredUser(),
  loadingUser: false,
  bolusResult: null,
  bolusError: "",
  healthStatus: "Pulsa el botón para comprobar.",
  visionResult: null,
  visionError: null,
};

// ... existing code ...

function renderDashboard() {
  if (!ensureAuthenticated()) return;
  const needsChange = state.user?.needs_password_change;
  app.innerHTML = `
    ${renderHeader()}
    <main class="page">
      ${needsChange ? '<div class="warning">Debes cambiar la contraseña predeterminada.</div>' : ""}
      
      <!-- Vision Card -->
      <section class="card">
        <div class="card-header">
           <h2>Foto del plato</h2>
           <span class="badge">BETA</span>
        </div>
        
        <form id="vision-form" class="stack">
          <label>Subir imagen (o hacer foto)
            <input type="file" id="vision-file" accept="image/*" capture="environment" />
          </label>
          
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
                   <option value="">(Auto)</option>
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
           
           <button type="submit" id="vision-submit-btn">Analizar plato</button>
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
        <!-- ... existing health card ... -->
        <div class="card-header">
          <h2>Estado del backend</h2>
          <button id="health-btn" class="ghost">Comprobar</button>
        </div>
        <pre id="health-output">${state.healthStatus}</pre>
      </section>
      
      <section class="card">
        <div class="card-header">
          <h2>Calculadora manual</h2>
          <button id="change-password-link" class="ghost">Cambiar contraseña</button>
        </div>
        <!-- ... existing bolus form ... -->
        <form id="bolus-form" class="stack">
          <label>Carbohidratos (g)
            <input type="number" step="0.1" id="carbs" required />
          </label>
          <label>Glucosa (mg/dL, opcional)
            <input type="number" step="1" id="bg" placeholder="Dejar vacío para usar Nightscout" />
          </label>
          <label>Franja
            <select id="meal-slot">
              <option value="breakfast">Desayuno</option>
              <option value="lunch" selected>Comida</option>
              <option value="dinner">Cena</option>
            </select>
          </label>
          <label>Objetivo (mg/dL, opcional)
            <input type="number" step="1" id="target" />
          </label>
          <button type="submit">Calcular</button>
          <p class="error" id="bolus-error" ${state.bolusError ? "" : "hidden"}>${state.bolusError || ""}</p>
        </form>
        <pre id="bolus-output">${state.bolusResult || "Pendiente de cálculo."}</pre>
        <div id="bolus-explain" class="explain" hidden>
          <h3>Detalles del cálculo</h3>
          <ul id="explain-list"></ul>
        </div>
      </section>
      
      <p class="hint">API base: <code>${getApiBase() || "(no configurado)"}</code></p>
    </main>
  `;

  const logoutBtn = document.querySelector("#logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => logout());

  // === VISION HANDLERS ===
  const visionForm = document.querySelector("#vision-form");
  const visionFile = document.querySelector("#vision-file");
  const visionError = document.querySelector("#vision-error");
  const visionResults = document.querySelector("#vision-results");
  const visionSubmitBtn = document.querySelector("#vision-submit-btn");

  visionForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    visionError.hidden = true;
    visionResults.hidden = true;

    if (!visionFile.files.length) {
      visionError.textContent = "Selecciona una imagen primero.";
      visionError.hidden = false;
      return;
    }

    visionSubmitBtn.disabled = true;
    visionSubmitBtn.textContent = "Analizando...";

    const options = {
      meal_slot: document.querySelector("#vision-meal-slot").value,
      portion_hint: document.querySelector("#vision-portion").value,
      prefer_extended: document.querySelector("#vision-extended").checked
    };

    // Pass current input bg if present, to help context
    const currentBg = document.querySelector("#bg").value;
    if (currentBg) options.bg_mgdl = currentBg;

    try {
      const data = await estimateCarbsFromImage(visionFile.files[0], options);
      state.visionResult = data;
      renderVisionResults(data);
    } catch (e) {
      visionError.textContent = e.message;
      visionError.hidden = false;
    } finally {
      visionSubmitBtn.disabled = false;
      visionSubmitBtn.textContent = "Analizar plato";
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
      document.querySelector("#meal-slot").value = "lunch"; // Default or dynamic? User might have changed it in vision form.
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


  document.querySelector("#health-btn").addEventListener("click", async () => {
    // ... existing health handler ...
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

  document.querySelector("#change-password-link").addEventListener("click", () => navigate("#/change-password"));

  const bolusForm = document.querySelector("#bolus-form");
  const explainBlock = document.querySelector("#bolus-explain");
  const explainList = document.querySelector("#explain-list");
  const bolusOutput = document.querySelector("#bolus-output");
  const bolusError = document.querySelector("#bolus-error");

  bolusForm.addEventListener("submit", async (evt) => {
    // ... existing bolus submit ...
    evt.preventDefault();
    bolusError.hidden = true;
    explainBlock.hidden = true;
    explainList.innerHTML = "";
    bolusOutput.textContent = "Calculando...";

    const payload = {
      carbs_g: parseFloat(document.querySelector("#carbs").value || "0"),
      meal_slot: document.querySelector("#meal-slot").value,
    };
    const bg = document.querySelector("#bg").value;
    if (bg) payload.bg_mgdl = parseFloat(bg);
    const target = document.querySelector("#target").value;
    if (target) payload.target_mgdl = parseFloat(target);

    try {
      const data = await recommendBolus(payload);
      state.bolusError = "";
      state.bolusResult = `Bolo recomendado: ${data.upfront_u} U (IOB: ${data.iob_u.toFixed(2)} U)`;
      bolusOutput.textContent = state.bolusResult;
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
}

function navigate(hash) {
  if (window.location.hash === hash) {
    render();
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
      // If valid session and on login/root, go to dashboard
      // Note: preserve current hash if it exists and is not login
      if (window.location.hash === "#/login" || !window.location.hash) {
        navigate("#/");
      }
    }
  } catch (error) {
    state.user = null;
    state.token = null;
    redirectToLogin();
  } finally {
    state.loadingUser = false;
    render();
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

async function renderSettings() {
  if (!ensureAuthenticated()) return;

  app.innerHTML = `
    ${renderHeader()}
    <main class="page">
      <section class="card">
        <h2>Configuración Nightscout</h2>
        <div id="ns-loading">Cargando configuración...</div>
        <form id="ns-form" class="stack" hidden>
           <label class="row-label">
             <input type="checkbox" id="ns-enabled" />
             Activar integración Nightscout
           </label>
           
           <label>URL Nightscout
             <input type="url" id="ns-url" placeholder="https://tusitio.herokuapp.com" />
           </label>
           
           <label>Token / API Secret
             <input type="password" id="ns-token" placeholder="Si no cambias, se mantiene el actual" />
             <small class="hint">API_SECRET o token de acceso.</small>
           </label>
           
           <div class="actions">
             <button type="button" id="ns-test-btn" class="secondary">Probar conexión</button>
             <button type="submit">Guardar</button>
           </div>
           
           <div id="ns-status-box" class="status-box hidden"></div>
        </form>
      </section>
    </main>
  `;

  const logoutBtn = document.querySelector("#logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => logout());

  const form = document.querySelector("#ns-form");
  const loading = document.querySelector("#ns-loading");
  const enabledInput = document.querySelector("#ns-enabled");
  const urlInput = document.querySelector("#ns-url");
  const tokenInput = document.querySelector("#ns-token");
  const testBtn = document.querySelector("#ns-test-btn");
  const statusBox = document.querySelector("#ns-status-box");

  // Load current status/config
  try {
    const status = await getNightscoutStatus();
    enabledInput.checked = status.enabled;
    urlInput.value = status.url || "";
    // Token is hidden

    form.hidden = false;
    loading.hidden = true;

    if (status.ok) {
      statusBox.textContent = "Estado actual: Conectado correctamente.";
      statusBox.className = "status-box success";
    } else if (status.enabled) {
      statusBox.textContent = `Estado actual: Error de conexión (${status.error || "Desconocido"})`;
      statusBox.className = "status-box error";
    } else {
      statusBox.textContent = "Integración desactivada.";
      statusBox.className = "status-box neutral";
    }
    statusBox.classList.remove("hidden");
  } catch (e) {
    loading.textContent = "Error cargando configuración: " + e.message;
  }

  testBtn.addEventListener("click", async () => {
    statusBox.textContent = "Probando conexión...";
    statusBox.className = "status-box neutral";
    statusBox.classList.remove("hidden");

    const config = {
      enabled: enabledInput.checked,
      url: urlInput.value,
      token: tokenInput.value || undefined // send undefined (or empty string?) if empty. 
      // If empty string, backend might try to auth with empty string. 
      // If the user wants to test with SAVED token, they should probably save first? 
      // Or we can handle logic. Backend 'test' uses saved logic if payload token is empty BUT we want to support 'test what I typed'.
      // If I type nothing, I mean "use saved". If I type something, use that.
    };
    // If token is empty string, we should send null/undefined so backend uses saved?
    // Our backend logic: if payload present, checks payload.token. If payload.token is falsey, it tries to load saved. So sending "" is fine.

    try {
      const res = await testNightscout(config);
      if (res.ok) {
        statusBox.textContent = res.message;
        statusBox.className = "status-box success";
      } else {
        statusBox.textContent = res.message;
        statusBox.className = "status-box error";
      }
    } catch (e) {
      statusBox.textContent = "Error: " + e.message;
      statusBox.className = "status-box error";
    }
  });

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    statusBox.textContent = "Guardando...";
    statusBox.className = "status-box neutral";
    statusBox.classList.remove("hidden");

    const config = {
      enabled: enabledInput.checked,
      url: urlInput.value,
      token: tokenInput.value // Send empty string if empty, backend handles "keep previous"
    };

    try {
      await saveNightscoutConfig(config);
      statusBox.textContent = "Configuración guardada correctamente.";
      statusBox.className = "status-box success";
      // Clear token input to simulate "saved" (and because it's sensitive)
      tokenInput.value = "";
    } catch (e) {
      statusBox.textContent = "Error al guardar: " + e.message;
      statusBox.className = "status-box error";
    }
  });
}

function renderDashboard() {
  if (!ensureAuthenticated()) return;
  const needsChange = state.user?.needs_password_change;
  app.innerHTML = `
    ${renderHeader()}
    <main class="page">
      ${needsChange ? '<div class="warning">Debes cambiar la contraseña predeterminada.</div>' : ""}
      <section class="card">
        <div class="card-header">
          <h2>Estado del backend</h2>
          <button id="health-btn" class="ghost">Comprobar</button>
        </div>
        <pre id="health-output">${state.healthStatus}</pre>
      </section>
      <section class="card">
        <div class="card-header">
          <h2>Nuevo cálculo</h2>
          <button id="change-password-link" class="ghost">Cambiar contraseña</button>
        </div>
        <form id="bolus-form" class="stack">
          <label>Carbohidratos (g)
            <input type="number" step="0.1" id="carbs" required />
          </label>
          <label>Glucosa (mg/dL, opcional)
            <input type="number" step="1" id="bg" placeholder="Dejar vacío para usar Nightscout" />
          </label>
          <label>Franja
            <select id="meal-slot">
              <option value="breakfast">Desayuno</option>
              <option value="lunch" selected>Comida</option>
              <option value="dinner">Cena</option>
            </select>
          </label>
          <label>Objetivo (mg/dL, opcional)
            <input type="number" step="1" id="target" />
          </label>
          <button type="submit">Calcular</button>
          <p class="error" id="bolus-error" ${state.bolusError ? "" : "hidden"}>${state.bolusError || ""}</p>
        </form>
        <pre id="bolus-output">${state.bolusResult || "Pendiente de cálculo."}</pre>
        <div id="bolus-explain" class="explain" hidden>
          <h3>Detalles del cálculo</h3>
          <ul id="explain-list"></ul>
        </div>
      </section>
      <p class="hint">API base: <code>${getApiBase() || "(no configurado)"}</code></p>
    </main>
  `;

  const logoutBtn = document.querySelector("#logout-btn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => logout());

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

  document.querySelector("#change-password-link").addEventListener("click", () => navigate("#/change-password"));

  const bolusForm = document.querySelector("#bolus-form");
  const explainBlock = document.querySelector("#bolus-explain");
  const explainList = document.querySelector("#explain-list");
  const bolusOutput = document.querySelector("#bolus-output");
  const bolusError = document.querySelector("#bolus-error");

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
    const bg = document.querySelector("#bg").value;
    if (bg) payload.bg_mgdl = parseFloat(bg);
    const target = document.querySelector("#target").value;
    if (target) payload.target_mgdl = parseFloat(target);

    try {
      const data = await recommendBolus(payload);
      state.bolusError = "";
      state.bolusResult = `Bolo recomendado: ${data.upfront_u} U (IOB: ${data.iob_u.toFixed(2)} U)`;
      bolusOutput.textContent = state.bolusResult;
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
