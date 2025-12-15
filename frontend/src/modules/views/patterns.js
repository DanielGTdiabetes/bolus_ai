import { navigate, ensureAuthenticated } from '../core/router.js';
import { renderHeader, renderBottomNav } from '../components/layout.js';
import { runAnalysis, getAnalysisSummary } from '../../lib/api.js';

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

export async function renderPatterns() {
    if (!ensureAuthenticated()) return;
    const app = document.getElementById("app");
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

    const selDays = document.getElementById('analysis-days');
    const btnRecalc = document.getElementById('btn-recalc-patterns');

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
