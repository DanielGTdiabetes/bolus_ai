import { state, syncSettings } from '../core/store.js';
import { navigate, ensureAuthenticated } from '../core/router.js';
import { renderHeader } from '../components/layout.js';
import { getApiBase, loginRequest, changePassword, saveSession } from '../../lib/api.js';

export function renderLogin() {
  const app = document.getElementById("app");
  app.innerHTML = `
      <main class="page narrow">
      <header class="topbar">
         <div class="header-title-group">
             <div class="header-title">Bolus AI</div>
         </div>
      </header>
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
          <button type="submit" class="btn-primary">Entrar</button>
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

      // Sync settings immediately
      await syncSettings();

      // Save session if available
      if (typeof saveSession === 'function') {
        saveSession(state.token, state.user);
      }

      if (data.user.needs_password_change) {
        navigate("#/change-password");
      } else {
        navigate("#/");
      }
    } catch (error) {
      errorBox.textContent = error.message || "No se pudo iniciar sesión";
      errorBox.hidden = false;
    }
  });
}

export function renderChangePassword() {
  if (!ensureAuthenticated()) return;
  const app = document.getElementById("app");

  app.innerHTML = `
    ${renderHeader("Seguridad", true)}
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
        <button type="submit" class="btn-primary">Actualizar</button>
        <p class="error" id="password-error" hidden></p>
        <p class="success" id="password-success" hidden>Contraseña actualizada.</p>
      </form>
    </section>
  </main>
  `;

  const form = document.querySelector("#password-form");
  const err = document.querySelector("#password-error");
  const ok = document.querySelector("#password-success");

  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    err.hidden = true;
    ok.hidden = true;
    const oldPass = document.querySelector("#old-password").value;
    const newPass = document.querySelector("#new-password").value;
    try {
      const result = await changePassword(oldPass, newPass);
      state.user = result.user || state.user;

      if (typeof saveSession === 'function') {
        saveSession(state.token, state.user);
      }

      ok.hidden = false;
      setTimeout(() => navigate("#/"), 1000);
    } catch (error) {
      err.textContent = error.message || "No se pudo actualizar";
      err.hidden = false;
    }
  });
}
