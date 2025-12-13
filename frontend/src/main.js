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
    <p class="hint">Define la variable de entorno <code>VITE_API_BASE_URL</code> en Render para apuntar al backend.</p>
  </main>
`;

const output = document.querySelector("#health-output");
document.querySelector("#health-btn").addEventListener("click", async () => {
  output.textContent = "Consultando...";
  try {
    const response = await fetch(new URL("/api/health", apiBase || window.location.origin));
    const body = await response.json();
    output.textContent = JSON.stringify(body, null, 2);
  } catch (error) {
    output.textContent = `Error: ${error}`;
  }
});
