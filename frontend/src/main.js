const apiBase = (window.__BOLUS_API_BASE__ || window.location.origin).replace(/\/$/, "");
const app = document.querySelector("#app");

app.innerHTML = `
  <main>
    <h1>Bolus AI</h1>
    <p class="hint">API base: <code>${apiBase || "(no configurado)"}</code></p>
    <div class="card">
      <p>Estado del backend:</p>
      <button id="health-btn">Comprobar /api/health</button>
      <pre id="health-output">Pulsa el botón para comprobar.</pre>
    </div>
    <div class="card">
      <h2>Nuevo cálculo</h2>
      <form id="bolus-form">
        <label>Carbohidratos (g)
          <input type="number" step="0.1" id="carbs" required />
        </label>
        <label>Glucosa (mg/dL, opcional)
          <input type="number" step="1" id="bg" />
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
        <label>Token (Bearer)
          <input type="text" id="token" placeholder="Opcional si la API exige login" />
        </label>
        <button type="submit">Calcular</button>
      </form>
      <pre id="bolus-output">Pendiente de cálculo.</pre>
      <div id="bolus-explain" class="explain" hidden>
        <h3>Detalles del cálculo</h3>
        <ul id="explain-list"></ul>
      </div>
    </div>
    <p class="hint">Define la variable de entorno <code>VITE_API_BASE_URL</code> en Render para apuntar al backend.</p>
  </main>
`;

const healthOutput = document.querySelector("#health-output");
document.querySelector("#health-btn").addEventListener("click", async () => {
  healthOutput.textContent = "Consultando...";
  try {
    const response = await fetch(new URL("/api/health", apiBase || window.location.origin));
    const body = await response.json();
    healthOutput.textContent = JSON.stringify(body, null, 2);
  } catch (error) {
    healthOutput.textContent = `Error: ${error}`;
  }
});

const bolusForm = document.querySelector("#bolus-form");
const bolusOutput = document.querySelector("#bolus-output");
const explainBlock = document.querySelector("#bolus-explain");
const explainList = document.querySelector("#explain-list");

bolusForm.addEventListener("submit", async (evt) => {
  evt.preventDefault();
  bolusOutput.textContent = "Calculando...";
  explainBlock.hidden = true;
  explainList.innerHTML = "";

  const payload = {
    carbs_g: parseFloat(document.querySelector("#carbs").value || "0"),
    meal_slot: document.querySelector("#meal-slot").value,
  };

  const bg = document.querySelector("#bg").value;
  if (bg) payload.bg_mgdl = parseFloat(bg);

  const target = document.querySelector("#target").value;
  if (target) payload.target_mgdl = parseFloat(target);

  const headers = { "Content-Type": "application/json" };
  const token = document.querySelector("#token").value.trim();
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    const response = await fetch(new URL("/api/bolus/recommend", apiBase), {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      bolusOutput.textContent = body.detail || JSON.stringify(body, null, 2);
      return;
    }
    bolusOutput.textContent = `Bolo recomendado: ${body.upfront_u} U (IOB: ${body.iob_u})`;
    if (Array.isArray(body.explain)) {
      explainBlock.hidden = false;
      body.explain.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        explainList.appendChild(li);
      });
    }
  } catch (error) {
    bolusOutput.textContent = `Error: ${error}`;
  }
});
