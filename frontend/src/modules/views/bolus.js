import { state, getSplitSettings, getCalcParams } from '../core/store.js';
import { navigate } from '../core/router.js';
import { renderHeader, renderBottomNav } from '../components/layout.js';
import {
    estimateCarbsFromImage,
    connectScale,
    disconnectScale,
    tare,
    setOnData,
    calculateBolusWithOptionalSplit,
    recalcSecondBolus,
    saveTreatment,
    getLocalNsConfig,
    getIOBData
} from '../../lib/api.js';

// --- HELPER: Plate Summary ---
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

// --- VIEW: SCAN ---
export function renderScan() {
    const app = document.getElementById("app");
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
            state.currentImageBase64 = ev.target.result;
        };
        reader.readAsDataURL(file);

        // Show loading...
        const actions = document.querySelector('.vision-actions');
        const originalContent = actions.innerHTML;
        actions.innerHTML = '<div class="spinner">⏳ Analizando IA...</div>';

        try {
            const options = {};
            let netWeight = null;

            if (state.scale?.grams > 0) {
                const previousWeight = state.plateBuilder.entries.reduce((sum, e) => sum + (e.weight || 0), 0);
                netWeight = Math.max(0, state.scale.grams - previousWeight);
                options.plate_weight_grams = netWeight;
            }

            if (state.plateBuilder.entries.length > 0) {
                options.existing_items = state.plateBuilder.entries.map(e => e.name).join(", ");
            }

            const result = await estimateCarbsFromImage(file, options);

            const entry = {
                carbs: result.carbs_estimate_g,
                weight: netWeight,
                img: state.currentImageBase64,
                name: result.food_name || "Alimento IA"
            };

            state.plateBuilder.entries.push(entry);
            updatePlateUI();

            actions.innerHTML = `<div class="success-msg" style="text-align:center">✅ Añadido: ${result.carbs_estimate_g}g</div>`;

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

    const handleScaleData = (data) => {
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
                setOnData(handleScaleData);
                updateScaleUI();
            } catch (e) {
                alert("Error conectando: " + e.message);
                state.scale.connected = false;
                updateScaleUI();
            }
        }
    };

    btnTare.onclick = async () => { await tare(); };

    if (state.scale.connected) {
        setOnData(handleScaleData);
    }

    updateScaleUI();

    // --- PLATE BUILDER LOGIC ---
    const plateList = document.getElementById('plate-entries');
    const btnFinPlate = document.getElementById('btn-finalize-plate');
    const btnFinPlateExtra = document.getElementById('btn-finalize-plate-extra');
    const plateTotalEl = document.getElementById('plate-total-carbs');

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

        const hasEntries = state.plateBuilder.entries.length > 0;
        if (btnFinPlate) btnFinPlate.hidden = !hasEntries;

        if (btnFinPlateExtra) {
            btnFinPlateExtra.hidden = !(hasEntries && state.lastBolusPlan);
            if (!btnFinPlateExtra.hidden && btnFinPlate) btnFinPlate.hidden = true;
        }
    };

    // Global Scope for inline onclicks 
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
            renderBolusResult(mockRes);

            setTimeout(() => {
                const inp = document.getElementById('u2-extra-carbs');
                if (inp) inp.value = state.plateBuilder.total;
                const btn = document.getElementById('btn-recalc-u2');
                if (btn) btn.click();
            }, 150);
        };
    }

    if (btnUse) {
        btnUse.onclick = () => {
            state.tempCarbs = state.scale.grams;
            navigate('#/bolus');
        };
    }

    updatePlateUI();
}

// --- VIEW: BOLUS ---
export function renderBolus() {
    const app = document.getElementById("app");
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
        if (state.currentGlucose.data?.bg_mgdl) {
            bgInput.value = Math.round(state.currentGlucose.data.bg_mgdl);
            bgSlider.value = bgInput.value;
        }
    }

    if (state.tempCarbs !== null && state.tempCarbs !== undefined) {
        if (carbsInput) carbsInput.value = state.tempCarbs;
        state.tempCarbs = null;
    }

    window.addCarbs = (val) => {
        if (carbsInput) {
            carbsInput.value = val;
            const chk = document.getElementById('chk-correction-only');
            if (chk) chk.checked = false;
        }
        document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
        event.target.classList.add('active');
    };

    const chkCorr = document.getElementById('chk-correction-only');
    if (chkCorr) {
        chkCorr.onchange = () => {
            if (chkCorr.checked) {
                if (carbsInput) {
                    carbsInput.value = 0;
                    carbsInput.parentElement.parentElement.classList.add('disabled-block');
                }
            } else {
                if (carbsInput) carbsInput.parentElement.parentElement.classList.remove('disabled-block');
            }
        }
    }

    const chkDual = document.getElementById('chk-dual-enabled');
    const divDualInfo = document.getElementById('dual-info');

    if (chkDual && divDualInfo) {
        const updateInfo = () => {
            const s = getSplitSettings() || {};
            divDualInfo.textContent = `Configurado: ${s.percent_now || 70}% ahora, resto en ${s.duration_min || 120} min.`;
            divDualInfo.hidden = !chkDual.checked;
        };

        chkDual.onchange = updateInfo;

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
                const info = d.iob_info || {};
                const val = typeof info.iob_u === 'number' ? info.iob_u : (d.iob_total || 0.0);

                if (info.status === 'unavailable') {
                    iobEl.innerHTML = `⚠️ N/A`;
                    if (iobBanner) {
                        iobBanner.style.background = "#fff1f2";
                        iobBanner.querySelector('div').style.color = "#881337";
                        iobBanner.querySelector('div:last-child').style.color = "#be123c";
                        const sub = document.createElement('div');
                        sub.style.fontSize = "0.7rem";
                        sub.style.color = "#be123c";
                        sub.textContent = info.reason;
                        iobBanner.children[0].appendChild(sub);
                    }
                } else if (info.status === 'partial') {
                    iobEl.innerHTML = `${val.toFixed(2)}⚠️ <span style="font-size:1rem">U</span>`;
                    if (iobBanner) iobBanner.style.background = "#fff7ed";
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

    if (calcBtn) {
        calcBtn.onclick = async () => {
            // ... (Calc Logic) ...
            // Re-implementing logic compactly
            calcBtn.textContent = "Calculando...";
            calcBtn.disabled = true;

            try {
                const bg = parseFloat(bgInput.value);
                const carbs = parseFloat(carbsInput.value) || 0;
                const slot = document.getElementById('meal-slot').value;
                const isCorrection = document.getElementById('chk-correction-only').checked;

                if (isNaN(bg)) throw new Error("Introduce tu glucosa actual.");

                const mealParams = getCalcParams();
                if (!mealParams) throw new Error("No hay configuración de ratios.");
                const slotParams = mealParams[slot];
                if (!slotParams || !slotParams.icr || !slotParams.isf || !slotParams.target) {
                    throw new Error(`Faltan datos para el horario '${slot}'.`);
                }

                const effectiveSlot = ["breakfast", "lunch", "dinner"].includes(slot) ? slot : "lunch";

                const payload = {
                    carbs_g: isCorrection ? 0 : carbs,
                    bg_mgdl: bg,
                    meal_slot: effectiveSlot,
                    target_mgdl: slotParams.target,
                    cr_g_per_u: slotParams.icr,
                    isf_mgdl_per_u: slotParams.isf,
                    dia_hours: mealParams.dia_hours || 4.0,
                    round_step_u: mealParams.round_step_u || 0.5,
                    max_bolus_u: mealParams.max_bolus_u || 15,
                };

                const isDual = document.getElementById('chk-dual-enabled').checked;
                let splitSettings = getSplitSettings() || {};
                if (isDual) {
                    splitSettings.enabled = true;
                } else {
                    splitSettings.enabled = false;
                }

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

// --- RENDER RESULT ---
export function renderBolusResult(res) {
    const calcBtn = document.getElementById('btn-calc-bolus');
    if (calcBtn) calcBtn.hidden = true;

    const existing = document.querySelector('.result-card');
    if (existing) existing.remove();

    const app = document.getElementById("app");
    const container = document.querySelector('main.page');
    const target = container || app;

    const div = document.createElement('div');

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

            ${res.kind === 'dual' ? `
                <div id="extra-carbs-block" style="margin-top:1rem; padding-top:1rem; border-top:1px dashed #eee;">
                    <div style="font-weight:600; font-size:0.9rem; color:#0f766e">➕ Añadir extra (postre / más)</div>
                    <div style="display:flex; gap:0.5rem; margin-top:0.5rem">
                        <input type="number" id="u2-extra-carbs" placeholder="g Carbs" style="width:80px; text-align:center; border:1px solid #ccc; border-radius:6px">
                        <button id="btn-recalc-u2" class="btn-ghost" style="font-size:0.8rem; border:1px solid var(--primary); color:var(--primary)">Recalcular 2ª parte</button>
                    </div>
                    ${state.plateBuilder && state.plateBuilder.entries.length > 0 ? `
                        <div style="margin-top:0.5rem">
                           <button id="btn-import-plate-extra" class="btn-secondary" style="font-size:0.8rem; width:100%">
                               🍽️ Importar ${state.plateBuilder.total}g del Plato
                           </button>
                        </div>
                    ` : ''}
                    <div id="u2-recalc-result" style="margin-top:0.5rem; display:none; background:#f0fdfa; padding:0.5rem; border-radius:6px; font-size:0.8rem;"></div>
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

    // 0. Cancel Handler
    const btnCancel = div.querySelector('#btn-cancel-res');
    if (btnCancel) {
        btnCancel.onclick = () => { renderBolus(); };
    }

    // 1. Recalc U2 Handler
    if (res.kind === 'dual') {
        const btnRecalc = div.querySelector('#btn-recalc-u2');
        const inpExtra = div.querySelector('#u2-extra-carbs');
        const resContainer = div.querySelector('#u2-recalc-result');
        const btnImport = div.querySelector('#btn-import-plate-extra');

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
                const slot = document.getElementById('meal-slot').value;
                const mealParams = getCalcParams();
                const slotParams = mealParams[slot];
                const nsConfig = getLocalNsConfig ? getLocalNsConfig() : {};

                const payload = {
                    later_u_planned: state.lastBolusPlan.later_u_planned,
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

                const u2Res = await recalcSecondBolus(payload);
                state.lastRecalcSecond = u2Res;

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

                const btnUse = resContainer.querySelector('#btn-use-u2');
                const btnClear = resContainer.querySelector('#btn-clear-u2');

                btnUse.onclick = () => {
                    document.getElementById('val-later-u').textContent = u2Res.u2_recommended_u;
                    res.later_u = u2Res.u2_recommended_u;
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
            const finalInsulin = parseFloat(div.querySelector('#final-bolus-input').value);

            if (isNaN(finalInsulin) || finalInsulin < 0) throw new Error("Valor de insulina no válido");
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
